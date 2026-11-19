import os
from pathlib import Path

from contextvars import ContextVar

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(os.getenv("HEALTH_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        if os.getenv("REQUIRE_DATABASE_URL"):
            # Hosted on a server without a persistent disk: a local SQLite file would be wiped on restart.
            raise RuntimeError("DATABASE_URL is not set. Add your database connection string in the host's settings.")
        return f"sqlite:///{DATA_DIR / 'health.db'}"
    # Hosted Postgres (Neon, Supabase, Render...) hands out postgres:// URLs; use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _database_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    # Postgres: no server-side prepared statements, so pooled endpoints (e.g. Neon "-pooler" / PgBouncer) work too.
    connect_args={"check_same_thread": False} if IS_SQLITE else {"prepare_threshold": None},
    pool_pre_ping=not IS_SQLITE,  # free hosted databases close idle connections
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---- several people in one app: each profile gets its own private copy of every table.
# Profile 1 (the original user) keeps the default tables; profile N lives in Postgres schema "uN"
# (or, on SQLite, its own file health_uN.db). No query has to know about it.
USER_COOKIE = "ht_user"
current_user: ContextVar[int] = ContextVar("current_user", default=1)
_engines: dict[int, object] = {}


def engine_for(uid: int):
    if uid == 1:
        return engine
    if uid not in _engines:
        if IS_SQLITE:
            _engines[uid] = create_engine(f"sqlite:///{DATA_DIR / f'health_u{uid}.db'}",
                                          connect_args={"check_same_thread": False})
        else:
            _engines[uid] = engine.execution_options(schema_translate_map={None: f"u{uid}"})
    return _engines[uid]


def session_for(uid: int):
    return sessionmaker(bind=engine_for(uid), autoflush=False, expire_on_commit=False)()


def create_user_tables(uid: int):
    from sqlalchemy import text
    from app import models  # noqa: F401

    if uid == 1:
        return
    if not IS_SQLITE:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "u{uid}"'))
    eng = engine_for(uid)
    tables = [t for t in Base.metadata.sorted_tables if t.name != "app_users"]
    with eng.begin() as conn:
        Base.metadata.create_all(conn, tables=tables)
    _add_missing_columns(eng, None if IS_SQLITE else f"u{uid}")


def request_user(request: Request) -> int:
    from app.models import AppUser

    raw = request.cookies.get(USER_COOKIE, "1")
    uid = int(raw) if raw.isdigit() else 1
    if uid != 1:
        with SessionLocal() as db:
            if db.get(AppUser, uid) is None:
                uid = 1
    return uid


def get_db(request: Request):
    uid = request_user(request)
    current_user.set(uid)
    db = session_for(uid)
    try:
        yield db
    finally:
        db.close()


def _add_missing_columns(eng=None, schema=None):
    """Tiny forward-only migration: add columns introduced after a table was created."""
    from sqlalchemy import inspect, text

    eng = eng or engine
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name, schema=schema):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name, schema=schema)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE {schema + "." if schema else ""}"{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                default = col.default.arg if col.default is not None and col.default.is_scalar else None
                if isinstance(default, bool):
                    ddl += " DEFAULT TRUE" if default else " DEFAULT FALSE"
                elif isinstance(default, (int, float)):
                    ddl += f" DEFAULT {default}"
                elif isinstance(default, str):
                    ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                conn.execute(text(ddl))


def init_db():
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _add_missing_columns()
    from sqlalchemy import select

    with SessionLocal() as db:
        for u in db.scalars(select(models.AppUser)).all():
            if u.id != 1:
                create_user_tables(u.id)
