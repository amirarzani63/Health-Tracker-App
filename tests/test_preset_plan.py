from sqlalchemy import select

from app.db import SessionLocal
from app.models import Goals, Profile, WorkoutPlan
from app.services import exlib, preset_plan


def test_install_once(client):
    db_session = SessionLocal()
    assert preset_plan.install(db_session)
    assert not preset_plan.install(db_session)
    plan = db_session.scalar(select(WorkoutPlan).where(WorkoutPlan.active))
    assert plan.weeks == 13 and [d["weekday"] for d in plan.days][0] == "Mon"
    g = db_session.scalar(select(Goals))
    assert plan.days[0]["est_kcal"] >= 500
    assert (g.calorie_target, g.protein_target_g, g.target_weight_kg) == (2100, 180, 95)
    assert db_session.scalar(select(Profile)).birth_year == 1984


def test_every_exercise_has_a_photo():
    if not exlib.available():
        return
    for d in preset_plan.DAYS:
        for x in d["exercises"]:
            m = exlib.match(x["exercise"])
            assert m and m["images"], x["exercise"]


def test_checkins(client):
    r = client.post("/api/plans/checkins/all", json={"day": "2026-11-18", "done": True})
    assert r.json() == {"2026-11-18": True}
    client.post("/api/plans/checkins/all", json={"day": "2026-11-19", "done": False})
    client.post("/api/plans/checkins/all", json={"day": "2026-11-18", "done": None})
    assert client.get("/api/plans/checkins/all").json() == {"2026-11-19": False}


def test_water(client):
    r = client.post("/api/water", json={"day": "2026-11-18", "change": 1}).json()
    assert r["glasses"] == 1 and 8 <= r["goal"] <= 12
    client.post("/api/water", json={"day": "2026-11-18", "change": -5})
    assert client.get("/api/water?day=2026-11-18").json()["glasses"] == 0


def test_steps_typed(client):
    client.post("/api/steps", json={"day": "2026-11-18", "steps": 8500})
    assert client.get("/api/steps?day=2026-11-18").json()["typed"] == 8500
    d = client.get("/api/dashboard?day=2026-11-18").json()
    assert d["goals"]["steps"]["value"] == 8500


def test_day_log(client):
    client.post("/api/day-log", json={"day": "2026-11-18", "sleep_h": 7})
    client.post("/api/day-log", json={"day": "2026-11-18", "burned": 3100})
    d = client.get("/api/dashboard?day=2026-11-18").json()
    assert d["burned"] == 3100 and d["goals"]["sleep_h"]["value"] == 7
    client.post("/api/plans/checkins/all", json={"day": "2026-11-18", "done": True})
    d = client.get("/api/dashboard?day=2026-11-18").json()
    assert d["today_done"] and d["goals"]["workouts_week"]["value"] >= 1


def test_remove_garmin_data(client):
    from datetime import date, datetime

    from app.models import Activity, DailyStats, StoredSecret, WeightEntry
    from app.services.remove_garmin import remove_garmin_data
    db = SessionLocal()
    db.query(StoredSecret).filter(StoredSecret.key == "garmin-removed-v1").delete()
    db.add_all([DailyStats(day=date(2026, 11, 1), steps=5000), StoredSecret(key="garmin_tokens", value="x"),
                WeightEntry(day=date(2026, 11, 1), weight_kg=106, source="garmin"),
                WeightEntry(day=date(2026, 11, 2), weight_kg=105.5, source="manual"),
                Activity(name="run", activity_type="running", start_time=datetime(2026, 11, 1, 8), duration_s=600, source="garmin")])
    db.commit()
    assert remove_garmin_data(db)
    assert db.query(DailyStats).count() == 0 and db.get(StoredSecret, "garmin_tokens") is None
    assert [w.source for w in db.query(WeightEntry)] == ["manual"] and db.query(Activity).count() == 0
    db.close()
