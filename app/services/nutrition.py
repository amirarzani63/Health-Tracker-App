"""Calorie/macro targets and meal suggestions.

Targets use the Mifflin-St Jeor equation for BMR. When Garmin data is
available for a day, the target is built from the watch's measured
expenditure (BMR + active calories) instead of a generic activity
multiplier, so a long run on the fenix automatically raises the budget.
"""

from dataclasses import asdict, dataclass
from datetime import date

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# Questionnaire profiles: everyday activity WITHOUT workouts (non-exercise), then the planned workouts are added on top.
DAILY_LIFE = {"sedentary": 1.2, "light": 1.3, "moderate": 1.4, "active": 1.55, "very_active": 1.7}
WORKOUT_MET = 5.0  # mixed strength training with short cardio, moderate effort


def workout_kcal_per_day(profile) -> float:
    """Average daily calories from the planned workouts (days × minutes), spread over the week."""
    days, mins = getattr(profile, "training_days", 0) or 0, getattr(profile, "session_minutes", 0) or 0
    return WORKOUT_MET * 3.5 * profile.weight_kg / 200 * mins * days / 7


GOAL_ADJUST = {"lose": -500, "maintain": 0, "gain": 300}
KCAL_PER_KG = 7700  # energy in 1 kg of body fat


def goal_adjust(profile, goals) -> tuple[float, str]:
    """Daily calories to add (+) or remove (-) to reach the goal weight in the chosen number of weeks.

    Safe limits: lose at most 1% of body weight (and 1,000 kcal) a day's worth per week; gain at most +500/day.
    Returns (adjustment, note).
    """
    target = goals.target_weight_kg if goals is not None else None
    weeks = getattr(profile, "goal_weeks", None)
    if not target or not weeks or profile.goal == "maintain":
        return float(GOAL_ADJUST.get(profile.goal, 0)) if not getattr(profile, "details_done", False) else 0.0, ""
    change = target - profile.weight_kg
    daily = change * KCAL_PER_KG / (weeks * 7)
    note = ""
    if daily < 0:
        cap = max(-1000.0, -profile.weight_kg * 0.01 * KCAL_PER_KG / 7)
        if daily < cap:
            daily, note = cap, "capped at a safe rate of loss"
    else:
        if daily > 500:
            daily, note = 500.0, "capped at a safe rate of gain"
    return daily, note
# grams of protein per kg body weight
PROTEIN_PER_KG = {"lose": 2.0, "maintain": 1.6, "gain": 1.8}
FAT_SHARE = 0.27  # fraction of calories from fat


def age_on(birth_year: int, today: date | None = None) -> int:
    return (today or date.today()).year - birth_year


def bmr_mifflin(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if sex == "male" else base - 161


def protein_reference_weight(profile) -> float:
    """Protein needs follow lean mass, so with a BMI over 30 use the weight at BMI 27 instead of total weight."""
    h = (profile.height_cm or 0) / 100
    if h <= 0:
        return profile.weight_kg
    return min(profile.weight_kg, 27 * h * h) if profile.weight_kg / (h * h) > 30 else profile.weight_kg


@dataclass
class Targets:
    bmr: float
    tdee: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    source: str  # "goal" (your own target), "garmin" (measured burn) or "estimate"
    fiber_g: float = 30

    def dict(self):
        return {k: round(v) if isinstance(v, float) else v for k, v in asdict(self).items()}


def compute_targets(profile, garmin_active_calories: float | None = None,
                    garmin_bmr: float | None = None, today: date | None = None, goals=None) -> Targets:
    bmr = bmr_mifflin(profile.sex, profile.weight_kg, profile.height_cm, age_on(profile.birth_year, today))
    if garmin_active_calories is not None:
        # Measured: watch BMR (or ours) + actual active burn, plus ~10% thermic effect of food.
        base = garmin_bmr or bmr
        tdee = (base + garmin_active_calories) * 1.1
        source = "garmin"
    else:
        if getattr(profile, "details_done", False):
            tdee = bmr * DAILY_LIFE.get(profile.activity_level, 1.2) + workout_kcal_per_day(profile)
        else:
            tdee = bmr * ACTIVITY_MULTIPLIERS.get(profile.activity_level, 1.55)
        source = "estimate"

    floor = 1500 if profile.sex == "male" else 1200
    adjust, _ = goal_adjust(profile, goals)
    calories = max(floor, tdee + adjust)
    g = goals
    if g is not None and g.calorie_target:
        calories, source = float(g.calorie_target), "goal"
    protein = (g.protein_target_g if g is not None and g.protein_target_g is not None
               else max(PROTEIN_PER_KG.get(profile.goal, 1.6),
                        1.8 if getattr(profile, "muscle_goal", "") in ("build", "strength") else 0) * protein_reference_weight(profile))
    fat = g.fat_target_g if g is not None and g.fat_target_g is not None else calories * FAT_SHARE / 9
    carbs = (g.carbs_target_g if g is not None and g.carbs_target_g is not None
             else max(0.0, (calories - protein * 4 - fat * 9) / 4))
    fiber = g.fiber_target_g if g is not None and g.fiber_target_g is not None else 30
    return Targets(bmr, tdee, calories, protein, carbs, fat, source, fiber)


# ---------------------------------------------------------------------------
# The food database lives in app/data/foods.csv (see services/food_db.py).
# ---------------------------------------------------------------------------

# tags: meat, fish, dairy, egg, gluten, nuts, soy
# Meal ideas with approximate macros. tags as above.
MEAL_IDEAS = [
    {"meal": "breakfast", "name": "Greek yogurt bowl with berries, oats & honey", "calories": 420, "protein_g": 30, "carbs_g": 58, "fat_g": 8, "tags": ["dairy", "gluten"]},
    {"meal": "breakfast", "name": "3-egg veggie omelette with whole-grain toast", "calories": 410, "protein_g": 27, "carbs_g": 30, "fat_g": 19, "tags": ["egg", "gluten"]},
    {"meal": "breakfast", "name": "Overnight oats with pea protein, banana & PB", "calories": 520, "protein_g": 34, "carbs_g": 66, "fat_g": 14, "tags": ["nuts", "gluten"]},
    {"meal": "breakfast", "name": "Tofu scramble with spinach, peppers & toast", "calories": 390, "protein_g": 26, "carbs_g": 32, "fat_g": 17, "tags": ["soy", "gluten"]},
    {"meal": "breakfast", "name": "Cottage cheese with pineapple & almonds", "calories": 340, "protein_g": 30, "carbs_g": 26, "fat_g": 12, "tags": ["dairy", "nuts"]},
    {"meal": "lunch", "name": "Grilled chicken quinoa bowl with roasted veg", "calories": 560, "protein_g": 48, "carbs_g": 55, "fat_g": 15, "tags": ["meat"]},
    {"meal": "lunch", "name": "Lentil & vegetable soup with crusty bread", "calories": 480, "protein_g": 24, "carbs_g": 76, "fat_g": 8, "tags": ["gluten"]},
    {"meal": "lunch", "name": "Tuna salad wrap with greens & avocado", "calories": 470, "protein_g": 36, "carbs_g": 38, "fat_g": 19, "tags": ["fish", "gluten"]},
    {"meal": "lunch", "name": "Chickpea, feta & cucumber Mediterranean salad", "calories": 510, "protein_g": 22, "carbs_g": 52, "fat_g": 24, "tags": ["dairy"]},
    {"meal": "lunch", "name": "Tofu & edamame soba noodle bowl", "calories": 540, "protein_g": 32, "carbs_g": 68, "fat_g": 15, "tags": ["soy", "gluten"]},
    {"meal": "lunch", "name": "Black bean & sweet potato burrito bowl", "calories": 530, "protein_g": 20, "carbs_g": 88, "fat_g": 11, "tags": []},
    {"meal": "dinner", "name": "Baked salmon, sweet potato & broccoli", "calories": 610, "protein_g": 42, "carbs_g": 45, "fat_g": 28, "tags": ["fish"]},
    {"meal": "dinner", "name": "Lean beef stir-fry with brown rice", "calories": 650, "protein_g": 45, "carbs_g": 62, "fat_g": 22, "tags": ["meat", "soy"]},
    {"meal": "dinner", "name": "Chicken fajitas with peppers & corn tortillas", "calories": 580, "protein_g": 46, "carbs_g": 54, "fat_g": 18, "tags": ["meat"]},
    {"meal": "dinner", "name": "Red lentil dal with basmati rice & spinach", "calories": 560, "protein_g": 25, "carbs_g": 92, "fat_g": 10, "tags": []},
    {"meal": "dinner", "name": "Whole-wheat pasta with turkey bolognese", "calories": 640, "protein_g": 44, "carbs_g": 72, "fat_g": 17, "tags": ["meat", "gluten"]},
    {"meal": "dinner", "name": "Shrimp & vegetable coconut curry with rice", "calories": 600, "protein_g": 34, "carbs_g": 66, "fat_g": 21, "tags": ["fish"]},
    {"meal": "dinner", "name": "Tempeh & vegetable peanut stir-fry", "calories": 590, "protein_g": 33, "carbs_g": 50, "fat_g": 28, "tags": ["soy", "nuts"]},
    {"meal": "snack", "name": "Protein shake (whey) with banana", "calories": 230, "protein_g": 26, "carbs_g": 30, "fat_g": 2, "tags": ["dairy"]},
    {"meal": "snack", "name": "Pea-protein smoothie with berries", "calories": 220, "protein_g": 25, "carbs_g": 24, "fat_g": 3, "tags": []},
    {"meal": "snack", "name": "Apple with 2 tbsp peanut butter", "calories": 285, "protein_g": 8, "carbs_g": 31, "fat_g": 16, "tags": ["nuts"]},
    {"meal": "snack", "name": "Hummus with carrot & cucumber sticks", "calories": 180, "protein_g": 6, "carbs_g": 20, "fat_g": 9, "tags": []},
    {"meal": "snack", "name": "Hard-boiled eggs (2) & cherry tomatoes", "calories": 170, "protein_g": 13, "carbs_g": 5, "fat_g": 10, "tags": ["egg"]},
    {"meal": "snack", "name": "Rice cakes with cottage cheese", "calories": 190, "protein_g": 16, "carbs_g": 24, "fat_g": 2, "tags": ["dairy"]},
]

# Approximate fibre (g) per serving / per meal idea, merged into the tables above.
_FIBER = {
    "Oatmeal (1 cup cooked)": 4, "Banana, medium": 3.1, "Apple, medium": 4.4, "Blueberries (1 cup)": 3.6,
    "Tofu, firm (150g)": 3.5, "Lentils, cooked (1 cup)": 15.6, "Chickpeas, cooked (1 cup)": 12.5,
    "Brown rice, cooked (1 cup)": 3.5, "Quinoa, cooked (1 cup)": 5.2, "Sweet potato, baked (medium)": 3.8,
    "Whole wheat bread (slice)": 1.9, "Whole wheat pasta, cooked (1 cup)": 6.3, "Broccoli (1 cup)": 5.1,
    "Mixed salad greens (2 cups)": 2, "Avocado (half)": 5, "Almonds (28g)": 3.5, "Peanut butter (2 tbsp)": 1.9,
    "Pea protein (1 scoop)": 1,
    "Greek yogurt bowl with berries, oats & honey": 5, "3-egg veggie omelette with whole-grain toast": 4,
    "Overnight oats with pea protein, banana & PB": 8, "Tofu scramble with spinach, peppers & toast": 6,
    "Cottage cheese with pineapple & almonds": 3, "Grilled chicken quinoa bowl with roasted veg": 8,
    "Lentil & vegetable soup with crusty bread": 16, "Tuna salad wrap with greens & avocado": 8,
    "Chickpea, feta & cucumber Mediterranean salad": 11, "Tofu & edamame soba noodle bowl": 8,
    "Black bean & sweet potato burrito bowl": 18, "Baked salmon, sweet potato & broccoli": 9,
    "Lean beef stir-fry with brown rice": 6, "Chicken fajitas with peppers & corn tortillas": 7,
    "Red lentil dal with basmati rice & spinach": 14, "Whole-wheat pasta with turkey bolognese": 10,
    "Shrimp & vegetable coconut curry with rice": 5, "Tempeh & vegetable peanut stir-fry": 9,
    "Protein shake (whey) with banana": 3, "Pea-protein smoothie with berries": 5,
    "Apple with 2 tbsp peanut butter": 6.5, "Hummus with carrot & cucumber sticks": 6,
    "Hard-boiled eggs (2) & cherry tomatoes": 1.5, "Rice cakes with cottage cheese": 1,
}
for _item in MEAL_IDEAS:
    _item["fiber_g"] = _FIBER.get(_item["name"], 0)

EXCLUDED_BY_DIET = {
    "omnivore": set(),
    "pescatarian": {"meat"},
    "vegetarian": {"meat", "fish"},
    "vegan": {"meat", "fish", "dairy", "egg"},
}


def allowed(item: dict, diet_type: str, allergies: list[str]) -> bool:
    banned = EXCLUDED_BY_DIET.get(diet_type, set()) | {a.lower().strip() for a in allergies}
    return not (set(item["tags"]) & banned)


def suggest_meals(profile, targets: Targets, consumed: dict, logged_meals: set[str]) -> dict:
    """Pick meal ideas that fit the remaining calorie/protein budget.

    Ranks each candidate by how well it fits a fair share of what's left,
    with extra weight on hitting protein, then returns tips.
    """
    remaining = {
        "calories": targets.calories - consumed["calories"],
        "protein_g": targets.protein_g - consumed["protein_g"],
        "carbs_g": targets.carbs_g - consumed["carbs_g"],
        "fat_g": targets.fat_g - consumed["fat_g"],
    }
    order = ["breakfast", "lunch", "dinner", "snack"]
    open_meals = [m for m in order if m not in logged_meals] or ["snack"]
    # Main meals take bigger shares than snacks
    weights = {"breakfast": 0.27, "lunch": 0.33, "dinner": 0.33, "snack": 0.12}
    total_w = sum(weights[m] for m in open_meals)

    suggestions = {}
    for meal in open_meals:
        share = weights[meal] / total_w
        budget_cal = max(0.0, remaining["calories"] * share)
        budget_pro = max(0.0, remaining["protein_g"] * share)
        candidates = [m for m in MEAL_IDEAS if m["meal"] == meal and allowed(m, profile.diet_type, profile.allergies or [])]

        def score(m):
            cal_err = abs(m["calories"] - budget_cal) / max(budget_cal, 150)
            pro_err = max(0.0, budget_pro - m["protein_g"]) / max(budget_pro, 10)
            return cal_err + 1.5 * pro_err

        ranked = sorted(candidates, key=score)[:3]
        suggestions[meal] = [{k: v for k, v in m.items() if k != "tags"} for m in ranked]

    tips = []
    if remaining["calories"] < -150:
        tips.append(f"You're about {round(-remaining['calories'])} kcal over today's target — keep the rest of the day light, veggies and lean protein.")
    elif remaining["calories"] > 0 and not open_meals:
        tips.append("Calories remain but all meals are logged — a protein-rich snack would fit well.")
    if remaining["protein_g"] > 40:
        tips.append(f"Still {round(remaining['protein_g'])} g protein to go. Prioritise a protein source at your next meal.")
    if targets.source == "garmin":
        tips.append("Today's target includes the active calories your Garmin recorded.")
    remaining_fiber = targets.fiber_g - consumed.get("fiber_g", 0)
    if remaining_fiber > 15 and open_meals:
        tips.append(f"{round(remaining_fiber)} g fibre to go: beans, lentils, berries, oats and veg are easy wins.")
    if profile.goal == "lose":
        tips.append("Fill half the plate with vegetables to stay full on fewer calories.")
    elif profile.goal == "gain":
        tips.append("Add calorie-dense extras like olive oil, nuts or an extra carb serving to hit your surplus.")

    return {"remaining": {k: round(v) for k, v in remaining.items()}, "meals": suggestions, "tips": tips}


def workout_fuel_tip(activity_calories: float | None, duration_s: float) -> str | None:
    if duration_s >= 75 * 60 or (activity_calories or 0) >= 800:
        return "Long session today — get 1–1.2 g/kg of carbs plus 20–30 g protein within a couple of hours to refuel."
    if duration_s >= 30 * 60:
        return "Good session — include 20–30 g of protein in your next meal to support recovery."
    return None
