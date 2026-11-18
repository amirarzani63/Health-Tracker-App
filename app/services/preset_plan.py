"""The 13-week fat-loss plan agreed with the user (Nov 2026): 105.5 kg -> 95 kg, home dumbbells + bands.

Installed once at start-up (guarded by a marker), then it is an ordinary plan the user can move or replace.
"""

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Goals, Profile, StoredSecret, WeightEntry, WorkoutPlan

MARKER = "preset:fatloss-95-v1"


def ex(name, sets, reps, rest=75, pattern=""):
    return {"exercise": name, "pattern": pattern, "sets": sets, "reps": reps, "rest_s": rest}


DAYS = [
    {"weekday": "Mon", "type": "strength", "title": "Upper body A", "exercises": [
        ex("Dumbbell bench press", 4, "6-10", 90, "h_push"),
        ex("One-arm dumbbell row", 4, "8-12", 90, "h_pull"),
        ex("Arnold press", 3, "8-12", 75, "v_push"),
        ex("Band lat pulldown", 3, "8-12", 75, "v_pull"),
        ex("Hammer curl", 3, "12", 60, "biceps"),
        ex("Dumbbell overhead triceps extension", 3, "12", 60, "triceps"),
    ]},
    {"weekday": "Tue", "type": "strength", "title": "Lower body A", "exercises": [
        ex("Goblet squat", 4, "8-12", 90, "squat"),
        ex("Dumbbell Romanian deadlift", 4, "8-12", 90, "hinge"),
        ex("Reverse lunge", 3, "10 each leg", 75, "lunge"),
        ex("Glute bridge", 3, "15", 60, "hinge"),
        ex("Plank", 3, "40s", 45, "core"),
    ]},
    {"weekday": "Wed", "type": "cardio", "title": "Zone 2 walk/bike", "zone": "Zone 2", "minutes": 45, "exercises": []},
    {"weekday": "Thu", "type": "strength", "title": "Upper body B", "exercises": [
        ex("Push-ups", 4, "max − 2", 75, "h_push"),
        ex("Band row", 4, "12-15", 75, "h_pull"),
        ex("Dumbbell lateral raise", 3, "12-15", 60, "v_push"),
        ex("Rear delt fly", 3, "15", 60, "h_pull"),
        ex("Dumbbell curl", 3, "12", 60, "biceps"),
        ex("Band triceps pushdown", 3, "12", 60, "triceps"),
    ]},
    {"weekday": "Fri", "type": "strength", "title": "Lower body B + finisher", "exercises": [
        ex("Bulgarian split squat", 3, "8-10 each leg", 90, "lunge"),
        ex("Single-leg Romanian deadlift", 3, "10 each leg", 75, "hinge"),
        ex("Dumbbell step-ups", 3, "10 each leg", 75, "lunge"),
        ex("Hip thrust", 3, "12", 60, "hinge"),
        ex("Dead bug", 3, "10 each side", 45, "core"),
        ex("Intervals: 30s hard / 90s easy", 1, "8 rounds", 0, "cardio"),
    ]},
    {"weekday": "Sat", "type": "cardio", "title": "Long Zone 2", "zone": "Zone 2", "minutes": 55, "exercises": []},
    {"weekday": "Sun", "type": "rest", "title": "Rest day", "exercises": []},
]

PROGRESSION = [
    {"week": w, "note": n} for w, n in [
        (1, "Find your weights: stop every set with 2 reps left. Weigh in 3+ mornings. Target ~104.5 kg."),
        (2, "Same weights, aim for the top of each rep range. ~104 kg."),
        (3, "Top of the range on every set? Go heavier / stronger band. ~103 kg."),
        (4, "Keep adding reps or weight. Check-in: ~102 kg."),
        (5, "Deload: 2 sets per exercise, same weights. Keep walking."),
        (6, "Back to full sets; beat week 4's numbers. ~101 kg."),
        (7, "Progress weights. Cardio Sat up to 60 min. ~100 kg."),
        (8, "Check-in: ~98.5 kg. Slower than 0.5 kg/wk for 2 weeks? Cut 150 kcal or add 2k steps."),
        (9, "Push the main lifts; finisher up to 10 rounds. ~98 kg."),
        (10, "Deload: 2 sets per exercise. ~97.5 kg."),
        (11, "Full sets, heaviest weights yet. ~96.5 kg."),
        (12, "Keep protein at 180 g; sleep 7.5 h. ~95.5 kg."),
        (13, "Goal week: 95 kg. Then raise calories by 200-300 to maintain."),
    ]
]


def install(db: Session, today: date | None = None) -> bool:
    if db.get(StoredSecret, MARKER):
        return False
    today = today or date.today()
    db.execute(update(WorkoutPlan).values(active=False))
    db.add(WorkoutPlan(name="Lose 10.5 kg in 13 weeks · home", goal="fat_loss", weeks=13,
                       days=DAYS, progression=PROGRESSION, active=True))

    p = db.scalar(select(Profile)) or Profile()
    p.birth_year, p.height_cm, p.weight_kg = 1984, p.height_cm or 180, 105.5
    p.goal, p.equipment, p.training_days, p.setup_done = "lose", "home", 4, True
    db.add(p)

    g = db.scalar(select(Goals)) or Goals()
    g.calorie_target, g.protein_target_g, g.carbs_target_g, g.fat_target_g = 2100, 180, 200, 65
    g.fiber_target_g, g.steps_target, g.workouts_per_week, g.target_weight_kg = 35, 10000, 4, 95
    g.active_minutes_per_week, g.saved, g.follow_garmin = 200, True, False
    db.add(g)

    w = db.scalar(select(WeightEntry).where(WeightEntry.day == today, WeightEntry.source == "manual"))
    db.add(w or WeightEntry(day=today, weight_kg=105.5, source="manual"))
    if w:
        w.weight_kg = 105.5

    # The old Garmin-based plan's workouts are cleared from the watch calendar on the next sync.
    from app.services import garmin_workouts as gw
    state = gw.load_state(db)
    if state.get("push"):
        state["clear_on_sync"] = True
        gw.save_state(db, state)

    db.add(StoredSecret(key=MARKER, value=today.isoformat()))
    db.commit()
    return True
