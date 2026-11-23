"""Weekly review and weekly meal plan, refreshed automatically every Monday.

Everything here is computed inside the app from what the user logged; no outside service.
"""

import json
import math
from datetime import date, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StoredSecret, WaterLog, WeightEntry
from app.services import insights, nutrition

KEY = "weekly_reviews"
MIN_KCAL, MAX_STEP = 1800, 100


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _load(db: Session) -> list:
    row = db.get(StoredSecret, KEY)
    try:
        return json.loads(row.value) if row and row.value else []
    except ValueError:
        return []


def _save(db: Session, reviews: list):
    row = db.get(StoredSecret, KEY) or StoredSecret(key=KEY)
    row.value = json.dumps(reviews[-30:])
    db.add(row)


def _avg_weight(db: Session, start: date, end: date) -> float | None:
    ws = [w.weight_kg for w in db.scalars(select(WeightEntry).where(WeightEntry.day >= start, WeightEntry.day <= end))]
    return round(mean(ws), 1) if ws else None


def _fmt_avg(vals):
    vals = [v for v in vals if v is not None]
    return round(mean(vals), 1) if vals else None


def build_review(db: Session, ws: date) -> dict:
    """Summary of the week starting on Monday ``ws``, plus a calorie change for the next week."""
    we = ws + timedelta(days=6)
    days = insights.daily_series(db, ws, we)
    goals = insights.get_goals(db)
    logged = [d for d in days if d["logged"]]
    plan, _ = insights.todays_session(db, ws)
    started = plan and plan.created_at.date() <= ws + timedelta(days=6)
    planned = sum(1 for d in (plan.days if started else []) if d.get("type") in ("strength", "cardio"))
    marks = insights.checkins(db)
    done = sum(1 for d in days if d["workouts"] > 0)
    missed = sum(1 for i in range(7) if marks.get((ws + timedelta(days=i)).isoformat()) is False)
    water = [r.glasses for r in db.scalars(select(WaterLog).where(WaterLog.day >= ws, WaterLog.day <= we))]

    w_now, w_before = _avg_weight(db, ws, we), _avg_weight(db, ws - timedelta(days=7), ws - timedelta(days=1))
    change = round(w_now - w_before, 1) if w_now is not None and w_before is not None else None
    target = goals.calorie_target or round(days[-1]["target_calories"])
    avg_kcal = _fmt_avg(d["calories"] for d in logged)
    followed = avg_kcal is not None and abs(avg_kcal - target) <= target * 0.12 and len(logged) >= 4

    new_target, notes = target, []
    if change is None:
        notes.append("Weigh yourself at least 2 mornings a week so the app can check your progress.")
    elif change > -0.4 and followed:
        new_target = max(MIN_KCAL, target - MAX_STEP)
        notes.append(f"Weight went {'up' if change > 0 else 'down'} only {abs(change)} kg. Daily calories lowered by "
                     f"{target - new_target} to {new_target}." if new_target < target else
                     "Weight is moving slowly, but calories are already at the safe minimum. Add 2,000 steps a day instead.")
    elif change > -0.4:
        notes.append(f"Weight changed {change:+} kg. Log your food on at least 4 days and stay near {target} calories "
                     "before the app lowers your calories.")
    elif change < -1.3:
        new_target = target + MAX_STEP
        notes.append(f"You lost {abs(change)} kg, faster than planned. Daily calories raised by {MAX_STEP} to "
                     f"{new_target} to protect your muscle.")
    else:
        notes.append(f"You lost {abs(change)} kg. Right on track, so calories stay at {target}.")
    if planned and done < planned:
        notes.append(f"You did {done} of {planned} workouts. Aim for all {planned} this week; the walks count too.")
    elif planned:
        notes.append(f"All {planned} workouts done. Great job! Try slightly heavier weights this week.")
    protein = _fmt_avg(d["protein_g"] for d in logged)
    if protein is not None and protein < (goals.protein_target_g or 0) * 0.85:
        notes.append(f"Protein averaged {round(protein)} g. Aim for {round(goals.protein_target_g)} g: add eggs, chicken, "
                     "Greek yogurt or a protein shake.")

    return {
        "week_start": ws.isoformat(), "week_end": we.isoformat(),
        "weight_avg": w_now, "weight_change": change,
        "days_logged": len(logged), "avg_calories": avg_kcal, "avg_protein": protein, "calorie_target": target,
        "workouts_done": done, "workouts_planned": planned, "workouts_missed": missed,
        "avg_steps": _fmt_avg(d["steps"] for d in days), "avg_sleep_h": _fmt_avg(d["sleep_h"] for d in days),
        "avg_water": round(mean(water), 1) if water else None,
        "new_calorie_target": new_target, "notes": notes,
    }


def run_weekly(db: Session, today: date | None = None) -> dict | None:
    """Review last week once, on the first visit of a new week; applies the calorie change."""
    today = today or date.today()
    last_ws = week_start(today) - timedelta(days=7)
    reviews = _load(db)
    if reviews and reviews[-1]["week_start"] >= last_ws.isoformat():
        return reviews[-1]
    review = build_review(db, last_ws)
    goals = insights.get_goals(db)
    if goals.calorie_target and review["new_calorie_target"] != goals.calorie_target:
        goals.calorie_target = review["new_calorie_target"]
        db.add(goals)
    reviews.append(review)
    _save(db, reviews)
    db.commit()
    return review


def _portion_amount(q: float, unit: str) -> str:
    """How much of an ingredient one person's portion needs, in kitchen terms."""
    if unit in ("g", "ml"):
        return f"{round(q / 5) * 5:g} {unit}"
    n = max(0.25, round(q * 4) / 4)
    whole, frac = int(n), {0.25: "¼", 0.5: "½", 0.75: "¾"}.get(n % 1, "")
    num = (str(whole) if whole else "") + frac
    return f"{num} {unit}".strip()


def meal_plan(db: Session, today: date | None = None) -> list[dict]:
    """Seven days of breakfast, lunch, dinner and a snack near the calorie target; changes every week."""
    today = today or date.today()
    ws = week_start(today)
    profile = insights.get_profile(db)
    target = insights.targets_for(db, today)
    ok = [m for m in nutrition.MEAL_IDEAS if nutrition.allowed(m, profile.diet_type, profile.allergies or [])]
    def high_protein(k):  # rotate through the more protein-dense half of the ideas for each meal
        ms = sorted((m for m in ok if m["meal"] == k), key=lambda m: -m["protein_g"] / max(1, m["calories"]))
        return ms[: max(2, (len(ms) + 1) // 2)]
    by_meal = {k: high_protein(k) for k in ("breakfast", "lunch", "dinner", "snack")}
    seed = ws.toordinal() // 7
    days = []
    for i in range(7):
        picks = {k: v[(seed + i * (2 + j)) % len(v)] for j, (k, v) in enumerate(by_meal.items()) if v}
        total = sum(m["calories"] for m in picks.values()) or 1
        factor = max(0.75, min(1.6, target.calories / total))
        meals = [{"meal": k, "name": m["name"], "portion": round(factor, 2),
                  **{n: round(m[n] * factor) for n in ("calories", "protein_g", "carbs_g", "fat_g")},
                  "ingredients": [{"item": it, "amount": _portion_amount(q * factor, u)} for it, q, u, _ in m.get("ingredients", [])]}
                 for k, m in picks.items()]
        days.append({"day": (ws + timedelta(days=i)).isoformat(), "meals": meals,
                     "calories": sum(m["calories"] for m in meals), "protein_g": sum(m["protein_g"] for m in meals)})
    return days


SECTION_ORDER = ["Fruit & vegetables", "Meat & fish", "Dairy & eggs", "Bread", "Pantry", "Frozen"]
LOAF_SLICES = 20


def _amount(total: float, unit: str) -> tuple[str, str]:
    """A shop-friendly amount and, where useful, what to pick up (packs, loaves, dozens)."""
    import math
    if unit == "g":
        g = math.ceil(total / 50) * 50
        return (f"{g / 1000:g} kg" if g >= 1000 else f"{g} g"), ""
    if unit == "ml":
        ml = math.ceil(total / 100) * 100
        return (f"{ml / 1000:g} L" if ml >= 1000 else f"{ml} ml"), ""
    if unit in ("tbsp", "tsp", "scoop"):
        n = math.ceil(total * 2) / 2
        return f"{n:g} {unit}{'s' if unit == 'scoop' and n != 1 else ''}", ""
    if unit == "slice":
        n = math.ceil(total)
        return f"{n} slices", f"{math.ceil(n / LOAF_SLICES)} loaf" + ("s" if n > LOAF_SLICES else "")
    if unit == "can":
        return f"{math.ceil(total)} can" + ("s" if math.ceil(total) != 1 else ""), ""
    n = math.ceil(total - 1e-9)
    return str(n), ""


def shopping_list(plan: list[dict]) -> list[dict]:
    """Everything to buy for the week's menu, added up from each meal's ingredients and portion size."""
    ideas = {m["name"]: m for m in nutrition.MEAL_IDEAS}
    totals: dict[tuple, float] = {}
    for day in plan:
        for meal in day["meals"]:
            idea = ideas.get(meal["name"])
            for item, qty, unit, section in (idea or {}).get("ingredients", []):
                key = (section, item, unit)
                totals[key] = totals.get(key, 0) + qty * meal["portion"]
    out = []
    for section in SECTION_ORDER:
        items = []
        for (sec, item, unit), total in sorted(totals.items()):
            if sec != section:
                continue
            amount, hint = _amount(total, unit)
            if unit == "slice" and section != "Bread":
                hint = ""
            if unit in ("tbsp", "tsp"):
                tbsp = total / (3 if unit == "tsp" else 1)
                kind = "bottle" if any(w in item.lower() for w in ("oil", "sauce")) else "tub" if item == "Hummus" else "jar"
                hint = f"1 {kind}" if tbsp <= 30 else f"{math.ceil(tbsp / 30)} {kind}s"
            if unit == "scoop":
                hint = "1 tub (lasts weeks)"
            if item == "Eggs":
                hint = f"{math.ceil(int(amount) / 12)} dozen" if int(amount) > 6 else ""
            items.append({"item": item, "amount": amount, "hint": hint})
        if items:
            out.append({"section": section, "items": items})
    return out
