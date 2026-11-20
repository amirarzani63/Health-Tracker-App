"""Rule-based workout plan generator.

Builds a weekly split from the number of training days, picks exercises
per movement pattern for the available equipment, and sets sets/reps/rest
from the goal. Each week adds a simple progression note, with a deload in
the final week of plans that are 4+ weeks long.
"""

EXERCISES = {
    "squat": {"gym": ["Barbell back squat", "Front squat", "Leg press"],
              "home": ["Goblet squat", "Dumbbell split squat"],
              "bodyweight": ["Bodyweight squat", "Bulgarian split squat"]},
    "hinge": {"gym": ["Romanian deadlift", "Conventional deadlift", "Hip thrust"],
              "home": ["Dumbbell Romanian deadlift", "Single-leg RDL"],
              "bodyweight": ["Glute bridge", "Single-leg hip hinge"]},
    "h_push": {"gym": ["Barbell bench press", "Incline dumbbell press", "Machine chest press"],
               "home": ["Dumbbell floor press", "Dumbbell bench press"],
               "bodyweight": ["Push-up", "Decline push-up"]},
    "v_push": {"gym": ["Overhead barbell press", "Seated dumbbell shoulder press"],
               "home": ["Dumbbell shoulder press", "Arnold press"],
               "bodyweight": ["Pike push-up", "Handstand hold (wall)"]},
    "h_pull": {"gym": ["Barbell row", "Seated cable row", "Chest-supported row"],
               "home": ["One-arm dumbbell row", "Band row"],
               "bodyweight": ["Inverted row (table)", "Towel door row"]},
    "v_pull": {"gym": ["Pull-up", "Lat pulldown"],
               "home": ["Band lat pulldown", "Pull-up (doorway bar)"],
               "bodyweight": ["Pull-up / negative", "Superman pull"]},
    "lunge": {"gym": ["Walking lunge", "Step-up"],
              "home": ["Dumbbell reverse lunge", "Step-up"],
              "bodyweight": ["Reverse lunge", "Lateral lunge"]},
    "calf": {"gym": ["Standing calf raise"], "home": ["Single-leg calf raise"], "bodyweight": ["Single-leg calf raise"]},
    "biceps": {"gym": ["EZ-bar curl", "Cable curl"], "home": ["Dumbbell curl", "Hammer curl"], "bodyweight": ["Chin-up hold", "Towel curl"]},
    "triceps": {"gym": ["Cable pushdown", "Skull crusher"], "home": ["Overhead dumbbell extension"], "bodyweight": ["Bench dip", "Diamond push-up"]},
    "core": {"gym": ["Cable crunch", "Hanging knee raise"], "home": ["Dead bug", "Plank"], "bodyweight": ["Plank", "Hollow hold"]},
    "carry": {"gym": ["Farmer's carry"], "home": ["Suitcase carry"], "bodyweight": ["Bear crawl"]},
}

DAY_TEMPLATES = {
    "full_a": ("Full Body A", ["squat", "h_push", "h_pull", "hinge", "core"]),
    "full_b": ("Full Body B", ["hinge", "v_push", "v_pull", "lunge", "core"]),
    "full_c": ("Full Body C", ["squat", "h_push", "v_pull", "carry", "core"]),
    "upper_a": ("Upper A", ["h_push", "h_pull", "v_push", "v_pull", "triceps", "biceps"]),
    "upper_b": ("Upper B", ["v_push", "v_pull", "h_push", "h_pull", "biceps", "triceps"]),
    "lower_a": ("Lower A", ["squat", "hinge", "lunge", "calf", "core"]),
    "lower_b": ("Lower B", ["hinge", "squat", "lunge", "calf", "core"]),
    "push": ("Push", ["h_push", "v_push", "h_push", "triceps", "core"]),
    "pull": ("Pull", ["v_pull", "h_pull", "hinge", "biceps", "core"]),
    "legs": ("Legs", ["squat", "hinge", "lunge", "calf", "core"]),
}

SPLITS = {
    2: ["full_a", "full_b"],
    3: ["full_a", "full_b", "full_c"],
    4: ["upper_a", "lower_a", "upper_b", "lower_b"],
    5: ["push", "pull", "legs", "upper_a", "lower_a"],
    6: ["push", "pull", "legs", "push", "pull", "legs"],
}

# Which weekdays to train on, spreading rest days out.
SCHEDULE = {
    2: ["Mon", "Thu"],
    3: ["Mon", "Wed", "Fri"],
    4: ["Mon", "Tue", "Thu", "Fri"],
    5: ["Mon", "Tue", "Wed", "Fri", "Sat"],
    6: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# (sets, reps, rest seconds) for main lifts and accessories
GOAL_SCHEME = {
    "strength": {"main": (5, "3-5", 180), "accessory": (3, "6-8", 120)},
    "hypertrophy": {"main": (4, "6-10", 120), "accessory": (3, "10-15", 75)},
    "fat_loss": {"main": (3, "8-12", 75), "accessory": (3, "12-15", 45)},
    "endurance": {"main": (3, "12-15", 60), "accessory": (2, "15-20", 45)},
    "general": {"main": (3, "8-10", 90), "accessory": (3, "10-12", 60)},
}
MAIN_PATTERNS = {"squat", "hinge", "h_push", "v_push", "h_pull", "v_pull"}
EXPERIENCE_SET_ADJUST = {"beginner": -1, "intermediate": 0, "advanced": 1}

# Cardio sessions keyed by HR zone – maps directly to fenix HR zones.
CARDIO = {
    "endurance": [
        {"name": "Easy aerobic run/ride", "zone": "Zone 2", "minutes": 45},
        {"name": "Tempo intervals 4×6 min", "zone": "Zone 3-4", "minutes": 40},
        {"name": "Long steady session", "zone": "Zone 2", "minutes": 75},
    ],
    "fat_loss": [
        {"name": "Fast walk, jog or bike ride", "zone": "Zone 2", "minutes": 40},
        {"name": "Intervals: 30 seconds hard, 90 seconds easy, 8 times", "zone": "Zone 4-5", "minutes": 25},
    ],
    "general": [{"name": "Easy cardio of choice", "zone": "Zone 2", "minutes": 30}],
    "hypertrophy": [{"name": "Light recovery cardio", "zone": "Zone 1-2", "minutes": 20}],
    "strength": [{"name": "Light recovery cardio", "zone": "Zone 1-2", "minutes": 20}],
}


# Extra exercises for the areas a person wants to work on (added to every strength day, by equipment).
FOCUS_EXTRAS = {
    "core": {"gym": ["Cable crunch", "Hanging knee raise", "Plank"], "home": ["Dead bug", "Plank", "Side plank"],
             "bodyweight": ["Plank", "Dead bug", "Side plank"]},
    "shoulders": {"gym": ["Dumbbell lateral raise", "Face pull (cable with rope)", "Seated dumbbell shoulder press"],
                  "home": ["Dumbbell lateral raise", "Dumbbell rear-delt fly", "Arnold press"],
                  "bodyweight": ["Pike push-up", "Prone Y-T raise", "Wall slide"]},
    "arms": {"gym": ["Cable curl", "Rope triceps pushdown (cable)"], "home": ["Hammer curl", "Overhead dumbbell extension"],
             "bodyweight": ["Diamond push-up", "Bench dip"]},
    "back": {"gym": ["Face pull (cable with rope)", "Back extension", "Seated cable row"],
             "home": ["Dumbbell rear-delt fly", "Superman hold", "One-arm dumbbell row"],
             "bodyweight": ["Superman hold", "Prone Y-T raise", "Inverted row (table)"]},
    "legs": {"gym": ["Leg extension", "Leg curl", "Goblet squat"], "home": ["Goblet squat", "Dumbbell reverse lunge"],
             "bodyweight": ["Bodyweight squat", "Reverse lunge"]},
    "glutes": {"gym": ["Hip thrust", "Cable glute kickback"], "home": ["Dumbbell hip thrust", "Glute bridge"],
               "bodyweight": ["Glute bridge", "Single-leg glute bridge"]},
    "chest": {"gym": ["Incline dumbbell press", "Cable fly"], "home": ["Dumbbell floor press", "Dumbbell fly"],
              "bodyweight": ["Push-up", "Incline push-up"]},
}
FOCUS_LABELS = {"core": "core", "shoulders": "shoulders", "arms": "arms", "back": "back & posture", "legs": "legs",
                "glutes": "glutes", "chest": "chest", "cardio": "stamina", "flexibility": "flexibility"}
# Movement patterns / words to leave out for a sore or injured area, and safer swaps.
INJURY_AVOID = {
    "knees": ({"lunge"}, ("lunge", "split squat", "step-up", "jump")),
    "lower_back": ({"carry"}, ("deadlift", "barbell row", "back squat", "good morning", "back extension", "superman")),
    "shoulders": ({"v_push"}, ("overhead", "shoulder press", "arnold", "pike", "handstand", "dip", "skull", "upright")),
    "wrists": (set(), ("push-up", "plank", "handstand", "crawl", "skull")),
    "neck": (set(), ("crunch", "handstand", "shrug")),
}
INJURY_SWAP = {
    "squat": "Box squat to a bench (pain-free depth)", "hinge": "Glute bridge", "h_push": "Machine chest press",
    "plank": "Dead bug", "push-up": "Dumbbell floor press", "crunch": "Dead bug",
}


def _avoid(exercise: str, pattern: str, injuries: list[str]) -> bool:
    for inj in injuries:
        pats, words = INJURY_AVOID.get(inj, (set(), ()))
        if pattern in pats or any(w in exercise.lower() for w in words):
            return True
    return False


def _safe(exercise: str, pattern: str, injuries: list[str], options: list[str]) -> str | None:
    """The exercise, or a safe alternative for the person's injuries (None = leave it out)."""
    if not _avoid(exercise, pattern, injuries):
        return exercise
    for alt in options:
        if not _avoid(alt, pattern, injuries):
            return alt
    for key, alt in INJURY_SWAP.items():
        if (key == pattern or key in exercise.lower()) and not _avoid(alt, pattern, injuries):
            return alt
    return None


def _week_note(week: int, weeks: int, goal: str) -> str:
    if weeks >= 4 and week == weeks:
        return "Deload: cut sets roughly in half and use ~60% of usual loads. Let your Garmin recovery time come down."
    if week == 1:
        return "Find working weights: finish each set with 2–3 reps in reserve."
    if goal == "strength":
        return "Add 2.5 kg / 5 lb to upper-body lifts and 5 kg / 10 lb to lower-body lifts if all reps were hit last week."
    if goal in ("endurance", "fat_loss"):
        return "Add 1–2 reps per set or ~10% cardio duration versus last week."
    return "Add a rep to each set, or add load once you hit the top of the rep range."


def generate_plan(goal: str = "general", days_per_week: int = 4, weeks: int = 4,
                  equipment: str = "gym", experience: str = "intermediate",
                  include_cardio: bool = True, focus_areas: list[str] | None = None,
                  injuries: list[str] | None = None, session_minutes: int = 60) -> dict:
    focus_areas, injuries = focus_areas or [], [i for i in (injuries or []) if i != "none"]
    # roughly 8-10 minutes per exercise including rest; the warm-up takes the rest
    max_ex = max(3, min(8, (session_minutes - 5) // 8))
    days_per_week = min(6, max(2, days_per_week))
    if experience == "beginner" and days_per_week > 4:
        days_per_week = 4  # beginners progress best on full-body / upper-lower
    split = SPLITS[days_per_week]
    if experience == "beginner" and days_per_week == 4:
        split = ["full_a", "full_b", "full_a", "full_c"]

    scheme = GOAL_SCHEME.get(goal, GOAL_SCHEME["general"])
    set_adj = EXPERIENCE_SET_ADJUST.get(experience, 0)
    usage: dict[str, int] = {}

    training_days = []
    for weekday, key in zip(SCHEDULE[days_per_week], split):
        title, patterns = DAY_TEMPLATES[key]
        exercises = []
        for i, pattern in enumerate(patterns):
            options = EXERCISES[pattern][equipment]
            idx = usage.get(pattern, 0)
            usage[pattern] = idx + 1
            is_main = i < 2 and pattern in MAIN_PATTERNS
            sets, reps, rest = scheme["main" if is_main else "accessory"]
            exercise = _safe(options[idx % len(options)], pattern, injuries, options)
            if exercise is None:
                continue
            if pattern == "carry" or any(w in exercise.lower() for w in ("plank", "hold", "crawl")):
                reps = "30-45s"
            exercises.append({
                "exercise": exercise,
                "pattern": pattern,
                "sets": max(2, sets + set_adj),
                "reps": reps,
                "rest_s": rest,
            })
        # the person's focus areas: one extra exercise each, rotating, most important first
        extra_n = 0
        for area in focus_areas:
            pool = FOCUS_EXTRAS.get(area, {}).get(equipment, [])
            for k in range(len(pool)):
                ex = pool[(usage.get("focus:" + area, 0) + k) % len(pool)]
                if _avoid(ex, "", injuries) or any(e["exercise"] == ex for e in exercises):
                    continue
                usage["focus:" + area] = usage.get("focus:" + area, 0) + k + 1
                hold = any(w in ex.lower() for w in ("plank", "hold"))
                exercises.insert(min(len(exercises), 2 + extra_n), {"exercise": ex, "pattern": "focus_" + area,
                                  "sets": 3, "reps": "30-45s" if hold else "10-15", "rest_s": 60, "focus": area})
                extra_n += 1
                break
        # fit the session length: drop the least important accessories first (never the focus work)
        while len(exercises) > max_ex:
            drop = next((i for i in range(len(exercises) - 1, -1, -1) if not exercises[i].get("focus")
                         and exercises[i]["pattern"] not in MAIN_PATTERNS), None)
            if drop is None:
                drop = next((i for i in range(len(exercises) - 1, -1, -1) if not exercises[i].get("focus")), len(exercises) - 1)
            exercises.pop(drop)
        if focus_areas:
            title += " + " + " & ".join(FOCUS_LABELS.get(a, a) for a in focus_areas[:2] if a in FOCUS_EXTRAS)
        if "flexibility" in focus_areas:
            exercises.append({"exercise": "Stretch: hips, hamstrings, chest and shoulders", "pattern": "mobility",
                              "sets": 1, "reps": "8 minutes", "rest_s": 0, "focus": "flexibility"})
        training_days.append({"weekday": weekday, "type": "strength", "title": title.replace(" + ", " + ", 1),
                              "minutes": session_minutes, "exercises": exercises})

    days = list(training_days)
    if include_cardio:
        rest_days = [d for d in WEEKDAYS if d not in SCHEDULE[days_per_week] and d != "Sun"]
        sessions = CARDIO.get(goal, CARDIO["general"])
        n_cardio = 3 if goal == "endurance" else 2 if goal == "fat_loss" else 1
        if "cardio" in focus_areas:
            n_cardio += 1
        for weekday, session in zip(rest_days, (sessions * 3)[:n_cardio]):
            days.append({"weekday": weekday, "type": "cardio", "title": session["name"],
                         "zone": session["zone"], "minutes": min(session["minutes"], max(20, session_minutes)), "exercises": []})
    days.sort(key=lambda d: WEEKDAYS.index(d["weekday"]))

    progression = [{"week": w, "note": _week_note(w, weeks, goal)} for w in range(1, weeks + 1)]
    name = f"{goal.replace('_', ' ').title()} · {days_per_week} days/week · {equipment}"
    return {"name": name, "goal": goal, "weeks": weeks, "days": days, "progression": progression}


def readiness(stats) -> dict:
    """Simple training-readiness hint from Garmin daily stats."""
    if stats is None:
        return {"level": "unknown", "message": "Sync Garmin to get readiness hints from sleep and Body Battery."}
    signals = []
    level = "good"
    if stats.body_battery_high is not None and stats.body_battery_high < 40:
        level = "low"
        signals.append(f"Body Battery only peaked at {stats.body_battery_high}")
    if stats.sleep_s is not None and stats.sleep_s < 6 * 3600:
        level = "low" if level == "low" else "moderate"
        signals.append(f"{stats.sleep_s / 3600:.1f} h sleep")
    if stats.avg_stress is not None and stats.avg_stress > 50:
        level = "moderate" if level == "good" else level
        signals.append(f"high stress ({stats.avg_stress})")
    messages = {
        "good": "Recovered — go ahead with today's planned session.",
        "moderate": "Partly recovered — train, but keep 1–2 extra reps in reserve.",
        "low": "Low recovery — consider swapping today for Zone 1–2 cardio or mobility.",
    }
    msg = messages[level]
    if signals:
        msg += " (" + ", ".join(signals) + ")"
    return {"level": level, "message": msg}
