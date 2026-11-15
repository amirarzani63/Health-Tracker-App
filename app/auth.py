"""Single-user password login for hosting the app on the internet.

Enabled when the ``APP_PASSWORD`` environment variable is set; without it the
app is open (fine on your own computer or home network). Sessions are an
HMAC-signed, HttpOnly cookie, so no server-side session store is needed.
Changing ``APP_PASSWORD`` (or ``SECRET_KEY``) signs everyone out.
"""

import hashlib
import hmac
import os
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.paths import STATIC

COOKIE = "ht_session"
SESSION_DAYS = 90  # phone home-screen apps shouldn't make you log in often
PUBLIC_PATHS = {
    "/login", "/api/auth/login", "/api/auth/status", "/healthz",
    "/static/styles.css", "/static/manifest.json", "/static/icon.svg",
    "/static/apple-touch-icon.png", "/static/icon-192.png", "/static/icon-512.png",
}

router = APIRouter(tags=["auth"])


def password() -> str:
    return os.getenv("APP_PASSWORD", "")


def enabled() -> bool:
    return bool(password())


def _secret() -> bytes:
    key = os.getenv("SECRET_KEY") or ("health-tracker:" + password())
    return hashlib.sha256(key.encode()).digest()


def make_token(now: float | None = None) -> str:
    expires = int((now or time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def valid_token(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, sig = token.split(".", 1)
    if not expires.isdigit() or int(expires) < (now or time.time()):
        return False
    expected = hmac.new(_secret(), expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


# --- brute-force protection: exponential lock-out per client after repeated failures
_failures: dict[str, tuple[int, float]] = {}


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _locked_for(client: str) -> float:
    count, last = _failures.get(client, (0, 0.0))
    if count < 5:
        return 0
    wait = min(300, 2 ** (count - 5))
    return max(0.0, last + wait - time.time())


async def auth_middleware(request: Request, call_next):
    if not enabled() or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if valid_token(request.cookies.get(COOKIE)):
        return await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path in ("/docs", "/openapi.json", "/redoc"):
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


class LoginIn(BaseModel):
    password: str


@router.get("/login", include_in_schema=False)
def login_page(request: Request):
    if not enabled() or valid_token(request.cookies.get(COOKIE)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "login.html")


@router.get("/api/auth/status")
def auth_status(request: Request):
    return {"enabled": enabled(), "signed_in": not enabled() or valid_token(request.cookies.get(COOKIE))}


@router.post("/api/auth/login")
def login(data: LoginIn, request: Request, response: Response):
    if not enabled():
        return {"ok": True}
    client = _client(request)
    wait = _locked_for(client)
    if wait > 0:
        raise HTTPException(429, f"Too many attempts. Try again in {int(wait) + 1} seconds.")
    if not hmac.compare_digest(data.password.encode(), password().encode()):
        count, _ = _failures.get(client, (0, 0.0))
        _failures[client] = (count + 1, time.time())
        raise HTTPException(401, "Wrong password")
    _failures.pop(client, None)
    response.set_cookie(COOKIE, make_token(), max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=is_https(request), samesite="lax", path="/")
    return {"ok": True}


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
