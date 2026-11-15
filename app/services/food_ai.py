"""AI calorie counter: estimate foods, portions and macros from text and/or photos.

Uses Claude's vision and structured outputs, so the response is always a
validated ``MealEstimate``. Estimates are returned to the UI as a draft for
the user to review and edit; nothing is logged automatically.

Requires an Anthropic API key in ``ANTHROPIC_API_KEY`` (or any credential
source the Anthropic SDK understands).
"""

import base64
import os
from typing import Any, Literal

from pydantic import BaseModel

MODEL = os.getenv("FOOD_AI_MODEL", "claude-opus-5-5")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 4

SYSTEM_PROMPT = """You are a careful nutrition analyst inside a personal diet-tracking app. \
The user tells you what they ate, shows you photos of it, or both. Break the meal into \
separate food items and estimate each item's portion, calories, protein, carbs and fat \
for the amount actually eaten.

How to estimate:
- Quantities the user states (weights, counts, "half", "two slices") override what you see in photos.
- In photos, judge portion size from visual cues: plate and bowl size, utensils, hands, packaging. \
If several photos show the same meal from different angles, count each food once.
- Count cooking fats, sauces, dressings, toppings and drinks that are visible or mentioned, \
as their own items when they are significant (roughly 30 kcal or more).
- For packaged foods with a readable nutrition label, use the label values.
- For restaurant or chain dishes, use typical published values for that dish when you know them.
- Prefer realistic, typical values over optimistic ones; restaurant portions are usually large.
- Use macros consistent with the calories (protein and carbs about 4 kcal/g, fat about 9 kcal/g, alcohol about 7 kcal/g).

Set confidence to "low" when the portion or the food itself is hard to tell, and say in notes \
what the user could add (e.g. a weight, or what's inside a wrap) to make the estimate better. \
If the photos contain no food and the text describes none, return an empty items list and \
explain in notes."""


class FoodItemEstimate(BaseModel):
    name: str
    portion: str  # e.g. "1 cup (about 185 g)"
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    confidence: Literal["high", "medium", "low"]


class MealEstimate(BaseModel):
    items: list[FoodItemEstimate]
    meal_guess: Literal["breakfast", "lunch", "dinner", "snack"]
    notes: str


class FoodAIError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def ai_configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def _default_client():
    import anthropic

    return anthropic.Anthropic()


class FoodAnalyzer:
    def __init__(self, client_factory=_default_client):
        self._client_factory = client_factory
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def analyze(self, description: str = "", images: list[tuple[bytes, str]] | None = None,
                meal_hint: str | None = None) -> dict[str, Any]:
        images = images or []
        description = (description or "").strip()
        if not description and not images:
            raise FoodAIError("Describe what you ate or add at least one photo.", 400)
        if len(images) > MAX_IMAGES:
            raise FoodAIError(f"Up to {MAX_IMAGES} photos per meal.", 400)

        content: list[dict] = []
        for data, media_type in images:
            if media_type not in ALLOWED_IMAGE_TYPES:
                raise FoodAIError(f"Unsupported image type {media_type}. Use JPEG, PNG, WebP or GIF.", 400)
            if len(data) > MAX_IMAGE_BYTES:
                raise FoodAIError("Each photo must be under 5 MB.", 400)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type,
                           "data": base64.standard_b64encode(data).decode("ascii")},
            })

        parts = []
        if images:
            parts.append(f"{len(images)} photo(s) of my meal are attached.")
        parts.append(f"What I ate: {description}" if description else "I didn't add a description.")
        if meal_hint:
            parts.append(f"This was my {meal_hint}.")
        content.append({"type": "text", "text": "\n".join(parts)})

        import anthropic

        try:
            response = self._get_client().beta.messages.parse(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_format=MealEstimate,
                output_config={"effort": "medium"},
                # If a safety classifier declines, let the API retry on its recommended model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise FoodAIError("The Anthropic API key is missing or invalid. Set ANTHROPIC_API_KEY and restart.", 503) from e
        except anthropic.RateLimitError as e:
            raise FoodAIError("The AI service is rate-limited right now. Try again in a minute.", 429) from e
        except anthropic.BadRequestError as e:
            raise FoodAIError(f"The AI service rejected the request: {e.message}", 400) from e
        except anthropic.APIStatusError as e:
            raise FoodAIError(f"The AI service returned an error ({e.status_code}). Try again shortly.") from e
        except anthropic.APIConnectionError as e:
            raise FoodAIError("Couldn't reach the AI service. Check your internet connection.") from e
        except TypeError as e:
            if "authentication" not in str(e).lower():
                raise
            # the SDK raises TypeError when no credential source can be resolved
            raise FoodAIError("No Anthropic API key configured. Set ANTHROPIC_API_KEY and restart.", 503) from e

        if response.stop_reason == "refusal":
            raise FoodAIError("The AI couldn't analyse this meal. Try a different photo or describe it in text.", 422)
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise FoodAIError("The AI response was incomplete. Please try again.")

        result: MealEstimate = response.parsed_output
        items = [i.model_dump() for i in result.items]
        for i in items:
            for k in ("calories", "protein_g", "carbs_g", "fat_g"):
                i[k] = max(0.0, round(float(i[k]), 1))
        totals = {k: round(sum(i[k] for i in items), 1) for k in ("calories", "protein_g", "carbs_g", "fat_g")}
        return {
            "items": items,
            "totals": totals,
            "meal_guess": meal_hint or result.meal_guess,
            "notes": result.notes,
        }


food_analyzer = FoodAnalyzer()
