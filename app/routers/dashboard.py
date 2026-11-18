from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activity, DailyStats, Goals, WorkoutPlan
from app.routers.diet import day_totals
from app.services import insights
from app.services.garmin import garmin_service
from app.services.workout_planner import readiness

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(day: date | None = None, db: Session = Depends(get_db)):
    day = day or date.today()
    targets = insights.targets_for(db, day)
    consumed, _ = day_totals(db, day)
    stats = db.get(DailyStats, day)
    # fall back to yesterday's wellness data for readiness if today isn't synced yet
    ready_stats = stats or db.get(DailyStats, day - timedelta(days=1))

    trend = insights.daily_series(db, day - timedelta(days=13), day)
    week = trend[-7:]
    acts = insights.activities_between(db, day - timedelta(days=6), day)
    plan, session = insights.todays_session(db, day)
    goals = db.get(Goals, 1)
    profile = insights.get_profile(db)

    return {
        "day": day,
        "targets": targets.dict(),
        "consumed": {k: round(v) for k, v in consumed.items()},
        "burned": trend[-1]["burned"],
        "cardio_kcal": trend[-1]["cardio_kcal"],
        "burn_source": trend[-1]["burn_source"],
        "active_calories": round(stats.active_calories) if stats and stats.active_calories else None,
        "stats": {c.name: getattr(stats, c.name) for c in DailyStats.__table__.columns} if stats else None,
        "readiness": readiness(ready_stats),
        "goals": insights.goal_progress(db, day),
        "week": {
            "count": len(acts),
            "duration_min": round(sum(a.duration_s for a in acts) / 60),
            "distance_km": round(sum(a.distance_m or 0 for a in acts) / 1000, 1),
            "calories": round(sum(a.calories or 0 for a in acts)),
            "days_logged": sum(1 for d in week if d["logged"]),
        },
        "recent_activities": [
            {"id": a.id, "name": a.name, "type": a.activity_type, "start_time": a.start_time,
             "duration_s": a.duration_s, "distance_m": a.distance_m, "calories": a.calories, "source": a.source}
            for a in sorted(acts, key=lambda a: a.start_time, reverse=True)[:5]
        ],
        "trend": trend,
        "today_session": session,
        "today_done": any(a.start_time.date() == day for a in acts) or insights.checkins(db).get(day.isoformat()) is True,
        "next_session": insights.upcoming_session(db, day),
        "plan_name": plan.name if plan else None,
        "plan_id": plan.id if plan else None,
        "recommendations": insights.recommendations(db, day)[:4],
        "setup": {
            "profile": profile.setup_done,
            "goals": bool(goals and goals.saved),
            "garmin": garmin_service.has_tokens(),
            "plan": db.scalar(select(WorkoutPlan.id).limit(1)) is not None,
            "food": db.scalar(select(Activity.id).limit(1)) is not None or any(d["logged"] for d in trend),
        },
    }
