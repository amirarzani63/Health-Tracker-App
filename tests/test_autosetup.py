from datetime import date, timedelta

from app.main import app
from app.routers import insights as insights_router
from app.services.autosetup import _kg, infer_focus, read_garmin_profile
from app.services.garmin import GarminService, MemoryTokenStore
from tests.test_api import FakeGarmin

TODAY = date.today()


def connected_service(client, tmp_path):
    FakeGarmin.mfa = False
    svc = GarminService(factory=FakeGarmin, store=MemoryTokenStore(), legacy_token_dir=tmp_path / "tok")
    app.dependency_overrides[insights_router.garmin_svc] = lambda: svc
    svc.login("a@b.c", "x")
    return svc


def test_read_garmin_profile():
    g = read_garmin_profile(FakeGarmin(), TODAY)
    assert g["sex"] == "male" and g["height_cm"] == 181 and g["birth_year"] == 1987
    assert g["weight_kg"] == 85.9  # latest weigh-in wins over the profile weight
    assert g["sleep_target_h"] == 8 and g["steps_target"] == 11000 and g["active_minutes_per_week"] == 180
    assert g["target_weight_kg"] == 80 and g["name"] == "Test Runner"


def test_read_garmin_profile_survives_broken_endpoints():
    class Broken:
        def __getattr__(self, name):
            def boom(*a, **k):
                raise RuntimeError("nope")
            return boom
    assert read_garmin_profile(Broken(), TODAY) == {}


def test_units_and_focus_inference():
    assert _kg(80500) == 80.5 and _kg(80.5) == 80.5 and _kg(None) is None and _kg(-1) is None
    hist = {"count": 0, "cardio_share": 0.0}
    assert infer_focus({"weight_kg": 90, "target_weight_kg": 82}, hist) == "lose_weight"
    assert infer_focus({"weight_kg": 70, "target_weight_kg": 75}, hist) == "build_muscle"
    assert infer_focus({}, {"count": 8, "cardio_share": 0.9}) == "improve_cardio"
    assert infer_focus({}, hist) == "stay_healthy"


def test_one_tap_setup_from_garmin(client, tmp_path):
    connected_service(client, tmp_path)
    # three strength sessions a week for the last 4 weeks -> intermediate, 3 days
    for n in range(28):
        if n % 7 in (0, 2, 4):
            d = (TODAY - timedelta(days=n + 1)).isoformat()
            client.post("/api/activities", json={"start_time": f"{d}T07:00:00", "activity_type": "strength_training",
                                                 "name": "Gym", "duration_s": 3600})
    try:
        r = client.post("/api/setup/auto", json={"focus": "auto", "equipment": "home", "diet_type": "vegetarian"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["focus"] == "lose_weight" and body["garmin_used"] is True and body["note"] is None
        assert any("from Garmin" in line for line in body["summary"])

        p = client.get("/api/profile").json()
        assert p["sex"] == "male" and p["height_cm"] == 181 and p["birth_year"] == 1987
        assert p["goal"] == "lose" and p["equipment"] == "home" and p["diet_type"] == "vegetarian"
        assert p["setup_done"] is True and p["experience"] == "intermediate"

        g = client.get("/api/goals").json()
        assert g["steps_target"] == 11000 and g["active_minutes_per_week"] == 180 and g["sleep_target_h"] == 8
        assert g["target_weight_kg"] == 80 and g["calorie_target"] is None and g["follow_garmin"] is True
        assert g["workouts_per_week"] == 4  # 3 a week, +1 for a weight-loss goal

        plan = client.get("/api/plans/active").json()
        assert plan["goal"] == "fat_loss" and "home" in plan["name"]
        assert sum(1 for d in plan["days"] if d["type"] == "strength") == 4

        t = client.get(f"/api/nutrition/summary?day={TODAY}").json()["targets"]
        assert t["source"] == "garmin"  # the 30-day sync during setup brought in today's burn
        assert client.get("/api/dashboard").json()["setup"]["profile"] is True
    finally:
        app.dependency_overrides.clear()


def test_setup_without_garmin_uses_defaults(client):
    svc = GarminService(factory=FakeGarmin, store=MemoryTokenStore(), legacy_token_dir=None)
    app.dependency_overrides[insights_router.garmin_svc] = lambda: svc
    try:
        r = client.post("/api/setup/auto", json={"focus": "build_muscle"}).json()
        assert r["garmin_used"] is False and "isn't connected" in r["note"]
        assert client.get("/api/plans/active").json()["goal"] == "hypertrophy"
        assert client.get("/api/profile").json()["goal"] == "gain"
    finally:
        app.dependency_overrides.clear()


def test_sync_keeps_weight_and_goals_current(client, tmp_path):
    from app.routers import garmin as garmin_router

    svc = connected_service(client, tmp_path)
    app.dependency_overrides[garmin_router.service] = lambda: svc
    try:
        client.post("/api/garmin/sync", json={"days": 1})
        assert client.get("/api/profile").json()["weight_kg"] == 79.2  # Index-scale weigh-in from the fake
        assert client.get("/api/goals").json()["steps_target"] == 11000

        # editing goals by hand (and unticking "follow Garmin") stops the overwrite
        g = client.get("/api/goals").json()
        client.put("/api/goals", json={**g, "steps_target": 7000, "follow_garmin": False})
        client.post("/api/garmin/sync", json={"days": 1})
        assert client.get("/api/goals").json()["steps_target"] == 7000
    finally:
        app.dependency_overrides.clear()


def test_invalid_choice_rejected(client):
    assert client.post("/api/setup/auto", json={"focus": "get_rich"}).status_code == 422
