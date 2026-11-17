"""Calorie counter: estimate foods and macros from a typed description.

Runs fully inside the app using a built-in food table -- no outside service,
no API key, no cost. Example input: "2 eggs, 150g chicken breast and a banana".
Estimates are returned as a draft for the user to review; nothing is saved here.
"""

import re
from typing import Any

# name aliases | unit label | grams per unit | per unit: kcal, protein, carbs, fat, fibre
# (values are typical USDA-style figures for the stated unit)
_FOODS: list[tuple[str, str, float, float, float, float, float, float]] = [
    # eggs & dairy
    ("egg|eggs|boiled egg|scrambled egg|fried egg", "1 large egg", 50, 72, 6.3, 0.4, 4.8, 0),
    ("egg white|egg whites", "1 egg white", 33, 17, 3.6, 0.2, 0.1, 0),
    ("milk|whole milk", "1 cup (240 ml)", 240, 149, 7.7, 11.7, 7.9, 0),
    ("skim milk|semi skimmed milk|low fat milk|2% milk", "1 cup (240 ml)", 240, 110, 8.0, 12.0, 3.0, 0),
    ("oat milk", "1 cup (240 ml)", 240, 120, 3.0, 16.0, 5.0, 2),
    ("almond milk", "1 cup (240 ml)", 240, 40, 1.0, 2.0, 3.0, 0.5),
    ("greek yogurt|greek yoghurt", "1 cup (200 g)", 200, 146, 20.0, 7.8, 3.8, 0),
    ("yogurt|yoghurt", "1 pot (150 g)", 150, 92, 5.2, 7.0, 4.9, 0),
    ("cottage cheese", "1/2 cup (113 g)", 113, 111, 12.5, 4.1, 4.9, 0),
    ("cheese|cheddar", "1 slice (28 g)", 28, 113, 7.0, 0.4, 9.3, 0),
    ("feta", "28 g", 28, 75, 4.0, 1.2, 6.0, 0),
    ("mozzarella", "28 g", 28, 85, 6.3, 0.6, 6.3, 0),
    ("parmesan", "1 tbsp (5 g)", 5, 21, 1.9, 0.2, 1.4, 0),
    ("butter", "1 tbsp (14 g)", 14, 102, 0.1, 0, 11.5, 0),
    ("cream cheese", "1 tbsp (15 g)", 15, 51, 0.9, 0.8, 5.0, 0),
    ("whey|protein shake|protein powder|scoop of protein", "1 scoop (30 g)", 30, 120, 24.0, 3.0, 1.5, 0),
    # meat & fish
    ("chicken breast|chicken|grilled chicken", "100 g cooked", 100, 165, 31.0, 0, 3.6, 0),
    ("chicken thigh", "100 g cooked", 100, 209, 26.0, 0, 10.9, 0),
    ("turkey", "100 g cooked", 100, 147, 30.0, 0, 2.1, 0),
    ("ground beef|minced beef|mince|beef mince", "100 g cooked", 100, 250, 26.0, 0, 15.0, 0),
    ("steak|beef", "100 g cooked", 100, 271, 25.0, 0, 19.0, 0),
    ("lamb", "100 g cooked", 100, 294, 25.0, 0, 21.0, 0),
    ("pork chop|pork", "100 g cooked", 100, 242, 27.0, 0, 14.0, 0),
    ("bacon", "1 slice (8 g)", 8, 43, 3.0, 0.1, 3.3, 0),
    ("ham", "1 slice (28 g)", 28, 33, 5.0, 0.6, 1.0, 0),
    ("sausage|sausages", "1 sausage (75 g)", 75, 230, 10.0, 2.0, 20.0, 0),
    ("salmon", "100 g cooked", 100, 206, 22.0, 0, 12.0, 0),
    ("tuna", "1 can drained (140 g)", 140, 160, 36.0, 0, 1.4, 0),
    ("shrimp|prawns|prawn", "100 g cooked", 100, 99, 24.0, 0.2, 0.3, 0),
    ("cod|white fish|tilapia|fish", "100 g cooked", 100, 105, 23.0, 0, 0.9, 0),
    ("kebab|doner", "1 kebab", 350, 800, 40.0, 70.0, 40.0, 4),
    ("tofu", "100 g", 100, 144, 15.6, 3.5, 8.7, 2.3),
    # grains & bread
    ("bread|toast|sourdough|slice of bread", "1 slice (32 g)", 32, 80, 3.0, 15.0, 1.0, 1.0),
    ("whole wheat bread|wholemeal bread|brown bread", "1 slice (32 g)", 32, 80, 4.0, 14.0, 1.1, 2.0),
    ("bagel", "1 bagel", 100, 270, 10.0, 53.0, 1.5, 2.3),
    ("pita|pitta", "1 pita", 60, 165, 5.5, 33.0, 0.7, 1.3),
    ("tortilla|wrap", "1 large tortilla", 70, 210, 5.5, 35.0, 5.0, 2.0),
    ("lavash|naan", "1 piece (90 g)", 90, 262, 8.7, 45.0, 5.1, 2.0),
    ("croissant", "1 croissant", 57, 231, 4.7, 26.0, 12.0, 1.5),
    ("oats|oatmeal|porridge", "1/2 cup dry (40 g)", 40, 150, 5.0, 27.0, 2.5, 4.0),
    ("granola", "1/2 cup (60 g)", 60, 270, 6.0, 38.0, 11.0, 4.0),
    ("cereal|cornflakes", "1 cup (30 g)", 30, 110, 2.0, 25.0, 0.3, 1.0),
    ("rice|white rice|basmati", "1 cup cooked (160 g)", 160, 205, 4.3, 45.0, 0.4, 0.6),
    ("brown rice", "1 cup cooked (195 g)", 195, 216, 5.0, 45.0, 1.8, 3.5),
    ("pasta|spaghetti|penne|noodles", "1 cup cooked (140 g)", 140, 220, 8.1, 43.0, 1.3, 2.5),
    ("quinoa", "1 cup cooked (185 g)", 185, 222, 8.1, 39.0, 3.6, 5.2),
    ("couscous", "1 cup cooked (157 g)", 157, 176, 6.0, 36.0, 0.3, 2.2),
    ("potato|potatoes|baked potato|boiled potatoes", "1 medium (173 g)", 173, 161, 4.3, 37.0, 0.2, 3.8),
    ("sweet potato", "1 medium (130 g)", 130, 112, 2.0, 26.0, 0.1, 3.9),
    ("fries|chips|french fries", "1 medium serving (117 g)", 117, 365, 4.0, 48.0, 17.0, 4.4),
    ("pancake|pancakes", "1 pancake (40 g)", 40, 90, 2.5, 11.0, 4.0, 0.4),
    # legumes & nuts
    ("lentils|lentil soup|dal|daal", "1 cup cooked (198 g)", 198, 230, 18.0, 40.0, 0.8, 15.6),
    ("chickpeas|garbanzo", "1 cup cooked (164 g)", 164, 269, 14.5, 45.0, 4.2, 12.5),
    ("hummus|houmous", "2 tbsp (30 g)", 30, 70, 2.0, 4.0, 5.0, 1.8),
    ("beans|black beans|kidney beans|baked beans", "1 cup (172 g)", 172, 227, 15.0, 41.0, 0.9, 15.0),
    ("peanut butter", "1 tbsp (16 g)", 16, 94, 3.6, 3.5, 8.0, 0.8),
    ("almonds", "1 handful (28 g)", 28, 164, 6.0, 6.1, 14.2, 3.5),
    ("walnuts", "1 handful (28 g)", 28, 185, 4.3, 3.9, 18.5, 1.9),
    ("pistachios", "1 handful (28 g)", 28, 159, 5.7, 7.7, 12.8, 3.0),
    ("nuts|mixed nuts|cashews", "1 handful (28 g)", 28, 170, 5.0, 7.0, 15.0, 2.0),
    ("dates|date", "1 date (24 g)", 24, 66, 0.4, 18.0, 0, 1.6),
    # fruit
    ("banana|bananas", "1 medium", 118, 105, 1.3, 27.0, 0.4, 3.1),
    ("apple|apples", "1 medium", 182, 95, 0.5, 25.0, 0.3, 4.4),
    ("orange|oranges", "1 medium", 131, 62, 1.2, 15.4, 0.2, 3.1),
    ("berries|blueberries|strawberries|raspberries", "1 cup", 150, 70, 1.0, 17.0, 0.4, 3.5),
    ("grapes", "1 cup", 151, 104, 1.1, 27.0, 0.2, 1.4),
    ("watermelon|melon", "1 cup diced", 152, 46, 0.9, 11.5, 0.2, 0.6),
    ("pear", "1 medium", 178, 101, 0.6, 27.0, 0.2, 5.5),
    ("mango", "1 cup", 165, 99, 1.4, 25.0, 0.6, 2.6),
    ("avocado", "1/2 avocado", 100, 160, 2.0, 8.5, 14.7, 6.7),
    # veg
    ("salad|lettuce|mixed greens|spinach", "1 bowl (85 g)", 85, 15, 1.2, 2.8, 0.2, 1.5),
    ("broccoli", "1 cup (91 g)", 91, 31, 2.5, 6.0, 0.3, 2.4),
    ("carrot|carrots", "1 medium", 61, 25, 0.6, 6.0, 0.1, 1.7),
    ("tomato|tomatoes", "1 medium", 123, 22, 1.1, 4.8, 0.2, 1.5),
    ("cucumber", "1/2 cucumber", 150, 23, 1.0, 5.4, 0.2, 0.8),
    ("vegetables|veggies|mixed vegetables|stir fry vegetables", "1 cup", 150, 60, 3.0, 12.0, 0.3, 4.0),
    ("mushrooms", "1 cup (70 g)", 70, 15, 2.2, 2.3, 0.2, 0.7),
    ("onion", "1 medium", 110, 44, 1.2, 10.0, 0.1, 1.9),
    ("corn|sweetcorn", "1 cup (145 g)", 145, 125, 4.7, 27.0, 1.9, 3.0),
    # fats, sauces, sweets
    ("olive oil|oil", "1 tbsp", 13.5, 119, 0, 0, 13.5, 0),
    ("mayonnaise|mayo", "1 tbsp", 14, 94, 0.1, 0.1, 10.3, 0),
    ("ketchup", "1 tbsp", 17, 17, 0.2, 4.7, 0, 0),
    ("salad dressing|dressing", "2 tbsp", 30, 120, 0.3, 4.0, 11.0, 0),
    ("honey", "1 tbsp", 21, 64, 0.1, 17.3, 0, 0),
    ("jam", "1 tbsp", 20, 56, 0.1, 13.8, 0, 0.2),
    ("sugar", "1 tsp", 4, 16, 0, 4.0, 0, 0),
    ("dark chocolate|chocolate", "1 bar (45 g)", 45, 240, 3.0, 26.0, 14.0, 3.0),
    ("ice cream", "1/2 cup (66 g)", 66, 137, 2.3, 16.0, 7.3, 0.5),
    ("cookie|cookies|biscuit|biscuits", "1 cookie (15 g)", 15, 75, 1.0, 10.0, 3.5, 0.3),
    ("cake", "1 slice (80 g)", 80, 300, 3.5, 40.0, 14.0, 1.0),
    ("protein bar", "1 bar", 60, 210, 20.0, 22.0, 7.0, 3.0),
    ("crisps|potato chips", "1 bag (28 g)", 28, 152, 2.0, 15.0, 10.0, 1.2),
    ("popcorn", "3 cups popped", 24, 93, 3.0, 19.0, 1.1, 3.5),
    # meals
    ("pizza", "1 slice", 107, 285, 12.0, 36.0, 10.0, 2.5),
    ("burger|hamburger|cheeseburger", "1 burger", 220, 540, 30.0, 40.0, 28.0, 2.0),
    ("sandwich", "1 sandwich", 200, 400, 20.0, 40.0, 16.0, 3.0),
    ("burrito", "1 burrito", 300, 650, 28.0, 80.0, 22.0, 8.0),
    ("sushi", "1 piece", 30, 45, 2.0, 7.5, 0.7, 0.2),
    ("soup", "1 bowl (250 ml)", 250, 150, 7.0, 18.0, 5.0, 3.0),
    ("curry", "1 cup (240 g)", 240, 350, 20.0, 15.0, 22.0, 4.0),
    ("stew", "1 bowl (300 g)", 300, 330, 25.0, 20.0, 15.0, 4.0),
    # drinks
    ("coffee|black coffee|espresso|americano", "1 cup", 240, 2, 0.3, 0, 0, 0),
    ("latte|cappuccino|flat white", "1 medium (350 ml)", 350, 190, 10.0, 15.0, 10.0, 0),
    ("tea", "1 cup", 240, 2, 0, 0.5, 0, 0),
    ("orange juice|juice", "1 cup (240 ml)", 240, 112, 1.7, 26.0, 0.5, 0.5),
    ("coke|cola|soda|soft drink", "1 can (330 ml)", 330, 139, 0, 35.0, 0, 0),
    ("diet coke|coke zero|diet soda", "1 can (330 ml)", 330, 1, 0, 0, 0, 0),
    ("beer", "1 pint (568 ml)", 568, 240, 2.5, 20.0, 0, 0),
    ("wine|red wine|white wine", "1 glass (150 ml)", 150, 125, 0.1, 4.0, 0, 0),
    ("smoothie", "1 cup (240 ml)", 240, 150, 2.0, 35.0, 0.5, 3.0),
    ("water|sparkling water", "1 glass", 250, 0, 0, 0, 0, 0),
]

_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half": 0.5, "a half": 0.5, "couple": 2,
         "a couple of": 2, "few": 3, "a few": 3, "dozen": 12, "quarter": 0.25}
# unit word -> grams (None means "count of the food's own unit")
_UNITS = {"g": 1, "gr": 1, "gram": 1, "grams": 1, "kg": 1000, "ml": 1, "l": 1000, "oz": 28.35,
          "lb": 453.6, "cup": 240, "cups": 240, "tbsp": 15, "tablespoon": 15, "tablespoons": 15,
          "tsp": 5, "teaspoon": 5, "teaspoons": 5,
          "slice": None, "slices": None, "piece": None, "pieces": None, "serving": None,
          "servings": None, "bowl": None, "bowls": None, "glass": None, "glasses": None,
          "can": None, "cans": None, "scoop": None, "scoops": None, "handful": None, "bar": None}

_INDEX = sorted(((alias.strip(), f) for f in _FOODS for alias in f[0].split("|")),
                key=lambda x: -len(x[0]))
_SPLIT = re.compile(r",|;|\n|\+|\band\b|\bwith\b|\bplus\b|&", re.I)
_QTY = re.compile(r"^\s*(\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?|\d+\s+\d/\d)\s*([a-z]+)?\b", re.I)

ALLOWED_IMAGE_TYPES: set[str] = set()
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 0


class FoodAIError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def ai_configured() -> bool:
    return True  # built in, always available


def _number(text: str) -> float:
    text = text.replace(",", ".").strip()
    if " " in text and "/" in text:  # "1 1/2"
        whole, frac = text.split(None, 1)
        return float(whole) + _number(frac)
    if "/" in text:
        a, b = text.split("/")
        return float(a) / float(b) if float(b) else 1
    return float(text)


def _match(chunk: str):
    for alias, food in _INDEX:
        if re.search(rf"\b{re.escape(alias)}\b", chunk):
            return food
    return None


def parse_item(chunk: str) -> dict[str, Any] | None:
    text = chunk.lower().strip(" .!")
    if not text:
        return None
    food = _match(text)
    if not food:
        return None
    _, unit_label, unit_g, kcal, p, c, f, fib = food

    factor, grams_given = 1.0, False
    m = _QTY.match(text)
    if m:
        qty = _number(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in _UNITS and _UNITS[unit] is not None:
            factor, grams_given = qty * _UNITS[unit] / unit_g, True
        else:
            factor = qty
    else:
        m = re.match(r"^\s*(a couple of|a few|a half|half|quarter|an?|one|two|three|four|five|six|"
                     r"seven|eight|nine|ten|couple|few|dozen)\b", text)
        if m:
            factor = _NUMS[m.group(1)]
        if re.search(r"\b(large|big|double)\b", text):
            factor *= 1.5
        elif re.search(r"\b(small|mini)\b", text):
            factor *= 0.7

    name = chunk.strip(" .!")
    portion = f"{round(factor * unit_g)} g" if grams_given else (
        unit_label if factor == 1 else f"{round(factor, 2):g} × {unit_label}")
    return {
        "name": name[:120], "portion": portion,
        "calories": round(kcal * factor, 1), "protein_g": round(p * factor, 1),
        "carbs_g": round(c * factor, 1), "fat_g": round(f * factor, 1), "fiber_g": round(fib * factor, 1),
        "confidence": "high" if grams_given else "medium",
    }


class FoodAnalyzer:
    def analyze(self, description: str = "", images=None, meal_hint: str | None = None) -> dict[str, Any]:
        description = (description or "").strip()
        if not description:
            raise FoodAIError("Type what you ate, e.g. \"2 eggs, toast and a banana\".", 400)
        items, unknown = [], []
        for chunk in _SPLIT.split(description):
            if not chunk.strip(" .!"):
                continue
            item = parse_item(chunk)
            (items.append(item) if item else unknown.append(chunk.strip()))
        notes = "Check the portions and adjust any numbers before adding."
        if unknown:
            notes = (f"Couldn't find: {', '.join(unknown)}. Add those with \"Add food manually\" below, "
                     "or try a simpler name. ") + notes
        keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
        totals = {k: round(sum(i[k] for i in items), 1) for k in keys}
        return {"items": items, "totals": totals, "meal_guess": meal_hint or "snack", "notes": notes}


food_analyzer = FoodAnalyzer()
