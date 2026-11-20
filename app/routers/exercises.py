from functools import lru_cache

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorkoutPlan
from app.services import exlib

router = APIRouter(prefix="/api", tags=["exercises"])

# Garmin exercise category -> body part shown in the picker
BODY_PARTS = {
    "Chest": ["BENCH_PRESS", "FLYE", "PUSH_UP"],
    "Back": ["ROW", "PULL_UP", "HYPEREXTENSION"],
    "Shoulders": ["SHOULDER_PRESS", "LATERAL_RAISE", "SHRUG", "SHOULDER_STABILITY"],
    "Arms": ["CURL", "TRICEPS_EXTENSION"],
    "Legs": ["SQUAT", "LUNGE", "DEADLIFT", "LEG_CURL", "CALF_RAISE"],
    "Glutes & hips": ["HIP_RAISE", "HIP_SWING", "HIP_STABILITY"],
    "Core": ["CORE", "CRUNCH", "PLANK", "SIT_UP", "LEG_RAISE", "CHOP"],
    "Full body": ["TOTAL_BODY", "OLYMPIC_LIFT", "PLYO", "CARRY", "SANDBAG", "SLED", "TIRE", "SLEDGE_HAMMER",
                  "BATTLE_ROPE", "LADDER", "SUSPENSION"],
    "Bands": ["BANDED_EXERCISES"],
    "Cardio & warm-up": ["CARDIO", "RUN", "RUN_INDOOR", "BIKE_OUTDOOR", "INDOOR_BIKE", "ELLIPTICAL",
                         "STAIR_STEPPER", "FLOOR_CLIMB", "WARM_UP"],
}


@lru_cache(maxsize=1)
def catalog() -> dict[str, list[str]]:
    try:
        from garminconnect.exercises import EXERCISES
    except Exception:  # pragma: no cover
        EXERCISES = []
    part_of = {cat: part for part, cats in BODY_PARTS.items() for cat in cats}
    groups: dict[str, set] = {p: set() for p in BODY_PARTS}
    for e in EXERCISES:
        groups[part_of.get(e["category"], "Full body")].add(e["name"])
    return {p: sorted(n) for p, n in groups.items() if n}


@router.get("/exercises")
def exercise_picker(db: Session = Depends(get_db)):
    """Exercises by body part for the workout logger, plus your plan's sessions and exercises first."""
    groups = catalog()
    lookup = {name.lower(): part for part, names in groups.items() for name in names}
    canonical = {name.lower(): name for names in groups.values() for name in names}
    plan = db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))
    mine: dict[str, list[str]] = {}
    sessions = []
    if plan:
        for d in plan.days:
            if d.get("type") in ("strength", "cardio") and d.get("title") not in sessions:
                sessions.append(d["title"])
            for x in d.get("exercises", []):
                name = canonical.get(x["exercise"].lower(), x["exercise"])  # Garmin's spelling when it's in the catalog
                part = lookup.get(name.lower(), "Full body")
                if name not in mine.setdefault(part, []):
                    mine[part].append(name)
    return {"body_parts": list(groups), "groups": groups, "plan_exercises": mine, "plan_sessions": sessions}


# ---------------------------------------------------------------- exercise photo library (free-exercise-db, public domain)
class _Names(BaseModel):
    names: list[str]


@router.post("/exlib/match")
def exlib_match(data: _Names):
    """Illustration, muscles and instructions for each exercise name (null when not found)."""
    return {"available": exlib.available(), "items": {n: exlib.match(n) for n in data.names[:200]}}


@router.get("/exlib/search")
def exlib_search(q: str = ""):
    return exlib.search(q)


@router.get("/exercise-videos")
def exercise_videos() -> dict:
    """Exercise name -> YouTube video id (one exact demonstration per exercise)."""
    from app.services.videos import VIDEOS
    return VIDEOS
