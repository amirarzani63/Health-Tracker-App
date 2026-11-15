from types import SimpleNamespace
from datetime import date

from app.services import nutrition


def profile(**kw):
    base = dict(sex="male", birth_year=1990, height_cm=180, weight_kg=80, activity_level="moderate",
                goal="maintain", diet_type="omnivore", allergies=[])
    base.update(kw)
    return SimpleNamespace(**base)


def test_bmr_mifflin():
    # 10*80 + 6.25*180 - 5*35 + 5 = 1755
    assert nutrition.bmr_mifflin("male", 80, 180, 35) == 1755
    assert nutrition.bmr_mifflin("female", 80, 180, 35) == 1755 - 166


def test_targets_estimate_and_goal():
    t = nutrition.compute_targets(profile(), today=date(2025, 1, 1))
    assert t.source == "estimate"
    assert round(t.tdee) == round(1755 * 1.55)
    lose = nutrition.compute_targets(profile(goal="lose"), today=date(2025, 1, 1))
    assert round(t.calories - lose.calories) == 500
    assert lose.protein_g == 160  # 2 g/kg on a cut


def test_targets_use_garmin_active_calories():
    t = nutrition.compute_targets(profile(), garmin_active_calories=900, garmin_bmr=1800, today=date(2025, 1, 1))
    assert t.source == "garmin"
    assert round(t.tdee) == round((1800 + 900) * 1.1)


def test_macros_add_up():
    t = nutrition.compute_targets(profile(goal="gain"), today=date(2025, 1, 1))
    assert abs(t.protein_g * 4 + t.carbs_g * 4 + t.fat_g * 9 - t.calories) < 1


def test_vegan_suggestions_exclude_animal_products():
    p = profile(diet_type="vegan", allergies=["nuts"])
    t = nutrition.compute_targets(p, today=date(2025, 1, 1))
    res = nutrition.suggest_meals(p, t, {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}, set())
    names = {m["name"] for meals in res["meals"].values() for m in meals}
    assert names
    allowed = {m["name"] for m in nutrition.MEAL_IDEAS if not set(m["tags"]) & {"meat", "fish", "dairy", "egg", "nuts"}}
    assert names <= allowed


def test_suggestions_skip_logged_meals():
    p = profile()
    t = nutrition.compute_targets(p, today=date(2025, 1, 1))
    res = nutrition.suggest_meals(p, t, {"calories": 500, "protein_g": 30, "carbs_g": 50, "fat_g": 15}, {"breakfast"})
    assert "breakfast" not in res["meals"]
    assert res["remaining"]["calories"] == round(t.calories - 500)


def test_protein_uses_reference_weight_above_bmi_30():
    # 105 kg at 180 cm (BMI 32.4): protein from the BMI-27 weight (87.5 kg) x 2.0 g/kg
    t = nutrition.compute_targets(profile(weight_kg=105, height_cm=180, goal="lose", birth_year=1984), today=date(2026, 11, 15))
    assert round(t.protein_g) == 175
    assert round(t.bmr) == 1970  # Mifflin-St Jeor, male, 42 years
    # normal BMI: unchanged, total weight
    assert nutrition.compute_targets(profile(goal="lose"), today=date(2025, 1, 1)).protein_g == 160
