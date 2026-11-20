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
        from app.services.workout_planner import CATALOG, EQUIPMENT_PRESETS
        have = EQUIPMENT_PRESETS[equipment]
        for ex in d["exercises"]:
            ok = {n for n, needs, _ in CATALOG[ex["pattern"]] if needs <= have}
            assert ex["exercise"] in ok, (equipment, ex["exercise"])
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



def test_equipment_age_and_experience_shape_the_plan():
    from app.services.workout_planner import CATALOG
    kit = ["dumbbells", "bench", "cable", "pullup"]  # no barbell, no machines
    plan = generate_plan(goal="fat_loss", days_per_week=4, experience="beginner", include_cardio=False, equipment_list=kit)
    needs = {n: nd for lst in CATALOG.values() for n, nd, _ in lst}
    for d in plan["days"]:
        for ex in d["exercises"]:
            assert needs.get(ex["exercise"], set()) <= set(kit), ex["exercise"]
    pro = generate_plan(goal="strength", days_per_week=4, experience="advanced", include_cardio=False)
    firsts = [d["exercises"][0]["exercise"] for d in pro["days"]]
    assert any("Barbell" in f or "deadlift" in f.lower() or "squat" in f.lower() for f in firsts)
    older = generate_plan(goal="strength", days_per_week=4, experience="advanced", include_cardio=False, age=63)
    mains = [e["exercise"] for d in older["days"] for e in d["exercises"][:2]]
    assert "Barbell back squat" not in mains and "Conventional deadlift" not in mains
    assert "Program basis" in older["progression"][0]["note"] and "60+" in older["progression"][0]["note"]
