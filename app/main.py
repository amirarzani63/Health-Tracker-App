import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import SessionLocal, init_db
from app.routers import dashboard, diet, exercise, food_ai, garmin, insights, plans, profile
from app.services.garmin import GarminError, garmin_service

log = logging.getLogger("health")
STATIC = Path(__file__).parent / "static"
AUTO_SYNC_HOURS = float(os.getenv("GARMIN_AUTO_SYNC_HOURS", "6"))


async def auto_sync_loop():
    """Periodically pull the last 2 days from Garmin when a session is saved."""
    while True:
        await asyncio.sleep(AUTO_SYNC_HOURS * 3600)
        if not garmin_service.has_tokens():
            continue
        db = SessionLocal()
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
    task = asyncio.create_task(auto_sync_loop()) if AUTO_SYNC_HOURS > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Health Tracker", lifespan=lifespan)
for r in (profile, diet, food_ai, exercise, plans, garmin, insights, dashboard):
    app.include_router(r.router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
