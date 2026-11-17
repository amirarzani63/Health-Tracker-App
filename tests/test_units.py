from types import SimpleNamespace

from app import units
from app.services.food_ai import parse_item

METRIC, IMPERIAL = SimpleNamespace(units="metric"), SimpleNamespace(units="imperial")


def test_mass_and_length():
    assert units.mass(105, METRIC) == "105.0 kg"
    assert units.mass(105, IMPERIAL) == "231.5 lb"
    assert units.mass(-1, IMPERIAL, signed=True) == "-2.2 lb"
    assert units.length(180, IMPERIAL) == "5′11″"
    assert units.length(180, METRIC) == "180 cm"


def test_imperial_food_amounts():
    assert parse_item("6 oz chicken breast")["portion"] == "170 g"
    assert parse_item("12 fl oz milk")["portion"] == "355 ml"
    assert round(parse_item("1 lb ground beef")["calories"]) == 1134


def test_profile_units_saved(client):
    p = client.get("/api/profile").json()
    assert p["units"] == "metric"
    p["units"] = "imperial"
    assert client.put("/api/profile", json=p).json()["units"] == "imperial"
