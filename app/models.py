from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Profile(Base):
    """Single-user profile used for calorie targets and plan generation."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    sex: Mapped[str] = mapped_column(String(10), default="male")  # male | female
    birth_year: Mapped[int] = mapped_column(Integer, default=1990)
    height_cm: Mapped[float] = mapped_column(Float, default=175)
    weight_kg: Mapped[float] = mapped_column(Float, default=75)
    activity_level: Mapped[str] = mapped_column(String(20), default="moderate")
    goal: Mapped[str] = mapped_column(String(20), default="maintain")  # lose | maintain | gain
    diet_type: Mapped[str] = mapped_column(String(20), default="omnivore")  # omnivore | vegetarian | vegan | pescatarian
    allergies: Mapped[list] = mapped_column(JSON, default=list)
    experience: Mapped[str] = mapped_column(String(20), default="intermediate")
    training_days: Mapped[int] = mapped_column(Integer, default=4)
    equipment: Mapped[str] = mapped_column(String(20), default="gym")  # gym | home | bodyweight
    setup_done: Mapped[bool] = mapped_column(Boolean, default=False)


class WeightEntry(Base):
    __tablename__ = "weight_entries"
    __table_args__ = (UniqueConstraint("day", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")


class FoodEntry(Base):
    __tablename__ = "food_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    meal: Mapped[str] = mapped_column(String(20), default="snack")  # breakfast | lunch | dinner | snack
    name: Mapped[str] = mapped_column(String(200))
    servings: Mapped[float] = mapped_column(Float, default=1)
    calories: Mapped[float] = mapped_column(Float, default=0)  # per entry (already multiplied)
    protein_g: Mapped[float] = mapped_column(Float, default=0)
    carbs_g: Mapped[float] = mapped_column(Float, default=0)
    fat_g: Mapped[float] = mapped_column(Float, default=0)
    fiber_g: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Activity(Base):
    """An exercise session, logged manually or imported from Garmin Connect."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | garmin
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    activity_type: Mapped[str] = mapped_column(String(50), default="other")
    name: Mapped[str] = mapped_column(String(200), default="")
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    aerobic_te: Mapped[float | None] = mapped_column(Float, nullable=True)
    anaerobic_te: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(String(2000), default="")
    sets: Mapped[list] = mapped_column(JSON, default=list)  # [{exercise, reps, weight_kg}]


class DailyStats(Base):
    """Daily wellness summary pulled from Garmin (steps, RHR, sleep, etc.)."""

    __tablename__ = "daily_stats"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr_calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_high: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_low: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intensity_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(String(30))
    weeks: Mapped[int] = mapped_column(Integer, default=4)
    days: Mapped[list] = mapped_column(JSON, default=list)
    progression: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StoredSecret(Base):
    """Small private blobs that must survive restarts, e.g. Garmin session tokens."""

    __tablename__ = "stored_secrets"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class SyncState(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000), default="")


class Goals(Base):
    """Daily and weekly targets. Nullable nutrition targets mean "calculate automatically"."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    calorie_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_target_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_target_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_target_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_target_g: Mapped[float] = mapped_column(Float, default=30)
    steps_target: Mapped[int] = mapped_column(Integer, default=10000)
    sleep_target_h: Mapped[float] = mapped_column(Float, default=7.5)
    workouts_per_week: Mapped[int] = mapped_column(Integer, default=4)
    active_minutes_per_week: Mapped[int] = mapped_column(Integer, default=150)
    target_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    # When true, step / intensity-minute / sleep goals keep following your Garmin settings.
    follow_garmin: Mapped[bool] = mapped_column(Boolean, default=True)


class Reminder(Base):
    __tablename__ = "reminders"

    key: Mapped[str] = mapped_column(String(30), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    time: Mapped[str] = mapped_column(String(5), default="12:00")  # HH:MM local time
    days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4, 5, 6])  # 0 = Monday


class ReminderLog(Base):
    """Which reminders were already shown on a given day (so each fires once)."""

    __tablename__ = "reminder_log"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    key: Mapped[str] = mapped_column(String(30), primary_key=True)
