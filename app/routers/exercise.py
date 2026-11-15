from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activity, DailyStats
from app.schemas import ActivityIn, ActivityOut, DailyStatsOut

router = APIRouter(prefix="/api", tags=["exercise"])


@router.get("/activities", response_model=list[ActivityOut])
def list_activities(start: date | None = None, end: date | None = None, limit: int = 100,
                    db: Session = Depends(get_db)):
    q = select(Activity).order_by(Activity.start_time.desc())
    if start:
        q = q.where(Activity.start_time >= datetime.combine(start, datetime.min.time()))
    if end:
        q = q.where(Activity.start_time < datetime.combine(end + timedelta(days=1), datetime.min.time()))
    return db.scalars(q.limit(limit)).all()


@router.post("/activities", response_model=ActivityOut)
def add_activity(data: ActivityIn, db: Session = Depends(get_db)):
    payload = data.model_dump()
    act = Activity(source="manual", **payload)
    db.add(act)
    db.commit()
    return act


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int, db: Session = Depends(get_db)):
    act = db.get(Activity, activity_id)
    if not act:
        raise HTTPException(404, "Activity not found")
    db.delete(act)
    db.commit()
    return {"ok": True}


@router.get("/daily-stats", response_model=list[DailyStatsOut])
def list_daily_stats(days: int = 30, db: Session = Depends(get_db)):
    since = date.today() - timedelta(days=days - 1)
    return db.scalars(select(DailyStats).where(DailyStats.day >= since).order_by(DailyStats.day)).all()
