from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import GarminLoginIn, GarminMfaIn, GarminSyncIn
from app.services.garmin import GarminError, garmin_service

router = APIRouter(prefix="/api/garmin", tags=["garmin"])


def service():
    return garmin_service


@router.get("/status")
def status(db: Session = Depends(get_db), svc=Depends(service)):
    return svc.status(db)


@router.post("/login")
def login(data: GarminLoginIn, svc=Depends(service)):
    try:
        return svc.login(data.email, data.password)
    except GarminError as e:
        raise HTTPException(401, str(e))


@router.post("/mfa")
def mfa(data: GarminMfaIn, svc=Depends(service)):
    try:
        return svc.submit_mfa(data.code.strip())
    except GarminError as e:
        raise HTTPException(401, str(e))


@router.post("/sync")
def sync(data: GarminSyncIn, db: Session = Depends(get_db), svc=Depends(service)):
    try:
        return svc.sync(db, days=data.days)
    except GarminError as e:
        raise HTTPException(400, str(e))


class StaleSyncIn(BaseModel):
    max_age_minutes: int = Field(60, ge=5, le=1440)


@router.post("/sync-if-stale")
def sync_if_stale(data: StaleSyncIn, db: Session = Depends(get_db), svc=Depends(service)):
    """Called when the app opens: pulls the last 2 days if the last sync is older than max_age."""
    status = svc.status(db)
    if not status["connected"]:
        return {"synced": False, "reason": "not_connected"}
    last = status["last_sync"]
    if last and datetime.fromisoformat(last) > datetime.now() - timedelta(minutes=data.max_age_minutes):
        return {"synced": False, "reason": "fresh"}
    try:
        return {"synced": True, **svc.sync(db, days=2)}
    except GarminError as e:
        return {"synced": False, "reason": "error", "error": str(e)}


@router.post("/logout")
def logout(svc=Depends(service)):
    svc.logout()
    return {"ok": True}
