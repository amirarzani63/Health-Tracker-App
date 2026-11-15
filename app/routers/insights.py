from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import AutoSetupIn, GoalsIn, GoalsOut, ReminderIn, ReminderOut
from app.services import autosetup, insights
from app.services.garmin import GarminError, garmin_service

router = APIRouter(prefix="/api", tags=["goals & insights"])


@router.get("/goals", response_model=GoalsOut)
def read_goals(db: Session = Depends(get_db)):
    return insights.get_goals(db)


@router.put("/goals", response_model=GoalsOut)
def update_goals(data: GoalsIn, db: Session = Depends(get_db)):
    goals = insights.get_goals(db)
    for k, v in data.model_dump().items():
        setattr(goals, k, v)
    goals.saved = True
    db.commit()
    return goals


def garmin_svc():
    return garmin_service


@router.post("/setup/auto")
def auto_setup(data: AutoSetupIn, db: Session = Depends(get_db), svc=Depends(garmin_svc)):
    """Build profile, goals and an active workout plan from Garmin data + three quick choices."""
    client, note = None, None
    if svc.has_tokens():
        try:
            client = svc.client()
            svc.sync(db, days=30)  # enough history to judge training frequency and habits
        except GarminError as e:
            note = f"Couldn't read Garmin ({e}); used your existing data and defaults instead."
            client = None
    else:
        note = "Garmin isn't connected, so defaults were used. Connect Garmin and run setup again for personal values."
    result = autosetup.run_auto_setup(db, client, data.focus, data.equipment, data.diet_type)
    result["note"] = note
    return result


@router.get("/nutrition/trends")
def nutrition_trends(days: int = Query(30, ge=7, le=365), end: date | None = None, db: Session = Depends(get_db)):
    end = end or date.today()
    return insights.daily_series(db, end - timedelta(days=days - 1), end)


@router.get("/nutrition/weekly")
def nutrition_weekly(weeks: int = Query(8, ge=1, le=52), db: Session = Depends(get_db)):
    return insights.weekly_summaries(db, weeks)


@router.get("/recommendations")
def get_recommendations(day: date | None = None, db: Session = Depends(get_db)):
    return insights.recommendations(db, day)


@router.get("/progress/exercises")
def progress_exercises(db: Session = Depends(get_db)):
    return insights.exercise_index(db)


@router.get("/progress/exercise")
def progress_exercise(name: str, db: Session = Depends(get_db)):
    return insights.exercise_progress(db, name)


# ------------------------------------------------------------------ reminders
@router.get("/reminders", response_model=list[ReminderOut])
def list_reminders(db: Session = Depends(get_db)):
    return insights.get_reminders(db)


@router.put("/reminders", response_model=list[ReminderOut])
def update_reminders(data: list[ReminderIn], db: Session = Depends(get_db)):
    current = {r.key: r for r in insights.get_reminders(db)}
    for item in data:
        r = current[item.key]
        r.enabled, r.time = item.enabled, item.time
        r.days = sorted({d for d in item.days if 0 <= d <= 6})
    db.commit()
    return list(current.values())


@router.get("/reminders/due")
def due_reminders(now: datetime | None = None, db: Session = Depends(get_db)):
    """`now` is the browser's local time, so reminders follow the user's timezone."""
    return insights.due_reminders(db, (now or datetime.now()).replace(tzinfo=None))


class AckIn(BaseModel):
    day: date
    keys: list[str]


@router.post("/reminders/ack")
def ack_reminders(data: AckIn, db: Session = Depends(get_db)):
    valid = set(insights.DEFAULT_REMINDERS)
    if not set(data.keys) <= valid:
        raise HTTPException(400, "Unknown reminder")
    insights.ack_reminders(db, data.day, data.keys)
    return {"ok": True}
