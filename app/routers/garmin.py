from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import GarminLoginIn, GarminMfaIn, GarminSyncIn
from app.services import garmin_workouts
from app.services.garmin import GarminError, garmin_service
from app.services.insights import get_goals, get_profile

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


@router.get("/workouts")
def saved_workouts(svc=Depends(service)):
    """Your saved Garmin Connect workouts (newest first)."""
    try:
        return garmin_workouts.list_saved_workouts(svc.client())
    except GarminError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Couldn't read your Garmin workouts: {e}")


class GarminPlanIn(BaseModel):
    workout_ids: list[int | str] = []
    days_per_week: int | None = Field(None, ge=2, le=6)
    send_to_watch: bool = True


@router.post("/plan-from-workouts")
def plan_from_workouts(data: GarminPlanIn, db: Session = Depends(get_db), svc=Depends(service)):
    profile, goals = get_profile(db), get_goals(db)
    try:
        client = svc.client()
        result = garmin_workouts.create_plan_from_garmin(
            db, client, profile.goal, profile.equipment, data.days_per_week or goals.workouts_per_week or 4,
            data.workout_ids, data.send_to_watch)
    except GarminError as e:
        raise HTTPException(400, str(e))
    if result is None:
        raise HTTPException(404, "No saved workouts found in your Garmin Connect account.")
    return result


@router.get("/watch-plan")
def watch_plan_status(db: Session = Depends(get_db)):
    s = garmin_workouts.load_state(db)
    return {"sending": bool(s.get("push")), "scheduled_until": s.get("scheduled_until"),
            "workouts": len(s.get("copies", {}))}


@router.post("/watch-plan/stop")
def stop_watch_plan(db: Session = Depends(get_db), svc=Depends(service)):
    try:
        removed = garmin_workouts.stop_pushing(db, svc.client())
    except GarminError as e:
        raise HTTPException(400, str(e))
    return {"removed": removed}


@router.post("/logout")
def logout(svc=Depends(service)):
    svc.logout()
    return {"ok": True}
