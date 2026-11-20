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


# ---------------------------------------------------------------- water, counted in glasses
from app.models import WaterLog  # noqa: E402

GLASS_ML = 250


def water_goal(db: Session) -> int:
    """About 30 ml per kg of body weight, in 250 ml glasses (8 to 12)."""
    kg = get_profile(db).weight_kg or 75
    return max(8, min(12, round(kg * 30 / GLASS_ML)))


class WaterIn(BaseModel):
    day: date
    change: int = Field(0, ge=-20, le=20)


@router.get("/water")
def get_water(day: date, db: Session = Depends(get_db)) -> dict:
    row = db.get(WaterLog, day)
    return {"day": day, "glasses": row.glasses if row else 0, "goal": water_goal(db), "glass_ml": GLASS_ML}


@router.post("/water")
def add_water(data: WaterIn, db: Session = Depends(get_db)) -> dict:
    row = db.get(WaterLog, data.day) or WaterLog(day=data.day, glasses=0)
    row.glasses = max(0, min(40, row.glasses + data.change))
    db.add(row)
    db.commit()
    return get_water(data.day, db)


# ---------------------------------------------------------------- steps typed in by hand
from app.models import DailyStats, StepLog  # noqa: E402


class StepsIn(BaseModel):
    day: date
    steps: int = Field(ge=0, le=200000)


@router.get("/steps")
def get_steps(day: date, db: Session = Depends(get_db)) -> dict:
    row, g = db.get(StepLog, day), db.get(DailyStats, day)
    return {"day": day, "typed": row.steps if row else None, "garmin": g.steps if g else None}


@router.post("/steps")
def set_steps(data: StepsIn, db: Session = Depends(get_db)) -> dict:
    row = db.get(StepLog, data.day) or StepLog(day=data.day)
    row.steps = data.steps
    db.add(row)
    db.commit()
    return get_steps(data.day, db)


# ---------------------------------------------------------------- sleep and calories burned typed in by hand
from app.models import DayLog  # noqa: E402


class DayLogIn(BaseModel):
    day: date
    sleep_h: float | None = Field(None, ge=0, le=24)
    burned: float | None = Field(None, ge=0, le=10000)


@router.get("/day-log")
def get_day_log(day: date, db: Session = Depends(get_db)) -> dict:
    row, g = db.get(DayLog, day), db.get(DailyStats, day)
    return {"day": day, "sleep_h": row.sleep_h if row else None, "burned": row.burned if row else None,
            "garmin_sleep_h": round(g.sleep_s / 3600, 1) if g and g.sleep_s else None,
            "garmin_burned": round(g.total_calories) if g and g.total_calories else None}


@router.post("/day-log")
def set_day_log(data: DayLogIn, db: Session = Depends(get_db)) -> dict:
    row = db.get(DayLog, data.day) or DayLog(day=data.day)
    for k in data.model_fields_set - {"day"}:
        setattr(row, k, getattr(data, k))
    db.add(row)
    db.commit()
    return get_day_log(data.day, db)


# ---------------------------------------------------------------- weekly review + weekly meal plan
from app.services import weekly  # noqa: E402


@router.get("/weekly")
def weekly_summary(db: Session = Depends(get_db)) -> dict:
    review = weekly.run_weekly(db)
    plan = weekly.meal_plan(db)
    return {"review": review, "meal_plan": plan, "shopping_list": weekly.shopping_list(plan)}



# ---------------------------------------------------------------- cardio done (activity + minutes -> calories)
from app.models import CardioLog  # noqa: E402
from app.services import cardio as cardio_svc  # noqa: E402


class CardioIn(BaseModel):
    day: date
    activity: str
    minutes: int = Field(ge=1, le=600)


def _cardio_day(db: Session, day: date) -> dict:
    rows = db.scalars(select(CardioLog).where(CardioLog.day == day).order_by(CardioLog.id)).all()
    return {"day": day, "items": [{"id": r.id, "activity": r.activity, "label": cardio_svc.ACTIVITIES[r.activity][0],
                                   "minutes": r.minutes, "calories": round(r.calories)} for r in rows],
            "total_minutes": sum(r.minutes for r in rows), "total_calories": round(sum(r.calories for r in rows)),
            "resting": cardio_svc.resting_burn(get_profile(db), day)}


@router.get("/cardio-log")
def get_cardio_log(day: date, db: Session = Depends(get_db)) -> dict:
    return _cardio_day(db, day)


@router.post("/cardio-log")
def add_cardio_log(data: CardioIn, db: Session = Depends(get_db)) -> dict:
    if data.activity not in cardio_svc.ACTIVITIES:
        raise HTTPException(422, "Unknown cardio activity")
    kg = get_profile(db).weight_kg or 80
    db.add(CardioLog(day=data.day, activity=data.activity, minutes=data.minutes,
                     calories=cardio_svc.calories(data.activity, data.minutes, kg)))
    db.commit()
    return _cardio_day(db, data.day)


@router.delete("/cardio-log/{item_id}")
def delete_cardio_log(item_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CardioLog, item_id)
    if not row:
        raise HTTPException(404, "Not found")
    day = row.day
    db.delete(row)
    db.commit()
    return _cardio_day(db, day)
