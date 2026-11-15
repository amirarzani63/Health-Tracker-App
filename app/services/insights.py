"""Summaries, trends, recommendations, reminders and progress built from all logged data.

This is where the manual food log and Garmin data are combined into a single
daily picture (intake vs. burned, steps, workouts, sleep) and compared with
your goals.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (Activity, DailyStats, FoodEntry, Goals, Profile, Reminder, ReminderLog,
                        WeightEntry, WorkoutPlan)
from app.services import nutrition
from app.services.workout_planner import WEEKDAYS

MACROS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")

DEFAULT_REMINDERS = {
    # key: (time, label)
    "breakfast": ("10:00", "Log breakfast"),
    "lunch": ("14:00", "Log lunch"),
    "dinner": ("20:30", "Log dinner"),
    "workout": ("17:00", "Workout reminder"),
    "weigh_in": ("08:00", "Morning weigh-in"),
    "evening_review": ("21:00", "Evening nutrition check"),
}
REMINDER_WINDOW = timedelta(hours=4)  # don't nag about things far in the past


# ---------------------------------------------------------------- singletons
def _get_or_create(db: Session, model, **defaults):
    """Fetch the single settings row, creating it once. Safe when two requests race on first use."""
    row = db.get(model, 1)
    if row is None:
        try:
            db.add(model(id=1, **defaults))
            db.commit()
        except IntegrityError:
            db.rollback()  # another request created it first; use theirs
        row = db.get(model, 1)
    return row


def get_profile(db: Session) -> Profile:
    return _get_or_create(db, Profile, allergies=[])


def get_goals(db: Session) -> Goals:
    return _get_or_create(db, Goals)


def get_reminders(db: Session) -> list[Reminder]:
    existing = {r.key: r for r in db.scalars(select(Reminder)).all()}
    missing = [k for k in DEFAULT_REMINDERS if k not in existing]
    if missing:
        for key in missing:
            # weigh-in defaults to Mondays only; everything else is off until the user opts in
            t = DEFAULT_REMINDERS[key][0]
            db.add(Reminder(key=key, enabled=False, time=t, days=[0] if key == "weigh_in" else list(range(7))))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # created concurrently by another request
        existing = {r.key: r for r in db.scalars(select(Reminder)).all()}
    return [existing[k] for k in DEFAULT_REMINDERS]


# ---------------------------------------------------------------- helpers
def _day_bounds(d: date):
    start = datetime.combine(d, time.min)
    return start, start + timedelta(days=1)


def targets_for(db: Session, day: date) -> nutrition.Targets:
    profile, goals = get_profile(db), get_goals(db)
    stats = db.get(DailyStats, day)
    active = stats.active_calories if stats and stats.active_calories is not None else None
    bmr = stats.bmr_calories if stats else None
    return nutrition.compute_targets(profile, active, bmr, today=day, goals=goals)


def intake_by_day(db: Session, start: date, end: date) -> dict[date, dict]:
    rows = db.execute(
        select(FoodEntry.day, *[func.sum(getattr(FoodEntry, m)) for m in MACROS], func.count(FoodEntry.id))
        .where(FoodEntry.day >= start, FoodEntry.day <= end).group_by(FoodEntry.day)
    ).all()
    return {r[0]: {**{m: float(v or 0) for m, v in zip(MACROS, r[1:6])}, "entries": r[6]} for r in rows}


def activities_between(db: Session, start: date, end: date) -> list[Activity]:
    return db.scalars(select(Activity).where(
        Activity.start_time >= _day_bounds(start)[0], Activity.start_time < _day_bounds(end)[1]
    ).order_by(Activity.start_time)).all()


def weights_between(db: Session, start: date, end: date) -> dict[date, float]:
    """One weight per day; manual entries win over Garmin scale entries."""
    out: dict[date, float] = {}
    rows = db.scalars(select(WeightEntry).where(WeightEntry.day >= start, WeightEntry.day <= end)
                      .order_by(WeightEntry.day)).all()
    for w in rows:
        if w.day not in out or w.source == "manual":
            out[w.day] = w.weight_kg
    return out


# ---------------------------------------------------------------- daily picture
def daily_series(db: Session, start: date, end: date) -> list[dict]:
    """Per-day combined picture: intake, targets, Garmin burn, net balance, steps, workouts, sleep, weight."""
    intake = intake_by_day(db, start, end)
    stats = {s.day: s for s in db.scalars(select(DailyStats).where(DailyStats.day >= start, DailyStats.day <= end)).all()}
    acts = defaultdict(list)
    for a in activities_between(db, start, end):
        acts[a.start_time.date()].append(a)
    weights = weights_between(db, start, end)

    out = []
    d = start
    while d <= end:
        i = intake.get(d)
        s = stats.get(d)
        t = targets_for(db, d)
        burned = s.total_calories if s and s.total_calories else None
        day_acts = acts.get(d, [])
        out.append({
            "day": d.isoformat(),
            "logged": bool(i),
            **{m: round(i[m]) if i else 0 for m in MACROS},
            "target_calories": round(t.calories),
            "target_protein_g": round(t.protein_g),
            "burned": round(burned) if burned else None,
            "net": round(i["calories"] - burned) if i and burned else None,
            "steps": s.steps if s else None,
            "resting_hr": s.resting_hr if s else None,
            "sleep_h": round(s.sleep_s / 3600, 1) if s and s.sleep_s else None,
            "intensity_minutes": s.intensity_minutes if s else None,
            "workouts": len(day_acts),
            "workout_minutes": round(sum(a.duration_s for a in day_acts) / 60),
            "weight_kg": weights.get(d),
        })
        d += timedelta(days=1)
    return out


def _avg(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_summaries(db: Session, weeks: int = 8, today: date | None = None) -> list[dict]:
    today = today or date.today()
    first = week_start(today) - timedelta(weeks=weeks - 1)
    days = daily_series(db, first, today)
    goals = get_goals(db)
    out = []
    for w in range(weeks):
        ws = first + timedelta(weeks=w)
        chunk = [d for d in days if ws.isoformat() <= d["day"] < (ws + timedelta(days=7)).isoformat()]
        logged = [d for d in chunk if d["logged"]]
        weights = [d["weight_kg"] for d in chunk if d["weight_kg"] is not None]
        active_min = sum((d["intensity_minutes"] or 0) for d in chunk) or sum(d["workout_minutes"] for d in chunk)
        on_target = sum(1 for d in logged if abs(d["calories"] - d["target_calories"]) <= 0.1 * d["target_calories"])
        out.append({
            "week_start": ws.isoformat(),
            "days_logged": len(logged),
            "avg_calories": _avg(d["calories"] for d in logged),
            "avg_target": _avg(d["target_calories"] for d in logged) or _avg(d["target_calories"] for d in chunk),
            "avg_protein_g": _avg(d["protein_g"] for d in logged),
            "avg_carbs_g": _avg(d["carbs_g"] for d in logged),
            "avg_fat_g": _avg(d["fat_g"] for d in logged),
            "avg_fiber_g": _avg(d["fiber_g"] for d in logged),
            "days_on_target": on_target,
            "protein_days_hit": sum(1 for d in logged if d["protein_g"] >= 0.9 * d["target_protein_g"]),
            "avg_burned": _avg(d["burned"] for d in chunk),
            "avg_net": _avg(d["net"] for d in chunk),
            "workouts": sum(d["workouts"] for d in chunk),
            "workouts_goal": goals.workouts_per_week,
            "active_minutes": active_min,
            "active_minutes_goal": goals.active_minutes_per_week,
            "avg_steps": _avg(d["steps"] for d in chunk),
            "avg_sleep_h": _avg(d["sleep_h"] for d in chunk),
            "weight_start": weights[0] if weights else None,
            "weight_end": weights[-1] if weights else None,
        })
    return out


# ---------------------------------------------------------------- goal progress
def goal_progress(db: Session, today: date) -> dict:
    goals = get_goals(db)
    ws = week_start(today)
    week = daily_series(db, ws, today)
    today_row = week[-1]
    workouts = sum(d["workouts"] for d in week)
    active = sum((d["intensity_minutes"] or 0) for d in week) or sum(d["workout_minutes"] for d in week)
    latest_w = db.scalar(select(WeightEntry).order_by(WeightEntry.day.desc()).limit(1))
    month_ago = db.scalar(select(WeightEntry).where(WeightEntry.day <= today - timedelta(days=28))
                          .order_by(WeightEntry.day.desc()).limit(1))
    return {
        "steps": {"value": today_row["steps"], "goal": goals.steps_target},
        "sleep_h": {"value": today_row["sleep_h"], "goal": goals.sleep_target_h},
        "workouts_week": {"value": workouts, "goal": goals.workouts_per_week},
        "active_minutes_week": {"value": active, "goal": goals.active_minutes_per_week},
        "weight": {
            "value": latest_w.weight_kg if latest_w else None,
            "goal": goals.target_weight_kg,
            "change_4w": round(latest_w.weight_kg - month_ago.weight_kg, 1) if latest_w and month_ago else None,
        },
        "days_left_in_week": 6 - today.weekday(),
    }


# ---------------------------------------------------------------- recommendations
def recommendations(db: Session, today: date | None = None) -> list[dict]:
    """Simple, rule-based coaching from the last 7 days of logs vs. goals."""
    today = today or date.today()
    profile, goals = get_profile(db), get_goals(db)
    last7 = daily_series(db, today - timedelta(days=6), today)
    past = [d for d in last7[:-1] if d["logged"]]  # completed days only; today is still in progress
    recs: list[dict] = []

    def add(level, title, detail):
        recs.append({"level": level, "title": title, "detail": detail})

    if len(past) < 4:
        add("info", "Log a few more days",
            f"You logged food on {len(past)} of the last 6 days. Trends get reliable after about 4–5 logged days a week.")
    if past:
        avg_cal = sum(d["calories"] for d in past) / len(past)
        avg_tgt = sum(d["target_calories"] for d in past) / len(past)
        diff = avg_cal - avg_tgt
        if profile.goal == "lose" and diff > 0.1 * avg_tgt:
            add("warn", "Calories above your weight-loss target",
                f"You've averaged {round(avg_cal)} kcal vs a {round(avg_tgt)} kcal target. Trimming ~{round(diff)} kcal a day "
                "(e.g. smaller portions of oils, sauces and snacks) gets you back on track.")
        elif profile.goal == "gain" and diff < -0.1 * avg_tgt:
            add("warn", "Not eating enough to gain",
                f"You've averaged {round(avg_cal)} kcal vs {round(avg_tgt)} kcal. Add a snack or a calorie-dense extra (nuts, olive oil, milk).")
        elif avg_cal < 0.75 * avg_tgt:
            add("warn", "Eating well under target",
                f"{round(avg_cal)} kcal a day on average is far below {round(avg_tgt)} kcal. Big deficits cost muscle and energy — "
                "or some foods aren't being logged.")
        elif abs(diff) <= 0.1 * avg_tgt:
            add("good", "Calories on target", f"Averaging {round(avg_cal)} kcal against {round(avg_tgt)} kcal. Nice consistency.")

        avg_pro = sum(d["protein_g"] for d in past) / len(past)
        pro_tgt = sum(d["target_protein_g"] for d in past) / len(past)
        if avg_pro < 0.9 * pro_tgt:
            add("warn", "Protein is low",
                f"Averaging {round(avg_pro)} g vs {round(pro_tgt)} g. Add a protein source to each meal — "
                "Greek yogurt, eggs, chicken, tofu, lentils or a shake.")
        else:
            add("good", "Protein target met", f"Averaging {round(avg_pro)} g a day.")

        avg_fib = sum(d["fiber_g"] for d in past) / len(past)
        if goals.fiber_target_g and avg_fib < 0.7 * goals.fiber_target_g and avg_fib > 0:
            add("info", "More fibre", f"Averaging {round(avg_fib)} g vs {round(goals.fiber_target_g)} g. "
                "Beans, lentils, berries, oats and vegetables help.")

    gp = goal_progress(db, today)
    w, wg = gp["workouts_week"]["value"], gp["workouts_week"]["goal"]
    if wg:
        remaining = wg - w
        if remaining <= 0:
            add("good", "Weekly workout goal reached", f"{w} of {wg} workouts done this week.")
        elif remaining > gp["days_left_in_week"] + 1:
            add("warn", "Workout goal at risk",
                f"{w} of {wg} workouts done with {gp['days_left_in_week'] + 1} days left (including today). Short sessions count.")
        else:
            nxt = _next_planned_session(db, today)
            detail = f"{w} of {wg} done this week."
            if nxt:
                detail += f" Next up: {nxt['title']} ({nxt['weekday']})."
            add("info", f"{remaining} workout{'s' if remaining > 1 else ''} to go this week", detail)

    steps = [d["steps"] for d in last7[:-1] if d["steps"] is not None]
    if steps and goals.steps_target:
        avg_steps = sum(steps) / len(steps)
        if avg_steps < 0.8 * goals.steps_target:
            add("info", "Move a bit more",
                f"Steps averaged {round(avg_steps):,} vs a {goals.steps_target:,} goal. A 20-minute walk adds ~2,000 steps.")
    sleeps = [d["sleep_h"] for d in last7 if d["sleep_h"] is not None]
    if sleeps and goals.sleep_target_h and sum(sleeps) / len(sleeps) < goals.sleep_target_h - 0.5:
        add("info", "Sleep is short",
            f"Averaging {sum(sleeps) / len(sleeps):.1f} h vs {goals.sleep_target_h:g} h. Poor sleep raises appetite and slows recovery.")

    weights = weights_between(db, today - timedelta(days=21), today)
    if len(weights) >= 2:
        vals = list(weights.values())
        change = vals[-1] - vals[0]
        if profile.goal == "lose" and change > 0.5:
            add("warn", "Weight is trending up",
                f"+{change:.1f} kg over 3 weeks. If logs say you're on target, some foods may be under-counted — try weighing portions for a few days.")
        elif profile.goal == "gain" and change < -0.3:
            add("warn", "Weight is trending down", f"{change:.1f} kg over 3 weeks while aiming to gain. Add ~200 kcal a day.")

    order = {"warn": 0, "info": 1, "good": 2}
    recs.sort(key=lambda r: order[r["level"]])
    return recs


def _next_planned_session(db: Session, today: date):
    plan = db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))
    if not plan:
        return None
    for offset in range(0, 7 - today.weekday()):
        wd = WEEKDAYS[(today.weekday() + offset) % 7]
        if offset == 0 and activities_between(db, today, today):
            continue
        session = next((d for d in plan.days if d.get("weekday") == wd and d.get("type") != "rest"), None)
        if session:
            return session
    return None


def upcoming_session(db: Session, day: date) -> dict | None:
    """The next planned session after ``day`` (looks up to a week ahead, wrapping into next week)."""
    plan = db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))
    if not plan:
        return None
    for offset in range(1, 8):
        d = day + timedelta(days=offset)
        session = next((x for x in plan.days if x.get("weekday") == WEEKDAYS[d.weekday()] and x.get("type") != "rest"), None)
        if session:
            return {**session, "date": d.isoformat(), "in_days": offset}
    return None


def todays_session(db: Session, day: date):
    plan = db.scalar(select(WorkoutPlan).where(WorkoutPlan.active).order_by(WorkoutPlan.created_at.desc()))
    if not plan:
        return None, None
    wd = WEEKDAYS[day.weekday()]
    session = next((d for d in plan.days if d.get("weekday") == wd), {"weekday": wd, "type": "rest", "title": "Rest day"})
    return plan, session


# ---------------------------------------------------------------- reminders
def due_reminders(db: Session, now: datetime) -> list[dict]:
    """Reminders whose time has passed today, whose condition still holds, and that weren't shown yet."""
    today = now.date()
    shown = set(db.scalars(select(ReminderLog.key).where(ReminderLog.day == today)).all())
    out = []
    for r in get_reminders(db):
        if not r.enabled or r.key in shown or today.weekday() not in (r.days or []):
            continue
        hh, mm = map(int, r.time.split(":"))
        at = datetime.combine(today, time(hh, mm))
        if not (at <= now <= at + REMINDER_WINDOW):
            continue
        msg = _reminder_message(db, r.key, today)
        if msg:
            out.append({"key": r.key, **msg})
    return out


def _reminder_message(db: Session, key: str, today: date) -> dict | None:
    if key in ("breakfast", "lunch", "dinner"):
        logged = db.scalar(select(func.count(FoodEntry.id)).where(FoodEntry.day == today, FoodEntry.meal == key))
        if logged:
            return None
        return {"title": f"Log your {key}", "body": "Snap a photo or describe it in the calorie counter — it takes 10 seconds."}
    if key == "weigh_in":
        if db.scalar(select(func.count(WeightEntry.id)).where(WeightEntry.day == today)):
            return None
        return {"title": "Time to weigh in", "body": "Weigh yourself before breakfast for the most consistent trend."}
    if key == "workout":
        if activities_between(db, today, today):
            return None
        _, session = todays_session(db, today)
        if not session or session.get("type") == "rest":
            return None
        detail = (f"{session['minutes']} min in {session['zone']}" if session.get("type") == "cardio"
                  else f"{len(session.get('exercises', []))} exercises")
        return {"title": f"Today's workout: {session['title']}", "body": detail}
    if key == "evening_review":
        t = targets_for(db, today)
        i = intake_by_day(db, today, today).get(today)
        if not i:
            return {"title": "Nothing logged today", "body": "Add today's meals so your weekly trends stay accurate."}
        cal_left, pro_left = t.calories - i["calories"], t.protein_g - i["protein_g"]
        parts = []
        if cal_left > 150:
            parts.append(f"{round(cal_left)} kcal left")
        elif cal_left < -150:
            parts.append(f"{round(-cal_left)} kcal over target")
        else:
            parts.append("calories on target")
        if pro_left > 15:
            parts.append(f"{round(pro_left)} g protein to go — a shake or yogurt would close the gap")
        return {"title": "Evening check-in", "body": "; ".join(parts).capitalize() + "."}
    return None


def ack_reminders(db: Session, day: date, keys: list[str]):
    for k in keys:
        if not db.get(ReminderLog, (day, k)):
            db.add(ReminderLog(day=day, key=k))
    db.commit()


# ---------------------------------------------------------------- exercise progress
def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def exercise_index(db: Session) -> list[dict]:
    """All exercises that appear in logged sets, most frequent first."""
    counts: dict[str, dict] = {}
    for a in db.scalars(select(Activity)).all():
        for s in a.sets or []:
            name = (s.get("exercise") or "").strip()
            if not name:
                continue
            e = counts.setdefault(_norm(name), {"name": name, "sets": 0, "sessions": set()})
            e["sets"] += 1
            e["sessions"].add(a.id)
    rows = [{"name": v["name"], "sets": v["sets"], "sessions": len(v["sessions"])} for v in counts.values()]
    return sorted(rows, key=lambda r: (-r["sessions"], r["name"]))


def exercise_progress(db: Session, name: str) -> list[dict]:
    """Per session: heaviest set, best estimated 1RM (Epley) and total volume for one exercise."""
    key = _norm(name)
    out = []
    for a in db.scalars(select(Activity).order_by(Activity.start_time)).all():
        sets = [s for s in (a.sets or []) if _norm(s.get("exercise") or "") == key]
        if not sets:
            continue
        weights = [s.get("weight_kg") or 0 for s in sets]
        e1rm = [(s.get("weight_kg") or 0) * (1 + (s.get("reps") or 0) / 30) for s in sets if s.get("reps")]
        out.append({
            "day": a.start_time.date().isoformat(),
            "sets": len(sets),
            "reps": sum(s.get("reps") or 0 for s in sets),
            "top_weight_kg": max(weights),
            "est_1rm_kg": round(max(e1rm), 1) if e1rm else None,
            "volume_kg": round(sum((s.get("weight_kg") or 0) * (s.get("reps") or 0) for s in sets)),
        })
    return out
