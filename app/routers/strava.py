from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import is_https
from app.db import get_db
from app.services.strava import StravaError, strava_service

router = APIRouter(prefix="/api/strava", tags=["strava"])


def service():
    return strava_service


def _redirect_uri(request: Request) -> str:
    scheme = "https" if is_https(request) else request.url.scheme
    return f"{scheme}://{request.headers.get('host', request.url.netloc)}/api/strava/callback"


@router.get("/status")
def status(db: Session = Depends(get_db), svc=Depends(service)):
    return svc.status(db)


@router.get("/connect", include_in_schema=False)
def connect(request: Request, db: Session = Depends(get_db), svc=Depends(service)):
    try:
        return RedirectResponse(svc.authorize_url(db, _redirect_uri(request)), status_code=303)
    except StravaError as e:
        raise HTTPException(400, str(e))


@router.get("/callback", include_in_schema=False)
def callback(code: str | None = None, state: str | None = None, scope: str | None = None,
             error: str | None = None, db: Session = Depends(get_db), svc=Depends(service)):
    """Strava sends the browser here after approval. Public route, protected by the one-time state."""
    try:
        if error:
            raise StravaError("Strava access wasn't granted.")
        svc.handle_callback(db, code, state, scope)
        svc.sync(db, days=60)
        return RedirectResponse("/?strava=connected#settings", status_code=303)
    except StravaError as e:
        from urllib.parse import quote

        return RedirectResponse(f"/?strava_error={quote(str(e))}#settings", status_code=303)


class SyncIn(BaseModel):
    days: int = Field(30, ge=1, le=365)


@router.post("/sync")
def sync(data: SyncIn, db: Session = Depends(get_db), svc=Depends(service)):
    try:
        return svc.sync(db, days=data.days)
    except StravaError as e:
        raise HTTPException(400, str(e))


@router.post("/sync-if-stale")
def sync_if_stale(db: Session = Depends(get_db), svc=Depends(service)):
    s = svc.status(db)
    if not s["connected"]:
        return {"synced": False, "reason": "not_connected"}
    if s["last_sync"] and datetime.fromisoformat(s["last_sync"]) > datetime.now() - timedelta(minutes=60):
        return {"synced": False, "reason": "fresh"}
    try:
        return {"synced": True, **svc.sync(db, days=3)}
    except StravaError as e:
        return {"synced": False, "reason": "error", "error": str(e)}


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db), svc=Depends(service)):
    svc.disconnect(db)
    return {"ok": True}
