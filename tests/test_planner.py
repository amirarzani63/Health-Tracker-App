import pytest

from app.services.workout_planner import EXERCISES, generate_plan, readiness
from types import SimpleNamespace


@pytest.mark.parametrize("days", [2, 3, 4, 5, 6])
@pytest.mark.parametrize("equipment", ["gym", "home", "bodyweight"])
def test_plan_shapes(days, equipment):
    plan = generate_plan(goal="hypertrophy", days_per_week=days, equipment=equipment, include_cardio=False)
    strength = [d for d in plan["days"] if d["type"] == "strength"]
    assert len(strength) == days
    for d in strength:
        for ex in d["exercises"]:
            assert ex["exercise"] in EXERCISES[ex["pattern"]][equipment]
    assert len({d["weekday"] for d in plan["days"]}) == len(plan["days"])  # no double-booked days


def test_cardio_and_deload():
    plan = generate_plan(goal="endurance", days_per_week=3, weeks=6)
    cardio = [d for d in plan["days"] if d["type"] == "cardio"]
    assert len(cardio) == 3 and all("Zone" in d["zone"] for d in cardio)
    assert "Deload" in plan["progression"][-1]["note"]
    assert len(plan["progression"]) == 6


def test_beginner_capped_to_full_body():
    plan = generate_plan(days_per_week=6, experience="beginner", include_cardio=False)
    assert all(d["title"].startswith("Full Body") for d in plan["days"])


def test_readiness():
    assert readiness(None)["level"] == "unknown"
    good = SimpleNamespace(body_battery_high=90, sleep_s=8 * 3600, avg_stress=20)
    low = SimpleNamespace(body_battery_high=30, sleep_s=5 * 3600, avg_stress=60)
    assert readiness(good)["level"] == "good"
    assert readiness(low)["level"] == "low"
