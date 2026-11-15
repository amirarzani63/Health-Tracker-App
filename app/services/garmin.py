"""Garmin Connect sync (fenix 7 Pro or any Garmin device).

Uses the community `garminconnect` library, which talks to the same
endpoints as the Garmin Connect website. Your password is only used for
the initial login and is never stored; the session tokens it produces are
saved in the app's database (so they survive restarts on hosts without a
persistent disk) and refreshed automatically, so later syncs don't need
the password again.

Garmin's official Health/Activity APIs require an approved business
developer account; this approach is meant for personal, self-hosted use.
"""

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import DATA_DIR, SessionLocal
from app.models import Activity, DailyStats, StoredSecret, SyncState, WeightEntry

log = logging.getLogger(__name__)

LEGACY_TOKEN_DIR = DATA_DIR / "garmin_tokens"  # where older versions kept tokens
TOKEN_KEY = "garmin_tokens"

# Factory is swappable so tests can inject a fake client.
ClientFactory = Callable[..., Any]


def _default_factory(**kwargs):
    from garminconnect import Garmin

    return Garmin(**kwargs)


class GarminError(Exception):
    pass


class DbTokenStore:
    """Keeps the Garmin session tokens (a small JSON string) in the database."""

    def get(self) -> str | None:
        with SessionLocal() as db:
            row = db.get(StoredSecret, TOKEN_KEY)
            return row.value if row and row.value else None

    def set(self, value: str) -> None:
        with SessionLocal() as db:
            row = db.get(StoredSecret, TOKEN_KEY) or StoredSecret(key=TOKEN_KEY)
            row.value = value
            db.add(row)
            db.commit()

    def clear(self) -> None:
        with SessionLocal() as db:
            row = db.get(StoredSecret, TOKEN_KEY)
            if row:
                db.delete(row)
                db.commit()


class MemoryTokenStore:
    def __init__(self):
        self.value = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def clear(self):
        self.value = None


class GarminService:
    def __init__(self, factory: ClientFactory = _default_factory, store=None, legacy_token_dir=LEGACY_TOKEN_DIR):
        self.factory = factory
        self.store = store if store is not None else DbTokenStore()
        self.legacy_token_dir = legacy_token_dir
        self._client = None
        self._pending_mfa: tuple[Any, Any] | None = None  # (client, client_state)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ auth
    def _legacy_tokens_present(self) -> bool:
        d = self.legacy_token_dir
        return bool(d) and d.exists() and any(d.iterdir())

    def has_tokens(self) -> bool:
        try:
            return bool(self.store.get()) or self._legacy_tokens_present()
        except Exception:  # database unavailable
            return False

    def _save_tokens(self, client):
        try:
            self.store.set(client.client.dumps())
        except Exception as e:  # pragma: no cover - depends on library internals
            log.warning("Could not save Garmin tokens: %s", e)

    def login(self, email: str, password: str) -> dict:
        """Log in with credentials. Returns {"status": "ok"|"needs_mfa"}."""
        with self._lock:
            client = self.factory(email=email, password=password, return_on_mfa=True)
            try:
                status, state = client.login()
            except Exception as e:
                raise GarminError(f"Garmin login failed: {e}") from e
            if status == "needs_mfa":
                self._pending_mfa = (client, state)
                return {"status": "needs_mfa"}
            self._client = client
            self._save_tokens(client)
            return {"status": "ok"}

    def submit_mfa(self, code: str) -> dict:
        with self._lock:
            if not self._pending_mfa:
                raise GarminError("No login is waiting for an MFA code. Start the login again.")
            client, state = self._pending_mfa
            try:
                client.resume_login(state, code)
            except Exception as e:
                raise GarminError(f"MFA verification failed: {e}") from e
            self._pending_mfa = None
            self._client = client
            self._save_tokens(client)
            return {"status": "ok"}

    def client(self):
        if self._client is not None:
            return self._client
        tokens = self.store.get()
        if not tokens and self._legacy_tokens_present():
            tokens = str(self.legacy_token_dir)  # one-time migration from the old token folder
        if not tokens:
            raise GarminError("Not connected to Garmin Connect. Log in first.")
        client = self.factory()
        try:
            client.login(tokens)  # accepts the saved JSON string (or a folder path)
        except Exception as e:
            raise GarminError(f"Saved Garmin session is no longer valid, please log in again ({e}).") from e
        self._client = client
        self._save_tokens(client)
        return client

    def logout(self):
        with self._lock:
            self._client = None
            self._pending_mfa = None
            self.store.clear()
            if self._legacy_tokens_present():
                for f in self.legacy_token_dir.iterdir():
                    f.unlink()

    def status(self, db: Session) -> dict:
        last = db.get(SyncState, "garmin_last_sync")
        return {
            "connected": self._client is not None or self.has_tokens(),
            "mfa_pending": self._pending_mfa is not None,
            "last_sync": last.value if last else None,
        }

    # ------------------------------------------------------------------ sync
    def sync(self, db: Session, days: int = 7, today: date | None = None) -> dict:
        client = self.client()
        end = today or date.today()
        start = end - timedelta(days=days - 1)
        result = {"activities_added": 0, "activities_updated": 0, "days_synced": 0, "weights": 0, "errors": []}

        try:
            acts = client.get_activities_by_date(start.isoformat(), end.isoformat())
        except Exception as e:
            acts = []
            result["errors"].append(f"activities: {e}")
        for raw in acts or []:
            added = upsert_activity(db, raw)
            result["activities_added" if added else "activities_updated"] += 1

        today_summary = None
        d = start
        while d <= end:
            try:
                summary = client.get_user_summary(d.isoformat()) or {}
                if d == end:
                    today_summary = summary
            except Exception as e:
                summary = {}
                result["errors"].append(f"summary {d}: {e}")
            try:
                sleep = client.get_sleep_data(d.isoformat()) or {}
            except Exception:
                sleep = {}
            if summary or sleep:
                upsert_daily(db, d, summary, sleep)
                result["days_synced"] += 1
            d += timedelta(days=1)

        try:
            body = client.get_body_composition(start.isoformat(), end.isoformat()) or {}
            result["weights"] = upsert_weights(db, body)
        except Exception as e:
            result["errors"].append(f"body composition: {e}")

        from app.services.autosetup import refresh_from_sync

        refresh_from_sync(db, today_summary)  # latest weight -> profile, goals that follow Garmin
        try:
            from app.services.garmin_workouts import keep_calendar_filled

            result["workouts_scheduled"] = keep_calendar_filled(db, client)
        except Exception as e:
            result["errors"].append(f"watch calendar: {e}")
        self._save_tokens(client)  # tokens may have been refreshed during the sync
        state = db.get(SyncState, "garmin_last_sync") or SyncState(key="garmin_last_sync")
        state.value = datetime.now().isoformat(timespec="seconds")
        db.add(state)
        db.commit()
        return result


# ---------------------------------------------------------------------- mapping
def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _parse_time(raw: dict) -> datetime:
    for key in ("startTimeLocal", "startTimeGMT"):
        v = raw.get(key)
        if v:
            try:
                return datetime.fromisoformat(str(v).replace("Z", ""))
            except ValueError:
                pass
    return datetime.now()


def upsert_activity(db: Session, raw: dict) -> bool:
    """Insert or update a Garmin activity. Returns True if newly added."""
    ext_id = str(raw.get("activityId"))
    act = db.scalar(select(Activity).where(Activity.external_id == ext_id))
    is_new = act is None
    if is_new:
        from app.services.strava import find_overlap

        # the same session imported from Strava earlier: Garmin's richer copy takes its place
        act = find_overlap(db, _parse_time(raw), _num(raw.get("duration")) or 0, ("strava",))
        if act is not None:
            act.source, act.external_id = "garmin", ext_id
        else:
            act = Activity(source="garmin", external_id=ext_id, sets=[])
    type_info = raw.get("activityType") or {}
    act.start_time = _parse_time(raw)
    act.activity_type = type_info.get("typeKey", "other") if isinstance(type_info, dict) else str(type_info)
    act.name = raw.get("activityName") or act.activity_type.replace("_", " ").title()
    act.duration_s = _num(raw.get("duration")) or 0
    act.distance_m = _num(raw.get("distance"))
    act.calories = _num(raw.get("calories"))
    act.avg_hr = _num(raw.get("averageHR"))
    act.max_hr = _num(raw.get("maxHR"))
    act.elevation_gain_m = _num(raw.get("elevationGain"))
    act.aerobic_te = _num(raw.get("aerobicTrainingEffect"))
    act.anaerobic_te = _num(raw.get("anaerobicTrainingEffect"))
    act.training_load = _num(raw.get("activityTrainingLoad"))
    db.add(act)
    db.flush()
    return is_new


def upsert_daily(db: Session, day: date, summary: dict, sleep: dict) -> DailyStats:
    stats = db.get(DailyStats, day) or DailyStats(day=day)

    def i(v):
        return int(v) if isinstance(v, (int, float)) else None

    if summary:
        stats.steps = i(summary.get("totalSteps"))
        stats.total_calories = _num(summary.get("totalKilocalories"))
        stats.active_calories = _num(summary.get("activeKilocalories"))
        stats.bmr_calories = _num(summary.get("bmrKilocalories"))
        stats.resting_hr = i(summary.get("restingHeartRate"))
        stats.min_hr = i(summary.get("minHeartRate"))
        stats.max_hr = i(summary.get("maxHeartRate"))
        stats.avg_stress = i(summary.get("averageStressLevel"))
        stats.body_battery_high = i(summary.get("bodyBatteryHighestValue"))
        stats.body_battery_low = i(summary.get("bodyBatteryLowestValue"))
        mod, vig = summary.get("moderateIntensityMinutes"), summary.get("vigorousIntensityMinutes")
        if mod is not None or vig is not None:
            stats.intensity_minutes = int((mod or 0) + 2 * (vig or 0))
        if summary.get("sleepingSeconds"):
            stats.sleep_s = i(summary.get("sleepingSeconds"))
    dto = (sleep or {}).get("dailySleepDTO") or {}
    if dto.get("sleepTimeSeconds"):
        stats.sleep_s = i(dto["sleepTimeSeconds"])
    score = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
    if score is not None:
        stats.sleep_score = i(score)
    db.add(stats)
    db.flush()
    return stats


def upsert_weights(db: Session, body: dict) -> int:
    count = 0
    for item in body.get("dateWeightList") or []:
        grams = item.get("weight")
        cal = item.get("calendarDate")
        if not grams or not cal:
            continue
        day = date.fromisoformat(str(cal)[:10])
        entry = db.scalar(select(WeightEntry).where(WeightEntry.day == day, WeightEntry.source == "garmin"))
        entry = entry or WeightEntry(day=day, source="garmin")
        entry.weight_kg = round(grams / 1000, 2)
        entry.body_fat_pct = _num(item.get("bodyFat"))
        db.add(entry)
        count += 1
    db.flush()
    return count


garmin_service = GarminService()
