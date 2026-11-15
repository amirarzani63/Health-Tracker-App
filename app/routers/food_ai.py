from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FoodEntry
from app.schemas import FoodIn, FoodOut
from app.services.food_ai import MAX_IMAGE_BYTES, MAX_IMAGES, FoodAIError, ai_configured, food_analyzer

router = APIRouter(prefix="/api", tags=["calorie-counter"])

MEALS = {"breakfast", "lunch", "dinner", "snack"}


def analyzer():
    return food_analyzer


@router.get("/ai/status")
def ai_status():
    return {"configured": ai_configured()}


@router.post("/foods/analyze")
async def analyze_meal(
    description: str = Form(""),
    meal: str = Form(""),
    photos: list[UploadFile] = File(default=[]),
    svc=Depends(analyzer),
):
    """Estimate foods and macros from a description and/or photos. Nothing is saved."""
    if len(photos) > MAX_IMAGES:
        raise HTTPException(400, f"Up to {MAX_IMAGES} photos per meal.")
    images = []
    for photo in photos:
        data = await photo.read(MAX_IMAGE_BYTES + 1)
        if not data:
            continue
        images.append((data, (photo.content_type or "").lower()))
    try:
        return svc.analyze(description, images, meal if meal in MEALS else None)
    except FoodAIError as e:
        raise HTTPException(e.status, str(e))


class BulkFoodIn(BaseModel):
    items: list[FoodIn]


@router.post("/foods/bulk", response_model=list[FoodOut])
def add_foods(data: BulkFoodIn, db: Session = Depends(get_db)):
    if not data.items:
        raise HTTPException(400, "No items to add.")
    rows = [FoodEntry(**i.model_dump()) for i in data.items]
    db.add_all(rows)
    db.commit()
    return rows
