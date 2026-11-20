from datetime import date

import pytest

from app.services.food_ai import FoodAIError, FoodAnalyzer, parse_item

TODAY = date.today().isoformat()
svc = FoodAnalyzer()


def test_counts_and_words():
    out = svc.analyze("2 eggs, a banana and toast")
    names = [i["name"] for i in out["items"]]
    assert names == ["2 eggs", "a banana", "toast"]
    assert out["items"][0]["calories"] == 144
    assert out["totals"]["calories"] == 144 + 105 + 80


def test_grams_scale_portion():
    item = parse_item("150g chicken breast")
    assert item["calories"] == pytest.approx(247.5) and item["protein_g"] == pytest.approx(46.5)
    assert item["confidence"] == "high" and item["portion"] == "150 g"


def test_longest_name_wins_and_fractions():
    assert parse_item("greek yogurt")["protein_g"] == 20
    assert parse_item("1/2 avocado")["calories"] == 160  # half of a 320 kcal avocado
    assert parse_item("1 tbsp peanut butter")["calories"] == 94


def test_unknown_foods_reported():
    out = svc.analyze("2 eggs with zzqx stuff", meal_hint="breakfast")
    assert len(out["items"]) == 1 and "zzqx" in out["notes"] and out["meal_guess"] == "breakfast"


def test_empty_rejected():
    with pytest.raises(FoodAIError):
        svc.analyze("  ")


def test_endpoint_and_bulk_log(client):
    r = client.post("/api/foods/analyze", data={"description": "2 eggs and toast", "meal": "breakfast"})
    assert r.status_code == 200, r.text
    body = r.json()
    items = [{"day": TODAY, "meal": "breakfast", "name": i["name"], "servings": 1,
              "calories": i["calories"], "protein_g": i["protein_g"], "carbs_g": i["carbs_g"], "fat_g": i["fat_g"]}
             for i in body["items"]]
    assert client.post("/api/foods/bulk", json={"items": items}).status_code == 200
    assert client.get(f"/api/nutrition/summary?day={TODAY}").json()["consumed"]["calories"] == 224
    assert client.post("/api/foods/analyze", data={"description": ""}).status_code == 400
    assert client.post("/api/foods/bulk", json={"items": []}).status_code == 400
    assert client.get("/api/ai/status").json() == {"configured": True}


def test_database_rows_are_consistent():
    from app.services import food_db
    foods = food_db.builtin_foods()
    assert len(foods) > 350
    seen = {}
    for f in foods:
        for n in f.names:
            assert n not in seen, f"'{n}' listed twice ({seen[n]} and {f.name})"
            seen[n] = f.name
        if "alcohol" in f.tags or f.name in {"beer", "wine", "spirits", "cocktail", "prosecco", "light beer"}:
            continue
        est = 4 * f.protein_g + 4 * f.carbs_g + 9 * f.fat_g
        assert abs(est - f.calories) <= max(25, 0.2 * f.calories), (f.name, f.calories, round(est))


def test_cup_amounts_and_trailing_amounts():
    assert parse_item("1 cup brown rice")["calories"] == 216
    assert parse_item("pepperoni pizza 2 slices")["calories"] == 620
    assert parse_item("3 strawberries")["calories"] == 12


def test_my_foods_are_learned(client):
    r = client.post("/api/foods/analyze", data={"description": "2 mama's kotlet"})
    assert r.json()["items"] == []
    client.post("/api/my-foods", json={"name": "Mama's kotlet", "calories": 210, "protein_g": 12, "fat_g": 13, "carbs_g": 11})
    items = client.post("/api/foods/analyze", data={"description": "2 mama's kotlet and a banana"}).json()["items"]
    assert [round(i["calories"]) for i in items] == [420, 105]
    found = client.get("/api/food-library?q=kotlet").json()
    assert found[0]["custom"] and found[0]["calories"] == 210
    assert client.get("/api/food-db/stats").json()["mine"] == 1


def test_every_food_is_measured_in_one_logical_unit():
    """Portions are one cup / tbsp / piece / slice / item (or grams), never "10 olives" or "1/2 cup"."""
    import csv
    import re
    from app.services.food_db import CSV_PATH
    bad = []
    for r in csv.reader(open(CSV_PATH)):
        if not r or r[0].startswith("#") or r[0] == "names" or r[0].startswith("grapefruit") or r[0].startswith("sub"):
            continue
        m = re.match(r"^(\d+/\d+|\d+(?:\.\d+)?)\s+(\S+)", r[1])
        if m and m.group(2) not in ("g", "ml") and m.group(1) != "1":
            bad.append(r[1])
    assert not bad, bad
