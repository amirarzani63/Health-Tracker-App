# Health Tracker

A self-hosted web app to track diet and exercise, generate workout plans, get diet
suggestions, and automatically pull activity and wellness data from Garmin Connect
(built for a fenix 7 Pro, but works with any Garmin device that syncs to Garmin Connect).

## Features

| Tab | What it does |
| --- | --- |
| **Today** | Everything at a glance: calories and protein left, steps, workouts and active minutes this week, sleep and weight vs. your goals; a "today's picture" combining what you ate with what your Garmin says you burned (energy balance); recommendations; today's planned workout with a recovery hint; a 14-day eaten-vs-burned chart; quick buttons to log food, a workout or your weight; a setup checklist for first-time use |
| **Food** | AI calorie counter (describe a meal and/or snap photos: Claude itemizes it, you review and log); searchable food list; calories, protein, carbs, fat and fibre vs. targets; food log by meal; meal ideas that fit what's left of today's calories and protein, filtered by diet type and foods to avoid |
| **Workouts** | Log workouts with type, duration, distance, calories, heart rate and sets (exercise, reps, weight). "Load today's plan" pre-fills the sets from your active plan. History merges manual workouts with those synced from your fenix |
| **Plans** | Builds a weekly plan for strength, muscle gain, weight loss, cardio/endurance or general fitness: 2–6 days, gym/home/bodyweight, goal-specific sets/reps/rest, heart-rate-zone cardio days, weekly progression and a deload week |
| **Progress** | Week / month / 3-month / year views: calories eaten vs. target vs. burned, daily macros, a weekly summary table (days logged, averages, days on target, workouts vs. goal, active minutes, steps, sleep, weight change), body weight vs. target, workouts per week vs. goal, strength progress per exercise (estimated 1-rep max and heaviest set), steps, resting heart rate and sleep |
| **Settings** | Goals (calories, macros, fibre, steps, sleep, workouts/week, active minutes/week, target weight; blank nutrition targets are calculated for you), profile, reminders, Garmin connection |

### Garmin + food log = full daily picture

- **Calorie targets** follow your Garmin-measured burn on synced days (unless you set a fixed target in Goals).
- **Energy balance**: eaten (your log) minus burned (Garmin) per day, shown on Today and in Progress.
- **Readiness**: low Body Battery, short sleep or high stress suggests an easier session.
- **Auto-sync**: when you open the app it syncs if the last sync is over an hour old, and the server re-syncs every 6 hours.
  Synced data: workouts (with avg/max HR, Training Effect, load), steps, total/active calories, resting/min/max heart
  rate, stress, Body Battery, sleep and Index-scale weigh-ins.

### One-tap setup and your own Garmin workouts

- **Set it all up for me** (Today tab, or Settings → Goals): reads your sex, height, weight, birth year, sleep
  schedule, step goal, intensity-minute goal and goal weight from Garmin, works out your experience and
  training days from the last 30 days of activities, and sets goals and daily nutrition targets.
- **Your saved Garmin workouts become the plan.** They're adapted to your goal and equipment. At home, barbell,
  cable and machine moves are swapped for dumbbell or band versions from Garmin's own exercise catalog, with no
  duplicates in a workout. For weight loss, low-rep sets go to 10 reps, rests are capped at 60 s and sets at 4,
  and two Zone 2 cardio days are added.
- **Send to your fenix:** adapted copies are saved in Garmin Connect (originals untouched, copies end in
  "· Health Tracker") and scheduled on your Garmin calendar two weeks ahead. Each sync keeps the calendar
  filled. Plans tab → **Stop sending** removes the upcoming ones.
- Protein targets use lean-mass reference weight (BMI 27) when BMI is over 30.

### Strava

Settings → Strava imports your Strava activities through Strava's official API, which is a reliable second
source if Garmin sign-in is ever blocked. Sessions that come from both Garmin and Strava are counted once:
Garmin's copy wins because it has Training Effect and load. One-time setup:

1. Create an app at strava.com/settings/api with **Authorization Callback Domain** = your app's domain
   (e.g. `health-tracker-xxxx.onrender.com`).
2. Add `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` to your Render service's Environment.
3. In the app: Settings → Strava → **Connect Strava**.

### Appearance

Dark theme by default with WCAG-checked contrast (body text 14.7:1, secondary text 7.2:1). Switch to Light or
"Match my phone" in Settings → Appearance.

### Recommendations

Rule-based coaching from the last 7 days vs. your goals, for example: protein consistently low, calories above a
weight-loss target (or below a gain target), very low intake, too few logged days, workout goal at risk with the days
left this week (and what's next in your plan), low steps, short sleep, low fibre, and weight trending the wrong way.

### Reminders

Turn on any of: log breakfast/lunch/dinner, planned workout, weigh-in, and an evening nutrition check-in, each with
its own time and days. They're smart: "log lunch" doesn't fire if lunch is logged, the workout reminder only fires on
plan days when you haven't trained yet, and the evening check-in tells you the calories and protein you have left.
Reminders show as in-app banners and, if you allow it, as browser notifications. Notifications only arrive while
the app is open in a browser tab or added to your home screen. True push notifications to a closed app would need
web push and HTTPS hosting (see next steps).

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

### Use it on your phone

Run the server so other devices on your home Wi-Fi can reach it, then open `http://<your-computer's-IP>:8000`
on your phone and choose **Add to Home Screen**. It then opens like an app, and the camera button in the calorie
counter takes photos directly:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Put it on your phone (free hosting)

To use the app on your iPhone from anywhere, with no computer left on, host it for free on
[Render](https://render.com), with your data in a free [Neon](https://neon.tech) Postgres database.
Everything below can be done from your phone's browser.

**1. Create the free database (Neon)**
1. Go to neon.tech, sign up (GitHub sign-in is quickest) and create a project (any name, the region nearest you).
2. On the project dashboard tap **Connect** and copy the connection string. It looks like
   `postgresql://user:password@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`. Keep it private.

**2. Create the app (Render)**
1. Go to render.com and sign up with GitHub. Allow access to the **Health-Tracker-App** repo.
2. Tap **New → Blueprint** and pick **Health-Tracker-App**. Render reads `render.yaml` and uses the **Free** plan.
3. Fill in:
   - `DATABASE_URL`: the Neon connection string from step 1.
   - `APP_PASSWORD`: the password you'll sign in with. Make it long; the app is on the internet.
   - `ANTHROPIC_API_KEY`: optional, for the photo/text calorie counter. Leave blank to skip.
4. Tap **Apply** and wait a few minutes for the first build. You get an address like
   `https://health-tracker-xxxx.onrender.com`.

**3. Add it to your iPhone**
1. Open that address in **Safari** and sign in. Then tap **Share → Add to Home Screen**.
2. Open it from the new icon and sign in once more (iOS keeps home-screen apps separate from Safari).
   You stay signed in for 90 days.
3. Go to **Settings → Garmin Connect** and connect your account.

**What to expect on the free plan**
- After ~15 minutes without use the server sleeps. The next open can take up to a minute while it wakes up;
  after that it's normal speed. Your data is safe in the database the whole time.
- Garmin data syncs when you open the app (the 6-hourly background sync only runs while the server is awake).
- Every push to `main` redeploys automatically.

The `Dockerfile` also works on other hosts (Fly.io, Railway, a VPS). Set `DATABASE_URL` and `APP_PASSWORD`,
or mount a persistent volume at `/data` to use the built-in SQLite database instead.

**If Garmin sign-in fails from the server:** Garmin sometimes blocks logins from cloud data centers. If that
happens, connect Garmin once from the app running on your own computer pointed at the same `DATABASE_URL`;
the saved session is stored in the database and the server will use it.

### Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `HEALTH_DATA_DIR` | `./data` | Where the SQLite DB and Garmin session tokens live |
| `DATABASE_URL` | `sqlite:///<data dir>/health.db` | Postgres (`postgres://…`, e.g. Neon) or any SQLAlchemy URL |
| `GARMIN_AUTO_SYNC_HOURS` | `6` | Background sync interval; `0` disables it |
| `ANTHROPIC_API_KEY` | – | Enables the AI calorie counter |
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | – | Enables Strava import (from strava.com/settings/api) |
| `APP_PASSWORD` | – | Turns on the sign-in page. **Required when the app is on the internet** |
| `SECRET_KEY` | derived from the password | Signs session cookies; changing it signs out all devices |
| `FOOD_AI_MODEL` | `claude-opus-5-5` | Claude model used for meal analysis |

## Garmin Connect: how the connection works

Garmin's official Health/Activity APIs are only available to approved business developers, so this
app uses the community [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
library, which talks to the same endpoints as the Garmin Connect website.

- Your password is sent to Garmin once to obtain session tokens and is **never stored**.
- Session tokens are saved in the app's database and refreshed automatically.
  Click **Disconnect** to delete them.
- If your account has two-step verification, the app asks for the code Garmin sends you.
- This is intended for personal, self-hosted use of your own data. Because it uses unofficial
  endpoints, a Garmin-side change can occasionally break sync until the library is updated
  (`pip install -U garminconnect`).

**Security note:** set `APP_PASSWORD` before putting the app on the internet. Without it there is no
sign-in page, which is only fine on your own computer or home network. Failed sign-ins are rate-limited.

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
    insights.py           Daily/weekly summaries, goal progress, recommendations, reminders, strength progress
  static/                 Single-page frontend (HTML/CSS/JS, vendored Chart.js)
tests/                    pytest suite (uses a fake Garmin client)
```

## Tests

```bash
pytest
```

## Ideas for next steps

- Web push notifications so reminders arrive even when the app is closed (needs HTTPS hosting)
- Barcode scanning / Open Food Facts lookup for packaged foods
- Remember frequent meals for one-tap re-logging
- AI-generated meal plans and plan adjustments (e.g. with the Claude API)
- Push the generated strength workouts to Garmin Connect so they appear on the watch
- Multi-user accounts and authentication
