"""The app's own food database.

Built-in foods live in ``app/data/foods.csv`` (one row per food: names separated by
"|", the serving it describes, its weight in grams, then calories, protein, carbs,
fat and fibre for that serving, and tags used by diet filters). Foods the user adds
are stored in the ``custom_foods`` table and are matched first.
"""

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CustomFood

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "foods.csv"


@dataclass
class Food:
    names: list[str]
    unit: str
    grams: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    tags: list[str] = field(default_factory=list)
    custom: bool = False
    recipe: tuple = ()  # (ingredient, grams in ONE unit, kcal, protein, carbs, fat) when built from ingredients

    @property
    def name(self) -> str:
        return self.names[0]

    def as_dict(self) -> dict:
        return {"name": f"{self.name.capitalize()}, {self.unit}", "calories": round(self.calories),
                "protein_g": round(self.protein_g, 1), "carbs_g": round(self.carbs_g, 1),
                "fat_g": round(self.fat_g, 1), "fiber_g": round(self.fiber_g, 1),
                "tags": self.tags, "custom": self.custom,
                "food": self.name.capitalize(), "unit": self.unit, "grams": self.grams}


@lru_cache
def builtin_foods() -> tuple[Food, ...]:
    foods = []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        rows = (line for line in fh if line.strip() and not line.startswith("#"))
        for r in csv.DictReader(rows):
            foods.append(Food(
                names=[n.strip().lower() for n in r["names"].split("|") if n.strip()],
                unit=r["unit"].strip(), grams=float(r["grams"]),
                calories=float(r["kcal"]), protein_g=float(r["protein"]), carbs_g=float(r["carbs"]),
                fat_g=float(r["fat"]), fiber_g=float(r["fiber"]), tags=(r["tags"] or "").split()))
    _apply_recipes(foods)
    return tuple(foods)


INGREDIENTS_PATH = CSV_PATH.parent / "ingredients.csv"
RECIPES_PATH = CSV_PATH.parent / "recipes.json"


def ingredients() -> dict[str, dict]:
    with open(INGREDIENTS_PATH, newline="", encoding="utf-8") as fh:
        rows = (line for line in fh if line.strip() and not line.startswith("#"))
        return {r["name"]: {k: float(r[k]) for k in ("kcal", "protein", "carbs", "fat", "fiber")} for r in csv.DictReader(rows)}


def recipes() -> dict:
    import json
    return {k: v for k, v in json.loads(RECIPES_PATH.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def _apply_recipes(foods: list) -> None:
    """Dishes with a recipe get their nutrition calculated from the ingredients, scaled to one unit."""
    ing, rec = ingredients(), recipes()
    for f in foods:
        r = rec.get(f.name)
        if not r:
            continue
        # one unit of the dish is this share of the recipe
        share = (f.grams / r["makes_g"]) if r.get("makes_g") and f.grams else 1.0
        parts, tot = [], dict.fromkeys(("kcal", "protein", "carbs", "fat", "fiber"), 0.0)
        for name, grams in r["ingredients"]:
            n, g = ing[name], grams * share
            vals = {k: n[k] * g / 100 for k in tot}
            for k in tot:
                tot[k] += vals[k]
            parts.append((name, round(g, 1), round(vals["kcal"], 1), round(vals["protein"], 1),
                          round(vals["carbs"], 1), round(vals["fat"], 1)))
        f.calories, f.protein_g, f.carbs_g = round(tot["kcal"]), round(tot["protein"], 1), round(tot["carbs"], 1)
        f.fat_g, f.fiber_g, f.recipe = round(tot["fat"], 1), round(tot["fiber"], 1), tuple(parts)


def _shared():
    """Foods people add are shared by everyone: they're kept in the main (profile 1) tables."""
    from app.db import SessionLocal
    return SessionLocal()


def custom_foods(db: Session | None) -> list[Food]:
    if db is None:
        return []
    with _shared() as sdb:
        rows = list(sdb.scalars(select(CustomFood)))
        if db.bind is not sdb.bind:  # foods a person saved privately before sharing existed
            names = {r.name.lower() for r in rows}
            rows += [c for c in db.scalars(select(CustomFood)) if c.name.lower() not in names]
        return [Food(names=[c.name.lower()], unit=c.unit or "1 serving", grams=0, calories=c.calories,
                     protein_g=c.protein_g, carbs_g=c.carbs_g, fat_g=c.fat_g, fiber_g=c.fiber_g, custom=True)
                for c in rows]


def all_foods(db: Session | None = None) -> list[Food]:
    return custom_foods(db) + list(builtin_foods())


def _plural_variants(word: str) -> set[str]:
    out = {word}
    if word.endswith("ies"):
        out.add(word[:-3] + "y")
    elif word.endswith("es"):
        out |= {word[:-2], word[:-1]}
    elif word.endswith("s"):
        out.add(word[:-1])
    else:
        out.add(word + "s")
    return out


def match_len(text: str, db: Session | None = None) -> int:
    """Length of the longest food name found in the phrase (0 = none)."""
    text = " " + re.sub(r"[^\w%&' ]+|_", " ", text.lower().replace("\u200c", " ")) + " "
    best = 0
    for food in all_foods(db):
        for n in food.names:
            if len(n) > best:
                last = n.split()[-1]
                if any(f" {n[: len(n) - len(last)] + v} " in text for v in _plural_variants(last)):
                    best = len(n)
    return best


def _hits(text: str, db: Session | None):
    """Every food name found in the phrase, with where it starts and ends."""
    out = []
    for food in all_foods(db):
        for n in food.names:
            last = n.split()[-1]
            for v in _plural_variants(last):
                cand = f" {n[: len(n) - len(last)] + v} "
                i = text.find(cand)
                if i >= 0:
                    out.append((food, len(n), i, i + len(cand) - 1))
                    break
    return out


def match(text: str, db: Session | None = None) -> Food | None:
    """Best food for a phrase: the longest name found in it (custom foods win ties).
    A food word right in front of another one only describes it: "pistachio cake" is cake, not pistachios."""
    text = " " + re.sub(r"[^\w%&' ]+|_", " ", text.lower().replace("\u200c", " ")) + " "  # keeps Farsi letters
    hits = _hits(text, db)
    if not hits:
        return None
    best = max(hits, key=lambda h: (h[1], h[0].custom))  # max keeps the first of equals: custom foods come first
    while True:
        head = [h for h in hits if h[2] == best[3]]  # a food that starts right where this one ends
        if not head:
            return best[0]
        best = max(head, key=lambda h: (h[1], h[0].custom))


def search(query: str, db: Session | None = None, banned: set[str] | None = None, limit: int = 20) -> list[dict]:
    q = query.lower().strip()
    if not q:
        return []
    banned = banned or set()
    scored = []
    for food in all_foods(db):
        if set(food.tags) & banned:
            continue
        hits = [n for n in food.names if q in n]
        if not hits:
            continue
        best = min(hits, key=len)
        score = (0 if food.custom else 1, 0 if best.startswith(q) else 1, len(best))
        scored.append((score, food))
    scored.sort(key=lambda x: x[0])
    return [f.as_dict() for _, f in scored[:limit]]


def save_custom(db: Session, name: str, unit: str, values: dict) -> CustomFood:
    name = name.strip()[:120]
    with _shared() as sdb:
        row = sdb.scalar(select(CustomFood).where(CustomFood.name == name)) or CustomFood(name=name)
        row.unit = (unit or "1 serving").strip()[:60]
        for k in ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g"):
            setattr(row, k, max(0.0, float(values.get(k) or 0)))
        sdb.add(row)
        sdb.commit()
        sdb.refresh(row)
        return row
