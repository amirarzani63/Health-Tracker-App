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
