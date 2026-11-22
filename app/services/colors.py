"""Turn a favourite colour, as a person says it ("teal", "baby blue", "dark red", "#3fa"), into a hex colour."""
import re

from fastapi import HTTPException

NAMED = {
    # everyday names
    "red": "#ff3b3b", "orange": "#ff8a1a", "yellow": "#ffd21a", "green": "#2fd35a", "blue": "#3d7bff",
    "purple": "#9b5cff", "pink": "#ff4fa3", "brown": "#a0652e", "black": "#6b7280", "white": "#e8eef7",
    "grey": "#9aa5b5", "gray": "#9aa5b5", "silver": "#c0c8d4", "gold": "#ffc21a", "golden": "#ffc21a",
    "beige": "#d9c39a", "cream": "#f2e2b8", "tan": "#c9a174",
    # shades people often name
    "navy": "#3a5bff", "navy blue": "#3a5bff", "sky blue": "#5ec8ff", "light blue": "#6fcfff", "baby blue": "#8fd3ff",
    "royal blue": "#3d63ff", "cobalt": "#2f6bff", "azure": "#2fa0ff", "cyan": "#22d3ee", "aqua": "#22e3e3",
    "turquoise": "#2ed8c3", "teal": "#14b8a6", "mint": "#5ef2b0", "mint green": "#5ef2b0", "emerald": "#22e39a",
    "lime": "#a3e635", "olive": "#9ab33a", "forest green": "#2f9e55", "dark green": "#2f9e55", "sage": "#8fb996",
    "khaki": "#c3b26b", "mustard": "#e0b41f", "amber": "#ffb01a", "peach": "#ffad85", "apricot": "#ffb27a",
    "coral": "#ff6f61", "salmon": "#ff8c7a", "tangerine": "#ff8f1f", "rust": "#c8552b", "copper": "#c87533",
    "bronze": "#b8803a", "maroon": "#b03050", "burgundy": "#a3264a", "wine": "#a3264a", "crimson": "#e3263f",
    "scarlet": "#ff3a24", "cherry": "#e8204a", "ruby": "#e0115f", "rose": "#ff5c8a", "hot pink": "#ff3da6",
    "magenta": "#ff3df0", "fuchsia": "#ff3df0", "blush": "#f7a1b5", "lilac": "#c4a2ff", "lavender": "#b59cff",
    "violet": "#a46bff", "indigo": "#6b5cff", "plum": "#b04fa8", "mauve": "#c18fc8", "periwinkle": "#8f9cff",
    "charcoal": "#7a8494", "chocolate": "#a0582e", "coffee": "#a8754a", "caramel": "#d08a3d", "sand": "#d8b98a",
    # Persian names
    "قرمز": "#ff3b3b", "نارنجی": "#ff8a1a", "زرد": "#ffd21a", "سبز": "#2fd35a", "آبی": "#3d7bff",
    "بنفش": "#9b5cff", "صورتی": "#ff4fa3", "قهوه‌ای": "#a0652e", "مشکی": "#6b7280", "سفید": "#e8eef7",
    "طوسی": "#9aa5b5", "خاکستری": "#9aa5b5", "طلایی": "#ffc21a", "فیروزه‌ای": "#2ed8c3", "یاسی": "#c4a2ff",
    "سرمه‌ای": "#3a5bff", "زرشکی": "#a3264a", "گلبهی": "#ff8c7a",
}
SHADE = {"light": 1.25, "pale": 1.3, "pastel": 1.3, "bright": 1.1, "neon": 1.1, "dark": 0.75, "deep": 0.8}


def _scale(hexc: str, f: float) -> str:
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    if f > 1:  # lighter: move towards white
        k = f - 1
        r, g, b = (round(c + (255 - c) * k) for c in (r, g, b))
    else:
        r, g, b = (round(c * f) for c in (r, g, b))
    return "#%02x%02x%02x" % (r, g, b)


def resolve(said: str) -> str:
    s = re.sub(r"\s+", " ", (said or "").strip().lower())
    m = re.fullmatch(r"#?([0-9a-f]{6}|[0-9a-f]{3})", s)
    if m:
        h = m.group(1)
        return "#" + (h if len(h) == 6 else "".join(c * 2 for c in h))
    s = re.sub(r"^(my favou?rite colou?r is|it'?s|i like)\s+", "", s).strip(" .!")
    if s in NAMED:
        return NAMED[s]
    s2 = s.replace("-", " ").replace("ish", "").strip()
    if s2 in NAMED:
        return NAMED[s2]
    words = s2.split()
    if len(words) >= 2 and words[0] in SHADE and " ".join(words[1:]) in NAMED:
        return _scale(NAMED[" ".join(words[1:])], SHADE[words[0]])
    if words and words[-1] in NAMED:  # "ocean blue", "army green"
        return NAMED[words[-1]]
    raise HTTPException(422, f"I don't know the colour “{said.strip()}”. Try a simple name like teal, lavender or dark red.")
