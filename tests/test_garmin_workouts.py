import copy
from datetime import date, timedelta

from garminconnect.workout import StrengthWorkout, WorkoutSegment, create_strength_set

from app.main import app
from app.routers import garmin as garmin_router
from app.routers import insights as insights_router
from app.services import garmin_workouts as gw
from app.services.garmin import GarminService, MemoryTokenStore
from tests.test_api import FakeGarmin

TODAY = date.today()
SEG = {"sportTypeId": 5, "sportTypeKey": "strength_training"}


def strength(wid, name, blocks):
    steps, order = [], 1
    for cat, ex, sets, reps, rest in blocks:
        steps.append(create_strength_set(cat, step_order=order, sets=sets, reps=reps, rest_seconds=rest, exercise_name=ex))
        order += 3
    w = StrengthWorkout(workoutName=name, estimatedDurationInSecs=3000,
                        workoutSegments=[WorkoutSegment(segmentOrder=1, sportType=SEG, workoutSteps=steps)]).to_dict()
    w["workoutId"] = wid
    return w


UPPER = strength(101, "Gym Upper", [("BENCH_PRESS", "BARBELL_BENCH_PRESS", 5, 5, 150),
                                    ("ROW", "BARBELL_ROW", 4, 8, 90),
                                    ("CURL", "ALTERNATING_DUMBBELL_BICEPS_CURL", 3, 12, 60)])
LOWER = strength(102, "Gym Lower", [("SQUAT", "BARBELL_BACK_SQUAT", 4, 6, 180),
                                    ("SQUAT", "LEG_PRESS", 3, 10, 90),
                                    ("LUNGE", "DUMBBELL_REVERSE_LUNGE", 3, 10, 60)])


class WorkoutGarmin(FakeGarmin):
    """Fake Garmin account with two saved strength workouts and a writable workout library."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.library = {101: copy.deepcopy(UPPER), 102: copy.deepcopy(LOWER)}
        self.next_id = 900
        self.scheduled = {}
        self.updates = []

    def get_workouts(self, start=0, limit=100, **kw):
        return [{"workoutId": w["workoutId"], "workoutName": w["workoutName"], "sportType": w["sportType"],
                 "estimatedDurationInSecs": 3000, "updateDate": "2026-11-01"} for w in self.library.values()]

    def get_workout_by_id(self, wid):
        return copy.deepcopy(self.library[int(wid)])

    def copy_workout(self, wid, name):
        self.next_id += 1
        c = copy.deepcopy(self.library[int(wid)])
        c.update(workoutId=self.next_id, workoutName=name)
        self.library[self.next_id] = c
        return c

    def update_workout(self, wid, body):
        assert body["workoutId"] == wid
        self.library[int(wid)] = copy.deepcopy(body)
        self.updates.append(wid)
        return body

    def upload_workout(self, body):
        self.next_id += 1
        self.library[self.next_id] = {**body, "workoutId": self.next_id}
        return {"workoutId": self.next_id}

    def schedule_workout(self, wid, d):
        sid = len(self.scheduled) + 5000
        self.scheduled[sid] = (wid, d)
        return {"workoutScheduleId": sid, "calendarDate": d}

    def unschedule_workout(self, sid):
        self.scheduled.pop(int(sid))


def all_exercise_names(w):
    return [s.get("exerciseName") for seg in w["workoutSegments"] for s in gw._walk(seg["workoutSteps"]) if s.get("category")]


def test_parse_garmin_workout():
    day = gw.parse_workout(UPPER)
    assert day["type"] == "strength" and day["title"] == "Gym Upper"
    bench = day["exercises"][0]
    assert bench["exercise"] == "Barbell Bench Press" and bench["sets"] == 5 and bench["reps"] == "5" and bench["rest_s"] == 150
    assert [e["exercise"] for e in day["exercises"]] == ["Barbell Bench Press", "Barbell Row", "Alternating Dumbbell Biceps Curl"]


def test_adapt_for_home_weight_loss():
    original = copy.deepcopy(LOWER)
    adapted, changes = gw.adapt_workout(LOWER, goal="lose", equipment="home")
    assert LOWER == original  # the original is never modified
    names = all_exercise_names(adapted)
    assert not any("BARBELL" in (n or "") or "LEG_PRESS" in (n or "") for n in names)
    assert "GOBLET_SQUAT" in names and "DUMBBELL_REVERSE_LUNGE" in names  # already home-friendly: untouched
    day = gw.parse_workout(adapted)
    squat = day["exercises"][0]
    assert squat["exercise"] == "Goblet Squat" and squat["reps"] == "10" and squat["rest_s"] == 60
    assert "Barbell Back Squat → Goblet Squat (home equipment)" in changes
    # every substitute is a real Garmin catalog exercise
    for s in (s for seg in adapted["workoutSegments"] for s in gw._walk(seg["workoutSteps"]) if s.get("category")):
        assert (s["category"], s.get("exerciseName") or "") in gw.NAMES


def test_gym_and_maintain_leave_workout_alone():
    adapted, changes = gw.adapt_workout(UPPER, goal="maintain", equipment="gym")
    assert adapted == UPPER and changes == []


def test_build_plan_rotates_and_adds_cardio():
    plan = gw.build_plan([UPPER, LOWER], goal="lose", equipment="home", days_per_week=4)
    strength_days = [d for d in plan["days"] if d["type"] == "strength"]
    cardio_days = [d for d in plan["days"] if d["type"] == "cardio"]
    assert [d["title"] for d in strength_days] == ["Gym Upper", "Gym Lower", "Gym Upper", "Gym Lower"]
    assert len(cardio_days) == 2 and all(d["zone"] == "Zone 2" for d in cardio_days)
    assert len({d["weekday"] for d in plan["days"]}) == 6 and plan["goal"] == "fat_loss"


def setup_service(client, tmp_path):
    FakeGarmin.mfa = False
    svc = GarminService(factory=WorkoutGarmin, store=MemoryTokenStore(), legacy_token_dir=tmp_path / "t")
    app.dependency_overrides[garmin_router.service] = lambda: svc
    app.dependency_overrides[insights_router.garmin_svc] = lambda: svc
    svc.login("a@b.c", "x")
    return svc


def test_plan_from_workouts_and_send_to_watch(client, tmp_path):
    svc = setup_service(client, tmp_path)
    try:
        p = client.get("/api/profile").json()
        client.put("/api/profile", json={**p, "goal": "lose", "equipment": "home"})
        listed = client.get("/api/garmin/workouts").json()
        assert [w["name"] for w in listed] == ["Gym Upper", "Gym Lower"]

        r = client.post("/api/garmin/plan-from-workouts", json={"workout_ids": [101, 102], "days_per_week": 4})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["used"] == ["Gym Upper", "Gym Lower"] and body["pushed"]["errors"] == []
        assert "Barbell Bench Press → Dumbbell Floor Press (home equipment)" in body["changes"]

        g = svc._client
        originals = [g.library[101], g.library[102]]
        assert originals == [UPPER, LOWER]  # originals untouched in Garmin
        copies = [w for wid, w in g.library.items() if wid >= 900 and w["workoutName"].endswith(gw.COPY_SUFFIX)]
        assert len(copies) == 3  # two adapted copies + Zone 2 cardio
        for c in copies:
            assert not any("BARBELL" in (n or "") for n in all_exercise_names(c))
        # 6 sessions a week, two weeks ahead
        assert len(g.scheduled) == body["pushed"]["scheduled"] and 10 <= len(g.scheduled) <= 12

        plan = client.get("/api/plans/active").json()
        assert plan["name"].startswith("My Garmin workouts") and len(plan["days"]) == 6
        assert client.get("/api/garmin/watch-plan").json()["sending"] is True

        # running it again reuses the copies and replaces (doesn't duplicate) the calendar
        before = set(g.library)
        client.post("/api/garmin/plan-from-workouts", json={"workout_ids": [101, 102], "days_per_week": 4})
        assert set(g.library) == before
        assert 10 <= len(g.scheduled) <= 12

        assert client.post("/api/garmin/watch-plan/stop").json()["removed"] >= 10
        assert g.scheduled == {} and client.get("/api/garmin/watch-plan").json()["sending"] is False
    finally:
        app.dependency_overrides.clear()


def test_calendar_is_kept_filled(client, tmp_path):
    from app.db import SessionLocal

    svc = setup_service(client, tmp_path)
    try:
        client.post("/api/garmin/plan-from-workouts", json={"workout_ids": [101, 102], "days_per_week": 4})
        g = svc._client
        n = len(g.scheduled)
        db = SessionLocal()
        assert gw.keep_calendar_filled(db, g) == 0  # still two weeks ahead: nothing to do
        later = TODAY + timedelta(days=9)
        added = gw.keep_calendar_filled(db, g, today=later)
        db.close()
        assert added > 0 and len(g.scheduled) == n + added
        assert max(d for _, d in g.scheduled.values()) == (later + timedelta(days=13)).isoformat()
    finally:
        app.dependency_overrides.clear()


def test_auto_setup_uses_saved_garmin_workouts(client, tmp_path):
    svc = setup_service(client, tmp_path)
    try:
        r = client.post("/api/setup/auto", json={"focus": "lose_weight", "equipment": "home", "send_to_watch": True}).json()
        text = " ".join(r["summary"])
        assert "Workout plan from your Garmin workouts: Gym Upper, Gym Lower" in text
        assert "Sent to your fenix" in text and "Goblet Squat" in text
        assert client.get("/api/plans/active").json()["name"].startswith("My Garmin workouts")
        assert len(svc._client.scheduled) > 0
    finally:
        app.dependency_overrides.clear()


def test_auto_setup_can_skip_watch(client, tmp_path):
    svc = setup_service(client, tmp_path)
    try:
        client.post("/api/setup/auto", json={"focus": "lose_weight", "equipment": "home", "send_to_watch": False})
        assert svc._client.scheduled == {} and all(wid < 900 for wid in svc._client.library)
    finally:
        app.dependency_overrides.clear()


def test_adapting_twice_changes_nothing_more():
    once, _ = gw.adapt_workout(LOWER, goal="lose", equipment="home")
    twice, changes = gw.adapt_workout(once, goal="lose", equipment="home")
    assert twice == once and changes == []


def test_no_duplicate_home_swaps_in_one_workout():
    adapted, _ = gw.adapt_workout(LOWER, goal="lose", equipment="home")
    names = [e["exercise"] for e in gw.parse_workout(adapted)["exercises"]]
    assert names == ["Goblet Squat", "Dumbbell Step-up", "Dumbbell Reverse Lunge"]
    assert all(o in gw.NAMES for opts in gw.HOME_SUBS.values() for o in opts)
