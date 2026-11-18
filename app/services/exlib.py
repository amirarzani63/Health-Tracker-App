"""Exercise photos and details from free-exercise-db (public domain; see scripts/fetch_exercise_library.py).

Matches exercise names used in plans and Garmin workouts ("Bent-over Row with Dumbbell")
to library entries ("Bent Over Two-Dumbbell Row") by comparing normalised words.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "static" / "exlib"

# library muscle names -> the app's muscle groups (shared with the 3D model)
MUSCLE = {
    "abdominals": ["abs"], "abductors": ["glutes"], "adductors": ["adductors"], "biceps": ["biceps"],
    "calves": ["calves"], "chest": ["chest"], "forearms": ["forearms"], "glutes": ["glutes"],
    "hamstrings": ["hamstrings"], "lats": ["lats"], "lower back": ["lower_back"], "middle back": ["upper_back"],
    "neck": ["traps"], "quadriceps": ["quads"], "shoulders": ["front_delts", "side_delts"], "traps": ["traps"],
    "triceps": ["triceps"],
}
SYN = {
    "db": "dumbbell", "dumbbells": "dumbbell", "bb": "barbell", "kb": "kettlebell", "kettlebells": "kettlebell",
    "pushup": "push up", "pushups": "push up", "pullup": "pull up", "pullups": "pull up", "chinup": "chin up",
    "situp": "sit up", "flye": "fly", "flyes": "fly", "flies": "fly", "rows": "row", "curls": "curl",
    "raises": "raise", "presses": "press", "squats": "squat", "lunges": "lunge", "extensions": "extension",
    "crunches": "crunch", "bridges": "bridge", "thrusts": "thrust", "deadlifts": "deadlift", "rdl": "romanian deadlift",
    "ohp": "overhead press", "skullcrusher": "skull crusher", "skullcrushers": "skull crusher",
    "bentover": "bent over", "stepup": "step up", "stepups": "step up", "tricep": "triceps", "bicep": "", "biceps": "", "bodyweight": "", "body": "",
    "resistance": "band", "bands": "band", "banded": "band", "weighted": "", "standing": "", "seated": "seated",
    "alternating": "", "single": "one", "1": "one", "arm": "arm", "with": "", "the": "", "a": "", "on": "", "and": "",
}
EQUIP = {"dumbbell", "barbell", "kettlebell", "band", "cable", "machine", "smith", "ez"}
GENERIC = {"one", "arm", "leg", "grip", "close", "wide", "hold", "position"}


def words(name: str) -> list[str]:
    s = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("-", " ").replace("/", " "))
    out = []
    for w in s.split():
        w = SYN.get(w, w)
        out.extend(w.split())
    keep = {"triceps", "biceps", "press", "abs", "glutes", "lats", "delts", "hamstrings", "cross", "pass"}
    return [w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") and w not in keep else w for w in out if w]


@lru_cache(maxsize=1)
def library() -> dict:
    f = DIR / "exercises.json"
    if not f.exists():
        return {"items": [], "by_id": {}}
    items = []
    for e in json.loads(f.read_text()):
        if not isinstance(e, dict) or not e.get("name"):
            continue
        items.append({
            "id": e.get("id", e["name"]), "name": e["name"], "words": set(words(e["name"])),
            "category": e.get("category"), "equipment": e.get("equipment"), "level": e.get("level"),
            "primary": sorted({g for m in e.get("primaryMuscles", []) for g in MUSCLE.get(m, [])}),
            "secondary": sorted({g for m in e.get("secondaryMuscles", []) for g in MUSCLE.get(m, [])}),
            "instructions": e.get("instructions", []), "tips": [],
            "images": ["/static/exlib/img/" + p for p in e.get("images", [])
                       if isinstance(p, str) and ".." not in p and (DIR / "img" / p).exists()],
        })
    import math
    df: dict[str, int] = {}
    for it in items:
        for w in it["words"]:
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log((len(items) + 1) / (c + 0.5)) for w, c in df.items()}
    for it in items:  # a muscle can't be both main and supporting
        it["secondary"] = [m for m in it["secondary"] if m not in it["primary"]]
    return {"items": items, "by_id": {i["id"]: i for i in items}, "idf": idf}


def available() -> bool:
    return bool(library()["items"])


def _score(q: set[str], item: dict) -> float:
    w = item["words"]
    if not q or not w:
        return 0
    common = q & w
    if not common - EQUIP - GENERIC:  # need at least one movement word in common
        return 0
    idf = library()["idf"]
    def weight(s):
        return sum(idf.get(x, 6.0) * (0.5 if x in GENERIC else 1.0) for x in s)
    score = weight(common) / weight(q | w)
    # equipment named in the query but different in the item is a worse match
    if (q & EQUIP) and (w & EQUIP) and not (q & w & EQUIP):
        score *= 0.6
    return score


# Common names whose closest-word match would be wrong: pattern -> library exercise name
ALIASES = [
    (r"^push.?ups?$|^push.?ups? \(", "Pushups"),
    (r"rear delt fly|reverse fly", "Seated Bent-Over Rear Delt Raise"),
    (r"single.?leg (romanian )?deadlift|single.?leg rdl|one.?leg(ged)? (romanian )?deadlift", "Kettlebell One-Legged Deadlift"),
    (r"incline push.?ups?", "Incline Push-Up"),
    (r"split squat", "Split Squat with Dumbbells"),
    (r"sumo (dumbbell |db )?squat|plie squat", "Plie Dumbbell Squat"),
    (r"brisk walk|walking|zone 2 walk", "Trail Running/Walking"),
    (r"interval|sprint", "Wind Sprints"),
    (r"lateral raise|side raise|side lateral", "Side Lateral Raise"),
    (r"band.*(lat )?pull.?down|(lat )?pull.?down.*band", "Wide-Grip Lat Pulldown"),
    (r"lat pull.?down|pull.?down", "Wide-Grip Lat Pulldown"),
    (r"chin.?up", "Chin-Up"),
    (r"pull.?up", "Pullups"),
    (r"band(ed)? row|row.*band", "Seated Cable Rows"),
    (r"reverse lunge|rear lunge", "Dumbbell Rear Lunge"),
    (r"^dumbbell pullover|^pullover", "Straight-Arm Dumbbell Pullover"),
    (r"^glute bridge|^bridge|hip bridge", "Butt Lift (Bridge)"),
    (r"single.?leg glute bridge|single.?leg bridge", "Single Leg Glute Bridge"),
    (r"overhead.*(tricep|extension)|tricep.*overhead", "Standing Dumbbell Triceps Extension"),
    (r"lying leg raise|^leg raise", "Flat Bench Lying Leg Raise"),
    (r"hanging leg raise|hanging knee raise", "Hanging Leg Raise"),
    (r"^burpee", "Burpee"),
]


# When no photo of the exact exercise exists, show a real photo of the closest movement.
SIMILAR = [
    (r"roll.?out|slide.?out|ab wheel", "Ab Roller"),
    (r"back extension|spine extension|superman|u-boat|opposite arm|arm and leg", "Superman"),
    (r"dead.?bug", "Dead Bug"),
    (r"lat.?pull|pull.?over|power pull|y fly", "Straight-Arm Dumbbell Pullover"),
    (r"hang pull|jump shrug", "Clean Pull"),
    (r"\bdips?\b", "Dips - Triceps Version"),
    (r"toes to bar|teaser|pike|x abs|windshield|knee drive", "Hanging Leg Raise"),
    (r"wall ball|slam|sledge", "Overhead Slam"),
    (r"triple under|moguls|power switch|duck under|step.?over|lateral slide", "Knee Tuck Jump"),
    (r"chest fly", "Dumbbell Flyes"),
    (r"get.?up|step.?up|floor to shelf", "Dumbbell Step Ups"),
    (r"hip drop|hip crossover|lateral roll|pendulum|reach, roll|roll.?down|flex and extend|kick tabletop|pretzel|inner.?thigh|t.?stabil|stability|reverse leg raise", "Hip Circles (prone)"),
    (r"wall slide|reach to sky|shoulder flexion|plate reach", "Front Raise And Pullover"),
    (r"dorsiflexion", "Calf Stretch Hands Against Wall"),
    (r"warm.?up|total body|core|suspension|banded exercises", "Mountain Climbers"),
    (r"burpee|man maker|sprawl", "Mountain Climbers"),
    (r"hollow|l.?sit|leg lever|leg lowering|elevator abs|front lever", "Flat Bench Lying Leg Raise"),
    (r"plank|bear crawl|crawl|quadruped|bird.?dog", "Plank"),
    (r"handstand", "Handstand Push-Ups"),
    (r"deadlift|hip hinge|good morning|rdl", "Barbell Deadlift"),
    (r"chest.?supported.*row|towel.*row|door.*row|inverted row", "Alternating Kettlebell Row"),
    (r"row(?!ing)", "Bent Over Barbell Row"),
    (r"battle rope|battling", "Battling Ropes"),
    (r"jump rope|double under|skip", "Rope Jumping"),
    (r"bike|cycl|assault", "Bicycling, Stationary"),
    (r"rowing|calorie row|erg", "Rowing, Stationary"),
    (r"elliptical|cross.?trainer", "Elliptical Trainer"),
    (r"stair|step.?mill", "Stairmaster"),
    (r"\brun|jog|walk|track|treadmill|cardio|ladder|agility", "Trail Running/Walking"),
    (r"thruster", "Kettlebell Thruster"),
    (r"chop|woodchop|rotation|twist", "Standing Cable Wood Chop"),
    (r"clam|fire hydrant|abduct|lateral walk|monster", "Monster Walk"),
    (r"donkey kick|kickback|kick-back", "Glute Kickback"),
    (r"carry|waiter|farmer|hold", "Farmer's Walk"),
    (r"crunch|curl.?up|roll.?up|sit.?up|ab ", "Cross-Body Crunch"),
    (r"stretch|pose|mobility|swing", "Cat Stretch"),
    (r"bridge|hip raise|hip thrust", "Butt Lift (Bridge)"),
    (r"lunge|split", "Dumbbell Lunges"),
    (r"squat|plie|plié", "Bodyweight Squat"),
    (r"jack", "Rope Jumping"),
    (r"punch|jab|strike|bob and weave", "Battling Ropes"),
    (r"press.?down|tricep", "Triceps Pushdown"),
    (r"push.?up", "Pushups"),
    (r"[iytwl] raise|scapular|serratus", "Bent Over Dumbbell Rear Delt Raise With Head On Bench"),
    (r"curl", "Dumbbell Bicep Curl"),
    (r"press", "Dumbbell Shoulder Press"),
]


def _by_name(target: str) -> dict | None:
    t = target.lower()
    return next((i for i in library()["items"] if i["name"].lower() == t and i["images"]), None)


@lru_cache(maxsize=4096)
def match(name: str) -> dict | None:
    exact = _match_exact(name)
    if exact and exact.get("images"):
        return exact
    lower = name.lower()
    for pattern, target in SIMILAR:
        if re.search(pattern, lower) and (it := _by_name(target)):
            return {k: v for k, v in it.items() if k != "words"} | {"score": 0.3, "similar": True}
    return exact


def _match_exact(name: str) -> dict | None:
    lower = name.lower()
    for pattern, target in ALIASES:
        if re.search(pattern, lower):
            it = next((i for i in library()["items"] if i["name"].lower() == target.lower()), None)
            if it:
                return {k: v for k, v in it.items() if k != "words"} | {"score": 1.0}
    q = set(words(name))
    best, best_score = None, 0.0
    for it in library()["items"]:
        s = _score(q, it)
        if s > best_score or (s == best_score and best and len(it["words"]) < len(best["words"])):
            best, best_score = it, s
    if not best or best_score < 0.34:
        return None
    return {k: v for k, v in best.items() if k != "words"} | {"score": round(best_score, 2)}


def search(q: str, limit: int = 60) -> list[dict]:
    qw = set(words(q))
    rows = []
    for it in library()["items"]:
        s = _score(qw, it) if qw else 1
        if s > 0 or (q.lower() in it["name"].lower()):
            rows.append((s, it))
    rows.sort(key=lambda r: (-r[0], r[1]["name"]))
    return [{k: v for k, v in it.items() if k != "words"} for _, it in rows[:limit]]
