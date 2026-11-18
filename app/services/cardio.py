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
    "treadmill_walk": ("Treadmill walk (incline)", 5.0),
    "run": ("Jog / run outside", 7.0),
    "treadmill_run": ("Treadmill jog", 7.0),
    "bike": ("Upright exercise bike", 6.8),
    "recumbent": ("Recumbent bike", 5.5),
    "elliptical": ("Elliptical / cross-trainer", 5.0),
    "rower": ("Rowing machine", 6.0),
    "stairs": ("Stair climber", 8.0),
    "jump_rope": ("Rope skipping", 8.8),
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
