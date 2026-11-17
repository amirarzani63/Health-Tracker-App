from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Activity, FoodEntry
from app.schemas import FoodIn, FoodOut
from app.services import food_db, insights, nutrition
from app.services.insights import get_profile

router = APIRouter(prefix="/api", tags=["diet"])


def day_totals(db: Session, day: date) -> tuple[dict, list[FoodEntry]]:
    entries = db.scalars(select(FoodEntry).where(FoodEntry.day == day).order_by(FoodEntry.created_at)).all()
    totals = {k: sum(getattr(e, k) or 0 for e in entries) for k in insights.MACROS}
    return totals, entries


def targets_for(db: Session, day: date):
    return get_profile(db), insights.targets_for(db, day)


@router.get("/foods", response_model=list[FoodOut])
def list_foods(day: date, db: Session = Depends(get_db)):
    return day_totals(db, day)[1]


@router.post("/foods", response_model=FoodOut)
def add_food(data: FoodIn, db: Session = Depends(get_db)):
    entry = FoodEntry(**data.model_dump())
    db.add(entry)
    db.commit()
    return entry


@router.delete("/foods/{entry_id}")
def delete_food(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(FoodEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Food entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.get("/food-library")
def food_library(q: str = "", db: Session = Depends(get_db)):
    profile = get_profile(db)
    banned = nutrition.EXCLUDED_BY_DIET.get(profile.diet_type, set()) | {a.lower().strip() for a in profile.allergies or []}
    return food_db.search(q, db, banned)


class MyFoodIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    unit: str = "1 serving"
    calories: float = Field(ge=0)
    protein_g: float = Field(0, ge=0)
    carbs_g: float = Field(0, ge=0)
    fat_g: float = Field(0, ge=0)
    fiber_g: float = Field(0, ge=0)


@router.post("/my-foods")
def save_my_food(data: MyFoodIn, db: Session = Depends(get_db)):
    """Remember a food the user typed in, so search and the calorie counter know it."""
    row = food_db.save_custom(db, data.name, data.unit, data.model_dump())
    return {"id": row.id, "name": row.name}


@router.get("/my-foods")
def list_my_foods(db: Session = Depends(get_db)):
    return [f.as_dict() for f in food_db.custom_foods(db)]


@router.get("/food-db/stats")
def food_db_stats(db: Session = Depends(get_db)):
    return {"builtin": len(food_db.builtin_foods()), "mine": len(food_db.custom_foods(db))}


@router.get("/nutrition/summary")
def nutrition_summary(day: date, db: Session = Depends(get_db)):
    _, targets = targets_for(db, day)
    totals, _ = day_totals(db, day)
    return {"day": day, "targets": targets.dict(), "consumed": {k: round(v) for k, v in totals.items()}}


@router.get("/nutrition/suggestions")
def diet_suggestions(day: date, db: Session = Depends(get_db)):
    profile, targets = targets_for(db, day)
    totals, entries = day_totals(db, day)
    result = nutrition.suggest_meals(profile, targets, totals, {e.meal for e in entries})
    day_start = datetime.combine(day, datetime.min.time())
    acts = db.scalars(select(Activity).where(Activity.start_time >= day_start,
                                             Activity.start_time < day_start + timedelta(days=1))).all()
    for a in acts:
        tip = nutrition.workout_fuel_tip(a.calories, a.duration_s)
        if tip:
            result["tips"].insert(0, tip)
            break
    result["targets"] = targets.dict()
    return result
