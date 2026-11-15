from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/logout")
def logout(svc=Depends(service)):
    svc.logout()
    return {"ok": True}
