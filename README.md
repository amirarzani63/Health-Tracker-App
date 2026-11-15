# Health Tracker

A self-hosted web app to track diet and exercise, generate workout plans, get diet
suggestions, and automatically pull activity and wellness data from Garmin Connect
(built for a fenix 7 Pro, but works with any Garmin device that syncs to Garmin Connect).

## Features

| Area | What it does |
| --- | --- |
| **Dashboard** | Calories left, protein, steps, sleep, training readiness, today's planned session, last-7-day totals, 14-day intake vs. burned chart |
| **Calorie counter** | Describe what you ate ("2 eggs, toast with butter, a latte"), snap up to 4 photos of your plate, or both. Claude identifies each food, estimates portion, calories and macros, and flags low-confidence guesses; you review and edit the items before they're added to the log |
| **Diet** | Food log by meal, quick-add food library, macro progress bars, calorie/macro targets (Mifflin-St Jeor), meal suggestions that fit your remaining budget and respect diet type (omnivore / pescatarian / vegetarian / vegan) and foods to avoid |
| **Exercise** | Manual workout logging with sets/reps/weight, activity history (incl. Garmin Training Effect), weekly volume chart, resting HR / sleep / Body Battery trends |
| **Plans** | Generates a weekly split (full body, upper/lower, PPL) for 2–6 days, for gym / home / bodyweight, with goal-specific sets/reps/rest, HR-zone cardio days, weekly progression and a deload week |
| **Garmin** | Connect your Garmin Connect account (MFA supported), sync activities, daily stats (steps, calories, RHR, stress, Body Battery, sleep), and Index scale weigh-ins; auto-syncs every 6 hours |

### How Garmin data is used

- **Calorie targets**: on days with Garmin data, your target uses the watch's measured burn
  (BMR + active calories) instead of a generic activity multiplier, so a long run raises your budget.
- **Readiness**: low Body Battery, short sleep or high stress turns the dashboard hint amber/red and
  suggests easier training.
- **Refuel tips**: long or high-calorie sessions trigger post-workout nutrition tips.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

To use the AI calorie counter, set an Anthropic API key before starting the server
(get one at https://console.anthropic.com):

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
```

Without a key everything else works and the counter shows a setup hint instead.

Open http://localhost:8000, fill in **Profile** first (height, weight, goal, diet), then go to
**Garmin** and sign in with your Garmin Connect account.

API docs are at http://localhost:8000/docs.

### Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `HEALTH_DATA_DIR` | `./data` | Where the SQLite DB and Garmin session tokens live |
| `DATABASE_URL` | `sqlite:///<data dir>/health.db` | Any SQLAlchemy URL |
| `GARMIN_AUTO_SYNC_HOURS` | `6` | Background sync interval; `0` disables it |
| `ANTHROPIC_API_KEY` | – | Enables the AI calorie counter |
| `FOOD_AI_MODEL` | `claude-opus-5-5` | Claude model used for meal analysis |

## Garmin Connect: how the connection works

Garmin's official Health/Activity APIs are only available to approved business developers, so this
app uses the community [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
library, which talks to the same endpoints as the Garmin Connect website.

- Your password is sent to Garmin once to obtain session tokens and is **never stored**.
- Tokens are saved in `data/garmin_tokens/` (permissions `600`) and refreshed automatically.
  Delete that folder or click **Disconnect** to revoke local access.
- If your account has two-step verification, the app asks for the code Garmin sends you.
- This is intended for personal, self-hosted use of your own data. Because it uses unofficial
  endpoints, a Garmin-side change can occasionally break sync until the library is updated
  (`pip install -U garminconnect`).

**Security note:** the app has no login of its own — it's designed to run on your own machine or
home network. Don't expose it to the internet without putting it behind authentication
(e.g. a reverse proxy with basic auth, Tailscale, or Cloudflare Access).

## AI calorie counter: how it works

- Photos are resized in your browser (max 1568 px, JPEG) before upload, so big phone photos are fast
  and cheap to analyse. iPhone HEIC photos work in browsers that can display them (e.g. Safari).
- The description and photos are sent to the Claude API, which returns a structured list of items.
  Quantities you type override what's seen in the photo, so "200 g chicken" beats a visual guess.
- Nothing is saved until you click **Add to food log**. Untick items, fix names, or adjust numbers first.
- Each analysis is one API call, typically a few US cents with photos (set `FOOD_AI_MODEL=claude-sonnet-5-5` for roughly half the cost). Photos aren't stored by the app.

## Project layout

```
app/
  main.py                 FastAPI app, static files, background Garmin auto-sync
  db.py, models.py        SQLAlchemy setup and tables
  schemas.py              Request/response validation
  routers/                REST endpoints (profile, diet, exercise, plans, garmin, dashboard)
  services/
    nutrition.py          BMR/TDEE, macro targets, food library, meal suggestions
    workout_planner.py    Plan generator and readiness hints
    garmin.py             Garmin login/MFA, token storage, sync + data mapping
    food_ai.py            AI calorie counter (Claude vision + structured outputs)
  static/                 Single-page frontend (HTML/CSS/JS, vendored Chart.js)
tests/                    pytest suite (uses a fake Garmin client)
```

## Tests

```bash
pytest
```

## Ideas for next steps

- Barcode scanning / Open Food Facts lookup for packaged foods
- Remember frequent meals for one-tap re-logging
- AI-generated meal plans and plan adjustments (e.g. with the Claude API)
- Push the generated strength workouts to Garmin Connect so they appear on the watch
- Multi-user accounts and authentication
