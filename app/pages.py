"""Serve the HTML pages with cache-busting asset URLs.

Phones (especially iPhone home-screen apps) cache CSS/JS/images aggressively. Every
asset URL gets ``?v=<version>`` (the deployed git commit on Render, else a hash of
the static files), and the HTML itself is sent with ``Cache-Control: no-cache``, so
a new deploy is picked up on the next open.
"""

import hashlib
import os
import re
from functools import lru_cache

from fastapi.responses import HTMLResponse

from app.paths import STATIC

ASSET = re.compile(r'((?:src|href)=")(/static/[^"?#]+)(")')


@lru_cache(maxsize=1)
def app_version() -> str:
    commit = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT")
    if commit:
        return commit[:8]
    h = hashlib.sha1()
    for p in sorted(STATIC.rglob("*")):
        if p.is_file():
            h.update(p.name.encode())
            h.update(str(p.stat().st_mtime_ns).encode())
    return h.hexdigest()[:8]


@lru_cache(maxsize=8)
def _render(name: str, version: str) -> str:
    html = (STATIC / name).read_text(encoding="utf-8")
    html = ASSET.sub(lambda m: f"{m.group(1)}{m.group(2)}?v={version}{m.group(3)}", html)
    return html.replace("{{APP_VERSION}}", version)


def page(name: str) -> HTMLResponse:
    return HTMLResponse(_render(name, app_version()), headers={"Cache-Control": "no-cache"})
