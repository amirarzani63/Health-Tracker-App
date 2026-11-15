import time
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.main import app
from app.routers import strava as strava_router
from app.services.strava import StravaService

TODAY = date.today()
START = datetime.combine(TODAY - timedelta(days=1), datetime.min.time()).replace(hour=7)


class FakeStrava:
    def __init__(self):
        self.calls = []
        self.expires_at = int(time.time()) + 3600
        self.activities = [
            {"id": 11, "name": "Morning Run", "sport_type": "Run", "start_date_local": START.isoformat() + "Z",
             "elapsed_time": 2700, "distance": 8000.0, "total_elevation_gain": 40.0,
             "average_heartrate": 150.0, "max_heartrate": 172.0},
            {"id": 12, "name": "Evening Ride", "sport_type": "Ride",
             "start_date_local": (START + timedelta(hours=11)).isoformat() + "Z",
             "elapsed_time": 3600, "distance": 25000.0, "kilojoules": 640.0},
        ]

    def __call__(self, request: httpx.Request):
        self.calls.append((request.method, request.url.path))
        if request.url.path == "/oauth/token":
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                assert form["code"] == ["good-code"] and form["client_secret"] == ["shh"]
            return httpx.Response(200, json={"access_token": "acc", "refresh_token": "ref", "expires_at": self.expires_at,
                                             "athlete": {"id": 7, "firstname": "Amir", "lastname": "A"}})
        if request.url.path == "/api/v3/athlete/activities":
            assert request.headers["authorization"] == "Bearer acc"
            return httpx.Response(200, json=self.activities if request.url.params["page"] == "1" else [])
        if request.url.path == "/oauth/deauthorize":
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture()
def strava(client, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "123")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "shh")
    fake = FakeStrava()
    svc = StravaService(transport=httpx.MockTransport(fake))
    app.dependency_overrides[strava_router.service] = lambda: svc
    yield client, fake
    app.dependency_overrides.clear()


def connect(client):
    r = client.get("/api/strava/connect", follow_redirects=False)
    assert r.status_code == 303
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "www.strava.com" and q["client_id"] == ["123"] and "activity:read_all" in q["scope"][0]
    assert q["redirect_uri"] == ["http://testserver/api/strava/callback"]
    return q["state"][0]


def test_not_configured(client, monkeypatch):
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    assert client.get("/api/strava/status").json()["configured"] is False
    assert client.get("/api/strava/connect", follow_redirects=False).status_code == 400


def test_connect_import_and_status(strava):
    client, fake = strava
    state = connect(client)
    r = client.get(f"/api/strava/callback?code=good-code&state={state}&scope=read,activity:read_all", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?strava=connected#settings"
    s = client.get("/api/strava/status").json()
    assert s["connected"] is True and s["athlete"] == "Amir A" and s["last_sync"]

    acts = {a["name"]: a for a in client.get("/api/activities").json()}
    run, ride = acts["Morning Run"], acts["Evening Ride"]
    assert run["source"] == "strava" and run["activity_type"] == "running" and run["avg_hr"] == 150
    assert ride["activity_type"] == "cycling" and ride["calories"] == 640  # kJ ≈ kcal for rides
    # re-sync updates, doesn't duplicate
    r = client.post("/api/strava/sync", json={"days": 30}).json()
    assert r["activities_added"] == 0 and r["activities_updated"] == 2
    assert len(client.get("/api/activities").json()) == 2


def test_state_is_single_use_and_checked(strava):
    client, _ = strava
    state = connect(client)
    bad = client.get("/api/strava/callback?code=good-code&state=forged&scope=activity:read_all", follow_redirects=False)
    assert "strava_error" in bad.headers["location"]
    # the real state was consumed by the failed attempt too
    again = client.get(f"/api/strava/callback?code=good-code&state={state}&scope=activity:read_all", follow_redirects=False)
    assert "strava_error" in again.headers["location"]
    assert client.get("/api/strava/status").json()["connected"] is False


def test_missing_activity_scope_is_refused(strava):
    client, _ = strava
    state = connect(client)
    r = client.get(f"/api/strava/callback?code=good-code&state={state}&scope=read", follow_redirects=False)
    assert "strava_error" in r.headers["location"] and "activities" in r.headers["location"]


def test_callback_reachable_without_app_login(strava, monkeypatch):
    client, _ = strava
    state = connect(client)
    monkeypatch.setenv("APP_PASSWORD", "pw")  # signed out, like Safari outside the home-screen app
    r = client.get(f"/api/strava/callback?code=good-code&state={state}&scope=activity:read_all", follow_redirects=False)
    assert r.headers["location"] == "/?strava=connected#settings"
    assert client.get("/api/strava/status").status_code == 401  # everything else stays locked


def test_token_refresh(strava):
    client, fake = strava
    state = connect(client)
    fake.expires_at = int(time.time()) - 10  # first token already expired
    client.get(f"/api/strava/callback?code=good-code&state={state}&scope=activity:read_all")
    token_calls = [c for c in fake.calls if c[1] == "/oauth/token"]
    assert len(token_calls) >= 2  # exchange + refresh before the API call


def test_dedupe_with_garmin_both_directions(strava, tmp_path):
    from app.routers import garmin as garmin_router
    from app.services.garmin import GarminService, MemoryTokenStore
    from tests.test_api import FakeGarmin

    client, fake = strava
    # 1) Strava first, then Garmin brings the same run: Garmin's richer copy replaces it
    fake.activities[0]["start_date_local"] = f"{TODAY.isoformat()}T06:31:00Z"
    state = connect(client)
    client.get(f"/api/strava/callback?code=good-code&state={state}&scope=activity:read_all")
    FakeGarmin.mfa = False
    gsvc = GarminService(factory=FakeGarmin, store=MemoryTokenStore(), legacy_token_dir=None)
    app.dependency_overrides[garmin_router.service] = lambda: gsvc
    client.post("/api/garmin/login", json={"email": "a@b.c", "password": "x"})
    client.post("/api/garmin/sync", json={"days": 2})  # FakeGarmin has a 45-min run at 06:30 today
    runs = [a for a in client.get("/api/activities").json() if a["activity_type"] == "running"]
    assert len(runs) == 1 and runs[0]["source"] == "garmin" and runs[0]["aerobic_te"] == 3.4
    # 2) Strava again: the run is now known from Garmin, so it's skipped
    r = client.post("/api/strava/sync", json={"days": 30}).json()
    assert r["duplicates_skipped"] == 1
    assert len([a for a in client.get("/api/activities").json() if a["activity_type"] == "running"]) == 1


def test_disconnect(strava):
    client, fake = strava
    state = connect(client)
    client.get(f"/api/strava/callback?code=good-code&state={state}&scope=activity:read_all")
    client.post("/api/strava/disconnect")
    assert client.get("/api/strava/status").json()["connected"] is False
    assert ("POST", "/oauth/deauthorize") in fake.calls
    assert client.post("/api/strava/sync-if-stale").json()["reason"] == "not_connected"
