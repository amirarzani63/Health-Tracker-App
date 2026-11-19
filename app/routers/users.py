"""Several people, one app: pick who you are, add someone, rename or remove a person."""

from datetime import date

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import auth
from app.db import USER_COOKIE, SessionLocal, create_user_tables, request_user, session_for
from app.models import AppUser, WeightEntry
from app.services import insights

router = APIRouter(prefix="/api/users", tags=["users"])
COLORS = ["#ff8a3d", "#3dbbff", "#39d98a", "#ff5c8a", "#b28cff", "#ffd23d"]


def _ensure_first(db) -> None:
    """The original user is profile 1 (their data never moves)."""
    if db.get(AppUser, 1) is None:
        with session_for(1) as udb:
            name = (insights.get_profile(udb).name or "").strip() or "Me"
        db.add(AppUser(id=1, name=name, color=COLORS[0]))
        db.commit()


def _out(u: AppUser, current: int) -> dict:
    return {"id": u.id, "name": u.name, "color": u.color, "current": u.id == current}


@router.get("")
def list_users(request: Request):
    cur = request_user(request)
    with SessionLocal() as db:
        _ensure_first(db)
        users = db.scalars(select(AppUser).order_by(AppUser.id)).all()
        return {"users": [_out(u, cur) for u in users], "current": cur,
                "chosen": USER_COOKIE in request.cookies}


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    sex: str = Field("male", pattern="^(male|female)$")
    birth_year: int = Field(ge=1920, le=2020)
    height_cm: float = Field(ge=100, le=250)
    weight_kg: float = Field(ge=30, le=350)
    target_weight_kg: float | None = Field(None, ge=30, le=350)
    focus: str = "stay_healthy"   # lose_weight | build_muscle | get_stronger | improve_cardio | stay_healthy
    equipment: str = "gym"        # gym | home | bodyweight
    diet_type: str = "omnivore"
    experience: str = Field("beginner", pattern="^(beginner|intermediate|advanced)$")


def _select(response: Response, request: Request, uid: int):
    response.set_cookie(USER_COOKIE, str(uid), max_age=auth.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=auth.is_https(request))


@router.post("")
def add_user(data: NewUser, request: Request, response: Response):
    from app.services.autosetup import run_auto_setup

    with SessionLocal() as db:
        _ensure_first(db)
        n = len(db.scalars(select(AppUser)).all())
        u = AppUser(name=data.name.strip(), color=COLORS[n % len(COLORS)])
        db.add(u)
        db.commit()
        uid = u.id
    create_user_tables(uid)
    with session_for(uid) as udb:  # their own profile, targets and plan, built from their answers
        p = insights.get_profile(udb)
        p.name, p.sex, p.birth_year = data.name.strip(), data.sex, data.birth_year
        p.height_cm, p.weight_kg, p.setup_done = data.height_cm, data.weight_kg, True
        udb.add(WeightEntry(day=date.today(), weight_kg=data.weight_kg, source="manual"))
        udb.commit()
        result = run_auto_setup(udb, None, data.focus, data.equipment, data.diet_type)
        p, g = insights.get_profile(udb), insights.get_goals(udb)
        p.experience = data.experience
        if data.target_weight_kg:
            g.target_weight_kg = data.target_weight_kg
        udb.commit()
    _select(response, request, uid)
    return {"id": uid, "name": data.name.strip(), "summary": result.get("summary", [])}


class Pick(BaseModel):
    id: int


@router.post("/select")
def select_user(data: Pick, request: Request, response: Response):
    with SessionLocal() as db:
        _ensure_first(db)
        u = db.get(AppUser, data.id)
        if u is None:
            raise HTTPException(404, "That person isn't in the app.")
        _select(response, request, u.id)
        return {"id": u.id, "name": u.name}


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.put("/{uid}")
def rename_user(uid: int, data: Rename):
    with SessionLocal() as db:
        _ensure_first(db)
        u = db.get(AppUser, uid)
        if u is None:
            raise HTTPException(404, "That person isn't in the app.")
        u.name = data.name.strip()
        db.commit()
        return {"id": u.id, "name": u.name}
