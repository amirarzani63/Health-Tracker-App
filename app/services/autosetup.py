"""One-tap setup: build the profile, goals and workout plan from Garmin data.

Garmin already knows your sex, height, weight, birth date, sleep schedule,
step goal, weekly intensity-minute goal and (optionally) goal weight, and
your synced activities show how often and how you train. The only things it
can't know are your main goal, where you train and how you eat; those come
from three quick choices, each with an "auto" option.

Everything Garmin provides is read defensively: missing or oddly shaped
fields are skipped and sensible defaults are used instead.
"""

import logging
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Activity, DailyStats, WeightEntry, WorkoutPlan
from app.services import insights
from app.services.workout_planner import generate_plan

log = logging.getLogger(__name__)

# focus -> (profile goal, plan goal)
FOCUS = {
    "lose_weight": ("lose", "fat_loss"),
    "build_muscle": ("gain", "hypertrophy"),
    "get_stronger": ("maintain", "strength"),
    "improve_cardio": ("maintain", "endurance"),
    "stay_healthy": ("maintain", "general"),
}
FOCUS_LABEL = {
    "lose_weight": "lose weight", "build_muscle": "build muscle", "get_stronger": "get stronger",
    "improve_cardio": "improve cardio", "stay_healthy": "stay healthy",
}
CARDIO_TYPES = ("run", "cycl", "bik", "swim", "walk", "hik", "row", "ski", "elliptical", "trail")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _kg(v):
    """Garmin reports weight in grams in most places; accept kg too."""
    v = _num(v)
    if v is None or v <= 0:
        return None
    return round(v / 1000, 1) if v > 500 else round(v, 1)


def _find_number(obj, keys):
    """Depth-first search for the first numeric value under any of ``keys``."""
    if isinstance(obj, dict):
        for k in keys:
            if _num(obj.get(k)) is not None:
                return _num(obj[k])
        for v in obj.values():
            found = _find_number(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_number(v, keys)
            if found is not None:
                return found
    return None


def read_garmin_profile(client, today: date) -> dict:
    """Collect what Garmin knows about the user. Every field is optional."""
    out: dict = {}

    def safe(fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # one failing endpoint shouldn't stop the rest
            log.info("Garmin %s unavailable: %s", getattr(fn, "__name__", fn), e)
            return None

    settings = safe(client.get_user_profile) or {}
    data = settings.get("userData") or {}
    gender = str(data.get("gender") or "").lower()
    if gender in ("male", "female"):
        out["sex"] = gender
    if _num(data.get("height")):
        out["height_cm"] = round(_num(data["height"]), 1)
    if _kg(data.get("weight")):
        out["weight_kg"] = _kg(data["weight"])
    birth = str(data.get("birthDate") or "")
    if len(birth) >= 4 and birth[:4].isdigit():
        out["birth_year"] = int(birth[:4])
    sleep = settings.get("userSleep") or {}
    bed, wake = _num(sleep.get("sleepTime")), _num(sleep.get("wakeTime"))
    if bed is not None and wake is not None:
        hours = ((wake - bed) % 86400) / 3600
        if 4 <= hours <= 12:
            out["sleep_target_h"] = round(hours * 2) / 2

    name = getattr(client, "full_name", None) or safe(getattr(client, "get_full_name", lambda: None))
    if isinstance(name, str) and name.strip():
        out["name"] = name.strip()

    latest = safe(client.get_latest_weight, today.isoformat()) if hasattr(client, "get_latest_weight") else None
    w = _kg(_find_number(latest, ("weight",))) if latest else None
    if w:
        out["weight_kg"] = w

    summary = safe(client.get_user_summary, today.isoformat()) or {}
    if _num(summary.get("dailyStepGoal")):
        out["steps_target"] = int(summary["dailyStepGoal"])
    if _num(summary.get("intensityMinutesGoal")):
        out["active_minutes_per_week"] = int(summary["intensityMinutesGoal"])

    if hasattr(client, "get_weight_goal"):
        goal = safe(client.get_weight_goal, (today - timedelta(days=30)).isoformat(), today.isoformat())
        gw = _kg(_find_number(goal, ("goalValue", "weightGoal", "targetValue", "goal")))
        if gw and 30 <= gw <= 300:
            out["target_weight_kg"] = gw
    return out


def training_history(db: Session, today: date, weeks: int = 4) -> dict:
    """Workouts per week, experience level and cardio/strength mix from synced activities."""
    since = datetime.combine(today - timedelta(weeks=weeks), datetime.min.time())
    acts = db.scalars(select(Activity).where(Activity.start_time >= since)).all()
    per_week = len(acts) / weeks
    kinds = Counter("cardio" if any(c in (a.activity_type or "") for c in CARDIO_TYPES) else "strength" for a in acts)
    steps = [s for s in db.scalars(select(DailyStats.steps).where(DailyStats.day >= today - timedelta(days=28))).all() if s]
    avg_steps = sum(steps) / len(steps) if steps else None
    return {
        "workouts_per_week": per_week,
        "cardio_share": kinds["cardio"] / len(acts) if acts else 0.0,
        "avg_steps": avg_steps,
        "count": len(acts),
    }


def _activity_level(avg_steps):
    if avg_steps is None:
        return None
    for limit, level in ((5000, "sedentary"), (7500, "light"), (10000, "moderate"), (12500, "active")):
        if avg_steps < limit:
            return level
    return "very_active"


def _experience(per_week: float) -> str:
    if per_week < 1.5:
        return "beginner"
    return "intermediate" if per_week < 4.5 else "advanced"


def infer_focus(garmin: dict, history: dict) -> str:
    current, target = garmin.get("weight_kg"), garmin.get("target_weight_kg")
    if current and target:
        if target < current - 1:
            return "lose_weight"
        if target > current + 1:
            return "build_muscle"
    if history["count"] >= 4 and history["cardio_share"] >= 0.7:
        return "improve_cardio"
    return "stay_healthy"


def run_auto_setup(db: Session, client, focus: str = "auto", equipment: str = "auto",
                   diet_type: str = "auto", today: date | None = None,
                   use_garmin_workouts: bool = True, send_to_watch: bool = False) -> dict:
    """Fill profile + goals and build an active plan. Returns a human-readable summary."""
    today = today or date.today()
    profile, goals = insights.get_profile(db), insights.get_goals(db)
    weight_known = profile.setup_done  # a weight the user entered earlier is real; the model default isn't
    garmin = read_garmin_profile(client, today) if client is not None else {}
    history = training_history(db, today)
    done: list[str] = []

    # ---- profile
    for field, label, unit in (("name", "Name", ""), ("sex", "Sex", ""), ("birth_year", "Birth year", ""),
                               ("height_cm", "Height", " cm"), ("weight_kg", "Weight", " kg")):
        if garmin.get(field) is not None:
            setattr(profile, field, garmin[field])
            done.append(f"{label}: {garmin[field]}{unit} (from Garmin)")
    level = _activity_level(history["avg_steps"])
    if level:
        profile.activity_level = level
    weekly = history["workouts_per_week"]
    profile.experience = _experience(weekly)
    done.append(f"Experience: {profile.experience} (about {weekly:.1f} workouts/week in your last 4 weeks)"
                if history["count"] else f"Experience: {profile.experience} (no workout history yet)")

    if focus not in FOCUS:
        focus = infer_focus(garmin, history)
        why = " (inferred from your Garmin goal weight)" if garmin.get("target_weight_kg") else " (default; change it any time)"
    else:
        why = ""
    profile.goal, plan_goal = FOCUS[focus]
    done.append(f"Main goal: {FOCUS_LABEL[focus]}{why}")
    if equipment in ("gym", "home", "bodyweight"):
        profile.equipment = equipment
    if diet_type in ("omnivore", "vegetarian", "vegan", "pescatarian"):
        profile.diet_type = diet_type

    days = max(2, min(6, round(weekly) if weekly >= 1.5 else 3))
    if focus == "lose_weight" and days < 4:
        days += 1  # a little more movement helps a deficit
    profile.training_days = days
    profile.setup_done = True

    # ---- goals (nutrition targets stay automatic: computed from profile + Garmin burn)
    goals.calorie_target = goals.protein_target_g = goals.carbs_target_g = goals.fat_target_g = None
    goals.workouts_per_week = days
    for field, label in (("steps_target", "Daily steps"), ("active_minutes_per_week", "Active minutes/week"),
                         ("sleep_target_h", "Sleep"), ("target_weight_kg", "Target weight")):
        if garmin.get(field) is not None:
            setattr(goals, field, garmin[field])
            done.append(f"{label}: {garmin[field]} (from Garmin)")
    weight_known = weight_known or garmin.get("weight_kg") is not None
    if goals.target_weight_kg is None and focus == "lose_weight" and weight_known:
        goals.target_weight_kg = round(profile.weight_kg * 0.93, 1)  # a realistic first milestone (~7%)
        done.append(f"Target weight: {goals.target_weight_kg} kg (first milestone, ~7% below today)")
    goals.follow_garmin = True
    goals.saved = True
    done.append(f"Workouts/week: {days}")

    if garmin.get("weight_kg"):
        entry = db.scalar(select(WeightEntry).where(WeightEntry.day == today, WeightEntry.source == "garmin"))
        if entry is None:
            db.add(WeightEntry(day=today, weight_kg=garmin["weight_kg"], source="garmin"))

    # ---- workout plan: your own saved Garmin workouts first, adapted to goal + equipment
    garmin_plan = None
    if client is not None and use_garmin_workouts:
        db.commit()  # profile/goals must be saved before the plan reads them
        try:
            from app.services.garmin_workouts import create_plan_from_garmin

            garmin_plan = create_plan_from_garmin(db, client, profile.goal, profile.equipment, days,
                                                  send_to_watch=send_to_watch)
        except Exception as e:
            log.warning("Building the plan from Garmin workouts failed: %s", e)
            done.append(f"Couldn't use your saved Garmin workouts ({e}); built a plan instead.")
    if garmin_plan:
        done.append(f"Workout plan from your Garmin workouts: {', '.join(garmin_plan['used'])}")
        done += [f"Adjusted: {c}" for c in garmin_plan["changes"][:8]]
        if len(garmin_plan["changes"]) > 8:
            done.append(f"…and {len(garmin_plan['changes']) - 8} more adjustments")
        p = garmin_plan["pushed"]
        if p:
            done.append(f"Sent to your fenix: {len(p['saved'])} workouts saved in Garmin Connect, "
                        f"{p['scheduled']} sessions on your Garmin calendar (next 2 weeks; kept topped up)")
            if p["errors"]:
                done.append(f"Some Garmin updates failed ({len(p['errors'])}); they'll be retried next time you run setup.")
    if not garmin_plan:
        if client is not None and use_garmin_workouts:
            done.append("No saved Garmin workouts found, so a plan was built for you.")
        _generated_plan(db, profile, plan_goal, days, history, done)
    db.commit()
    targets = insights.targets_for(db, today)
    done.append(f"Daily nutrition: ~{round(targets.calories)} kcal, {round(targets.protein_g)} g protein "
                + ("(recalculated every day from your Garmin burn)" if client is not None
                   else "(estimated; becomes exact once Garmin is connected)"))
    return {"focus": focus, "garmin_used": bool(garmin), "summary": done}


def _generated_plan(db, profile, plan_goal, days, history, done):
    plan = generate_plan(goal=plan_goal, days_per_week=days, weeks=6 if plan_goal in ("strength", "hypertrophy") else 4,
                         equipment=profile.equipment, experience=profile.experience,
                         include_cardio=plan_goal != "strength" or history["cardio_share"] > 0.3)
    db.execute(update(WorkoutPlan).values(active=False))
    db.add(WorkoutPlan(name=plan["name"], goal=plan["goal"], weeks=plan["weeks"], days=plan["days"],
                       progression=plan["progression"], active=True))
    done.append(f"Workout plan: {plan['name']}")


def refresh_from_sync(db: Session, today_summary: dict | None):
    """Keep things current after each sync: weight in the profile, goals that follow Garmin."""
    profile, goals = insights.get_profile(db), insights.get_goals(db)
    latest = db.scalar(select(WeightEntry).order_by(WeightEntry.day.desc(), WeightEntry.id.desc()).limit(1))
    if latest and abs(latest.weight_kg - profile.weight_kg) >= 0.05:
        profile.weight_kg = latest.weight_kg
    if goals.follow_garmin and today_summary:
        if _num(today_summary.get("dailyStepGoal")):
            goals.steps_target = int(today_summary["dailyStepGoal"])
        if _num(today_summary.get("intensityMinutesGoal")):
            goals.active_minutes_per_week = int(today_summary["intensityMinutesGoal"])
    db.flush()
