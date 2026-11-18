import pytest

from app.services import exlib

pytestmark = pytest.mark.skipif(not exlib.available(), reason="exercise library not downloaded")


@pytest.mark.parametrize("name,expected", [
    ("Bent-over Row with Dumbbell", "Bent-Over Dumbbell Row"),
    ("Dumbbell Curl", "Dumbbell Bicep Curl"),
    ("Incline Dumbbell Bench Press", "Incline Dumbbell Press"),
    ("Mountain Climber", "Mountain Climbers"),
    ("Goblet Squat", "Goblet Squat"),
])
def test_matches(name, expected):
    m = exlib.match(name)
    assert m and m["name"] == expected and m["images"]


def test_unknown_and_endpoint(client):
    assert exlib.match("zzqx blorp") is None
    r = client.post("/api/exlib/match", json={"names": ["Push Up"]}).json()
    assert r["available"] and r["items"]["Push Up"]["primary"]
