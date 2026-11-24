from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.garmin import service as garmin_service_dep
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorkoutPlan
from app.services.insights import get_profile
from app.schemas import PlanOut, PlanRequest
from app.services.workout_planner import generate_plan

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _with_loads(plan: WorkoutPlan | None, db: Session) -> dict | None:
    """The plan with a suggested starting weight on each exercise, worked out for this person."""
    if plan is None:
        return None
    from app.services.loads import add_loads
    out = PlanOut.model_validate(plan).model_dump()
    prof = get_profile(db)
    out["days"] = _your_sets(add_loads(plan.days or [], prof, plan.goal), db)
    from app.services.cardio import workout_kcal
    for d in out["days"]:  # calories from the real session length and this person's weight
        if d.get("type") in ("strength", "cardio"):
            d["est_kcal"] = round(workout_kcal(d, prof.weight_kg or 75))
    return out


TOO_HARD = {"Pull-up / negative"}  # needs the strength to lower yourself slowly from the bar


def _easier_pulls(days: list, db: Session) -> list:
    """Swap moves most people can't do yet for an easier one that works the same muscles (lats / upper back)."""
    from app.services.workout_planner import equipment_set
    prof = get_profile(db)
    have = equipment_set(prof.equipment or "gym", prof.equipment_list or [])
    # easier moves for the lats / upper back, best first, that this person has the equipment for
    easy = [n for n, need in (("Lat pulldown", {"cable"}), ("Band lat pulldown", {"bands"}),
                              ("One-arm dumbbell row", {"dumbbells"}), ("Superman pull", set())) if need <= have]
    out = []
    for d in days:
        names = {e.get("exercise") for e in d.get("exercises", [])}
        exs = []
        for e in d.get("exercises", []):
            if e.get("exercise") in TOO_HARD:
                swap = next((n for n in easy if n not in names), None)
                if swap:
                    e = {**e, "exercise": swap, "swapped_from": e["exercise"]}
                    names.add(swap)
            exs.append(e)
        out.append({**d, "exercises": exs})
    return out


def _your_sets(days: list, db: Session) -> list:
    """If you've been doing more sets of an exercise than the plan says, the plan shows what you actually do."""
    from datetime import datetime, timedelta
    from app.models import Activity
    done: dict[str, int] = {}
    since = datetime.now() - timedelta(days=60)
    for a in db.scalars(select(Activity).where(Activity.start_time >= since).order_by(Activity.start_time.desc())):
        per: dict[str, int] = {}
        for st in a.sets or []:
            n = (st.get("exercise") or "").strip().lower()
            if n:
                per[n] = per.get(n, 0) + 1
        for n, c in per.items():
            done.setdefault(n, c)  # newest session wins
    from app.services.workout_planner import normalize_day
    days = [normalize_day(d) for d in days]  # 3 sets each, and the real session length
    days = _easier_pulls(days, db)
    for d in days:
        for e in d.get("exercises", []):
            n = (e.get("exercise") or "").strip().lower()
            if e.get("pattern") != "cardio" and done.get(n, 0) > (e.get("sets") or 0):
                e["sets"], e["sets_note"] = min(done[n], 6), "what you did last time"
                d["_more"] = True
    return [normalize_day({k: v for k, v in d.items() if k != "_more"}) if d.get("_more") else d for d in days]


@router.get("", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db)):
    return [_with_loads(p, db) for p in db.scalars(select(WorkoutPlan).order_by(WorkoutPlan.created_at.desc())).all()]


@router.get("/active", response_model=PlanOut | None)
def active_plan(db: Session = Depends(get_db)):
    return _with_loads(db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc())), db)


@router.post("/generate", response_model=PlanOut)
def create_plan(req: PlanRequest, db: Session = Depends(get_db)):
    profile = get_profile(db)
    plan = generate_plan(
        goal=req.goal,
        days_per_week=req.days_per_week or profile.training_days,
        weeks=req.weeks,
        equipment=req.equipment or profile.equipment,
        experience=req.experience or profile.experience,
        include_cardio=req.include_cardio,
    )
    db.execute(update(WorkoutPlan).values(active=False))
    row = WorkoutPlan(name=plan["name"], goal=plan["goal"], weeks=plan["weeks"],
                      days=plan["days"], progression=plan["progression"], active=True)
    db.add(row)
    db.commit()
    return row


@router.post("/{plan_id}/activate", response_model=PlanOut)
def activate_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(WorkoutPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.execute(update(WorkoutPlan).values(active=False))
    plan.active = True
    db.commit()
    return plan


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(WorkoutPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.delete(plan)
    db.commit()
    return {"ok": True}


WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class MoveIn(BaseModel):
    from_day: str
    to_day: str


@router.post("/{plan_id}/move", response_model=PlanOut)
def move_session(plan_id: int, data: MoveIn, db: Session = Depends(get_db), garmin=Depends(garmin_service_dep)):
    """Move a session to another weekday; whatever was on that day swaps into its place."""
    if data.from_day not in WEEK or data.to_day not in WEEK:
        raise HTTPException(400, "Unknown day")
    plan = db.get(WorkoutPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    days = [dict(d) for d in plan.days]
    for d in days:
        if d.get("weekday") == data.from_day:
            d["weekday"] = data.to_day
        elif d.get("weekday") == data.to_day:
            d["weekday"] = data.from_day
    days.sort(key=lambda d: WEEK.index(d.get("weekday", "Sun")))
    plan.days = days
    flag_modified(plan, "days")
    db.commit()
    result = {}
    if plan.active:
        try:  # keep the Garmin calendar on the watch in step
            from app.services import garmin_workouts

            svc = garmin
            if svc.has_tokens():
                result = garmin_workouts.swap_weekdays(db, svc.client(), data.from_day, data.to_day)
        except Exception as e:
            result = {"errors": [str(e)]}
    plan.__dict__["garmin"] = result
    return plan


# ---- "Did you complete today's workout?" answers, per calendar date ----
import json as _json
from datetime import date as _date

from app.models import StoredSecret

_CHECKINS = "workout_checkins"


def _load_checkins(db: Session) -> dict:
    row = db.get(StoredSecret, _CHECKINS)
    try:
        return _json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


class CheckIn(BaseModel):
    day: _date
    done: bool | None  # None clears the answer


@router.get("/checkins/all")
def get_checkins(db: Session = Depends(get_db)) -> dict:
    """Done/missed per date: the user's answers plus what the app works out from their logs."""
    from app.services.insights import workout_status
    return workout_status(db)


@router.post("/checkins/all")
def set_checkin(data: CheckIn, db: Session = Depends(get_db)) -> dict:
    marks = _load_checkins(db)
    if data.done is None:
        marks.pop(data.day.isoformat(), None)
    else:
        marks[data.day.isoformat()] = data.done
    row = db.get(StoredSecret, _CHECKINS) or StoredSecret(key=_CHECKINS)
    row.value = _json.dumps(marks)
    db.add(row)
    db.commit()
    return marks


# ---- which cardio activity the user picked for a day ("default" = for every cardio day) ----
_CARDIO = "cardio_choices"
from app.services.cardio import ACTIVITIES as _ACTS

CARDIO_KEYS = set(_ACTS)


class CardioItem(BaseModel):
    activity: str
    minutes: int = Field(ge=1, le=300)


class CardioPick(BaseModel):
    day: str  # YYYY-MM-DD or "default"
    activity: str | list[CardioItem] | None  # one activity, or several with minutes each


@router.get("/cardio/all")
def get_cardio(db: Session = Depends(get_db)) -> dict:
    row = db.get(StoredSecret, _CARDIO)
    try:
        return _json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


@router.post("/cardio/all")
def set_cardio(data: CardioPick, db: Session = Depends(get_db)) -> dict:
    if data.day != "default":
        _date.fromisoformat(data.day)
    items = data.activity if isinstance(data.activity, list) else []
    if isinstance(data.activity, str) and data.activity not in CARDIO_KEYS or any(i.activity not in CARDIO_KEYS for i in items):
        raise HTTPException(422, "Unknown cardio activity")
    if isinstance(data.activity, list) and not items:
        data.activity = None
    picks = get_cardio(db)
    if data.activity is None:
        picks.pop(data.day, None)
    else:
        picks[data.day] = [i.model_dump() for i in items] if items else data.activity
    row = db.get(StoredSecret, _CARDIO) or StoredSecret(key=_CARDIO)
    row.value = _json.dumps(picks)
    db.add(row)
    db.commit()
    return picks
