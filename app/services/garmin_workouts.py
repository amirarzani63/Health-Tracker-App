"""Build the workout plan from your own saved Garmin Connect workouts.

1. Reads the workouts you saved in Garmin Connect (your originals are never changed).
2. Adapts them to your goal and equipment: gym-only exercises (barbell, cable,
   machine...) are swapped for dumbbell/band versions from Garmin's own exercise
   catalog, and for weight loss low-rep sets move to 10+ reps with shorter rests.
3. Spreads them over your training days and adds Zone 2 cardio days.
4. Optionally sends it to your watch: each adapted workout is saved as a copy in
   Garmin Connect (Garmin duplicates it, then we edit the copy) and scheduled on
   your Garmin calendar two weeks ahead; later syncs keep the calendar filled.

Garmin's workout JSON is read and edited defensively; anything unexpected is
left as it was.
"""

import copy
import json
import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import StoredSecret
from app.services.workout_planner import SCHEDULE, WEEKDAYS, _week_note

log = logging.getLogger(__name__)

STATE_KEY = "garmin_plan"
COPY_SUFFIX = " · Health Tracker"
SCHEDULE_DAYS = 14

try:  # Garmin's exercise catalog, to show friendly names and validate substitutions
    from garminconnect.exercises import EXERCISES as _CATALOG
except Exception:  # pragma: no cover - library layout changed
    _CATALOG = []
NAMES = {(e["category"], e["exercise"]): e["name"] for e in _CATALOG}

GYM_ONLY_MARKERS = ("BARBELL", "CABLE", "MACHINE", "SMITH", "LEG_PRESS", "EZ_BAR", "TRAP_BAR", "SLED",
                    "PULLDOWN", "HACK_SQUAT", "PEC_DECK", "T_BAR", "LANDMINE", "ASSISTED_DIP")

# Category -> home (dumbbell / band) replacements, best first; all present in Garmin's catalog.
# A later option is used when an earlier one is already in the same workout.
HOME_SUBS = {
    "SQUAT": [("SQUAT", "GOBLET_SQUAT"), ("SQUAT", "DUMBBELL_STEP_UP"), ("LUNGE", "DUMBBELL_BULGARIAN_SPLIT_SQUAT")],
    "BENCH_PRESS": [("BENCH_PRESS", "DUMBBELL_FLOOR_PRESS"), ("BENCH_PRESS", "DUMBBELL_BENCH_PRESS"),
                    ("BENCH_PRESS", "INCLINE_DUMBBELL_BENCH_PRESS")],
    "ROW": [("ROW", "BENT_OVER_ROW_WITH_DUMELL"), ("BANDED_EXERCISES", "ROW"), ("ROW", "BANDED_FACE_PULLS")],
    "DEADLIFT": [("DEADLIFT", "DUMBBELL_STRAIGHT_LEG_DEADLIFT"), ("DEADLIFT", "DUMBBELL_DEADLIFT"),
                 ("DEADLIFT", "SINGLE_LEG_ROMANIAN_DEADLIFT_WITH_DUMBBELL")],
    "SHOULDER_PRESS": [("SHOULDER_PRESS", "DUMBBELL_SHOULDER_PRESS"), ("SHOULDER_PRESS", "ARNOLD_PRESS")],
    "PULL_UP": [("BANDED_EXERCISES", "ROW"), ("ROW", "BENT_OVER_ROW_WITH_DUMELL")],
    "LUNGE": [("LUNGE", "DUMBBELL_REVERSE_LUNGE"), ("LUNGE", "ALTERNATING_DUMBBELL_LUNGE"),
              ("LUNGE", "DUMBBELL_BULGARIAN_SPLIT_SQUAT")],
    "CURL": [("CURL", "ALTERNATING_DUMBBELL_BICEPS_CURL"), ("CURL", "DUMBBELL_HAMMER_CURL"), ("BANDED_EXERCISES", "CURL")],
    "TRICEPS_EXTENSION": [("TRICEPS_EXTENSION", "OVERHEAD_DUMBBELL_TRICEPS_EXTENSION"),
                          ("TRICEPS_EXTENSION", "DUMBBELL_LYING_TRICEPS_EXTENSION")],
    "LEG_CURL": [("LEG_CURL", "SLIDING_LEG_CURL"), ("BANDED_EXERCISES", "HAMSTRING_CURLS")],
    "HIP_RAISE": [("BANDED_EXERCISES", "GLUTE_BRIDGE")],
    "FLYE": [("FLYE", "DUMBBELL_FLYE"), ("FLYE", "INCLINE_DUMBBELL_FLYE")],
    "LATERAL_RAISE": [("LATERAL_RAISE", "DUMBBELL_LATERAL_RAISE"), ("BANDED_EXERCISES", "LATERAL_RAISE")],
    "CALF_RAISE": [("CALF_RAISE", "STANDING_DUMBBELL_CALF_RAISE"), ("CALF_RAISE", "SINGLE_LEG_STANDING_DUMBBELL_CALF_RAISE")],
    "SHRUG": [("SHRUG", "DUMBBELL_SHRUG")],
}
# Garmin's catalog spells the dumbbell row "DUMELL" in some versions; keep whatever it actually lists.
HOME_SUBS = {cat: [opt if opt in NAMES or opt[1] != "BENT_OVER_ROW_WITH_DUMELL" else ("ROW", "BENT_OVER_ROW_WITH_DUMBELL")
                   for opt in opts] for cat, opts in HOME_SUBS.items()}
HOME_SUBS = {cat: [o for o in opts if o in NAMES] or opts for cat, opts in HOME_SUBS.items()}


# ---------------------------------------------------------------- state
def load_state(db: Session) -> dict:
    row = db.get(StoredSecret, STATE_KEY)
    try:
        return json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


def save_state(db: Session, state: dict):
    row = db.get(StoredSecret, STATE_KEY) or StoredSecret(key=STATE_KEY)
    row.value = json.dumps(state)
    db.add(row)
    db.commit()


# ---------------------------------------------------------------- reading Garmin workouts
def _sport(w: dict) -> str:
    return ((w.get("sportType") or {}).get("sportTypeKey") or "other").lower()


def natural_key(name: str):
    """Sort 'Day 2' before 'Day 10', case-insensitively."""
    import re

    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name or "")]


def list_saved_workouts(client) -> list[dict]:
    """Your own saved workouts in name order (Day 1, Day 2, ...); copies this app made are skipped."""
    try:
        raw = client.get_workouts(0, 100, my_workouts_only=True, order_by="UPDATE_DATE", order_seq="DESC")
    except TypeError:  # older library without keyword filters
        raw = client.get_workouts(0, 100)
    out = []
    for w in raw or []:
        name = w.get("workoutName") or "Workout"
        if name.endswith(COPY_SUFFIX) or w.get("workoutId") is None:
            continue
        out.append({
            "id": w["workoutId"], "name": name, "sport": _sport(w),
            "minutes": round((w.get("estimatedDurationInSecs") or 0) / 60) or None,
            "updated": w.get("updateDate") or w.get("updatedDate") or w.get("createdDate"),
        })
    return sorted(out, key=lambda w: natural_key(w["name"]))


def _walk(steps):
    for s in steps or []:
        yield s
        yield from _walk(s.get("workoutSteps"))


def _is_repeat(step) -> bool:
    return "Repeat" in str(step.get("type", "")) or (step.get("stepType") or {}).get("stepTypeKey") == "repeat"


def _key(step):
    return (step.get("stepType") or {}).get("stepTypeKey")


def exercise_label(category, name) -> str:
    if (category, name or "") in NAMES:
        return NAMES[(category, name or "")]
    return str(name or category or "Exercise").replace("_", " ").title()


def _reps_label(step) -> str:
    cond = (step.get("endCondition") or {}).get("conditionTypeKey")
    v = step.get("endConditionValue")
    if cond == "reps" and v:
        return str(int(v))
    if cond == "time" and v:
        return f"{int(v)}s"
    return "until done"


def parse_workout(detail: dict) -> dict:
    """Turn Garmin workout JSON into the app's plan-day format."""
    exercises: list[dict] = []
    cardio_secs = 0

    def add_exercise(step, sets):
        label = exercise_label(step.get("category"), step.get("exerciseName"))
        last = exercises[-1] if exercises else None
        if last and last["exercise"] == label and last["reps"] == _reps_label(step):
            last["sets"] += sets  # consecutive identical steps = more sets
        else:
            exercises.append({"exercise": label, "sets": sets, "reps": _reps_label(step), "rest_s": None,
                              "weight_kg": step.get("weightValue")})

    def visit(steps, iterations=1):
        nonlocal cardio_secs
        for s in steps or []:
            if _is_repeat(s):
                visit(s.get("workoutSteps"), int(s.get("numberOfIterations") or 1) * iterations)
            elif s.get("category"):
                add_exercise(s, iterations)
            elif _key(s) in ("rest", "recovery") and exercises and (s.get("endCondition") or {}).get("conditionTypeKey") == "time":
                exercises[-1]["rest_s"] = int(s.get("endConditionValue") or 0)
            elif (s.get("endCondition") or {}).get("conditionTypeKey") == "time":
                cardio_secs += int(s.get("endConditionValue") or 0) * iterations

    for seg in detail.get("workoutSegments") or []:
        visit(seg.get("workoutSteps"))
    sport = _sport(detail)
    is_strength = bool(exercises) or sport in ("strength_training", "hiit")
    day = {"type": "strength" if is_strength else "cardio", "title": detail.get("workoutName") or "Workout",
           "exercises": exercises, "garmin_source_id": detail.get("workoutId")}
    if not is_strength:
        day["minutes"] = round(cardio_secs / 60) or round((detail.get("estimatedDurationInSecs") or 0) / 60) or 30
        day["zone"] = "as programmed"
    return day


# ---------------------------------------------------------------- adapting
def gym_only(step) -> bool:
    name = str(step.get("exerciseName") or "")
    return any(m in name for m in GYM_ONLY_MARKERS)


def adapt_workout(detail: dict, goal: str, equipment: str) -> tuple[dict, list[str]]:
    """Return an adjusted deep copy of a Garmin workout plus a list of the changes made."""
    w = copy.deepcopy(detail)
    changes: list[str] = []
    fat_loss = goal == "lose"
    used = {(s.get("category"), s.get("exerciseName") or "") for seg in w.get("workoutSegments") or []
            for s in _walk(seg.get("workoutSteps")) if s.get("category") and not gym_only(s)}
    for seg in w.get("workoutSegments") or []:
        for s in _walk(seg.get("workoutSteps")):
            if _is_repeat(s) and fat_loss and int(s.get("numberOfIterations") or 1) > 4:
                changes.append(f"{s['numberOfIterations']} sets → 4 sets (keeps sessions short)")
                s["numberOfIterations"] = 4
                if s.get("endConditionValue"):
                    s["endConditionValue"] = 4.0
            if s.get("category"):
                if equipment in ("home", "bodyweight") and gym_only(s):
                    before = exercise_label(s.get("category"), s.get("exerciseName"))
                    options = HOME_SUBS.get(s["category"]) or [(s["category"], "")]
                    cat, ex = next((o for o in options if o not in used), options[0])
                    used.add((cat, ex))
                    s["category"], s["exerciseName"] = cat, (ex or None)
                    s["weightValue"] = None
                    after = exercise_label(cat, ex)
                    note = f"Home swap for {before}"
                    s["description"] = f"{s.get('description')} · {note}" if s.get("description") else note
                    changes.append(f"{before} → {after} (home equipment)")
                cond = (s.get("endCondition") or {}).get("conditionTypeKey")
                if fat_loss and cond == "reps" and 0 < float(s.get("endConditionValue") or 0) < 8:
                    changes.append(f"{exercise_label(s.get('category'), s.get('exerciseName'))}: "
                                   f"{int(s['endConditionValue'])} → 10 reps")
                    s["endConditionValue"] = 10.0
            elif fat_loss and _key(s) == "rest" and (s.get("endCondition") or {}).get("conditionTypeKey") == "time":
                if float(s.get("endConditionValue") or 0) > 75:
                    changes.append(f"Rest {int(s['endConditionValue'])}s → 60s (keeps heart rate up)")
                    s["endConditionValue"] = 60.0
    # de-duplicate change notes while keeping order
    seen, unique = set(), []
    for c in changes:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return w, unique


def zone2_cardio_workout(minutes: int = 40) -> dict:
    """A Garmin 'cardio' workout: warm-up, steady Zone 2, cool-down. Do it as a brisk walk, bike or cross-trainer."""
    from garminconnect.workout import (BaseWorkout, WorkoutSegment, create_cooldown_step,
                                       create_interval_step, create_warmup_step)

    sport = {"sportTypeId": 6, "sportTypeKey": "cardio_training", "displayOrder": 6}
    main = max(10, minutes - 10)
    w = BaseWorkout(
        workoutName=f"Zone 2 cardio {minutes} min{COPY_SUFFIX}",
        description="Brisk walk, bike or cross-trainer. Stay in heart-rate Zone 2: you can talk in full sentences.",
        sportType=sport,
        estimatedDurationInSecs=minutes * 60,
        workoutSegments=[WorkoutSegment(segmentOrder=1, sportType=sport, workoutSteps=[
            create_warmup_step(300, 1),
            create_interval_step(main * 60, 2, target_type={"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone",
                                                         "displayOrder": 4}, zone_number=2),
            create_cooldown_step(300, 3),
        ])],
    )
    return w.to_dict()


# ---------------------------------------------------------------- building the plan
def build_plan(details: list[dict], goal: str, equipment: str, days_per_week: int, weeks: int = 4) -> dict:
    """App plan from adapted Garmin workouts: strength rotation + Zone 2 cardio for weight loss."""
    days_per_week = max(2, min(6, days_per_week))
    adapted = []
    for d in details:
        new, changes = adapt_workout(d, goal, equipment)
        day = parse_workout(new)
        day["changes"] = changes
        day["garmin_source_id"] = d.get("workoutId")
        adapted.append(day)
    strength = sorted([a for a in adapted if a["type"] == "strength"] or adapted, key=lambda a: natural_key(a["title"]))
    cardio_own = [a for a in adapted if a["type"] == "cardio" and a not in strength]

    plan_days = []
    for i, wd in enumerate(SCHEDULE[days_per_week]):
        day = dict(strength[i % len(strength)])
        day["weekday"] = wd
        plan_days.append(day)
    free = [d for d in WEEKDAYS if d not in SCHEDULE[days_per_week] and d != "Sun"]
    n_cardio = 2 if goal == "lose" else (1 if cardio_own else 0)
    for i, wd in enumerate(free[:n_cardio]):
        if cardio_own:
            day = dict(cardio_own[i % len(cardio_own)])
        else:
            day = {"type": "cardio", "title": "Zone 2 cardio", "zone": "Zone 2", "minutes": 40,
                   "exercises": [], "garmin_source_id": "zone2"}
        day["weekday"] = wd
        plan_days.append(day)
    plan_days.sort(key=lambda d: WEEKDAYS.index(d["weekday"]))
    plan_goal = {"lose": "fat_loss", "gain": "hypertrophy"}.get(goal, "general")
    return {
        "name": f"My Garmin workouts · {days_per_week} days · {equipment}",
        "goal": plan_goal, "weeks": weeks, "days": plan_days,
        "progression": [{"week": w, "note": _week_note(w, weeks, plan_goal)} for w in range(1, weeks + 1)],
    }


# ---------------------------------------------------------------- sending to Garmin
def _id_from(resp, *keys):
    if isinstance(resp, dict):
        for k in keys:
            if resp.get(k):
                return resp[k]
        for v in resp.values():
            found = _id_from(v, *keys) if isinstance(v, dict) else None
            if found:
                return found
    return None


def push_plan(db: Session, client, plan: dict, goal: str, equipment: str, today: date | None = None) -> dict:
    """Save adapted copies in Garmin Connect and schedule them on the Garmin calendar."""
    today = today or date.today()
    state = load_state(db)
    copies: dict = state.get("copies", {})
    result = {"saved": [], "scheduled": 0, "errors": []}
    workout_for_source: dict = {}

    for source_id in {d.get("garmin_source_id") for d in plan["days"] if d.get("garmin_source_id")}:
        try:
            if source_id == "zone2":
                cid = copies.get("zone2")
                if not cid:
                    cid = _id_from(client.upload_workout(zone2_cardio_workout()), "workoutId")
                    copies["zone2"] = cid
                workout_for_source["zone2"] = cid
                result["saved"].append("Zone 2 cardio")
                continue
            original = client.get_workout_by_id(source_id)
            name = (original.get("workoutName") or "Workout")[: 60 - len(COPY_SUFFIX)] + COPY_SUFFIX
            cid = copies.get(str(source_id))
            same_settings = state.get("goal") == goal and state.get("equipment") == equipment
            if cid and same_settings:
                try:
                    client.get_workout_by_id(cid)
                except Exception:
                    cid = None  # the copy was deleted in Garmin Connect; make a new one
            else:
                cid = None  # goal or equipment changed: start again from your original
            if not cid:
                cid = _id_from(client.copy_workout(source_id, name), "workoutId") or _find_by_name(client, name)
                if not cid:
                    raise RuntimeError("Garmin didn't return the copied workout")
            # edit the copy's own JSON (keeps Garmin's ids for the copy); adapting is idempotent
            copy_detail = client.get_workout_by_id(cid)
            adapted, _ = adapt_workout(copy_detail, goal, equipment)
            adapted["workoutName"] = name
            adapted["description"] = "Adapted by Health Tracker from your saved workout. Your original is unchanged."
            client.update_workout(cid, adapted)
            copies[str(source_id)] = cid
            workout_for_source[source_id] = cid
            result["saved"].append(name)
        except Exception as e:
            log.warning("Could not save Garmin workout %s: %s", source_id, e)
            result["errors"].append(f"{source_id}: {e}")

    # replace what we scheduled before (from today on) with the new plan
    for item in state.get("scheduled", []):
        if item.get("date", "") >= today.isoformat() and item.get("id"):
            try:
                client.unschedule_workout(item["id"])
            except Exception as e:
                log.info("Unschedule %s failed: %s", item, e)
    state.update({"copies": copies, "push": True, "goal": goal, "equipment": equipment,
                  "by_weekday": {d["weekday"]: workout_for_source.get(d.get("garmin_source_id")) for d in plan["days"]},
                  "scheduled": [i for i in state.get("scheduled", []) if i.get("date", "") < today.isoformat()],
                  "scheduled_until": (today - timedelta(days=1)).isoformat()})
    result["scheduled"], errs = _schedule(client, state, today, today + timedelta(days=SCHEDULE_DAYS - 1))
    result["errors"] += errs
    save_state(db, state)
    return result


def _find_by_name(client, name):
    try:
        for w in client.get_workouts(0, 100) or []:
            if w.get("workoutName") == name:
                return w.get("workoutId")
    except Exception:
        pass
    return None


def _schedule(client, state: dict, start: date, end: date) -> tuple[int, list[str]]:
    count, errors = 0, []
    d = start
    while d <= end:
        wid = state.get("by_weekday", {}).get(WEEKDAYS[d.weekday()])
        if wid:
            try:
                resp = client.schedule_workout(wid, d.isoformat())
                sid = _id_from(resp, "workoutScheduleId", "scheduledWorkoutId", "id")
                state.setdefault("scheduled", []).append({"id": sid, "date": d.isoformat(), "workout": wid})
                count += 1
            except Exception as e:
                errors.append(f"schedule {d}: {e}")
        d += timedelta(days=1)
    state["scheduled_until"] = end.isoformat()
    return count, errors


def keep_calendar_filled(db: Session, client, today: date | None = None) -> int:
    """Called after each sync: keep two weeks of the plan scheduled on the Garmin calendar."""
    today = today or date.today()
    state = load_state(db)
    if state.get("clear_on_sync"):  # a new non-Garmin plan replaced the pushed one
        state.pop("clear_on_sync")
        save_state(db, state)
        stop_pushing(db, client, today)
        return 0
    if not state.get("push") or not state.get("by_weekday"):
        return 0
    if state.get("needs_reschedule"):  # the plan's days were re-ordered: redo the calendar from today
        for item in state.get("scheduled", []):
            if item.get("date", "") >= today.isoformat() and item.get("id"):
                try:
                    client.unschedule_workout(item["id"])
                except Exception:
                    pass
        state["scheduled"] = [i for i in state.get("scheduled", []) if i.get("date", "") < today.isoformat()]
        state["needs_reschedule"] = False
        count, _ = _schedule(client, state, today, today + timedelta(days=SCHEDULE_DAYS - 1))
        save_state(db, state)
        return count
    until = date.fromisoformat(state.get("scheduled_until") or today.isoformat())
    if until >= today + timedelta(days=7):
        return 0
    start = max(until + timedelta(days=1), today)
    count, _ = _schedule(client, state, start, today + timedelta(days=SCHEDULE_DAYS - 1))
    # forget old entries so the state stays small
    state["scheduled"] = [i for i in state.get("scheduled", []) if i.get("date", "") >= (today - timedelta(days=7)).isoformat()]
    save_state(db, state)
    return count


def stop_pushing(db: Session, client, today: date | None = None) -> int:
    """Remove this app's future workouts from the Garmin calendar and stop scheduling."""
    today = today or date.today()
    state = load_state(db)
    removed = 0
    for item in state.get("scheduled", []):
        if item.get("date", "") >= today.isoformat() and item.get("id"):
            try:
                client.unschedule_workout(item["id"])
                removed += 1
            except Exception:
                pass
    state.update({"push": False, "scheduled": [], "scheduled_until": None})
    save_state(db, state)
    return removed


# ---------------------------------------------------------------- one call used by setup + the Plans tab
def create_plan_from_garmin(db: Session, client, goal: str, equipment: str, days_per_week: int,
                            workout_ids: list | None = None, send_to_watch: bool = False) -> dict | None:
    """Build (and activate) the app plan from saved Garmin workouts; optionally send it to the watch.

    With no ``workout_ids`` the newest saved strength workouts are used (one per training day,
    rotating if there are fewer). Returns None when there are no saved workouts to use.
    """
    from sqlalchemy import update

    from app.models import WorkoutPlan

    saved = list_saved_workouts(client)
    if workout_ids:
        wanted = {str(i) for i in workout_ids}
        chosen = [w for w in saved if str(w["id"]) in wanted]
    else:
        # the workouts you edited most recently are your current program; then put them in name order
        strength = sorted([w for w in saved if w["sport"] in ("strength_training", "hiit")],
                          key=lambda w: str(w.get("updated") or ""), reverse=True)[:days_per_week]
        strength.sort(key=lambda w: natural_key(w["name"]))
        chosen = strength + [w for w in saved if w["sport"] not in ("strength_training", "hiit")][:1]
    if not chosen:
        return None
    details = []
    for w in chosen:
        try:
            details.append(client.get_workout_by_id(w["id"]))
        except Exception as e:
            log.warning("Could not read Garmin workout %s: %s", w["id"], e)
    if not details:
        return None
    plan = build_plan(details, goal, equipment, days_per_week)
    db.execute(update(WorkoutPlan).values(active=False))
    row = WorkoutPlan(name=plan["name"], goal=plan["goal"], weeks=plan["weeks"], days=plan["days"],
                      progression=plan["progression"], active=True)
    db.add(row)
    db.commit()
    changes = sorted({c for d in plan["days"] for c in d.get("changes", [])})
    pushed = push_plan(db, client, plan, goal, equipment) if send_to_watch else None
    return {"plan_id": row.id, "plan_name": plan["name"], "used": [w["name"] for w in chosen],
            "changes": changes, "pushed": pushed}


def swap_weekdays(db: Session, client, a: str, b: str, today: date | None = None) -> dict:
    """Mirror a moved session on the Garmin calendar: swap two weekdays and reschedule from today."""
    today = today or date.today()
    state = load_state(db)
    if not state.get("push") or not state.get("by_weekday"):
        return {"rescheduled": 0}
    bw = state["by_weekday"]
    bw[a], bw[b] = bw.get(b), bw.get(a)
    errors = []
    keep = []
    for item in state.get("scheduled", []):
        if item.get("date", "") >= today.isoformat() and item.get("id"):
            try:
                client.unschedule_workout(item["id"])
            except Exception as e:
                errors.append(f"unschedule {item.get('date')}: {e}")
        else:
            keep.append(item)
    state["scheduled"] = keep
    count, errs = _schedule(client, state, today, today + timedelta(days=SCHEDULE_DAYS - 1))
    save_state(db, state)
    return {"rescheduled": count, "errors": errors + errs}


def reorder_saved_plans(db: Session) -> int:
    """Repair plans built before workouts were ordered by name: Day 1, Day 2, ... go on the training
    days in order (same weekdays, same sessions). Flags the Garmin calendar for rescheduling."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from app.models import WorkoutPlan

    fixed = 0
    for plan in db.scalars(select(WorkoutPlan)).all():
        days = [dict(d) for d in plan.days or []]
        strength = [d for d in days if d.get("type") == "strength" and d.get("garmin_source_id")]
        if len(strength) < 2:
            continue
        weekdays = sorted((d["weekday"] for d in strength), key=WEEKDAYS.index)
        templates = {}
        for d in strength:  # one template per distinct workout
            templates.setdefault(d.get("title", ""), d)
        names = sorted(templates, key=natural_key)
        current = [d.get("title") for d in sorted(strength, key=lambda d: WEEKDAYS.index(d["weekday"]))]
        wanted = [names[i % len(names)] for i in range(len(weekdays))]  # Day 1, Day 2, ... rotating
        if current == wanted:
            continue
        rebuilt = [{**templates[n], "weekday": wd} for n, wd in zip(wanted, weekdays)]
        days = [d for d in days if d not in strength] + rebuilt
        days.sort(key=lambda d: WEEKDAYS.index(d.get("weekday", "Sun")))
        plan.days = days
        flag_modified(plan, "days")
        fixed += 1
        if plan.active:
            state = load_state(db)
            if state.get("push"):
                copies = state.get("copies", {})
                state["by_weekday"] = {d["weekday"]: copies.get(str(d.get("garmin_source_id"))) for d in days}
                state["needs_reschedule"] = True
                save_state(db, state)
    db.commit()
    return fixed
