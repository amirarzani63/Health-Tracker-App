"""The 13-week fat-loss plan agreed with the user (Nov 2026): 105.5 kg -> 95 kg, home dumbbells + bands.

Installed once at start-up (guarded by a marker), then it is an ordinary plan the user can move or replace.
"""

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Goals, Profile, StoredSecret, WeightEntry, WorkoutPlan

MARKER = "preset:fatloss-95-v2"
PLAN_NAME = "Lose 10.5 kg in 13 weeks · home"


def ex(name, sets, reps, rest=75, pattern=""):
    return {"exercise": name, "pattern": pattern, "sets": sets, "reps": reps, "rest_s": rest}


# Beginner-friendly: 3 sets, simple moves, 60-75 s rest, then a steady cardio block so every
# session burns ~500+ kcal at ~105 kg (weights ~3.5 MET, brisk walk/bike ~4.5-6.5 MET).
CARDIO_FINISH = ex("Brisk walk or easy bike (Zone 2)", 1, "25 min", 0, "cardio")

DAYS = [
    {"weekday": "Mon", "type": "strength", "title": "Upper body A", "minutes": 65, "est_kcal": 520, "exercises": [
        ex("Dumbbell bench press", 3, "10-12", 75, "h_push"),
        ex("One-arm dumbbell row", 3, "10-12", 75, "h_pull"),
        ex("Seated dumbbell shoulder press", 3, "10-12", 75, "v_push"),
        ex("Band lat pulldown", 3, "12-15", 60, "v_pull"),
        ex("Hammer curl", 2, "12", 60, "biceps"),
        ex("Dumbbell overhead triceps extension", 2, "12", 60, "triceps"),
        CARDIO_FINISH,
    ]},
    {"weekday": "Tue", "type": "strength", "title": "Lower body A", "minutes": 65, "est_kcal": 540, "exercises": [
        ex("Goblet squat", 3, "10-12", 75, "squat"),
        ex("Dumbbell Romanian deadlift", 3, "10-12", 75, "hinge"),
        ex("Dumbbell step-ups", 3, "10 each leg", 75, "lunge"),
        ex("Glute bridge", 3, "15", 60, "hinge"),
        ex("Plank", 3, "20-30s", 45, "core"),
        CARDIO_FINISH,
    ]},
    {"weekday": "Wed", "type": "cardio", "title": "Zone 2 brisk walk or bike", "zone": "Zone 2", "minutes": 60,
     "est_kcal": 500, "exercises": []},
    {"weekday": "Thu", "type": "strength", "title": "Upper body B", "minutes": 65, "est_kcal": 510, "exercises": [
        ex("Incline push-ups (hands on bench)", 3, "8-12", 75, "h_push"),
        ex("Band row", 3, "12-15", 60, "h_pull"),
        ex("Dumbbell lateral raise", 3, "12", 60, "v_push"),
        ex("Rear delt fly", 2, "12-15", 60, "h_pull"),
        ex("Dumbbell curl", 2, "12", 60, "biceps"),
        ex("Band triceps pushdown", 2, "12-15", 60, "triceps"),
        CARDIO_FINISH,
    ]},
    {"weekday": "Fri", "type": "strength", "title": "Lower body B", "minutes": 65, "est_kcal": 540, "exercises": [
        ex("Split squat (hold a chair)", 3, "8-10 each leg", 75, "lunge"),
        ex("Sumo dumbbell squat", 3, "10-12", 75, "squat"),
        ex("Hip thrust", 3, "12", 60, "hinge"),
        ex("Dead bug", 3, "8 each side", 45, "core"),
        ex("Walking intervals: 1 min fast / 2 min easy", 1, "8 rounds (24 min)", 0, "cardio"),
    ]},
    {"weekday": "Sat", "type": "cardio", "title": "Long Zone 2 walk or bike", "zone": "Zone 2", "minutes": 70,
     "est_kcal": 580, "exercises": []},
    {"weekday": "Sun", "type": "rest", "title": "Rest day", "exercises": []},
]

PROGRESSION = [
    {"week": w, "note": n} for w, n in [
        (1, "Learn the moves with light weights; stop every set with 3 reps left. Weigh in 3+ mornings. ~104.5 kg."),
        (2, "Same weights, aim for the top of each rep range. ~104 kg."),
        (3, "Top of the range on every set? Go heavier / stronger band. ~103 kg."),
        (4, "Keep adding reps or weight. Check-in: ~102 kg."),
        (5, "Deload: 2 sets per exercise, same weights. Keep walking."),
        (6, "Back to full sets; beat week 4's numbers. ~101 kg."),
        (7, "Progress weights. Cardio blocks up to 30 min. ~100 kg."),
        (8, "Check-in: ~98.5 kg. Slower than 0.5 kg/wk for 2 weeks? Cut 150 kcal or add 2k steps."),
        (9, "Add a 4th set to squats, rows and presses if you feel good. ~98 kg."),
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
    old = db.scalar(select(WorkoutPlan).where(WorkoutPlan.name == PLAN_NAME))  # v1: update in place
    plan = old or WorkoutPlan(name=PLAN_NAME, goal="fat_loss", weeks=13)
    plan.days, plan.progression, plan.active = DAYS, PROGRESSION, True
    db.add(plan)
    first_time = not db.get(StoredSecret, "preset:fatloss-95-v1")

    p = db.scalar(select(Profile)) or Profile()
    p.birth_year, p.height_cm, p.weight_kg = 1984, p.height_cm or 180, 105.5
    p.goal, p.equipment, p.training_days, p.setup_done = "lose", "home", 4, True
    p.experience = "beginner"
    db.add(p)

    g = db.scalar(select(Goals)) or Goals()
    g.calorie_target, g.protein_target_g, g.carbs_target_g, g.fat_target_g = 2100, 180, 200, 65
    g.fiber_target_g, g.steps_target, g.workouts_per_week, g.target_weight_kg = 35, 10000, 4, 95
    g.active_minutes_per_week, g.saved, g.follow_garmin = 300, True, False
    db.add(g)

    if first_time:
        _first_install(db, today)
    db.add(StoredSecret(key=MARKER, value=today.isoformat()))
    db.commit()
    return True


def _first_install(db: Session, today: date):
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
