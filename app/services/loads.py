"""Suggested starting weights for each exercise, worked out for the person.

Basis: published strength standards for a trained ("intermediate") adult man, as a share of body
weight for a set of about 10 reps (roughly 75% of a one-rep max), e.g. squat ~0.85x BW on the bar,
bench ~0.75x, deadlift ~1.1x. These are then scaled for the person:
  * experience: beginner x0.6, some experience x1.0, very fit x1.25
  * sex: women about 55% of men's upper-body and 70% of lower-body loads (same standards, women's tables)
  * age: 40-49 x0.95, 50-59 x0.85, 60+ x0.75 (strength declines with age)
  * goal: strength sets (3-5 reps) x1.15, fat-loss / endurance sets (12-15+ reps) x0.9
  * body: upper-body loads use a lean reference weight (BMI 27 cap), so extra fat doesn't inflate them
Rounded to what gyms actually have (dumbbells in 2 kg steps, bars in 2.5 kg, machines in 5 kg).
Always a starting point: the first week is for finding the weight that leaves 2-3 reps in the tank.
"""

from datetime import date

from app.services import nutrition

# name: (share of body weight, how it's loaded, upper/lower body)
# kind: "db" = each dumbbell, "db1" = one dumbbell, "bar" = barbell total, "stack" = machine / cable stack
RATIOS = {
    # squats & legs
    "Barbell back squat": (0.85, "bar", "lower"), "Front squat": (0.7, "bar", "lower"),
    "Box squat to a bench (pain-free depth)": (0.6, "bar", "lower"),
    "Leg press": (1.6, "stack", "lower"), "Goblet squat": (0.3, "db1", "lower"),
    "Goblet squat (one dumbbell)": (0.3, "db1", "lower"), "Dumbbell split squat": (0.15, "db", "lower"),
    "Split squat (dumbbells, hold the rack for balance if needed)": (0.15, "db", "lower"),
    "Bulgarian split squat": (0.13, "db", "lower"), "Sumo dumbbell squat": (0.35, "db1", "lower"),
    "Walking lunge": (0.15, "db", "lower"), "Dumbbell reverse lunge": (0.15, "db", "lower"),
    "Step-up": (0.12, "db", "lower"), "Leg extension": (0.5, "stack", "lower"),
    "Leg extension (cable station)": (0.35, "stack", "lower"), "Leg curl": (0.4, "stack", "lower"),
    "Leg curl (cable station)": (0.3, "stack", "lower"), "Standing calf raise": (1.0, "stack", "lower"),
    "Single-leg calf raise": (0.12, "db1", "lower"),
    # hinges & glutes
    "Conventional deadlift": (1.1, "bar", "lower"), "Romanian deadlift": (0.75, "bar", "lower"),
    "Dumbbell Romanian deadlift": (0.3, "db", "lower"), "Single-leg RDL": (0.2, "db1", "lower"),
    "Hip thrust": (1.0, "bar", "lower"), "Dumbbell hip thrust": (0.35, "db1", "lower"),
    "Hip thrust (shoulders on bench, dumbbell on hips)": (0.35, "db1", "lower"),
    "Cable glute kickback": (0.12, "stack", "lower"),
    # pushes
    "Barbell bench press": (0.75, "bar", "upper"), "Dumbbell bench press": (0.28, "db", "upper"),
    "Dumbbell bench press (flat bench)": (0.28, "db", "upper"), "Incline dumbbell press": (0.24, "db", "upper"),
    "Incline dumbbell press (bench on incline)": (0.24, "db", "upper"), "Dumbbell floor press": (0.26, "db", "upper"),
    "Machine chest press": (0.6, "stack", "upper"), "Chest press (multi-gym, seated press arms)": (0.6, "stack", "upper"),
    "Concentration curl": (0.1, "db1", "upper"), "Concentration curl (dumbbell, seated on the bench)": (0.1, "db1", "upper"), "Overhead barbell press": (0.45, "bar", "upper"),
    "Seated dumbbell shoulder press": (0.18, "db", "upper"), "Dumbbell shoulder press": (0.17, "db", "upper"),
    "Seated dumbbell shoulder press (bench upright)": (0.18, "db", "upper"), "Arnold press": (0.15, "db", "upper"),
    "Dumbbell lateral raise": (0.07, "db", "upper"), "Dumbbell fly": (0.12, "db", "upper"),
    "Cable fly": (0.12, "stack", "upper"),
    # pulls
    "Barbell row": (0.6, "bar", "upper"), "Chest-supported row": (0.25, "db", "upper"),
    "One-arm dumbbell row": (0.32, "db1", "upper"), "One-arm dumbbell row (hand on bench)": (0.32, "db1", "upper"),
    "Seated cable row": (0.65, "stack", "upper"), "Seated cable row (cable station)": (0.65, "stack", "upper"),
    "Lat pulldown": (0.65, "stack", "upper"), "Lat pulldown (cable station)": (0.65, "stack", "upper"),
    "Face pull (cable with rope)": (0.2, "stack", "upper"), "Dumbbell rear-delt fly": (0.06, "db", "upper"),
    # arms & core
    "EZ-bar curl": (0.3, "bar", "upper"), "Cable curl": (0.25, "stack", "upper"), "Cable biceps curl": (0.25, "stack", "upper"),
    "Dumbbell curl": (0.12, "db", "upper"), "Hammer curl": (0.13, "db", "upper"), "Dumbbell hammer curl": (0.13, "db", "upper"),
    "Cable pushdown": (0.3, "stack", "upper"), "Rope triceps pushdown (cable)": (0.25, "stack", "upper"),
    "Skull crusher": (0.3, "bar", "upper"), "Overhead dumbbell extension": (0.2, "db1", "upper"),
    "Cable crunch": (0.4, "stack", "upper"), "Cable woodchop": (0.15, "stack", "upper"),
    "Pallof press": (0.12, "stack", "upper"),
    "Farmer's carry": (0.35, "db", "lower"), "Suitcase carry": (0.35, "db1", "lower"),
}
EXPERIENCE = {"beginner": 0.6, "intermediate": 1.0, "advanced": 1.25}
GOAL = {"strength": 1.15, "hypertrophy": 1.0, "general": 1.0, "fat_loss": 0.9, "endurance": 0.85}
STEP = {"db": 2.0, "db1": 2.0, "bar": 2.5, "stack": 5.0}
MIN = {"db": 2.0, "db1": 4.0, "bar": 20.0, "stack": 5.0}
LABEL = {"db": "each dumbbell", "db1": "one dumbbell", "bar": "on the bar, bar included", "stack": "on the machine"}


def _age_factor(age: int) -> float:
    return 1.0 if age < 40 else 0.95 if age < 50 else 0.85 if age < 60 else 0.75


def suggest(profile, exercise: str, plan_goal: str = "general", today: date | None = None) -> dict | None:
    """{"kg": 14.0, "lb": 30, "per": "each dumbbell"} or None for bodyweight moves."""
    r = RATIOS.get(exercise)
    if not r or not profile or not profile.weight_kg:
        return None
    share, kind, region = r
    lean = nutrition.protein_reference_weight(profile)
    body = lean if region == "upper" else min(profile.weight_kg, lean * 1.15)
    sex = 1.0 if profile.sex != "female" else (0.55 if region == "upper" else 0.7)
    age = nutrition.age_on(profile.birth_year, today)
    kg = share * body * sex * _age_factor(age) * EXPERIENCE.get(profile.experience, 0.8) * GOAL.get(plan_goal, 1.0)
    step = STEP[kind]
    floor = 10.0 if exercise in ("EZ-bar curl", "Skull crusher") else MIN[kind]  # EZ bar weighs ~10 kg
    kg = max(floor, round(kg / step) * step)
    return {"kg": kg, "lb": round(kg * 2.2046 / (5 if kind == "stack" else 2.5)) * (5 if kind == "stack" else 2.5),
            "per": LABEL[kind]}


def add_loads(plan_days: list, profile, plan_goal: str = "general") -> list:
    """A copy of the plan's days with a suggested starting weight on each weighted exercise."""
    out = []
    for d in plan_days:
        d = dict(d)
        exs = []
        for e in d.get("exercises", []):
            e = dict(e)
            s = suggest(profile, e.get("exercise", ""), plan_goal)
            if s:
                e["load"] = s
            exs.append(e)
        d["exercises"] = exs
        out.append(d)
    return out
