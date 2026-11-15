from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activity, DailyStats, FoodEntry, WorkoutPlan
from app.routers.diet import day_totals, targets_for
from app.services.workout_planner import WEEKDAYS, readiness

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(day: date | None = None, db: Session = Depends(get_db)):
    day = day or date.today()
    _, targets = targets_for(db, day)
    consumed, _ = day_totals(db, day)
    stats = db.get(DailyStats, day)
    # fall back to yesterday's wellness data for readiness if today isn't synced yet
    ready_stats = stats or db.get(DailyStats, day - timedelta(days=1))

    week_start = day - timedelta(days=6)
    acts = db.scalars(
        select(Activity).where(Activity.start_time >= datetime.combine(week_start, datetime.min.time()),
                               Activity.start_time < datetime.combine(day + timedelta(days=1), datetime.min.time()))
        .order_by(Activity.start_time.desc())
    ).all()

    trend = []
    for i in range(13, -1, -1):
        d = day - timedelta(days=i)
        foods = db.scalars(select(FoodEntry.calories).where(FoodEntry.day == d)).all()
        s = db.get(DailyStats, d)
        trend.append({
            "day": d.isoformat(),
            "intake": round(sum(foods)),
            "burned": round(s.total_calories) if s and s.total_calories else None,
            "steps": s.steps if s else None,
        })

    plan = db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))
    today_session = None
    if plan:
        wd = WEEKDAYS[day.weekday()]
        today_session = next((d for d in plan.days if d.get("weekday") == wd), {"weekday": wd, "type": "rest", "title": "Rest day"})

    return {
        "day": day,
        "targets": targets.dict(),
        "consumed": {k: round(v) for k, v in consumed.items()},
        "stats": {c.name: getattr(stats, c.name) for c in DailyStats.__table__.columns} if stats else None,
        "readiness": readiness(ready_stats),
        "week": {
            "count": len(acts),
            "duration_min": round(sum(a.duration_s for a in acts) / 60),
            "distance_km": round(sum(a.distance_m or 0 for a in acts) / 1000, 1),
            "calories": round(sum(a.calories or 0 for a in acts)),
        },
        "recent_activities": [
            {"id": a.id, "name": a.name, "type": a.activity_type, "start_time": a.start_time,
             "duration_s": a.duration_s, "distance_m": a.distance_m, "calories": a.calories, "source": a.source}
            for a in acts[:5]
        ],
        "trend": trend,
        "today_session": today_session,
        "plan_name": plan.name if plan else None,
    }
