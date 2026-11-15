from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.garmin import service as garmin_service_dep
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorkoutPlan
from app.services.insights import get_profile
from app.schemas import PlanOut, PlanRequest
from app.services.workout_planner import generate_plan

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db)):
    return db.scalars(select(WorkoutPlan).order_by(WorkoutPlan.created_at.desc())).all()


@router.get("/active", response_model=PlanOut | None)
def active_plan(db: Session = Depends(get_db)):
    return db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))


@router.post("/generate", response_model=PlanOut)
def create_plan(req: PlanRequest, db: Session = Depends(get_db)):
    profile = get_profile(db)
    plan = generate_plan(
        goal=req.goal,
        days_per_week=req.days_per_week or profile.training_days,
        weeks=req.weeks,
        equipment=req.equipment or profile.equipment,
        experience=req.experience or profile.experience,
        include_cardio=req.include_cardio,
    )
    db.execute(update(WorkoutPlan).values(active=False))
    row = WorkoutPlan(name=plan["name"], goal=plan["goal"], weeks=plan["weeks"],
                      days=plan["days"], progression=plan["progression"], active=True)
    db.add(row)
    db.commit()
    return row


@router.post("/{plan_id}/activate", response_model=PlanOut)
def activate_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(WorkoutPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.execute(update(WorkoutPlan).values(active=False))
    plan.active = True
    db.commit()
    return plan


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.get(WorkoutPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.delete(plan)
    db.commit()
    return {"ok": True}


WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class MoveIn(BaseModel):
    from_day: str
    to_day: str


@router.post("/{plan_id}/move", response_model=PlanOut)
def move_session(plan_id: int, data: MoveIn, db: Session = Depends(get_db), garmin=Depends(garmin_service_dep)):
    """Move a session to another weekday; whatever was on that day swaps into its place."""
    if data.from_day not in WEEK or data.to_day not in WEEK:
        raise HTTPException(400, "Unknown day")
    plan = db.get(WorkoutPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    days = [dict(d) for d in plan.days]
    for d in days:
        if d.get("weekday") == data.from_day:
            d["weekday"] = data.to_day
        elif d.get("weekday") == data.to_day:
            d["weekday"] = data.from_day
    days.sort(key=lambda d: WEEK.index(d.get("weekday", "Sun")))
    plan.days = days
    flag_modified(plan, "days")
    db.commit()
    result = {}
    if plan.active:
        try:  # keep the Garmin calendar on the watch in step
            from app.services import garmin_workouts

            svc = garmin
            if svc.has_tokens():
                result = garmin_workouts.swap_weekdays(db, svc.client(), data.from_day, data.to_day)
        except Exception as e:
            result = {"errors": [str(e)]}
    plan.__dict__["garmin"] = result
    return plan
