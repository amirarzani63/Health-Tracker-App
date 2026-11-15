from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Sex = Literal["male", "female"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
Goal = Literal["lose", "maintain", "gain"]
DietType = Literal["omnivore", "vegetarian", "vegan", "pescatarian"]
Meal = Literal["breakfast", "lunch", "dinner", "snack"]
Experience = Literal["beginner", "intermediate", "advanced"]
Equipment = Literal["gym", "home", "bodyweight"]
PlanGoal = Literal["strength", "hypertrophy", "fat_loss", "endurance", "general"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProfileIn(BaseModel):
    name: str = ""
    sex: Sex = "male"
    birth_year: int = Field(1990, ge=1900, le=2100)
    height_cm: float = Field(175, gt=50, lt=260)
    weight_kg: float = Field(75, gt=20, lt=400)
    activity_level: ActivityLevel = "moderate"
    goal: Goal = "maintain"
    diet_type: DietType = "omnivore"
    allergies: list[str] = []
    experience: Experience = "intermediate"
    training_days: int = Field(4, ge=1, le=7)
    equipment: Equipment = "gym"


class ProfileOut(ProfileIn, ORM):
    setup_done: bool = False


class WeightIn(BaseModel):
    day: date
    weight_kg: float = Field(gt=20, lt=400)
    body_fat_pct: float | None = Field(None, ge=1, le=75)


class WeightOut(WeightIn, ORM):
    id: int
    source: str


class FoodIn(BaseModel):
    day: date
    meal: Meal = "snack"
    name: str = Field(min_length=1, max_length=200)
    servings: float = Field(1, gt=0, le=50)
    calories: float = Field(ge=0)
    protein_g: float = Field(0, ge=0)
    carbs_g: float = Field(0, ge=0)
    fat_g: float = Field(0, ge=0)
    fiber_g: float = Field(0, ge=0)


class FoodOut(FoodIn, ORM):
    id: int


class SetIn(BaseModel):
    exercise: str
    reps: int | None = None
    weight_kg: float | None = None


class ActivityIn(BaseModel):
    start_time: datetime
    activity_type: str = "other"
    name: str = ""
    duration_s: float = Field(ge=0)
    distance_m: float | None = None
    calories: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    notes: str = ""
    sets: list[SetIn] = []


class ActivityOut(ORM):
    id: int
    source: str
    external_id: str | None
    start_time: datetime
    activity_type: str
    name: str
    duration_s: float
    distance_m: float | None
    calories: float | None
    avg_hr: float | None
    max_hr: float | None
    elevation_gain_m: float | None
    aerobic_te: float | None
    anaerobic_te: float | None
    training_load: float | None
    notes: str
    sets: list


class DailyStatsOut(ORM):
    day: date
    steps: int | None
    total_calories: float | None
    active_calories: float | None
    bmr_calories: float | None
    resting_hr: int | None
    avg_stress: int | None
    body_battery_high: int | None
    body_battery_low: int | None
    sleep_s: int | None
    sleep_score: int | None
    intensity_minutes: int | None
    min_hr: int | None = None
    max_hr: int | None = None


class PlanRequest(BaseModel):
    goal: PlanGoal = "general"
    days_per_week: int | None = Field(None, ge=2, le=6)
    weeks: int = Field(4, ge=1, le=16)
    equipment: Equipment | None = None
    experience: Experience | None = None
    include_cardio: bool = True


class PlanOut(ORM):
    id: int
    name: str
    goal: str
    weeks: int
    days: list
    progression: list
    active: bool
    created_at: datetime


class GarminLoginIn(BaseModel):
    email: str
    password: str


class GarminMfaIn(BaseModel):
    code: str = Field(min_length=4, max_length=10)


class GarminSyncIn(BaseModel):
    days: int = Field(7, ge=1, le=365)


class GoalsIn(BaseModel):
    calorie_target: float | None = Field(None, ge=800, le=8000)
    protein_target_g: float | None = Field(None, ge=0, le=500)
    carbs_target_g: float | None = Field(None, ge=0, le=1000)
    fat_target_g: float | None = Field(None, ge=0, le=400)
    fiber_target_g: float = Field(30, ge=0, le=100)
    steps_target: int = Field(10000, ge=0, le=100000)
    sleep_target_h: float = Field(7.5, ge=3, le=14)
    workouts_per_week: int = Field(4, ge=0, le=14)
    active_minutes_per_week: int = Field(150, ge=0, le=3000)
    target_weight_kg: float | None = Field(None, gt=20, lt=400)


class GoalsOut(GoalsIn, ORM):
    saved: bool = False


ReminderKey = Literal["breakfast", "lunch", "dinner", "workout", "weigh_in", "evening_review"]


class ReminderIn(BaseModel):
    key: ReminderKey
    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: list[int] = Field(default_factory=lambda: list(range(7)))


class ReminderOut(ReminderIn, ORM):
    pass
