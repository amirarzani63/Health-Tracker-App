"""Several people, one app: pick who you are, add someone, rename or remove a person."""

from datetime import date

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import auth
from app.db import USER_COOKIE, SessionLocal, create_user_tables, request_user, session_for
from app.models import AppUser, WeightEntry
from app.services import colors, insights

router = APIRouter(prefix="/api/users", tags=["users"])
COLORS = ["#ff8a3d", "#3dbbff", "#39d98a", "#ff5c8a", "#b28cff", "#ffd23d"]
# colour schemes, each with its main colour (also used for the person's round initial)
SCHEMES = {"orange": "#ff7a1a", "pink": "#ff3d9a", "emerald": "#22e39a", "violet": "#a46bff", "red": "#ff4d4d", "gold": "#ffc21a",
           "sky": "#5ec8ff", "navy": "#7896ff", "forest": "#3fbf6a"}


def _free_scheme(db, prefer: str) -> str:
    used = {u.scheme for u in db.scalars(select(AppUser)).all() if u.scheme}
    for k in [prefer, *SCHEMES]:
        if k not in used:
            return k
    return prefer


def _ensure_schemes(db) -> None:
    """Give everyone who doesn't have one their own colour scheme (orange for men, pink for women first)."""
    changed = False
    for u in db.scalars(select(AppUser).order_by(AppUser.id)).all():
        if not u.scheme:
            u.scheme = _free_scheme(db, "pink" if _sex(u.id) == "female" else "orange")
            u.color = SCHEMES[u.scheme]
            db.flush()
            changed = True
    if changed:
        db.commit()


def _ensure_first(db) -> None:
    """The original user is profile 1 (their data never moves)."""
    if db.get(AppUser, 1) is None:
        with session_for(1) as udb:
            name = (insights.get_profile(udb).name or "").strip() or "Me"
        db.add(AppUser(id=1, name=name, color=COLORS[0], scheme="orange"))
        db.commit()


def _sex(uid: int) -> str:
    with session_for(uid) as udb:
        return insights.get_profile(udb).sex or "male"


def _out(u: AppUser, current: int) -> dict:
    return {"id": u.id, "name": u.name, "color": u.color, "current": u.id == current, "sex": _sex(u.id),
            "scheme": u.scheme or "orange", "favorite_color": u.fav_color or ""}


@router.get("")
def list_users(request: Request):
    cur = request_user(request)
    with SessionLocal() as db:
        _ensure_first(db)
        _ensure_schemes(db)
        users = db.scalars(select(AppUser).order_by(AppUser.id)).all()
        return {"users": [_out(u, cur) for u in users], "current": cur,
                "chosen": USER_COOKIE in request.cookies or bool(request.headers.get("x-ht-user")), "schemes": SCHEMES}


def _select(response: Response, request: Request, uid: int):
    response.set_cookie(USER_COOKIE, str(uid), max_age=auth.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=auth.is_https(request))


ACTIVITY_LABEL = {"sedentary": "mostly sitting", "light": "lightly active", "moderate": "moderately active",
                  "active": "very active", "very_active": "extremely active"}
AREAS = {"waist", "core", "shoulders", "arms", "back", "legs", "glutes", "chest", "cardio", "flexibility"}
INJURIES = {"none", "knees", "lower_back", "shoulders", "wrists", "neck"}


class Details(BaseModel):
    """Everything needed to work out a person's targets and plan exactly. No defaults: all must be answered."""
    name: str = Field(min_length=1, max_length=60)
    favorite_color: str | None = Field(None, max_length=40)  # their dashboard is themed in shades of it
    sex: str = Field(pattern="^(male|female)$")
    birth_year: int = Field(ge=1920, le=2020)
    height_cm: float = Field(ge=100, le=250)
    weight_kg: float = Field(ge=30, le=350)
    activity_level: str = Field(pattern="^(sedentary|light|moderate|active|very_active)$")
    weight_goal: str = Field(pattern="^(lose|maintain|gain)$")
    target_weight_kg: float | None = Field(None, ge=30, le=350)
    goal_weeks: int | None = Field(None, ge=1, le=104)
    muscle_goal: str = Field(pattern="^(none|tone|build|strength)$")
    focus_areas: list[str]
    training_days: int = Field(ge=0, le=7)
    session_minutes: int = Field(ge=15, le=180)
    experience: str = Field(pattern="^(beginner|intermediate|advanced)$")
    equipment: str = Field("gym", pattern="^(gym|home|bodyweight)$")
    equipment_list: list[str]  # exactly what the person can use; [] = no equipment
    split_style: str = Field(pattern="^(auto|body_part|full_body|upper_lower|ppl)$")
    injuries: list[str] = Field(min_length=1)
    diet_type: str = Field(pattern="^(omnivore|vegetarian|vegan|pescatarian)$")
    allergies: list[str] = []
    rebuild_plan: bool = True

    def check(self):
        if self.weight_goal != "maintain":
            if not self.target_weight_kg or not self.goal_weeks:
                raise HTTPException(422, "Please enter your goal weight and how many weeks you'd like to take.")
            if self.weight_goal == "lose" and self.target_weight_kg >= self.weight_kg:
                raise HTTPException(422, "To lose weight, the goal weight must be below your current weight.")
            if self.weight_goal == "gain" and self.target_weight_kg <= self.weight_kg:
                raise HTTPException(422, "To gain weight, the goal weight must be above your current weight.")
        from app.services.workout_planner import EQUIPMENT_ITEMS
        if set(self.equipment_list) - set(EQUIPMENT_ITEMS):
            raise HTTPException(422, "Unknown equipment.")
        have = set(self.equipment_list)
        self.equipment = "gym" if have & {"barbell", "machines", "cable"} else "home" if have else "bodyweight"
        if self.favorite_color is not None:
            if not self.favorite_color.strip():
                raise HTTPException(422, "Please tell us your favourite colour.")
            colors.resolve(self.favorite_color)
        if set(self.focus_areas) - AREAS or set(self.injuries) - INJURIES:
            raise HTTPException(422, "Unknown focus area or injury.")


def person_args(p) -> dict:
    """Equipment, age, sex and body size: what the plan generator needs to fit the person."""
    from app.services import nutrition
    h = (p.height_cm or 170) / 100
    return {"equipment_list": p.equipment_list or None, "age": nutrition.age_on(p.birth_year),
            "split_style": getattr(p, "split_style", None) or "auto",
            "sex": p.sex, "bmi": p.weight_kg / (h * h)}


def apply_details(udb, d: Details) -> list[str]:
    """Save the answers, then work out calories, protein and (optionally) the workout plan. Returns the maths."""
    from sqlalchemy import update

    from app.models import WorkoutPlan
    from app.services import nutrition
    from app.services.workout_planner import generate_plan

    p, g = insights.get_profile(udb), insights.get_goals(udb)
    p.name, p.sex, p.birth_year = d.name.strip(), d.sex, d.birth_year
    p.height_cm, p.weight_kg, p.activity_level = d.height_cm, d.weight_kg, d.activity_level
    p.goal = d.weight_goal
    p.goal_weeks = d.goal_weeks if d.weight_goal != "maintain" else None
    p.muscle_goal, p.focus_areas = d.muscle_goal, list(d.focus_areas)
    p.injuries = [i for i in d.injuries if i != "none"] or []
    p.training_days, p.session_minutes = max(1, d.training_days), d.session_minutes
    p.experience, p.equipment, p.diet_type, p.allergies = d.experience, d.equipment, d.diet_type, d.allergies
    p.equipment_list = list(d.equipment_list)
    p.split_style = d.split_style
    p.setup_done = p.details_done = True
    g.target_weight_kg = d.target_weight_kg if d.weight_goal != "maintain" else None
    g.calorie_target = g.protein_target_g = g.carbs_target_g = g.fat_target_g = None  # worked out exactly from the answers
    g.workouts_per_week, g.saved = d.training_days, True
    entry = udb.scalar(select(WeightEntry).where(WeightEntry.day == date.today(), WeightEntry.source == "manual"))
    if entry is None:
        udb.add(WeightEntry(day=date.today(), weight_kg=d.weight_kg, source="manual"))
    else:
        entry.weight_kg = d.weight_kg
    udb.commit()

    out = budget_maths(udb)

    if d.rebuild_plan and d.training_days > 0:
        plan_goal = {"build": "hypertrophy", "strength": "strength"}.get(d.muscle_goal) \
            or ("fat_loss" if d.weight_goal == "lose" else "general")
        plan = generate_plan(goal=plan_goal, days_per_week=min(6, max(2, d.training_days)), weeks=6 if plan_goal in ("strength", "hypertrophy") else 4,
                             equipment=d.equipment, experience=d.experience,
                             include_cardio=d.weight_goal == "lose" or "cardio" in d.focus_areas or d.training_days >= 3,
                             focus_areas=d.focus_areas, injuries=p.injuries, session_minutes=d.session_minutes,
                             **person_args(p))
        udb.execute(update(WorkoutPlan).values(active=False))
        udb.add(WorkoutPlan(name=plan["name"], goal=plan["goal"], weeks=plan["weeks"], days=plan["days"],
                            progression=plan["progression"], active=True))
        udb.commit()
        out.append(f"Workout plan: {plan['name']}"
                   + (f", with extra {', '.join(d.focus_areas)} work" if d.focus_areas else "")
                   + (f", avoiding strain on {', '.join(i.replace('_', ' ') for i in p.injuries)}" if p.injuries else ""))
    return out


def budget_maths(udb) -> list[str]:
    """Every step from the person's answers to their daily food budget, in plain words."""
    from app.services import nutrition

    p, g = insights.get_profile(udb), insights.get_goals(udb)
    t = insights.targets_for(udb, date.today())
    age = nutrition.age_on(p.birth_year)
    out = [f"For {p.name or 'this profile'}: {p.sex}, {age} years, {p.height_cm:g} cm, {p.weight_kg:g} kg",
           f"Resting burn: {round(t.bmr):,} kcal/day (Mifflin–St Jeor formula)"]
    if not p.details_done:
        out.append("⚠ The About me questions haven't been answered for this profile yet, so this is the old estimate "
                   f"(× {nutrition.ACTIVITY_MULTIPLIERS.get(p.activity_level, 1.55)} activity, assumed).")
    else:
        mult = nutrition.DAILY_LIFE.get(p.activity_level, 1.2)
        out += [f"Everyday life: {round(t.bmr):,} × {mult} ({ACTIVITY_LABEL.get(p.activity_level, p.activity_level)}) = {round(t.bmr * mult):,} kcal",
                f"Workouts: {p.training_days} × {p.session_minutes} min a week ≈ {round(nutrition.workout_kcal_per_day(p)):,} kcal/day on average"]
    out.append(f"Total daily burn: {round(t.tdee):,} kcal")
    if g.calorie_target:
        out.append(f"⚠ A fixed limit of {round(g.calorie_target):,} kcal is set (from an earlier plan or weekly review), "
                   "so it's used instead of the calculation. Saving About me replaces it.")
    else:
        adj, capped = nutrition.goal_adjust(p, g)
        if p.goal == "maintain" or not adj:
            out.append(f"Goal: keep your weight → {round(t.calories):,} kcal/day")
        else:
            kg = abs((g.target_weight_kg or p.weight_kg) - p.weight_kg)
            out.append(f"Goal: {'lose' if adj < 0 else 'gain'} {kg:.1f} kg in {p.goal_weeks} weeks → {round(adj):+,} kcal/day "
                       f"(about {abs(adj) * 7 / nutrition.KCAL_PER_KG:.2f} kg a week{'; ' + capped if capped else ''})")
    out.append(f"Daily food budget: {round(t.calories):,} kcal")
    out.append(f"Protein: {round(t.protein_g)} g/day · carbs {round(t.carbs_g)} g · fat {round(t.fat_g)} g")
    return out


@router.get("/me/maths")
def my_maths(request: Request):
    with session_for(request_user(request)) as udb:
        return {"lines": budget_maths(udb)}


@router.post("")
def add_user(data: Details, request: Request, response: Response):
    data.check()
    with SessionLocal() as db:
        _ensure_first(db)
        ids = db.scalars(select(AppUser.id)).all()
        n = len(ids)
        # explicit id: profile 1 was inserted with a fixed id, so Postgres' counter can't be trusted
        _ensure_schemes(db)
        scheme = _free_scheme(db, "pink" if data.sex == "female" else "orange")
        u = AppUser(id=max(ids) + 1, name=data.name.strip(), color=SCHEMES[scheme], scheme=scheme)
        if data.favorite_color:
            _set_fav(u, data.favorite_color)
        db.add(u)
        db.commit()
        uid = u.id
    create_user_tables(uid)
    with session_for(uid) as udb:
        summary = apply_details(udb, data)
    _select(response, request, uid)
    return {"id": uid, "name": data.name.strip(), "summary": summary}


@router.put("/me")
def update_me(data: Details, request: Request):
    """The current person corrects or updates their answers; targets (and optionally the plan) are redone."""
    data.check()
    uid = request_user(request)
    with session_for(uid) as udb:
        summary = apply_details(udb, data)
    with SessionLocal() as db:
        _ensure_first(db)
        u = db.get(AppUser, uid)
        if u:
            u.name = data.name.strip()
            if data.favorite_color:
                _set_fav(u, data.favorite_color)
            db.commit()
    return {"id": uid, "summary": summary}


def _set_fav(u, said: str) -> None:
    """Theme this person's app in shades of their favourite colour."""
    u.color, u.scheme, u.fav_color = colors.resolve(said), "custom", said.strip()[:40]


class FavPick(BaseModel):
    color: str = Field(min_length=1, max_length=40)


@router.put("/me/favorite-color")
def set_favorite(data: FavPick, request: Request):
    uid = request_user(request)
    with SessionLocal() as db:
        _ensure_first(db)
        u = db.get(AppUser, uid)
        _set_fav(u, data.color)
        db.commit()
        return {"scheme": u.scheme, "color": u.color, "favorite_color": u.fav_color}


@router.get("/color")
def color_preview(name: str):
    """What colour a word means, for the live preview while typing."""
    return {"color": colors.resolve(name)}


class SchemePick(BaseModel):
    scheme: str


@router.put("/me/scheme")
def set_scheme(data: SchemePick, request: Request):
    if data.scheme not in SCHEMES:
        raise HTTPException(422, "Unknown colour scheme.")
    uid = request_user(request)
    with SessionLocal() as db:
        _ensure_first(db)
        taken = db.scalar(select(AppUser).where(AppUser.scheme == data.scheme, AppUser.id != uid))
        if taken:
            raise HTTPException(409, f"{taken.name} already uses that colour. Pick another.")
        u = db.get(AppUser, uid)
        u.scheme, u.color, u.fav_color = data.scheme, SCHEMES[data.scheme], ""
        db.commit()
        return {"scheme": u.scheme}


class Pick(BaseModel):
    id: int


@router.post("/select")
def select_user(data: Pick, request: Request, response: Response):
    with SessionLocal() as db:
        _ensure_first(db)
        u = db.get(AppUser, data.id)
        if u is None:
            raise HTTPException(404, "That person isn't in the app.")
        _select(response, request, u.id)
        return {"id": u.id, "name": u.name}


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.put("/{uid}")
def rename_user(uid: int, data: Rename):
    with SessionLocal() as db:
        _ensure_first(db)
        u = db.get(AppUser, uid)
        if u is None:
            raise HTTPException(404, "That person isn't in the app.")
        u.name = data.name.strip()
        db.commit()
        return {"id": u.id, "name": u.name}


def refresh_beginner_plans() -> int:
    """One-time update: generated plans for beginners at a full gym switch to machine/dumbbell versions.

    Hand-made plans (like the 13-week building-gym plan) are never touched. Returns how many were rebuilt.
    """
    from app.models import StoredSecret, WorkoutPlan
    from app.services.workout_planner import generate_plan

    marker, done = "plans:beginner-gym-v1", 0
    with SessionLocal() as db:
        ids = [u.id for u in db.scalars(select(AppUser)).all()] or [1]
    for uid in ids:
        with session_for(uid) as udb:
            if udb.get(StoredSecret, marker):
                continue
            p = insights.get_profile(udb)
            plan = udb.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))
            if plan and p.details_done and p.experience == "beginner" and p.equipment == "gym" and "days/week" in plan.name:
                new = generate_plan(goal=plan.goal, days_per_week=min(6, max(2, p.training_days)), weeks=plan.weeks,
                                    equipment="gym", experience="beginner",
                                    include_cardio=any(d.get("type") == "cardio" for d in plan.days),
                                    focus_areas=p.focus_areas or [], injuries=p.injuries or [],
                                    session_minutes=p.session_minutes or 60, **person_args(p))
                plan.days, plan.progression = new["days"], new["progression"]
                done += 1
            udb.add(StoredSecret(key=marker, value=date.today().isoformat()))
            udb.commit()
    return done
