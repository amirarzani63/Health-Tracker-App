from fastapi import APIRouter, Depends, HTTPException
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
