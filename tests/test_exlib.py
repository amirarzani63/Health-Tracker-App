"""The photo-library loader and name matching, using a small archive in the free-exercise-db layout."""
import io
import json
import tarfile
import importlib.util
from pathlib import Path

import pytest

from app.services import exlib

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = [
    {"id": "Bent_Over_Two-Dumbbell_Row", "name": "Bent Over Two-Dumbbell Row", "primaryMuscles": ["middle back"],
     "secondaryMuscles": ["biceps", "lats", "shoulders"], "instructions": ["Hinge forward.", "Row the weights."],
     "equipment": "dumbbell", "category": "strength", "images": ["Bent_Over_Two-Dumbbell_Row/0.jpg", "Bent_Over_Two-Dumbbell_Row/1.jpg"]},
    {"id": "Pushups", "name": "Pushups", "primaryMuscles": ["chest"], "secondaryMuscles": ["shoulders", "triceps"],
     "instructions": ["Lower.", "Push."], "equipment": "body only", "category": "strength", "images": ["Pushups/0.jpg", "Pushups/1.jpg"]},
    {"id": "Goblet_Squat", "name": "Goblet Squat", "primaryMuscles": ["quadriceps"], "secondaryMuscles": ["glutes"],
     "instructions": ["Squat."], "equipment": "kettlebells", "category": "strength", "images": ["Goblet_Squat/0.jpg", "Goblet_Squat/1.jpg"]},
    {"id": "Dumbbell_Bicep_Curl", "name": "Dumbbell Bicep Curl", "primaryMuscles": ["biceps"], "secondaryMuscles": ["forearms"],
     "instructions": ["Curl."], "equipment": "dumbbell", "category": "strength", "images": ["Dumbbell_Bicep_Curl/0.jpg"]},
]


def make_archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name, data):
            info = tarfile.TarInfo("free-exercise-db-main/" + name); info.size = len(data); tar.addfile(info, io.BytesIO(data))
        add("dist/exercises.json", json.dumps(SAMPLE).encode())
        add("LICENSE", b"Unlicense")
        for e in SAMPLE:
            for img in e["images"]:
                add("exercises/" + img, b"\xff\xd8fakejpg")
        add("exercises/../evil.jpg", b"x")
    return buf.getvalue()


@pytest.fixture
def lib(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fetch", ROOT / "scripts" / "fetch_exercise_library.py")
    fetch = importlib.util.module_from_spec(spec); spec.loader.exec_module(fetch)
    dest = tmp_path / "exlib"
    assert fetch.extract(make_archive(), dest) == 7
    assert not (tmp_path / "evil.jpg").exists()
    monkeypatch.setattr(exlib, "DIR", dest)
    exlib.library.cache_clear(); exlib.match.cache_clear()
    yield
    exlib.library.cache_clear(); exlib.match.cache_clear()


@pytest.mark.parametrize("name,expected", [
    ("Bent-over Row with Dumbbell", "Bent Over Two-Dumbbell Row"),
    ("Push Up", "Pushups"),
    ("Goblet Squat", "Goblet Squat"),
    ("Dumbbell Curl", "Dumbbell Bicep Curl"),
])
def test_matches(lib, name, expected):
    m = exlib.match(name)
    assert m and m["name"] == expected and m["images"][0].startswith("/static/exlib/img/")


def test_muscles_and_endpoint(lib, client):
    m = exlib.match("Bent-over Row with Dumbbell")
    assert m["primary"] == ["upper_back"] and "lats" in m["secondary"] and "front_delts" in m["secondary"]
    assert exlib.match("zzqx blorp") is None
    r = client.post("/api/exlib/match", json={"names": ["Push Up"]}).json()
    assert r["available"] and r["items"]["Push Up"]["primary"] == ["chest"]
