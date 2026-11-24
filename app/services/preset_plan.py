"""The 13-week fat-loss plan agreed with the user (Nov 2026): 105.5 kg -> 95 kg, home dumbbells + bands.

Installed once at start-up (guarded by a marker), then it is an ordinary plan the user can move or replace.
"""

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Goals, Profile, StoredSecret, WeightEntry, WorkoutPlan

MARKER = "preset:fatloss-95-v5"
PLAN_NAME = "Lose 10.5 kg in 13 weeks · home"
PLAN_NAME_GYM = "Lose 10.5 kg in 13 weeks · building gym"


def ex(name, sets, reps, rest=75, pattern=""):
    return {"exercise": name, "pattern": pattern, "sets": sets, "reps": reps, "rest_s": rest}


# Beginner-friendly: 3 sets, simple moves, 60-75 s rest, then a steady cardio block so every
# session burns ~500+ kcal at ~105 kg (weights ~3.5 MET, brisk walk/bike ~4.5-6.5 MET).
CARDIO_FINISH = ex("Treadmill walk or bike (no stopping)", 1, "25 minutes", 0, "cardio")


def gx(name, photo, sets, reps, rest=75, pattern=""):
    """An exercise done with the user's gym equipment; ``photo`` is the matching library photo."""
    return {**ex(name, sets, reps, rest, pattern), "photo": photo}


# Only equipment in the user's building gym (Nov 2026 photos): dumbbell rack, adjustable benches,
# cable station (lat pulldown, seated row, leg extension / leg curl, rope), pull-up/dip/knee-raise tower,
# back-extension bench, stability ball, treadmills, upright + recumbent bike, elliptical.
# Gym rule: cardio machines max 30 minutes at a time.
DAYS = [
    {"weekday": "Mon", "type": "strength", "title": "Upper body A", "minutes": 65, "est_kcal": 520, "exercises": [
        gx("Dumbbell bench press (flat bench)", "Dumbbell Bench Press", 3, "10-12", 75, "h_push"),
        gx("Seated cable row (cable station)", "Seated Cable Rows", 3, "10-12", 75, "h_pull"),
        gx("Seated dumbbell shoulder press (bench upright)", "Dumbbell Shoulder Press", 3, "10-12", 75, "v_push"),
        gx("Lat pulldown (cable station)", "Wide-Grip Lat Pulldown", 3, "10-12", 75, "v_pull"),
        gx("Dumbbell hammer curl", "Hammer Curls", 2, "12", 60, "biceps"),
        gx("Rope triceps pushdown (cable)", "Triceps Pushdown - Rope Attachment", 2, "12-15", 60, "triceps"),
        CARDIO_FINISH,
    ]},
    {"weekday": "Tue", "type": "strength", "title": "Lower body A", "minutes": 65, "est_kcal": 540, "exercises": [
        gx("Goblet squat (one dumbbell)", "Goblet Squat", 3, "10-12", 75, "squat"),
        ex("Dumbbell Romanian deadlift", 3, "10-12", 75, "hinge"),
        gx("Leg extension (cable station)", "Leg Extensions", 3, "12-15", 60, "squat"),
        gx("Leg curl (cable station)", "Seated Leg Curl", 3, "12-15", 60, "hinge"),
        gx("Back extension (back-extension bench)", "Hyperextensions (Back Extensions)", 2, "10-12", 60, "hinge"),
        gx("Plank", "Plank", 3, "hold 20-30 seconds", 45, "core"),
        CARDIO_FINISH,
    ]},
    {"weekday": "Wed", "type": "cardio", "title": "Cardio machines", "zone": "Zone 2", "minutes": 60,
     "est_kcal": 500, "exercises": []},
    {"weekday": "Thu", "type": "strength", "title": "Upper body B", "minutes": 65, "est_kcal": 510, "exercises": [
        gx("Incline dumbbell press (bench on incline)", "Incline Dumbbell Press", 3, "10-12", 75, "h_push"),
        gx("One-arm dumbbell row (hand on bench)", "One-Arm Dumbbell Row", 3, "10-12", 75, "h_pull"),
        gx("Dumbbell lateral raise", "Side Lateral Raise", 3, "12", 60, "v_push"),
        gx("Face pull (cable with rope)", "Face Pull", 2, "12-15", 60, "h_pull"),
        gx("Cable biceps curl", "Standing Biceps Cable Curl", 2, "12", 60, "biceps"),
        gx("Knee raise (on the dip / knee-raise tower)", "Knee/Hip Raise On Parallel Bars", 2, "8-12", 60, "core"),
        CARDIO_FINISH,
    ]},
    {"weekday": "Fri", "type": "strength", "title": "Lower body B", "minutes": 65, "est_kcal": 540, "exercises": [
        gx("Split squat (dumbbells, hold the rack for balance if needed)", "Split Squat with Dumbbells", 3, "8-10 each leg", 75, "lunge"),
        gx("Sumo dumbbell squat", "Plie Dumbbell Squat", 3, "10-12", 75, "squat"),
        ex("Hip thrust (shoulders on bench, dumbbell on hips)", 3, "12", 60, "hinge"),
        gx("Leg curl (cable station)", "Seated Leg Curl", 2, "12-15", 60, "hinge"),
        gx("Dead bug", "Dead Bug", 3, "8 each side (left + right = 1)", 45, "core"),
        ex("Treadmill: 1 minute fast, then 2 minutes slow", 1, "24 minutes", 0, "cardio"),
    ]},
    {"weekday": "Sat", "type": "cardio", "title": "Cardio machines (longer)", "zone": "Zone 2", "minutes": 70,
     "est_kcal": 580, "exercises": []},
    {"weekday": "Sun", "type": "rest", "title": "Rest day", "exercises": []},
]

PROGRESSION = [
    {"week": w, "note": n} for w, n in [
        (1, "Use light weights and learn each move. Stop each round when you could still do 3 more. Weigh yourself 3 mornings this week. Goal: about 104.5 kg."),
        (2, "Same weights as last week. Try to reach the higher number of times in each round. Goal: about 104 kg."),
        (3, "If every round felt easy, use slightly heavier dumbbells or a stronger band. Goal: about 103 kg."),
        (4, "Keep going a little heavier or a few more times. Goal: about 102 kg."),
        (5, "Easy week: do only 2 rounds of each exercise, same weights. Keep walking."),
        (6, "Back to normal rounds. Try to beat what you did in week 4. Goal: about 101 kg."),
        (7, "A little heavier again. Make the walk or bike ride after your exercises 30 minutes. Goal: about 100 kg."),
        (8, "Goal: about 98.5 kg. If you lost less than half a kilo a week for 2 weeks, eat a little less (150 calories, e.g. one slice of bread) or walk 2,000 more steps a day."),
        (9, "If you feel strong, add a 4th round to squats, rows and presses. Goal: about 98 kg."),
        (10, "Easy week: 2 rounds of each exercise. Goal: about 97.5 kg."),
        (11, "Back to normal rounds with your heaviest weights so far. Goal: about 96.5 kg."),
        (12, "Keep eating 180 g of protein a day and sleep 7 to 8 hours. Goal: about 95.5 kg."),
        (13, "Goal week: 95 kg! After this, eat 200 to 300 calories more per day to stay at your new weight."),
    ]
]


def install(db: Session, today: date | None = None) -> bool:
    if db.get(StoredSecret, MARKER):
        return False
    today = today or date.today()
    db.execute(update(WorkoutPlan).values(active=False))
    old = db.scalar(select(WorkoutPlan).where(WorkoutPlan.name.in_([PLAN_NAME, PLAN_NAME_GYM])))  # update in place
    plan = old or WorkoutPlan(name=PLAN_NAME_GYM, goal="fat_loss", weeks=13)
    plan.name = PLAN_NAME_GYM
    plan.days, plan.progression, plan.active = DAYS, PROGRESSION, True
    db.add(plan)
    first_time = not db.get(StoredSecret, "preset:fatloss-95-v1")
    if db.get(StoredSecret, "preset:fatloss-95-v2"):  # goals/profile already set; only refresh the plan
        prof = db.scalar(select(Profile))
        if prof:
            prof.equipment = "gym"
            db.add(prof)
        db.add(StoredSecret(key=MARKER, value=today.isoformat()))
        db.commit()
        return True

    p = db.scalar(select(Profile)) or Profile()
    p.birth_year, p.height_cm, p.weight_kg = 1984, p.height_cm or 180, 105.5
    p.goal, p.equipment, p.training_days, p.setup_done = "lose", "gym", 4, True
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
