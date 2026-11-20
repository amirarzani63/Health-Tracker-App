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
