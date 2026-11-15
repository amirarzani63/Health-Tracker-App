import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import auth
from app.db import SessionLocal, init_db
from app.pages import page
from app.paths import STATIC
from app.routers import dashboard, diet, exercise, food_ai, garmin, insights, plans, profile, strava
from app.services.garmin import GarminError, garmin_service
from app.services.strava import strava_service

log = logging.getLogger("health")
AUTO_SYNC_HOURS = float(os.getenv("GARMIN_AUTO_SYNC_HOURS", "6"))


async def auto_sync_loop():
    """Periodically pull the last 2 days from Garmin when a session is saved."""
    while True:
        await asyncio.sleep(AUTO_SYNC_HOURS * 3600)
        db = SessionLocal()
        try:
            if strava_service.status(db)["connected"]:
                await asyncio.to_thread(strava_service.sync, db, 3)
        except Exception:
            log.exception("Strava auto-sync failed")
        if not garmin_service.has_tokens():
            db.close()
            continue
        try:
            result = await asyncio.to_thread(garmin_service.sync, db, 2)
            log.info("Garmin auto-sync: %s", result)
        except GarminError as e:
            log.warning("Garmin auto-sync skipped: %s", e)
        except Exception:
            log.exception("Garmin auto-sync failed")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not auth.enabled():
        log.warning("APP_PASSWORD is not set: the app is open to anyone who can reach it. "
                    "Set APP_PASSWORD before putting it on the internet.")
    task = asyncio.create_task(auto_sync_loop()) if AUTO_SYNC_HOURS > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Health Tracker", lifespan=lifespan)
app.middleware("http")(auth.auth_middleware)
app.include_router(auth.router)
for r in (profile, diet, food_ai, exercise, plans, garmin, strava, insights, dashboard):
    app.include_router(r.router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def index():
    return page("index.html")
