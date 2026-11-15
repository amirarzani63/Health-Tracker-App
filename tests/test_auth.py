import time

import pytest

from app import auth


@pytest.fixture()
def locked(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "correct horse")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    auth._failures.clear()
    yield client
    auth._failures.clear()


def test_open_without_password(client, monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert client.get("/api/profile").status_code == 200
    assert client.get("/api/auth/status").json() == {"enabled": False, "signed_in": True}


def test_everything_locked_until_login(locked):
    c = locked
    assert c.get("/api/profile").status_code == 401
    assert c.get("/docs").status_code == 401
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    # public bits needed for the login page and home-screen install
    for path in ("/login", "/healthz", "/static/styles.css", "/static/manifest.json", "/static/apple-touch-icon.png"):
        assert c.get(path).status_code == 200, path
    assert c.get("/static/app.js", follow_redirects=False).status_code == 303  # app code stays private

    assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"password": "correct horse"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=7776000" in cookie
    assert c.get("/api/profile").status_code == 200
    assert c.get("/api/auth/status").json()["signed_in"] is True

    c.post("/api/auth/logout")
    assert c.get("/api/profile").status_code == 401


def test_secure_cookie_behind_https_proxy(locked):
    r = locked.post("/api/auth/login", json={"password": "correct horse"}, headers={"x-forwarded-proto": "https"})
    assert "Secure" in r.headers["set-cookie"]


def test_lockout_after_repeated_failures(locked):
    for _ in range(5):
        assert locked.post("/api/auth/login", json={"password": "x"}).status_code == 401
    assert locked.post("/api/auth/login", json={"password": "x"}).status_code == 429
    # even the right password is refused during the lock-out
    assert locked.post("/api/auth/login", json={"password": "correct horse"}).status_code == 429


def test_tokens(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw1")
    t = auth.make_token()
    assert auth.valid_token(t)
    assert not auth.valid_token(t[:-1] + ("0" if t[-1] != "0" else "1"))
    assert not auth.valid_token("garbage") and not auth.valid_token(None)
    assert not auth.valid_token(t, now=time.time() + 91 * 86400)  # expired
    monkeypatch.setenv("APP_PASSWORD", "pw2")
    assert not auth.valid_token(t)  # changing the password signs everyone out


def test_pages_are_cache_busted(client, monkeypatch):
    import re

    from app import pages

    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef1234567")
    pages.app_version.cache_clear()
    pages._render.cache_clear()
    try:
        r = client.get("/")
        assert r.headers["cache-control"] == "no-cache"
        refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', r.text)
        assert refs and all(ref.endswith("?v=abcdef12") for ref in refs)
        assert "App version abcdef12" in r.text and "{{APP_VERSION}}" not in r.text
        assert client.get("/static/styles.css?v=abcdef12").status_code == 200
    finally:
        pages.app_version.cache_clear()
        pages._render.cache_clear()
