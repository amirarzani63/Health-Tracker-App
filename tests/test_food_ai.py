import base64
from datetime import date
from types import SimpleNamespace

import pytest

from app.main import app
from app.routers import food_ai as food_ai_router
from app.services.food_ai import FoodAIError, FoodAnalyzer, FoodItemEstimate, MealEstimate

TODAY = date.today().isoformat()
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class FakeMessages:
    def __init__(self, result=None, stop_reason="end_turn"):
        self.calls = []
        self.result = result
        self.stop_reason = stop_reason

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.result, stop_reason=self.stop_reason)


def fake_analyzer(result=None, stop_reason="end_turn"):
    msgs = FakeMessages(result, stop_reason)
    client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    return FoodAnalyzer(client_factory=lambda: client), msgs


EGGS = MealEstimate(
    items=[
        FoodItemEstimate(name="Scrambled eggs", portion="2 large eggs", calories=182, protein_g=12.4,
                         carbs_g=1.6, fat_g=13.8, fiber_g=0, confidence="high"),
        FoodItemEstimate(name="Sourdough toast with butter", portion="1 slice + 1 tsp", calories=155.44,
                         protein_g=4, carbs_g=22, fat_g=5.5, fiber_g=1.2, confidence="medium"),
    ],
    meal_guess="breakfast",
    notes="Assumed eggs cooked in a little butter.",
)


def test_text_only_request():
    svc, msgs = fake_analyzer(EGGS)
    out = svc.analyze("2 scrambled eggs and toast")
    call = msgs.calls[0]
    assert call["output_format"] is MealEstimate
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    content = call["messages"][0]["content"]
    assert [b["type"] for b in content] == ["text"]
    assert "2 scrambled eggs and toast" in content[0]["text"]
    assert out["totals"]["calories"] == pytest.approx(337.4)
    assert out["items"][1]["calories"] == 155.4
    assert out["meal_guess"] == "breakfast"


def test_photos_sent_as_base64_images_before_text():
    svc, msgs = fake_analyzer(EGGS)
    svc.analyze("", [(PNG, "image/png"), (PNG, "image/jpeg")], meal_hint="lunch")
    content = msgs.calls[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]
    assert base64.b64decode(content[0]["source"]["data"]) == PNG
    assert content[1]["source"]["media_type"] == "image/jpeg"
    assert "2 photo(s)" in content[2]["text"] and "lunch" in content[2]["text"]


def test_meal_hint_overrides_guess():
    svc, _ = fake_analyzer(EGGS)
    assert svc.analyze("eggs", meal_hint="dinner")["meal_guess"] == "dinner"


@pytest.mark.parametrize("kwargs,status", [
    ({}, 400),
    ({"images": [(PNG, "image/heic")]}, 400),
    ({"images": [(b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")]}, 400),
    ({"images": [(PNG, "image/png")] * 5}, 400),
])
def test_validation(kwargs, status):
    svc, msgs = fake_analyzer(EGGS)
    with pytest.raises(FoodAIError) as e:
        svc.analyze(**kwargs)
    assert e.value.status == status
    assert not msgs.calls


def test_refusal_and_incomplete():
    svc, _ = fake_analyzer(None, stop_reason="refusal")
    with pytest.raises(FoodAIError) as e:
        svc.analyze("eggs")
    assert e.value.status == 422
    svc, _ = fake_analyzer(None, stop_reason="max_tokens")
    with pytest.raises(FoodAIError):
        svc.analyze("eggs")


def test_analyze_endpoint_and_bulk_log(client):
    svc, msgs = fake_analyzer(EGGS)
    app.dependency_overrides[food_ai_router.analyzer] = lambda: svc
    try:
        r = client.post("/api/foods/analyze", data={"description": "eggs and toast", "meal": "breakfast"},
                        files=[("photos", ("plate.png", PNG, "image/png"))])
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) == 2
        assert msgs.calls[0]["messages"][0]["content"][0]["type"] == "image"

        items = [{"day": TODAY, "meal": "breakfast", "name": i["name"], "servings": 1,
                  "calories": i["calories"], "protein_g": i["protein_g"], "carbs_g": i["carbs_g"], "fat_g": i["fat_g"]}
                 for i in body["items"]]
        assert client.post("/api/foods/bulk", json={"items": items}).status_code == 200
        summary = client.get(f"/api/nutrition/summary?day={TODAY}").json()
        assert summary["consumed"]["calories"] == round(337.4)
    finally:
        app.dependency_overrides.clear()


def test_analyze_endpoint_errors(client):
    svc, _ = fake_analyzer(EGGS)
    app.dependency_overrides[food_ai_router.analyzer] = lambda: svc
    try:
        assert client.post("/api/foods/analyze", data={"description": ""}).status_code == 400
        r = client.post("/api/foods/analyze", files=[("photos", ("x.heic", PNG, "image/heic"))])
        assert r.status_code == 400 and "Unsupported" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()
    assert client.post("/api/foods/bulk", json={"items": []}).status_code == 400


def test_ai_status(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert client.get("/api/ai/status").json() == {"configured": False}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert client.get("/api/ai/status").json() == {"configured": True}


def test_missing_credentials_gives_clear_error(monkeypatch):
    def raise_no_auth(**kw):
        raise TypeError("Could not resolve authentication method. Expected one of api_key...")

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=raise_no_auth)))
    svc = FoodAnalyzer(client_factory=lambda: client)
    with pytest.raises(FoodAIError) as e:
        svc.analyze("eggs")
    assert e.value.status == 503 and "ANTHROPIC_API_KEY" in str(e.value)
