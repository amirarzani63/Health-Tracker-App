from datetime import date

from app.services.garmin import GarminService
from app.routers import garmin as garmin_router
from app.main import app

TODAY = date.today().isoformat()


def test_profile_roundtrip(client):
    r = client.get("/api/profile")
    assert r.status_code == 200
    body = r.json() | {"name": "Amir", "goal": "lose", "diet_type": "vegetarian", "allergies": ["nuts"]}
    r = client.put("/api/profile", json=body)
    assert r.json()["goal"] == "lose"
    assert client.get("/api/profile").json()["allergies"] == ["nuts"]


def test_food_logging_and_summary(client):
    client.post("/api/foods", json={"day": TODAY, "meal": "breakfast", "name": "Oats", "calories": 300, "protein_g": 10, "carbs_g": 50, "fat_g": 5})
    r = client.get(f"/api/nutrition/summary?day={TODAY}").json()
    assert r["consumed"]["calories"] == 300
    s = client.get(f"/api/nutrition/suggestions?day={TODAY}").json()
    assert "breakfast" not in s["meals"] and "dinner" in s["meals"]
    foods = client.get(f"/api/foods?day={TODAY}").json()
    assert client.delete(f"/api/foods/{foods[0]['id']}").status_code == 200
    assert client.get(f"/api/foods?day={TODAY}").json() == []


def test_food_validation(client):
    r = client.post("/api/foods", json={"day": TODAY, "name": "", "calories": -5})
    assert r.status_code == 422


def test_activity_and_dashboard(client):
    client.post("/api/activities", json={"start_time": f"{TODAY}T07:00:00", "activity_type": "strength_training",
                                         "name": "Upper A", "duration_s": 3600,
                                         "sets": [{"exercise": "Bench", "reps": 8, "weight_kg": 80}]})
    acts = client.get("/api/activities").json()
    assert acts[0]["sets"][0]["exercise"] == "Bench"
    client.post("/api/plans/generate", json={"goal": "strength", "days_per_week": 3})
    d = client.get(f"/api/dashboard?day={TODAY}").json()
    assert d["week"]["count"] == 1 and d["week"]["duration_min"] == 60
    assert d["today_session"] is not None and len(d["trend"]) == 14


def test_plans_activate(client):
    a = client.post("/api/plans/generate", json={"goal": "general"}).json()
    b = client.post("/api/plans/generate", json={"goal": "fat_loss"}).json()
    assert client.get("/api/plans/active").json()["id"] == b["id"]
    client.post(f"/api/plans/{a['id']}/activate")
    assert client.get("/api/plans/active").json()["id"] == a["id"]
    assert len(client.get("/api/plans").json()) == 2


def test_weight_updates_profile(client):
    client.post("/api/weights", json={"day": TODAY, "weight_kg": 78.4})
    assert client.get("/api/profile").json()["weight_kg"] == 78.4


# ------------------------------------------------------------------ garmin
class FakeInner:
    def dump(self, path):
        import pathlib
        pathlib.Path(path, "garmin_tokens.json").write_text("{}")


class FakeGarmin:
    mfa = False

    def __init__(self, **kw):
        self.client = FakeInner()

    def login(self, tokenstore=None):
        return ("needs_mfa", {"s": 1}) if FakeGarmin.mfa else (None, None)

    def resume_login(self, state, code):
        if code != "123456":
            raise ValueError("bad code")
        return None, None

    def get_activities_by_date(self, start, end):
        return [{
            "activityId": 111, "activityName": "Morning Run", "startTimeLocal": f"{TODAY} 06:30:00",
            "activityType": {"typeKey": "running"}, "duration": 2700.0, "distance": 8000.0,
            "calories": 620.0, "averageHR": 148.0, "maxHR": 171.0, "elevationGain": 55.0,
            "aerobicTrainingEffect": 3.4, "anaerobicTrainingEffect": 1.2, "activityTrainingLoad": 120.0,
        }]

    def get_user_summary(self, d):
        return {"totalSteps": 12000, "totalKilocalories": 2900, "activeKilocalories": 900,
                "bmrKilocalories": 1800, "restingHeartRate": 48, "averageStressLevel": 25,
                "bodyBatteryHighestValue": 85, "bodyBatteryLowestValue": 20,
                "moderateIntensityMinutes": 10, "vigorousIntensityMinutes": 30}

    def get_sleep_data(self, d):
        return {"dailySleepDTO": {"sleepTimeSeconds": 27000, "sleepScores": {"overall": {"value": 82}}}}

    def get_body_composition(self, s, e):
        return {"dateWeightList": [{"calendarDate": TODAY, "weight": 79200.0, "bodyFat": 15.5}]}


def _use_fake(tmp_path):
    svc = GarminService(factory=FakeGarmin, token_dir=tmp_path / "tokens")
    app.dependency_overrides[garmin_router.service] = lambda: svc
    return svc


def test_garmin_login_sync_and_idempotency(client, tmp_path):
    FakeGarmin.mfa = False
    _use_fake(tmp_path)
    try:
        assert client.get("/api/garmin/status").json()["connected"] is False
        assert client.post("/api/garmin/login", json={"email": "a@b.c", "password": "x"}).json() == {"status": "ok"}
        assert (tmp_path / "tokens" / "garmin_tokens.json").exists()

        r = client.post("/api/garmin/sync", json={"days": 2}).json()
        assert r["activities_added"] == 1 and r["days_synced"] == 2 and r["weights"] == 1 and not r["errors"]
        r = client.post("/api/garmin/sync", json={"days": 2}).json()
        assert r["activities_added"] == 0 and r["activities_updated"] == 1

        act = client.get("/api/activities").json()[0]
        assert act["source"] == "garmin" and act["activity_type"] == "running" and act["aerobic_te"] == 3.4

        stats = client.get("/api/daily-stats?days=1").json()[0]
        assert stats["steps"] == 12000 and stats["sleep_score"] == 82 and stats["intensity_minutes"] == 70

        t = client.get(f"/api/nutrition/summary?day={TODAY}").json()["targets"]
        assert t["source"] == "garmin" and t["tdee"] == round((1800 + 900) * 1.1)

        tips = client.get(f"/api/nutrition/suggestions?day={TODAY}").json()["tips"]
        assert any("protein" in tip for tip in tips)

        client.post("/api/garmin/logout")
        assert client.get("/api/garmin/status").json()["connected"] is False
    finally:
        app.dependency_overrides.clear()


def test_garmin_mfa_flow(client, tmp_path):
    FakeGarmin.mfa = True
    _use_fake(tmp_path)
    try:
        assert client.post("/api/garmin/login", json={"email": "a@b.c", "password": "x"}).json()["status"] == "needs_mfa"
        assert client.get("/api/garmin/status").json()["mfa_pending"] is True
        assert client.post("/api/garmin/mfa", json={"code": "000000"}).status_code == 401
        assert client.post("/api/garmin/mfa", json={"code": "123456"}).json() == {"status": "ok"}
        assert client.get("/api/garmin/status").json()["connected"] is True
    finally:
        FakeGarmin.mfa = False
        app.dependency_overrides.clear()


def test_sync_without_login_is_400(client, tmp_path):
    _use_fake(tmp_path)
    try:
        assert client.post("/api/garmin/sync", json={"days": 1}).status_code == 400
    finally:
        app.dependency_overrides.clear()
