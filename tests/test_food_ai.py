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
    assert parse_item("1/2 avocado")["calories"] == 80
    assert parse_item("1 tbsp peanut butter")["calories"] == pytest.approx(88.1, abs=0.1)


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
