"""Strava sync (official Strava API v3, OAuth 2).

Setup (once): create an API application at https://www.strava.com/settings/api with
"Authorization Callback Domain" = your app's domain, then set STRAVA_CLIENT_ID and
STRAVA_CLIENT_SECRET on the server. The user taps "Connect Strava", approves, and the
app stores the tokens in the database and refreshes them automatically.

Activities are de-duplicated against Garmin: if Garmin already has a session starting
within a few minutes, the Strava copy is skipped (Garmin's has heart-rate, Training
Effect and load). If Garmin's arrives later, it replaces the Strava one.
"""

import json
import logging
import os
import secrets
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Activity, StoredSecret, SyncState

log = logging.getLogger(__name__)

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
DEAUTH_URL = "https://www.strava.com/oauth/deauthorize"
API = "https://www.strava.com/api/v3"
SCOPE = "read,activity:read_all"
TOKENS_KEY, STATE_KEY = "strava_tokens", "strava_oauth_state"
DUPLICATE_WINDOW = timedelta(minutes=5)

SPORT_MAP = {
    "Run": "running", "TrailRun": "trail_running", "VirtualRun": "treadmill_running",
    "Ride": "cycling", "VirtualRide": "virtual_ride", "MountainBikeRide": "mountain_biking",
    "GravelRide": "gravel_cycling", "EBikeRide": "e_bike_fitness", "Walk": "walking", "Hike": "hiking",
    "Swim": "lap_swimming", "WeightTraining": "strength_training", "Crossfit": "hiit", "HighIntensityIntervalTraining": "hiit",
    "Yoga": "yoga", "Pilates": "pilates", "Rowing": "rowing", "Elliptical": "elliptical", "StairStepper": "stair_climbing",
    "Workout": "other",
}


class StravaError(Exception):
    pass


def configured() -> bool:
    return bool(os.getenv("STRAVA_CLIENT_ID") and os.getenv("STRAVA_CLIENT_SECRET"))


class StravaService:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.transport = transport  # tests inject httpx.MockTransport

    def _http(self) -> httpx.Client:
        return httpx.Client(timeout=30, transport=self.transport)

    # ------------------------------------------------------------ secrets
    @staticmethod
    def _get(db: Session, key: str) -> dict:
        row = db.get(StoredSecret, key)
        try:
            return json.loads(row.value) if row and row.value else {}
        except ValueError:
            return {}

    @staticmethod
    def _set(db: Session, key: str, value: dict | None):
        row = db.get(StoredSecret, key)
        if value is None:
            if row:
                db.delete(row)
        else:
            row = row or StoredSecret(key=key)
            row.value = json.dumps(value)
            db.add(row)
        db.commit()

    # ------------------------------------------------------------ OAuth
    def authorize_url(self, db: Session, redirect_uri: str) -> str:
        if not configured():
            raise StravaError("Strava isn't set up on the server yet (STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET).")
        state = secrets.token_urlsafe(24)
        # stored server-side so the callback works even in a browser that isn't signed in to the app
        self._set(db, STATE_KEY, {"state": state, "expires": time.time() + 600})
        return AUTH_URL + "?" + urlencode({
            "client_id": os.environ["STRAVA_CLIENT_ID"], "redirect_uri": redirect_uri, "response_type": "code",
            "approval_prompt": "auto", "scope": SCOPE, "state": state,
        })

    def handle_callback(self, db: Session, code: str | None, state: str | None, scope: str | None) -> dict:
        expected = self._get(db, STATE_KEY)
        self._set(db, STATE_KEY, None)  # single use
        if not state or not expected or not secrets.compare_digest(state, expected.get("state", "")) \
                or expected.get("expires", 0) < time.time():
            raise StravaError("This Strava link expired. Tap Connect Strava again.")
        if not code:
            raise StravaError("Strava access wasn't granted.")
        if "activity:read" not in (scope or ""):
            raise StravaError("Please allow 'View data about your activities' so workouts can be imported.")
        with self._http() as http:
            r = http.post(TOKEN_URL, data={"client_id": os.environ["STRAVA_CLIENT_ID"],
                                           "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
                                           "code": code, "grant_type": "authorization_code"})
        if r.status_code != 200:
            raise StravaError(f"Strava sign-in failed ({r.status_code}).")
        data = r.json()
        athlete = data.get("athlete") or {}
        tokens = {k: data.get(k) for k in ("access_token", "refresh_token", "expires_at")}
        tokens["athlete"] = {"id": athlete.get("id"), "name": " ".join(filter(None, [athlete.get("firstname"), athlete.get("lastname")]))}
        self._set(db, TOKENS_KEY, tokens)
        return tokens["athlete"]

    def _access_token(self, db: Session) -> str:
        t = self._get(db, TOKENS_KEY)
        if not t.get("refresh_token"):
            raise StravaError("Strava isn't connected.")
        if (t.get("expires_at") or 0) - 120 < time.time():
            with self._http() as http:
                r = http.post(TOKEN_URL, data={"client_id": os.environ.get("STRAVA_CLIENT_ID", ""),
                                               "client_secret": os.environ.get("STRAVA_CLIENT_SECRET", ""),
                                               "grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
            if r.status_code != 200:
                raise StravaError("Strava access was revoked or expired. Connect Strava again.")
            d = r.json()
            t.update(access_token=d["access_token"], refresh_token=d.get("refresh_token", t["refresh_token"]),
                     expires_at=d.get("expires_at"))
            self._set(db, TOKENS_KEY, t)
        return t["access_token"]

    def status(self, db: Session) -> dict:
        t = self._get(db, TOKENS_KEY)
        last = db.get(SyncState, "strava_last_sync")
        return {"configured": configured(), "connected": bool(t.get("refresh_token")),
                "athlete": (t.get("athlete") or {}).get("name"), "last_sync": last.value if last else None}

    def disconnect(self, db: Session):
        t = self._get(db, TOKENS_KEY)
        if t.get("access_token"):
            try:
                with self._http() as http:
                    http.post(DEAUTH_URL, data={"access_token": t["access_token"]})
            except httpx.HTTPError:
                pass
        self._set(db, TOKENS_KEY, None)

    # ------------------------------------------------------------ sync
    def sync(self, db: Session, days: int = 30, today: date | None = None) -> dict:
        token = self._access_token(db)
        after = int(datetime.combine((today or date.today()) - timedelta(days=days - 1), datetime.min.time()).timestamp())
        result = {"activities_added": 0, "activities_updated": 0, "duplicates_skipped": 0, "errors": []}
        page = 1
        with self._http() as http:
            while page <= 10:
                r = http.get(f"{API}/athlete/activities", params={"after": after, "per_page": 100, "page": page},
                             headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 429:
                    result["errors"].append("Strava rate limit reached; the rest will sync next time.")
                    break
                if r.status_code != 200:
                    raise StravaError(f"Strava returned {r.status_code}.")
                batch = r.json() or []
                for raw in batch:
                    outcome = upsert_strava_activity(db, raw)
                    result[{"added": "activities_added", "updated": "activities_updated",
                            "duplicate": "duplicates_skipped"}[outcome]] += 1
                if len(batch) < 100:
                    break
                page += 1
        state = db.get(SyncState, "strava_last_sync") or SyncState(key="strava_last_sync")
        state.value = datetime.now().isoformat(timespec="seconds")
        db.add(state)
        db.commit()
        return result


def _parse_local(raw: dict) -> datetime:
    v = raw.get("start_date_local") or raw.get("start_date")
    return datetime.fromisoformat(str(v).replace("Z", "")) if v else datetime.now()


def find_overlap(db: Session, start: datetime, duration_s: float, sources: tuple[str, ...]):
    """An activity from ``sources`` that starts within a few minutes and has a similar duration."""
    rows = db.scalars(select(Activity).where(Activity.source.in_(sources),
                                             Activity.start_time >= start - DUPLICATE_WINDOW,
                                             Activity.start_time <= start + DUPLICATE_WINDOW)).all()
    for a in rows:
        longer = max(a.duration_s or 0, duration_s or 0) or 1
        if abs((a.duration_s or 0) - (duration_s or 0)) / longer <= 0.25:
            return a
    return None


def upsert_strava_activity(db: Session, raw: dict) -> str:
    ext_id = f"strava:{raw.get('id')}"
    act = db.scalar(select(Activity).where(Activity.external_id == ext_id))
    start = _parse_local(raw)
    duration = float(raw.get("elapsed_time") or raw.get("moving_time") or 0)
    if act is None and find_overlap(db, start, duration, ("garmin", "manual")):
        return "duplicate"  # Garmin (or a manual log) already has this session
    is_new = act is None
    act = act or Activity(source="strava", external_id=ext_id, sets=[])
    sport = raw.get("sport_type") or raw.get("type") or "Workout"
    act.start_time = start
    act.activity_type = SPORT_MAP.get(sport, sport.lower())
    act.name = raw.get("name") or sport
    act.duration_s = duration
    act.distance_m = float(raw["distance"]) if raw.get("distance") else None
    act.elevation_gain_m = float(raw["total_elevation_gain"]) if raw.get("total_elevation_gain") else None
    act.avg_hr = float(raw["average_heartrate"]) if raw.get("average_heartrate") else None
    act.max_hr = float(raw["max_heartrate"]) if raw.get("max_heartrate") else None
    if raw.get("calories"):
        act.calories = float(raw["calories"])
    elif raw.get("kilojoules"):
        act.calories = round(float(raw["kilojoules"]))  # cycling: kJ of work ≈ kcal burned
    db.add(act)
    db.flush()
    return "added" if is_new else "updated"


strava_service = StravaService()
