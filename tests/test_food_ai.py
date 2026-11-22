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
    assert len(foods) > 800
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
    r = client.post("/api/foods/analyze", data={"description": "2 mama's zrazy qorma"})
    assert r.json()["items"] == []
    client.post("/api/my-foods", json={"name": "Mama's zrazy qorma", "calories": 210, "protein_g": 12, "fat_g": 13, "carbs_g": 11})
    items = client.post("/api/foods/analyze", data={"description": "2 mama's zrazy qorma and a banana"}).json()["items"]
    assert [round(i["calories"]) for i in items] == [420, 105]
    found = client.get("/api/food-library?q=zrazy").json()
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


def test_spoken_meals_are_understood():
    out = svc.analyze("for lunch I had 4 turkey meatballs, a cup of rice and then a salad", meal_hint="snack")
    assert out["meal_guess"] == "lunch"
    assert [round(i["calories"]) for i in out["items"]][:2] == [144, 205]
    assert svc.analyze("this morning I had two eggs", meal_hint="snack")["meal_guess"] == "breakfast"
    assert svc.analyze("tonight I ate 14 sauteed shrimp", meal_hint="snack")["meal_guess"] == "dinner"


def test_persian_dishes_and_last_night():
    out = svc.analyze("last night I had a cup of kashk bademjan and a cup of salad olivier", meal_hint="snack")
    assert out["meal_guess"] == "dinner" and out["day_offset"] == -1
    assert [round(i["calories"]) for i in out["items"]] == [280, 380]


def test_everyday_portions_and_farsi_names():
    out = svc.analyze("1 plate of kashk bademjan and half a plate of salad olivier", meal_hint="dinner")
    assert [round(i["calories"]) for i in out["items"]] == [420, 285]   # plate ~300 g of dishes measured per cup
    fa = svc.analyze("یک بشقاب کشک بادمجان و نصف بشقاب سالاد الویه", meal_hint="dinner")
    assert [round(i["calories"]) for i in fa["items"]] == [420, 285]
    kb = svc.analyze("۲ سیخ کباب کوبیده و یک دوغ", meal_hint="dinner")["items"]
    assert kb[0]["portion"] == "2 skewers" and len(kb) == 2
    assert svc.analyze("a big plate of mirza ghasemi")["items"][0]["portion"].startswith("1 big plate")
    assert svc.analyze("میرزا قاسمی")["items"]
    assert round(svc.analyze("a handful of almonds")["items"][0]["calories"]) > 100


def test_voice_commas_inside_a_dish_name_are_joined():
    items = svc.analyze("One bowl of salad, Olivier.")["items"]
    assert len(items) == 1 and round(items[0]["calories"]) == 665
    items = svc.analyze("a plate of kashk, bademjan, and a doogh")["items"]
    assert [round(i["calories"]) for i in items] == [420, 90]
    assert len(svc.analyze("rice, chicken breast, salad")["items"]) == 3   # real separate foods stay separate
