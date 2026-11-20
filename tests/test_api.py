from datetime import date

from app.services.garmin import GarminService, MemoryTokenStore
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
    def dumps(self):
        return '{"di_token": "tok"}'


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

    full_name = "Test Runner"

    def get_user_profile(self):
        return {"userData": {"gender": "MALE", "weight": 86400.0, "height": 181.0, "birthDate": "1987-05-02"},
                "userSleep": {"sleepTime": 81000, "wakeTime": 23400}}  # 22:30 -> 06:30 = 8 h

    def get_latest_weight(self, d):
        return {"date": d, "weight": 85900.0}

    def get_weight_goal(self, start, end):
        return {"weightGoal": {"goalValue": 80000.0}}

    def get_user_summary(self, d):
        return {"dailyStepGoal": 11000, "intensityMinutesGoal": 180, "totalSteps": 12000, "totalKilocalories": 2900, "activeKilocalories": 900,
                "bmrKilocalories": 1800, "restingHeartRate": 48, "minHeartRate": 44, "maxHeartRate": 172, "averageStressLevel": 25,
                "bodyBatteryHighestValue": 85, "bodyBatteryLowestValue": 20,
                "moderateIntensityMinutes": 10, "vigorousIntensityMinutes": 30}

    def get_sleep_data(self, d):
        return {"dailySleepDTO": {"sleepTimeSeconds": 27000, "sleepScores": {"overall": {"value": 82}}}}

    def get_body_composition(self, s, e):
        return {"dateWeightList": [{"calendarDate": TODAY, "weight": 79200.0, "bodyFat": 15.5}]}


def _use_fake(tmp_path):
    svc = GarminService(factory=FakeGarmin, store=MemoryTokenStore(), legacy_token_dir=tmp_path / "tokens")
    app.dependency_overrides[garmin_router.service] = lambda: svc
    return svc


def test_garmin_login_sync_and_idempotency(client, tmp_path):
    FakeGarmin.mfa = False
    svc = _use_fake(tmp_path)
    try:
        assert client.get("/api/garmin/status").json()["connected"] is False
        assert client.post("/api/garmin/login", json={"email": "a@b.c", "password": "x"}).json() == {"status": "ok"}
        assert svc.store.get() == '{"di_token": "tok"}'
        svc._client = None  # simulate a restart: must reconnect from the saved tokens
        assert client.get("/api/garmin/status").json()["connected"] is True

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


def test_move_plan_session(client):
    plan = client.post("/api/plans/generate", json={"goal": "strength", "days_per_week": 3, "include_cardio": False}).json()
    days = {d["weekday"]: d["title"] for d in plan["days"]}
    assert days == {"Mon": "Full Body A", "Wed": "Full Body B", "Fri": "Full Body C"}
    # move to an empty day
    p = client.post(f"/api/plans/{plan['id']}/move", json={"from_day": "Mon", "to_day": "Sun"}).json()
    assert {d["weekday"]: d["title"] for d in p["days"]} == {"Wed": "Full Body B", "Fri": "Full Body C", "Sun": "Full Body A"}
    # move onto a busy day swaps them
    p = client.post(f"/api/plans/{plan['id']}/move", json={"from_day": "Sun", "to_day": "Wed"}).json()
    assert {d["weekday"]: d["title"] for d in p["days"]} == {"Wed": "Full Body A", "Fri": "Full Body C", "Sun": "Full Body B"}
    assert client.post(f"/api/plans/{plan['id']}/move", json={"from_day": "Xyz", "to_day": "Mon"}).status_code == 400


def test_exercise_picker(client):
    r = client.get("/api/exercises").json()
    assert "Chest" in r["body_parts"] and "Goblet Squat" in r["groups"]["Legs"]
    assert "Dumbbell Floor Press" in r["groups"]["Chest"] and r["plan_sessions"] == []
    client.post("/api/plans/generate", json={"goal": "strength", "days_per_week": 3, "equipment": "home", "include_cardio": False})
    r = client.get("/api/exercises").json()
    assert r["plan_sessions"] == ["Full Body A", "Full Body B", "Full Body C"]
    assert "Goblet Squat" in r["plan_exercises"]["Legs"]


SARA = {"name": "Sara", "sex": "female", "birth_year": 1990, "height_cm": 165, "weight_kg": 70,
        "activity_level": "light", "weight_goal": "lose", "target_weight_kg": 64, "goal_weeks": 12,
        "muscle_goal": "tone", "focus_areas": ["core", "shoulders"], "training_days": 3, "session_minutes": 45,
        "experience": "beginner", "equipment": "home", "equipment_list": ["dumbbells", "bench"], "split_style": "auto", "injuries": ["knees"], "diet_type": "vegetarian"}


def test_people_have_separate_data(client):
    r = client.get("/api/users").json()
    assert [u["id"] for u in r["users"]] == [1]
    client.post("/api/weights", json={"day": "2026-11-19", "weight_kg": 105.5})
    new = client.post("/api/users", json=SARA).json()
    assert new["id"] == 2
    # the new person is now selected and sees only their own data and targets
    p = client.get("/api/profile").json()
    assert (p["name"], p["sex"], p["weight_kg"], p["diet_type"], p["equipment"]) == ("Sara", "female", 70, "vegetarian", "home")
    assert [w["weight_kg"] for w in client.get("/api/weights").json()] == [70]
    assert client.get("/api/goals").json()["target_weight_kg"] == 64
    client.post("/api/users/select", json={"id": 1})
    assert [w["weight_kg"] for w in client.get("/api/weights").json()] == [105.5]
    assert client.get("/api/profile").json()["name"] != "Sara"
    assert len(client.get("/api/users").json()["users"]) == 2
    assert client.post("/api/users/select", json={"id": 99}).status_code == 404



def test_new_person_targets_are_worked_out_exactly(client):
    from datetime import date
    r = client.post("/api/users", json=SARA).json()
    age = date.today().year - 1990
    bmr = 10 * 70 + 6.25 * 165 - 5 * age - 161
    workouts = 5.0 * 3.5 * 70 / 200 * 45 * 3 / 7  # 3 × 45 min a week
    want = bmr * 1.3 + workouts - 6 * 7700 / (12 * 7)  # light everyday life; lose 6 kg in 12 weeks
    t = client.get(f"/api/dashboard?day={date.today()}").json()["targets"]
    assert abs(t["calories"] - want) < 1
    assert any("× 1.3 " in line for line in r["summary"])
    active = client.get("/api/plans/active").json()
    strength = [d for d in active["days"] if d["type"] == "strength"]
    names = [e["exercise"].lower() for d in strength for e in d["exercises"]]
    assert any("plank" in n or "dead bug" in n for n in names) and any("lateral" in n or "rear-delt" in n for n in names)
    assert not any("lunge" in n or "split squat" in n for n in names)  # knees
    # missing answers are refused, nothing is guessed
    bad = {k: v for k, v in SARA.items() if k != "activity_level"}
    assert client.post("/api/users", json=bad).status_code == 422
    assert client.post("/api/users", json={**SARA, "goal_weeks": None}).status_code == 422


def test_each_person_has_their_own_colour_scheme(client):
    client.post("/api/users", json=SARA)                       # a woman: pink
    client.post("/api/users", json={**SARA, "name": "Ali", "sex": "male"})  # orange is taken by profile 1
    users = client.get("/api/users").json()["users"]
    schemes = [u["scheme"] for u in users]
    assert schemes[:2] == ["orange", "pink"] and len(set(schemes)) == 3
    assert client.put("/api/users/me/scheme", json={"scheme": "pink"}).status_code == 409  # Sara's
    assert client.put("/api/users/me/scheme", json={"scheme": "gold"}).json()["scheme"] == "gold"


def test_people_picker_can_switch():
    """Tapping a name in "Who's tracking?" must switch person (this handler was once lost in a refactor)."""
    from app.paths import STATIC
    js = (STATIC / "app.js").read_text()
    assert '$("#whoList").addEventListener("click"' in js and '"/api/users/select"' in js


def test_person_can_be_chosen_by_header(client):
    client.post("/api/users", json=SARA)
    client.cookies.clear()
    assert client.get("/api/profile", headers={"X-HT-User": "2"}).json()["name"] == "Sara"
    assert client.get("/api/profile", headers={"X-HT-User": "1"}).json()["name"] != "Sara"
    assert client.get("/api/profile", headers={"X-HT-User": "99"}).json()["name"] != "Sara"  # unknown -> profile 1


def test_sports_can_be_logged_on_any_day_and_count_as_burn(client):
    client.put("/api/profile", json={**client.get("/api/profile").json(), "weight_kg": 80})
    for act, met in (("yoga_vinyasa", 3.3), ("tennis_singles", 8.0), ("ski_downhill", 5.3), ("swim_freestyle", 5.8), ("padel", 6.0)):
        r = client.post("/api/cardio-log", json={"day": "2026-11-10", "activity": act, "minutes": 60}).json()
        assert r["items"][-1]["calories"] == round(met * 3.5 * 80 / 200 * 60)
    r = client.get("/api/cardio-log?day=2026-11-10").json()
    assert r["total_minutes"] == 300
    assert client.post("/api/cardio-log", json={"day": "2026-11-10", "activity": "made_up", "minutes": 10}).status_code == 422


def test_beginner_at_full_gym_starts_with_machines_and_dumbbells(client):
    from app.routers.users import refresh_beginner_plans
    client.post("/api/users", json={**SARA, "equipment_list": ["dumbbells", "barbell", "bench", "cable", "machines", "pullup"], "injuries": ["none"]})
    names = [e["exercise"] for d in client.get("/api/plans/active").json()["days"] for e in d["exercises"]]
    assert names and not any("barbell" in n.lower() or n in ("Front squat", "Conventional deadlift") for n in names)
    refresh_beginner_plans()
    assert refresh_beginner_plans() == 0  # runs only once per person


def test_foods_people_add_are_shared_by_everyone(client):
    client.post("/api/users", json=SARA)  # now Sara
    client.post("/api/my-foods", json={"name": "Sara's zrazy bake", "calories": 300, "protein_g": 20, "fat_g": 10, "carbs_g": 30})
    client.post("/api/users/select", json={"id": 1})
    found = client.get("/api/food-library?q=zrazy").json()
    assert found and found[0]["calories"] == 300


def test_weekly_shopping_list_matches_the_menu(client):
    r = client.get("/api/weekly").json()
    assert r["shopping_list"] and r["meal_plan"]
    items = {i["item"] for s in r["shopping_list"] for i in s["items"]}
    assert not any("tofu" in i.lower() or "tempeh" in i.lower() for i in items)
    from app.services import nutrition
    names = {m["name"] for d in r["meal_plan"] for m in d["meals"]}
    needed = {ing[0] for m in nutrition.MEAL_IDEAS if m["name"] in names for ing in m["ingredients"]}
    assert needed == items


def test_app_script_has_no_syntax_errors():
    """A broken app.js stops the whole app on the phone, so check it parses."""
    import shutil
    import subprocess

    import pytest
    from app.paths import STATIC
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(process.argv[1], 'utf8'))", str(STATIC / "app.js")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
