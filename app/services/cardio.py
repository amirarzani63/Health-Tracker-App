"""Cardio activities, their effort (MET) and calorie estimates.

MET values are for a steady, can-still-talk pace (Compendium of Physical Activities).
Calories = MET x 3.5 x body weight (kg) / 200 per minute.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardioLog
from app.services import nutrition

ACTIVITIES = {
    "walk": ("Fast walk outside", 4.3),
    "treadmill_walk_flat": ("Treadmill walk (flat, brisk)", 4.3),
    "treadmill_walk": ("Treadmill walk (incline)", 5.0),
    "run": ("Jog / run outside", 7.0),
    "treadmill_run": ("Treadmill jog", 7.0),
    "bike": ("Upright exercise bike", 6.8),
    "recumbent": ("Recumbent bike", 5.5),
    "elliptical": ("Elliptical / cross-trainer", 5.0),
    "rower": ("Rowing machine", 6.0),
    "stairs": ("Stair climber", 8.0),
    "jump_rope": ("Rope skipping", 8.8),
    # sports (Compendium of Physical Activities, 2011/2024)
    "tennis_singles": ("Tennis (singles)", 8.0),
    "tennis_doubles": ("Tennis (doubles)", 6.0),
    "padel": ("Padel", 6.0),
    "pickleball": ("Pickleball", 4.5),
    "badminton": ("Badminton (casual)", 5.5),
    "badminton_hard": ("Badminton (competitive)", 7.0),
    "squash": ("Squash", 7.3),
    "racquetball": ("Racquetball", 7.0),
    "table_tennis": ("Table tennis / ping pong", 4.0),
    "ski_downhill": ("Downhill skiing", 5.3),
    "ski_cross_country": ("Cross-country skiing", 9.0),
    "snowboarding": ("Snowboarding", 5.3),
    "ice_skating": ("Ice skating", 7.0),
    "ice_hockey": ("Ice hockey", 8.0),
    "snowshoeing": ("Snowshoeing", 5.3),
    "sledding": ("Sledding / tobogganing", 7.0),
    "snow_shoveling": ("Shoveling snow", 5.3),
    "swim_freestyle": ("Swimming: front crawl (easy–moderate)", 5.8),
    "swim_hard": ("Swimming: laps, fast", 9.8),
    "swim_breaststroke": ("Swimming: breaststroke", 5.3),
    "swim_backstroke": ("Swimming: backstroke", 4.8),
    "swim_leisure": ("Swimming: leisurely / playing", 6.0),
    "water_aerobics": ("Water aerobics / aqua fit", 5.5),
    "kayaking": ("Kayaking", 5.0),
    "canoeing": ("Canoeing", 5.8),
    "paddleboarding": ("Stand-up paddleboarding", 6.0),
    "rowing_boat": ("Rowing (boat)", 7.0),
    "surfing": ("Surfing", 3.0),
    "snorkeling": ("Snorkeling", 5.0),
    "water_polo": ("Water polo", 10.0),
    "yoga_hatha": ("Yoga: Hatha (gentle)", 2.5),
    "yoga_vinyasa": ("Yoga: Vinyasa / flow (sun salutations)", 3.3),
    "yoga_power": ("Yoga: Power / Ashtanga", 4.0),
    "yoga_yin": ("Yoga: Yin / restorative", 2.0),
    "water_skiing": ("Water skiing / wakeboarding", 6.0),
}


def calories(activity: str, minutes: float, weight_kg: float) -> float:
    return round(ACTIVITIES[activity][1] * 3.5 * weight_kg / 200 * minutes)


def resting_burn(profile, day: date) -> float:
    """Calories the body uses on a normal day without exercise (BMR x 1.2)."""
    bmr = nutrition.bmr_mifflin(profile.sex, profile.weight_kg, profile.height_cm,
                                nutrition.age_on(profile.birth_year, day))
    return round(bmr * 1.2)


def logged(db: Session, start: date, end: date) -> dict[date, float]:
    out: dict[date, float] = {}
    for r in db.scalars(select(CardioLog).where(CardioLog.day >= start, CardioLog.day <= end)):
        out[r.day] = out.get(r.day, 0) + r.calories
    return out


STRENGTH_MET = 5.0  # weight training, moderate-to-vigorous with short rests (Compendium of Physical Activities)


def _minutes(text: str) -> float:
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*min", str(text or ""))
    return float(m.group(1)) if m else 0.0


def planned_workout_kcal(db: Session, start: date, end: date, done: dict, profile) -> dict[date, float]:
    """Calories from planned workouts marked done (✓) that weren't logged as cardio.

    Strength days: the whole session (lifting + any cardio finisher) at ~5 METs; if cardio was also logged
    that day, only the lifting part counts so nothing is counted twice. Cardio days ticked done without a
    cardio log count their planned minutes at ~5 METs.
    """
    from datetime import timedelta

    from app.models import WorkoutPlan
    plan = db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))
    if not plan or not profile or not profile.weight_kg:
        return {}
    by_wd = {d.get("weekday"): d for d in plan.days or []}
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    logged_days = set(logged(db, start, end))
    per_min = STRENGTH_MET * 3.5 * profile.weight_kg / 200
    out: dict[date, float] = {}
    d = start
    while d <= end:
        day = by_wd.get(names[d.weekday()])
        if done.get(d.isoformat()) is True and day:
            if day.get("type") == "strength":
                exs = day.get("exercises") or []
                cardio_min = sum(_minutes(e.get("reps")) for e in exs if e.get("pattern") == "cardio")
                total = day.get("minutes") or (len([e for e in exs if e.get("pattern") != "cardio"]) * 8 + cardio_min)
                mins = total - cardio_min if d in logged_days else total
                out[d] = round(per_min * max(0, mins))
            elif day.get("type") == "cardio" and d not in logged_days:
                out[d] = round(per_min * (day.get("minutes") or 0))
        d += timedelta(days=1)
    return out


# ---- the whole day's burn, part by part -------------------------------------------------------
WALKING = {"walk": 110, "treadmill_walk_flat": 115, "treadmill_walk": 110, "run": 160, "treadmill_run": 160,
           "snowshoeing": 100}  # steps per minute counted by a phone/watch during these activities
TEF = 0.10  # digesting food uses ~10% of the day's energy (thermic effect of food)


def stride_m(profile) -> float:
    """Walking stride from height (~41.5% of height for men, 41.3% for women)."""
    return (profile.height_cm or 170) * (0.413 if profile.sex == "female" else 0.415) / 100


def steps_kcal(profile, steps: float) -> float:
    """Net calories from walking: ACSM walking equation, 0.1 ml O2 per kg per metre = 0.5 kcal per kg per km."""
    return 0.5 * profile.weight_kg * steps * stride_m(profile) / 1000


def rows_between(db: Session, start: date, end: date) -> dict[date, list]:
    out: dict[date, list] = {}
    for r in db.scalars(select(CardioLog).where(CardioLog.day >= start, CardioLog.day <= end)):
        out.setdefault(r.day, []).append(r)
    return out


def day_parts(profile, day: date, steps: float | None, cardio_rows: list, workout_kcal: float, other_kcal: float) -> dict:
    """Every part of the day's calorie burn.

    resting  = BMR (Mifflin-St Jeor): breathing, heartbeat, organs
    digestion = 10% thermic effect of food
    steps    = net cost of the steps walked (minus steps already counted inside logged walks/runs)
    movement = when no steps are logged: a light-activity allowance (BMR x 0.1) instead
    workouts = planned workouts marked done (weights at ~5 METs)
    cardio   = cardio and sports logged, by activity and minutes (Compendium METs)
    other    = workouts logged with their own calorie number
    """
    bmr = nutrition.bmr_mifflin(profile.sex, profile.weight_kg, profile.height_cm, nutrition.age_on(profile.birth_year, day))
    cardio_kcal = sum(r.calories for r in cardio_rows)
    parts = {"resting": round(bmr), "digestion": round(bmr * TEF), "steps": 0, "movement": 0,
             "workouts": round(workout_kcal), "cardio": round(cardio_kcal), "other": round(other_kcal)}
    if steps:
        in_cardio = sum(WALKING.get(r.activity, 0) * r.minutes for r in cardio_rows)
        parts["steps"] = round(steps_kcal(profile, max(0, steps - in_cardio)))
        parts["steps_counted"] = int(max(0, steps - in_cardio))
    else:
        parts["movement"] = round(bmr * 0.1)
    parts["total"] = sum(v for k, v in parts.items() if k in ("resting", "digestion", "steps", "movement", "workouts", "cardio", "other"))
    parts["exercise"] = parts["workouts"] + parts["cardio"] + parts["other"]
    return parts
