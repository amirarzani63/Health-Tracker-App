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
# Meal ideas: everyday food from any supermarket (no tofu/tempeh/specialty items).
# Each has the ingredients for ONE serving: (item, amount, unit, store section). The weekly
# shopping list adds these up for the week's menu. tags: meat, fish, dairy, egg, gluten, nuts, soy
def _m(meal, name, kcal, p, c, f, fiber, tags, ingredients):
    return {"meal": meal, "name": name, "calories": kcal, "protein_g": p, "carbs_g": c, "fat_g": f,
            "fiber_g": fiber, "tags": tags, "ingredients": ingredients}


P, M, D, B, PA, FR = "Fruit & vegetables", "Meat & fish", "Dairy & eggs", "Bread", "Pantry", "Frozen"
MEAL_IDEAS = [
    # breakfast
    _m("breakfast", "Greek yogurt bowl with berries, oats & honey", 420, 30, 58, 8, 7, ["dairy", "gluten"],
       [("Greek yogurt (plain)", 200, "g", D), ("Frozen mixed berries", 75, "g", FR), ("Rolled oats", 30, "g", PA), ("Honey", 1, "tbsp", PA)]),
    _m("breakfast", "3-egg veggie omelette with whole-wheat toast", 410, 27, 30, 19, 5, ["egg", "gluten", "dairy"],
       [("Eggs", 3, "", D), ("Bell pepper", 0.5, "", P), ("Baby spinach", 30, "g", P), ("Whole-wheat bread", 1, "slice", B), ("Butter", 5, "g", D)]),
    _m("breakfast", "Overnight oats with whey, banana & peanut butter", 520, 34, 66, 14, 8, ["dairy", "nuts", "gluten"],
       [("Rolled oats", 50, "g", PA), ("Milk", 200, "ml", D), ("Whey protein powder", 1, "scoop", PA), ("Bananas", 1, "", P), ("Peanut butter", 1, "tbsp", PA)]),
    _m("breakfast", "Scrambled eggs with spinach on whole-wheat toast", 420, 27, 30, 21, 5, ["egg", "gluten", "dairy"],
       [("Eggs", 3, "", D), ("Baby spinach", 40, "g", P), ("Whole-wheat bread", 2, "slice", B), ("Butter", 5, "g", D)]),
    _m("breakfast", "Cottage cheese with pineapple & almonds", 340, 30, 26, 12, 3, ["dairy", "nuts"],
       [("Cottage cheese", 200, "g", D), ("Pineapple chunks (fresh or canned)", 100, "g", P), ("Almonds", 15, "g", PA)]),
    _m("breakfast", "Oatmeal with banana, peanut butter & almond milk", 430, 12, 66, 14, 9, ["nuts", "gluten"],
       [("Rolled oats", 50, "g", PA), ("Almond milk", 250, "ml", D), ("Bananas", 1, "", P), ("Peanut butter", 1, "tbsp", PA)]),
    # lunch
    _m("lunch", "Grilled chicken rice bowl with roasted vegetables", 615, 43, 69, 18, 5, ["meat"],
       [("Chicken breast", 150, "g", M), ("Rice", 75, "g", PA), ("Frozen mixed vegetables", 150, "g", FR), ("Olive oil", 1, "tbsp", PA)]),
    _m("lunch", "Lentil & vegetable soup with bread", 435, 22, 68, 7, 14, ["gluten"],
       [("Red lentils (dry)", 70, "g", PA), ("Carrots", 1, "", P), ("Onions", 0.5, "", P), ("Canned diced tomatoes", 100, "g", PA),
        ("Whole-wheat bread", 1, "slice", B), ("Olive oil", 1, "tsp", PA)]),
    _m("lunch", "Tuna salad wrap with lettuce & avocado", 460, 36, 40, 17, 6, ["fish", "gluten", "egg"],
       [("Canned tuna (in water)", 1, "can", PA), ("Large flour tortillas", 1, "", B), ("Light mayonnaise", 1, "tbsp", PA),
        ("Lettuce", 30, "g", P), ("Avocados", 0.25, "", P)]),
    _m("lunch", "Chickpea, feta & cucumber salad", 420, 16, 36, 25, 9, ["dairy"],
       [("Canned chickpeas", 0.5, "can", PA), ("Feta cheese", 40, "g", D), ("Cucumbers", 0.5, "", P), ("Tomatoes", 1, "", P),
        ("Olive oil", 1, "tbsp", PA), ("Lemons", 0.5, "", P)]),
    _m("lunch", "Turkey & cheese sandwich with an apple", 445, 34, 58, 10, 8, ["meat", "dairy", "gluten"],
       [("Whole-wheat bread", 2, "slice", B), ("Sliced turkey breast", 100, "g", M), ("Cheese slices", 1, "slice", D),
        ("Lettuce", 20, "g", P), ("Tomatoes", 0.5, "", P), ("Apples", 1, "", P)]),
    _m("lunch", "Chicken burrito bowl with black beans & salsa", 530, 43, 65, 10, 9, ["meat", "dairy"],
       [("Chicken breast", 120, "g", M), ("Rice", 60, "g", PA), ("Canned black beans", 0.33, "can", PA), ("Salsa", 2, "tbsp", PA),
        ("Shredded cheese", 20, "g", D), ("Lettuce", 30, "g", P)]),
    # dinner
    _m("dinner", "Baked salmon, sweet potato & broccoli", 570, 37, 50, 25, 9, ["fish"],
       [("Salmon fillets", 150, "g", M), ("Sweet potatoes", 1, "", P), ("Broccoli", 150, "g", P), ("Olive oil", 1, "tsp", PA)]),
    _m("dinner", "Beef & vegetable stir-fry with rice", 590, 41, 66, 15, 5, ["meat", "soy", "gluten"],
       [("Beef sirloin (or stir-fry strips)", 150, "g", M), ("Rice", 70, "g", PA), ("Frozen stir-fry vegetables", 150, "g", FR),
        ("Soy sauce", 1, "tbsp", PA), ("Vegetable oil", 1, "tsp", PA)]),
    _m("dinner", "Chicken fajitas with peppers & tortillas", 545, 44, 60, 15, 6, ["meat", "gluten"],
       [("Chicken breast", 150, "g", M), ("Bell pepper", 1, "", P), ("Onions", 0.5, "", P), ("Small flour tortillas", 2, "", B),
        ("Vegetable oil", 1, "tsp", PA), ("Salsa", 2, "tbsp", PA)]),
    _m("dinner", "Red lentil dal with rice & spinach", 555, 23, 99, 6, 15, [],
       [("Red lentils (dry)", 70, "g", PA), ("Rice", 60, "g", PA), ("Onions", 0.5, "", P), ("Canned diced tomatoes", 100, "g", PA),
        ("Baby spinach", 50, "g", P), ("Vegetable oil", 1, "tsp", PA)]),
    _m("dinner", "Whole-wheat pasta with turkey bolognese", 585, 39, 71, 15, 9, ["meat", "gluten", "dairy"],
       [("Ground turkey", 130, "g", M), ("Whole-wheat pasta", 80, "g", PA), ("Tomato sauce / passata", 150, "g", PA),
        ("Onions", 0.5, "", P), ("Parmesan", 10, "g", D)]),
    _m("dinner", "Shrimp & vegetable stir-fry with rice", 495, 38, 70, 6, 5, ["fish", "soy", "gluten"],
       [("Frozen raw shrimp", 150, "g", FR), ("Rice", 70, "g", PA), ("Frozen stir-fry vegetables", 150, "g", FR),
        ("Soy sauce", 1, "tbsp", PA), ("Vegetable oil", 1, "tsp", PA)]),
    _m("dinner", "Chicken thigh tray bake with potatoes & green beans", 575, 42, 53, 22, 7, ["meat"],
       [("Boneless chicken thighs", 180, "g", M), ("Potatoes", 250, "g", P), ("Green beans", 150, "g", P), ("Olive oil", 1, "tbsp", PA)]),
    # snacks
    _m("snack", "Protein shake (whey) with banana", 230, 26, 30, 2, 3, ["dairy"],
       [("Whey protein powder", 1, "scoop", PA), ("Bananas", 1, "", P)]),
    _m("snack", "Greek yogurt with berries", 140, 17, 16, 0.5, 2, ["dairy"],
       [("Greek yogurt (plain)", 170, "g", D), ("Frozen mixed berries", 75, "g", FR)]),
    _m("snack", "Apple with 2 tbsp peanut butter", 285, 8, 31, 16, 6.5, ["nuts"],
       [("Apples", 1, "", P), ("Peanut butter", 2, "tbsp", PA)]),
    _m("snack", "Hummus with carrot & cucumber sticks", 180, 6, 20, 9, 6, [],
       [("Hummus", 4, "tbsp", D), ("Carrots", 1, "", P), ("Cucumbers", 0.5, "", P)]),
    _m("snack", "Hard-boiled eggs (2) & cherry tomatoes", 170, 13, 5, 10, 1.5, ["egg"],
       [("Eggs", 2, "", D), ("Cherry tomatoes", 100, "g", P)]),
    _m("snack", "Rice cakes with cottage cheese", 142, 13.5, 18, 1.5, 0.5, ["dairy"],
       [("Rice cakes", 2, "", PA), ("Cottage cheese", 100, "g", D)]),
    _m("snack", "String cheese & almonds", 167, 10, 3, 13, 2, ["dairy", "nuts"],
       [("String cheese", 1, "", D), ("Almonds", 15, "g", PA)]),
]

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
