from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WeightEntry
from app.schemas import ProfileIn, ProfileOut, WeightIn, WeightOut
from app.services.insights import get_profile

router = APIRouter(prefix="/api", tags=["profile"])


@router.get("/profile", response_model=ProfileOut)
def read_profile(db: Session = Depends(get_db)):
    return get_profile(db)


@router.put("/profile", response_model=ProfileOut)
def update_profile(data: ProfileIn, db: Session = Depends(get_db)):
    profile = get_profile(db)
    for k, v in data.model_dump().items():
        setattr(profile, k, v)
    profile.setup_done = True
    db.commit()
    if (profile.name or "").strip():  # keep the name on the "Who's tracking?" list in step
        from app.db import SessionLocal, current_user
        from app.models import AppUser

        with SessionLocal() as reg:
            u = reg.get(AppUser, current_user.get())
            if u:
                u.name = profile.name.strip()[:60]
                reg.commit()
    return profile


@router.get("/weights", response_model=list[WeightOut])
def list_weights(limit: int = 180, db: Session = Depends(get_db)):
    rows = db.scalars(select(WeightEntry).order_by(WeightEntry.day.desc()).limit(limit)).all()
    return list(reversed(rows))


@router.post("/weights", response_model=WeightOut)
def add_weight(data: WeightIn, db: Session = Depends(get_db)):
    entry = db.scalar(select(WeightEntry).where(WeightEntry.day == data.day, WeightEntry.source == "manual"))
    entry = entry or WeightEntry(day=data.day, source="manual")
    entry.weight_kg, entry.body_fat_pct = data.weight_kg, data.body_fat_pct
    db.add(entry)
    # keep profile weight current so targets follow the latest weigh-in
    latest = db.scalar(select(WeightEntry.day).order_by(WeightEntry.day.desc()).limit(1))
    if latest is None or data.day >= latest:
        get_profile(db).weight_kg = data.weight_kg
    db.commit()
    return entry
