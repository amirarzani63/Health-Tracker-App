from datetime import date, datetime, timedelta

from app.db import SessionLocal
from app.models import DailyStats

TODAY = date.today()
D = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731


def food(client, day, meal="lunch", cal=600, p=40, c=60, f=20, fib=5):
    r = client.post("/api/foods", json={"day": day, "meal": meal, "name": "Meal", "calories": cal,
                                        "protein_g": p, "carbs_g": c, "fat_g": f, "fiber_g": fib})
    assert r.status_code == 200, r.text


def workout(client, day, sets=None, minutes=45, hour=7):
    r = client.post("/api/activities", json={"start_time": f"{day}T{hour:02d}:00:00", "activity_type": "strength_training",
                                             "name": "Session", "duration_s": minutes * 60, "sets": sets or []})
    assert r.status_code == 200, r.text


def garmin_day(d, **kw):
    db = SessionLocal()
    db.merge(DailyStats(day=d, **kw))
    db.commit()
    db.close()


def test_goals_override_targets(client):
    auto = client.get(f"/api/nutrition/summary?day={TODAY}").json()["targets"]
    assert auto["source"] == "estimate"
    g = client.get("/api/goals").json()
    assert g["saved"] is False and g["steps_target"] == 10000
    r = client.put("/api/goals", json={**g, "calorie_target": 2100, "protein_target_g": 170, "workouts_per_week": 3})
    assert r.status_code == 200 and r.json()["saved"] is True
    t = client.get(f"/api/nutrition/summary?day={TODAY}").json()["targets"]
    assert t["source"] == "goal" and t["calories"] == 2100 and t["protein_g"] == 170
    assert abs(t["protein_g"] * 4 + t["carbs_g"] * 4 + t["fat_g"] * 9 - 2100) < 3
    assert client.put("/api/goals", json={**g, "calorie_target": 100}).status_code == 422


def test_fiber_logged_and_summarised(client):
    food(client, D(0), fib=12)
    s = client.get(f"/api/nutrition/summary?day={D(0)}").json()
    assert s["consumed"]["fiber_g"] == 12 and s["targets"]["fiber_g"] == 30


def test_daily_series_combines_food_and_garmin(client):
    food(client, D(1), cal=1800)
    garmin_day(TODAY - timedelta(days=1), total_calories=2600, steps=9000, sleep_s=7 * 3600, active_calories=700)
    workout(client, D(1), minutes=50)
    client.post("/api/weights", json={"day": D(1), "weight_kg": 80.2})
    rows = client.get("/api/nutrition/trends?days=7").json()
    assert len(rows) == 7
    y = rows[-2]
    assert y["calories"] == 1800 and y["burned"] == 2600 and y["net"] == -800
    assert y["steps"] == 9000 and y["sleep_h"] == 7.0 and y["workouts"] == 1 and y["workout_minutes"] == 50
    assert y["weight_kg"] == 80.2 and y["logged"] is True
    assert rows[-1]["logged"] is False and rows[-1]["net"] is None


def test_weekly_summary(client):
    for n in range(3):
        food(client, D(n), cal=2000, p=150)
        workout(client, D(n))
    weeks = client.get("/api/nutrition/weekly?weeks=2").json()
    assert len(weeks) == 2
    total_logged = sum(w["days_logged"] for w in weeks)
    assert total_logged == 3 and sum(w["workouts"] for w in weeks) == 3
    this_week = weeks[-1]
    assert this_week["avg_calories"] == 2000 and this_week["workouts_goal"] == 4


def test_recommendations(client):
    g = client.get("/api/goals").json()
    client.put("/api/goals", json={**g, "calorie_target": 2000, "protein_target_g": 160})
    for n in range(1, 6):
        food(client, D(n), cal=2000, p=80)
    recs = client.get("/api/recommendations").json()
    titles = [r["title"] for r in recs]
    assert "Protein is low" in titles
    assert "Calories on target" in titles
    assert recs[0]["level"] == "warn"  # warnings sorted first


def test_recommendations_need_more_logging(client):
    assert any(r["title"] == "Log a few more days" for r in client.get("/api/recommendations").json())


def test_reminders_defaults_update_and_due(client):
    rem = client.get("/api/reminders").json()
    assert {r["key"] for r in rem} == {"breakfast", "lunch", "dinner", "workout", "weigh_in", "evening_review"}
    assert not any(r["enabled"] for r in rem)
    for r in rem:
        r["enabled"], r["days"] = True, list(range(7))
        if r["key"] == "lunch":
            r["time"] = "13:00"
    assert client.put("/api/reminders", json=rem).status_code == 200
    assert client.put("/api/reminders", json=[{**rem[0], "time": "25:00"}]).status_code == 422

    now = datetime.combine(TODAY, datetime.min.time()).replace(hour=14)
    due = {r["key"]: r for r in client.get(f"/api/reminders/due?now={now.isoformat()}").json()}
    assert "lunch" in due and "breakfast" in due  # 10:00 is within the 4-hour window
    assert "dinner" not in due  # not time yet
    assert "workout" not in due  # no plan -> nothing to remind

    food(client, TODAY.isoformat(), meal="lunch")
    due = {r["key"] for r in client.get(f"/api/reminders/due?now={now.isoformat()}").json()}
    assert "lunch" not in due  # condition satisfied

    client.post("/api/reminders/ack", json={"day": TODAY.isoformat(), "keys": ["breakfast"]})
    due = {r["key"] for r in client.get(f"/api/reminders/due?now={now.isoformat()}").json()}
    assert "breakfast" not in due
    assert client.post("/api/reminders/ack", json={"day": TODAY.isoformat(), "keys": ["bogus"]}).status_code == 400

    late = now.replace(hour=21, minute=30)
    due = {r["key"]: r for r in client.get(f"/api/reminders/due?now={late.isoformat()}").json()}
    assert "evening_review" in due and "kcal" in due["evening_review"]["body"]


def test_workout_reminder_uses_plan(client):
    client.post("/api/plans/generate", json={"goal": "strength", "days_per_week": 6, "include_cardio": False})
    rem = client.get("/api/reminders").json()
    for r in rem:
        r["enabled"] = r["key"] == "workout"
    client.put("/api/reminders", json=rem)
    now = datetime.combine(TODAY, datetime.min.time()).replace(hour=17, minute=30)
    due = client.get(f"/api/reminders/due?now={now.isoformat()}").json()
    if TODAY.weekday() == 6:  # Sunday is a rest day in a 6-day plan
        assert due == []
    else:
        assert due[0]["title"].startswith("Today's workout")
        workout(client, TODAY.isoformat())
        assert client.get(f"/api/reminders/due?now={now.isoformat()}").json() == []


def test_exercise_progress(client):
    workout(client, D(14), sets=[{"exercise": "Bench press", "reps": 8, "weight_kg": 70},
                                 {"exercise": "Bench press", "reps": 8, "weight_kg": 70}])
    workout(client, D(7), sets=[{"exercise": "bench  press", "reps": 5, "weight_kg": 80},
                                {"exercise": "Squat", "reps": 5, "weight_kg": 100}])
    idx = client.get("/api/progress/exercises").json()
    assert idx[0]["name"] == "Bench press" and idx[0]["sessions"] == 2
    prog = client.get("/api/progress/exercise", params={"name": "BENCH PRESS"}).json()
    assert [p["top_weight_kg"] for p in prog] == [70, 80]
    assert prog[0]["volume_kg"] == 1120 and prog[1]["est_1rm_kg"] == round(80 * (1 + 5 / 30), 1)


def test_dashboard_full_picture(client):
    food(client, TODAY.isoformat(), cal=1500)
    garmin_day(TODAY, total_calories=2500, active_calories=600, steps=8000)
    d = client.get(f"/api/dashboard?day={TODAY}").json()
    assert d["burned"] == 2500 and d["consumed"]["calories"] == 1500
    assert d["goals"]["steps"] == {"value": 8000, "goal": 10000}
    assert d["setup"]["profile"] is False and isinstance(d["recommendations"], list)
    client.put("/api/profile", json=client.get("/api/profile").json())
    assert client.get("/api/dashboard").json()["setup"]["profile"] is True


def test_migration_adds_columns(tmp_path, monkeypatch):
    import sqlite3

    import app.db as dbmod
    from sqlalchemy import create_engine, inspect

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE food_entries (id INTEGER PRIMARY KEY, day DATE, meal VARCHAR(20), name VARCHAR(200),"
                " servings FLOAT, calories FLOAT, protein_g FLOAT, carbs_g FLOAT, fat_g FLOAT, created_at DATETIME)")
    con.execute("INSERT INTO food_entries (day, meal, name, servings, calories, protein_g, carbs_g, fat_g)"
                " VALUES ('2025-01-01', 'lunch', 'Old', 1, 500, 30, 50, 10)")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(dbmod, "engine", eng)
    dbmod.init_db()
    assert "fiber_g" in {c["name"] for c in inspect(eng).get_columns("food_entries")}
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT fiber_g FROM food_entries").scalar() == 0


def test_sync_if_stale(client, tmp_path):
    from app.main import app
    from app.routers import garmin as garmin_router
    from app.services.garmin import GarminService, MemoryTokenStore
    from tests.test_api import FakeGarmin

    svc = GarminService(factory=FakeGarmin, store=MemoryTokenStore(), legacy_token_dir=tmp_path / "tok")
    app.dependency_overrides[garmin_router.service] = lambda: svc
    try:
        assert client.post("/api/garmin/sync-if-stale", json={}).json() == {"synced": False, "reason": "not_connected"}
        client.post("/api/garmin/login", json={"email": "a@b.c", "password": "x"})
        first = client.post("/api/garmin/sync-if-stale", json={}).json()
        assert first["synced"] is True and first["activities_added"] == 1
        assert client.post("/api/garmin/sync-if-stale", json={}).json()["reason"] == "fresh"
        stats = client.get("/api/daily-stats?days=1").json()[0]
        assert stats["min_hr"] == 44 and stats["max_hr"] == 172
    finally:
        app.dependency_overrides.clear()
