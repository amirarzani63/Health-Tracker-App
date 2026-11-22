"""Calorie counter: estimate foods and macros from a typed description.

Runs fully inside the app using its own food database (``food_db``) -- no outside service,
no API key, no cost. Example input: "2 eggs, 150g chicken breast and a banana".
Estimates are returned as a draft for the user to review; nothing is saved here.
"""

import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import food_db

_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half": 0.5, "a half": 0.5, "couple": 2,
         "a couple of": 2, "few": 3, "a few": 3, "dozen": 12, "quarter": 0.25}
# unit word -> grams (None means "count of the food's own unit")
_UNITS = {"g": 1, "gr": 1, "gram": 1, "grams": 1, "kg": 1000, "ml": 1, "l": 1000, "oz": 28.35,
          "lb": 453.6, "lbs": 453.6, "pound": 453.6, "pounds": 453.6,
          "ounce": 28.35, "ounces": 28.35, "fl": 29.57, "floz": 29.57, "pint": 568, "pints": 568, "cup": 240, "cups": 240, "tbsp": 15, "tablespoon": 15, "tablespoons": 15,
          "tsp": 5, "teaspoon": 5, "teaspoons": 5,
          "slice": None, "slices": None, "piece": None, "pieces": None, "serving": None,
          "servings": None, "bowl": None, "bowls": None, "glass": None, "glasses": None,
          "can": None, "cans": None, "scoop": None, "scoops": None, "handful": None, "bar": None}

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


_UNIT_WORDS = {"cup": ("cup", "cups"), "cups": ("cup", "cups"), "tbsp": ("tbsp", "tablespoon"),
               "tablespoon": ("tbsp", "tablespoon"), "tablespoons": ("tbsp", "tablespoon"),
               "tsp": ("tsp", "teaspoon"), "teaspoon": ("tsp", "teaspoon"), "teaspoons": ("tsp", "teaspoon")}


def _per_unit_from_label(label: str, grams: float, unit: str) -> float | None:
    """Grams in one cup/tbsp/tsp of this food, read from a label like "1/2 cup dry (40 g)"."""
    words = _UNIT_WORDS.get(unit)
    if not words or not grams:
        return None
    m = re.match(r"^\s*(\d+(?:/\d+)?|\d*\.\d+)\s+(\w+)", label.lower())
    if not m or m.group(2) not in words:
        return None
    return grams / _number(m.group(1))


def parse_item(chunk: str, db: Session | None = None) -> dict[str, Any] | None:
    text = chunk.lower().strip(" .!")
    if not text:
        return None
    food = food_db.match(text, db)
    if not food:
        return None
    unit_label, unit_g = food.unit, food.grams
    kcal, p, c, f, fib = food.calories, food.protein_g, food.carbs_g, food.fat_g, food.fiber_g

    factor, grams_given = 1.0, False
    m = _QTY.match(text)
    if m:
        qty = _number(m.group(1))
        unit = (m.group(2) or "").lower()
        per = _per_unit_from_label(unit_label, unit_g, unit)
        if per:  # "1 cup rice" with a food measured in cups: use the food's own cup weight
            factor = qty * per / unit_g
        elif unit in _UNITS and _UNITS[unit] is not None and unit_g:
            factor, grams_given = qty * _UNITS[unit] / unit_g, True
        else:
            factor = qty
    else:
        m = re.match(r"^\s*(a couple of|a few|a half|half|quarter|an?|one|two|three|four|five|six|"
                     r"seven|eight|nine|ten|couple|few|dozen)\b", text)
        if m:
            factor = _NUMS[m.group(1)]
        later = re.search(rf"(\d+(?:[.,]\d+)?)\s*({'|'.join(_UNITS)})\b", text)
        if later:  # amount written after the food: "pizza 2 slices", "rice 200g"
            qty, unit = _number(later.group(1)), later.group(2)
            if _UNITS[unit] is not None and unit_g:
                factor, grams_given = qty * _UNITS[unit] / unit_g, True
            else:
                factor = qty
        if re.search(r"\b(large|big|double)\b", text):
            factor *= 1.5
        elif re.search(r"\b(small|mini)\b", text):
            factor *= 0.7

    name = chunk.strip(" .!")
    volume = bool(re.search(r"\b(ml|l|fl|floz|pints?|cups?)\b", text)) or re.search(r"\bml\b", unit_label)
    portion = f"{round(factor * unit_g)} {'ml' if volume else 'g'}" if grams_given else (
        unit_label if factor == 1 else f"{round(factor, 2):g} × {unit_label}")
    return {
        "name": name[:120], "portion": portion,
        "calories": round(kcal * factor, 1), "protein_g": round(p * factor, 1),
        "carbs_g": round(c * factor, 1), "fat_g": round(f * factor, 1), "fiber_g": round(fib * factor, 1),
        "confidence": "high" if grams_given else "medium",
    }


# Spoken meals ("for lunch I had 4 meatballs and then a coffee"): find the meal, drop the filler words.
_MEAL_WORDS = re.compile(r"\b(?:for|at|this|my)?\s*(breakfast|brunch|lunch|dinner|supper|snack)\b", re.I)
_FILLER = re.compile(r"^\s*(?:(?:and|then|also|plus|so|um+|uh+|okay|ok|well|today|this morning|tonight|"
                     r"i(?:'ve| have)? (?:had|ate|eaten|drank|drunk)|last night|yesterday(?: evening| morning)?|i also had|i just had|we had|had|ate|drank|"
                     r"some|about|around|roughly|like|for (?:breakfast|brunch|lunch|dinner|supper|snack)|"
                     r"(?:breakfast|brunch|lunch|dinner|supper|snack) was)\b[\s,:]*)+", re.I)
_MEAL_MAP = {"brunch": "breakfast", "supper": "dinner"}
_YESTERDAY = re.compile(r"\b(yesterday|last night)\b", re.I)


def spoken_day_offset(text: str) -> int:
    """-1 when the person says it was yesterday / last night, else 0 (today or the day being viewed)."""
    return -1 if _YESTERDAY.search(text or "") else 0


def spoken_meal(text: str) -> str | None:
    if re.search(r"\bthis morning\b", text or "", re.I) and not _MEAL_WORDS.search(text or ""):
        return "breakfast"
    if re.search(r"\b(tonight|last night|yesterday evening)\b", text or "", re.I) and not _MEAL_WORDS.search(text or ""):
        return "dinner"
    m = _MEAL_WORDS.search(text or "")
    return _MEAL_MAP.get(m.group(1).lower(), m.group(1).lower()) if m else None


def clean_chunk(chunk: str) -> str:
    return _FILLER.sub("", chunk).strip(" .!,")


class FoodAnalyzer:
    def analyze(self, description: str = "", images=None, meal_hint: str | None = None,
                db: Session | None = None) -> dict[str, Any]:
        description = (description or "").strip()
        if not description:
            raise FoodAIError("Type what you ate, e.g. \"2 eggs, toast and a banana\".", 400)
        items, unknown = [], []
        meal_hint = spoken_meal(description) or meal_hint
        for chunk in _SPLIT.split(description):
            chunk = clean_chunk(chunk)
            if not chunk:
                continue
            item = parse_item(chunk, db)
            (items.append(item) if item else unknown.append(chunk.strip()))
        notes = "Check the portions and adjust any numbers before adding."
        if unknown:
            notes = (f"Couldn't find: {', '.join(unknown)}. Add them once with \"Add food manually\" below and "
                     "the counter will know them next time. ") + notes
        keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
        totals = {k: round(sum(i[k] for i in items), 1) for k in keys}
        return {"items": items, "totals": totals, "meal_guess": meal_hint or "snack", "notes": notes,
                "day_offset": spoken_day_offset(description)}


food_analyzer = FoodAnalyzer()
