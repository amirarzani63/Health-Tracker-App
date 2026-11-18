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
