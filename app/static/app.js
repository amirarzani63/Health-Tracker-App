"use strict";

// ================================================================ helpers
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => (n == null ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const isoDate = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const localIso = (d = new Date()) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
const minutes = (s) => { const m = Math.round(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`; };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const numOrNull = (v) => (v === "" || v == null ? null : Number(v));
const shortDay = (iso) => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/api/garmin/")) {
    location.href = "/login"; // session expired
    throw new Error("Please sign in again");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : (j.detail?.[0]?.msg ? `${j.detail[0].loc?.at(-1)}: ${j.detail[0].msg}` : JSON.stringify(j.detail));
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg, error = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (error ? " error" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), 3500);
}

function formData(form) {
  const out = {};
  for (const [k, v] of new FormData(form)) out[k] = v;
  return out;
}

async function withBusy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
}

function bar(label, have, target, color, unit = "g") {
  const pct = target ? Math.min(100, (have / target) * 100) : 0;
  const over = target && have > target * 1.05;
  return `<div class="bar ${over ? "over" : ""}"><div class="top"><span>${label}</span><span>${fmt(have)} / ${fmt(target)} ${unit}</span></div>
    <div class="track"><div class="fill" style="width:${pct}%;${over ? "" : `background:${color}`}"></div></div></div>`;
}

// ================================================================ charts
const charts = {};
function drawChart(id, config) {
  if (typeof Chart === "undefined") return; // charts are optional; never break the page
  charts[id]?.destroy();
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--border");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  const base = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "bottom", labels: { boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3 } },
      tooltip: { padding: 10, boxPadding: 4 },
    },
    scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: css("--border") }, border: { display: false } } },
  };
  const options = deepMerge(base, config.options || {});
  charts[id] = new Chart($("#" + id), { ...config, options });
}
function deepMerge(a, b) {
  const out = { ...a };
  for (const [k, v] of Object.entries(b)) out[k] = v && typeof v === "object" && !Array.isArray(v) && typeof a[k] === "object" ? deepMerge(a[k], v) : v;
  return out;
}
const barDs = (label, data, color, extra = {}) => ({ type: "bar", label, data, backgroundColor: color, borderRadius: 4, borderSkipped: "start", maxBarThickness: 28, ...extra });
const lineDs = (label, data, color, extra = {}) => ({ type: "line", label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, spanGaps: true, ...extra });
const targetDs = (label, data) => lineDs(label, data, css("--target"), { borderDash: [5, 4], borderWidth: 1.5, tension: 0, backgroundColor: "transparent" });

// ================================================================ state & navigation
const state = { day: isoDate(new Date()), openedOn: isoDate(new Date()), view: "dashboard", progressDays: 30 };
const loaders = {};

function setDay(d) {
  state.day = d;
  $("#day").value = d;
  loaders[state.view]?.();
}
function shiftDay(n) {
  const d = new Date(state.day + "T12:00:00");
  d.setDate(d.getDate() + n);
  setDay(isoDate(d));
}

function show(view, focusSel) {
  state.view = view;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  $(".daybar").classList.toggle("hidden", !["dashboard", "diet"].includes(view));
  history.replaceState(null, "", "#" + view);
  window.scrollTo({ top: 0 });
  Promise.resolve(loaders[view]?.()).catch((e) => toast(e.message, true));
  if (focusSel) setTimeout(() => $(focusSel)?.focus(), 50);
}

// ================================================================ TODAY (dashboard)
function tile(label, value, unit, goal, sub, opts = {}) {
  const pct = goal && value != null ? Math.min(100, (value / goal) * 100) : 0;
  const cls = opts.over ? "over" : pct >= 100 ? "done" : "";
  return `<div class="tile ${cls}"><span class="label">${label}</span>
    <span class="value">${value == null ? "–" : esc(value)}${unit ? ` <small>${unit}</small>` : ""}</span>
    ${goal ? `<div class="track"><div class="fill" style="width:${pct}%"></div></div>` : ""}
    <span class="sub">${sub || ""}</span></div>`;
}

loaders.dashboard = async () => {
  const d = await api(`/api/dashboard?day=${state.day}`);
  const t = d.targets, c = d.consumed, g = d.goals;
  renderSetup(d.setup);

  const left = Math.round(t.calories - c.calories);
  $("#goalTiles").innerHTML = [
    tile("Calories", fmt(c.calories), "kcal", t.calories, left >= 0 ? `${fmt(left)} left of ${fmt(t.calories)}` : `${fmt(-left)} over ${fmt(t.calories)}`, { over: left < -0.05 * t.calories }),
    tile("Protein", fmt(c.protein_g), "g", t.protein_g, `goal ${fmt(t.protein_g)} g`),
    tile("Steps", g.steps.value == null ? null : fmt(g.steps.value), "", g.steps.goal, g.steps.value == null ? "sync Garmin" : `goal ${fmt(g.steps.goal)}`),
    tile("Workouts this week", g.workouts_week.value, `/ ${g.workouts_week.goal}`, g.workouts_week.goal, `${g.days_left_in_week} days left`),
    tile("Active minutes", fmt(g.active_minutes_week.value), `/ ${g.active_minutes_week.goal}`, g.active_minutes_week.goal, "this week"),
    tile("Sleep", g.sleep_h.value, "h", g.sleep_h.goal, `goal ${g.sleep_h.goal} h`),
    tile("Weight", g.weight.value == null ? null : fmt(g.weight.value, 1), "kg", null,
      [g.weight.change_4w != null && `${g.weight.change_4w > 0 ? "+" : ""}${g.weight.change_4w} kg in 4 wks`, g.weight.goal && `target ${g.weight.goal}`].filter(Boolean).join(" · ") || "log a weigh-in"),
  ].join("");

  // Garmin burn + food log = today's full picture
  const net = d.burned != null ? c.calories - d.burned : null;
  $("#balance").innerHTML = `
    <div><span class="label">Eaten</span><span class="value">${fmt(c.calories)}</span><span class="sub">kcal logged</span></div>
    <div><span class="label">Burned</span><span class="value">${fmt(d.burned)}</span><span class="sub">${d.active_calories != null ? `${fmt(d.active_calories)} active` : "from Garmin"}</span></div>
    <div><span class="label">Balance</span><span class="value">${net == null ? "–" : (net > 0 ? "+" : "") + fmt(net)}</span><span class="sub">${net == null ? "needs Garmin data" : (net < 0 ? "deficit" : "surplus") + (state.day === isoDate(new Date()) ? " so far" : "")}</span></div>`;
  $("#todayMacros").innerHTML =
    bar("Protein", c.protein_g, t.protein_g, css("--protein")) +
    bar("Carbs", c.carbs_g, t.carbs_g, css("--carbs")) +
    bar("Fat", c.fat_g, t.fat_g, css("--fat")) +
    bar("Fibre", c.fiber_g, t.fiber_g, css("--fiber"));
  $("#balanceNote").textContent = {
    goal: "Calorie target comes from your goals.",
    garmin: "Target adjusted for the activity your Garmin recorded today.",
    estimate: "Target estimated from your profile. Connect Garmin for measured burn.",
  }[t.source];

  $("#dashRecs").innerHTML = renderRecs(d.recommendations);

  const ts = d.today_session;
  const r = $("#readiness");
  r.className = "pill " + d.readiness.level;
  r.textContent = d.readiness.message;
  r.classList.toggle("hidden", ts?.type === "rest");
  $("#todaySession").innerHTML = !ts
    ? `<p class="muted">No active plan yet. <a href="#plans" data-goto="plans">Build one</a> from your goals.</p>`
    : renderPlanDay(ts, true) + `<div class="row-between" style="margin-top:8px"><span class="muted small">${esc(d.plan_name)}</span>
      ${ts.type !== "rest" ? (d.today_done ? `<span class="tag garmin">done ✓</span>` : `<button class="small-btn" data-start-session>Log this workout</button>`) : ""}</div>`;

  const w = d.week;
  $("#weekStats").innerHTML = [["Sessions", w.count], ["Time", minutes(w.duration_min * 60)], ["Distance", `${w.distance_km} km`], ["Food logged", `${w.days_logged}/7 days`]]
    .map(([l, v]) => `<div><span class="label">${l}</span><span class="value">${v}</span></div>`).join("");
  $("#recentActs").innerHTML = d.recent_activities.length
    ? d.recent_activities.map((a) => `<li><span>${esc(a.name)} <span class="tag ${a.source}">${a.source}</span></span><span class="muted small">${new Date(a.start_time).toLocaleDateString(undefined, { weekday: "short" })} · ${minutes(a.duration_s)}${a.distance_m ? ` · ${(a.distance_m / 1000).toFixed(1)} km` : ""}</span></li>`).join("")
    : `<li class="muted">No workouts this week yet.</li>`;

  drawChart("trendChart", {
    data: {
      labels: d.trend.map((x) => shortDay(x.day)),
      datasets: [
        barDs("Eaten", d.trend.map((x) => (x.logged ? x.calories : null)), css("--series-1")),
        lineDs("Burned (Garmin)", d.trend.map((x) => x.burned), css("--series-2"), { pointRadius: 2 }),
        targetDs("Target", d.trend.map((x) => x.target_calories)),
      ],
    },
    options: { scales: { y: { title: { display: true, text: "kcal" } } } },
  });
};

function renderRecs(recs) {
  const icon = { warn: "!", info: "i", good: "✓" };
  return recs.map((r) => `<li class="${r.level}"><span class="ic" aria-label="${r.level}">${icon[r.level]}</span>
    <div><strong>${esc(r.title)}</strong><span class="d">${esc(r.detail)}</span></div></li>`).join("")
    || `<li class="info"><span class="ic">i</span><div><strong>Nothing to flag</strong><span class="d">Keep logging and recommendations will appear here.</span></div></li>`;
}

function renderSetup(s) {
  const card = $("#setupCard");
  const show = state.justSetUp || (!s.profile && store.get("setupHidden") !== "1");
  card.classList.toggle("hidden", !show);
  if (show && !state.justSetUp) renderAutoSetup($("[data-auto-setup]", card), s.garmin);
}

// ---------------------------------------------------------------- automatic setup
const FOCUS_OPTS = [["auto", "Auto (from Garmin)"], ["lose_weight", "Lose weight"], ["build_muscle", "Build muscle"],
  ["get_stronger", "Get stronger"], ["improve_cardio", "Improve cardio / endurance"], ["stay_healthy", "Stay healthy"]];
const EQUIP_OPTS = [["auto", "Gym (default)"], ["gym", "Gym"], ["home", "Home (dumbbells / bands)"], ["bodyweight", "No equipment"]];
const DIET_OPTS = [["auto", "No restrictions (default)"], ["omnivore", "No restrictions"], ["vegetarian", "Vegetarian"], ["vegan", "Vegan"], ["pescatarian", "Pescatarian"]];
const opts = (list) => list.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");

function renderAutoSetup(el, garminConnected) {
  el.innerHTML = `
    <p class="lead">Your fenix and Garmin account already know your height, weight, age, step goal, sleep and training habits.
      The app uses them to fill in your profile and goals, pick your experience level and training days, build your workout plan
      and set daily calorie and protein targets.</p>
    <div class="garmin-line">${garminConnected
      ? `<span class="ok">✓ Garmin connected.</span> Your details and last 30 days come from your watch.`
      : `Garmin isn't connected yet. <a href="#settings" data-goto="settings" data-focus="#garminLogin input">Connect it first</a> for personal values (recommended).`}</div>
    <form class="form auto-form">
      ${garminConnected ? `
      <label class="check"><input type="checkbox" name="use_garmin_workouts" checked> Build my plan from my saved Garmin workouts (adapted to my goal and equipment)</label>
      <label class="check"><input type="checkbox" name="send_to_watch" checked> Send my plan to my fenix (Garmin calendar, 2 weeks ahead, kept topped up)</label>` : ""}
      <div class="row">
        <label>Main goal <select name="focus">${opts(FOCUS_OPTS)}</select></label>
        <label>Where you train <select name="equipment">${opts(EQUIP_OPTS)}</select></label>
        <label>How you eat <select name="diet_type">${opts(DIET_OPTS)}</select></label>
      </div>
      <button type="submit" class="go">Set it all up for me</button>
    </form>
    <ul class="auto-result"></ul>`;
  $(".auto-form", el).addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button", e.target);
    btn.disabled = true;
    btn.textContent = garminConnected ? "Reading your Garmin data… (up to a minute)" : "Setting up…";
    try {
      const body = formData(e.target);
      body.use_garmin_workouts = !!e.target.elements.use_garmin_workouts?.checked;
      body.send_to_watch = !!e.target.elements.send_to_watch?.checked;
      const r = await api("/api/setup/auto", { method: "POST", body });
      $(".auto-result", el).innerHTML = r.summary.map((x) => `<li>${esc(x)}</li>`).join("")
        + (r.note ? `<li class="warn-text">${esc(r.note)}</li>` : "")
        + `<li class="muted">You can change any of this in Settings. Weight and Garmin goals keep updating automatically.</li>`;
      e.target.classList.add("hidden");
      $(".lead", el).textContent = "All set! Here's what was set up:";
      toast("Everything is set up ✓");
      state.justSetUp = true;
      if (state.view === "dashboard") loaders.dashboard();
    } catch (err) {
      toast(err.message, true);
      btn.disabled = false;
      btn.textContent = "Set it all up for me";
    }
  });
}

$("#setupDismiss").onclick = () => { store.set("setupHidden", "1"); $("#setupCard").classList.add("hidden"); };

// quick weight dialog
$("#quickWeight").onclick = () => $("#weightDialog").showModal();
$("#weightDialog").addEventListener("close", async () => {
  const dlg = $("#weightDialog");
  const v = $("#weightQuick").elements.weight_kg.value;
  $("#weightQuick").reset();
  if (dlg.returnValue !== "save" || !v) return;
  try {
    await api("/api/weights", { method: "POST", body: { day: isoDate(new Date()), weight_kg: Number(v) } });
    toast("Weight logged");
    loaders[state.view]?.();
  } catch (err) { toast(err.message, true); }
});

// ================================================================ FOOD
loaders.diet = async () => {
  const [summary, foods, sugg] = await Promise.all([
    api(`/api/nutrition/summary?day=${state.day}`),
    api(`/api/foods?day=${state.day}`),
    api(`/api/nutrition/suggestions?day=${state.day}`),
  ]);
  const t = summary.targets, c = summary.consumed;
  $("#macroBars").innerHTML =
    bar("Calories", c.calories, t.calories, css("--accent"), "kcal") +
    bar("Protein", c.protein_g, t.protein_g, css("--protein")) +
    bar("Carbs", c.carbs_g, t.carbs_g, css("--carbs")) +
    bar("Fat", c.fat_g, t.fat_g, css("--fat")) +
    bar("Fibre", c.fiber_g, t.fiber_g, css("--fiber"));
  $("#targetSource").textContent = {
    goal: "Calorie target set in your goals (Settings).",
    garmin: `Based on Garmin: BMR ${fmt(t.bmr)} + today's active calories → ~${fmt(t.tdee)} kcal burned.`,
    estimate: `Estimated from your profile: ~${fmt(t.tdee)} kcal/day burned. Connect Garmin for measured burn, or set your own target in Settings.`,
  }[t.source];

  const byMeal = { breakfast: [], lunch: [], dinner: [], snack: [] };
  foods.forEach((f) => byMeal[f.meal].push(f));
  $("#foodLog").innerHTML = Object.entries(byMeal).map(([meal, items]) => `
    <h4><span style="text-transform:capitalize">${meal}</span> <span class="muted small">${fmt(items.reduce((a, f) => a + f.calories, 0))} kcal</span></h4>
    <ul class="list">${items.map((f) => `<li><span>${esc(f.name)}${f.servings !== 1 ? ` ×${f.servings}` : ""}</span>
      <span class="muted small">${fmt(f.calories)} kcal · P${fmt(f.protein_g)} C${fmt(f.carbs_g)} F${fmt(f.fat_g)}
      <button class="icon" data-del-food="${f.id}" title="Delete" aria-label="Delete ${esc(f.name)}">✕</button></span></li>`).join("") || `<li class="muted small">Nothing logged</li>`}</ul>`).join("");

  $("#dietTips").innerHTML = sugg.tips.map((x) => `<li>${esc(x)}</li>`).join("");
  const r = sugg.remaining;
  $("#mealSuggestions").innerHTML = (r.calories > 0 ? "" : `<p class="muted">You've reached today's calorie target. If you're still hungry, go for vegetables, broth-based soup or lean protein.</p>`)
    + Object.entries(sugg.meals).map(([meal, opts]) => `
    <div class="meal-card"><h4>${meal}</h4>${opts.map((m) => `
      <div class="meal-option"><div>${esc(m.name)}</div>
      <div class="macros">${m.calories} kcal · P${m.protein_g} C${m.carbs_g} F${m.fat_g}</div>
      <button class="ghost" data-log-meal='${esc(JSON.stringify(m))}'>Log this</button></div>`).join("") || `<p class="muted small">No matches for your diet settings.</p>`}
    </div>`).join("");
};

async function logFood(entry) {
  await api("/api/foods", { method: "POST", body: { day: state.day, ...entry } });
  toast(`Logged ${entry.name}`);
  loaders.diet();
}

let searchTimer;
$("#foodSearch").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) return ($("#foodResults").innerHTML = "");
  searchTimer = setTimeout(async () => {
    const items = await api(`/api/food-library?q=${encodeURIComponent(q)}`);
    $("#foodResults").innerHTML = items.slice(0, 8).map((f, i) =>
      `<li data-food-idx="${i}" tabindex="0"><span>${esc(f.name)}</span><span class="muted small">${f.calories} kcal · P${f.protein_g}</span></li>`).join("")
      || `<li class="muted small">No matches. Enter it manually below, or use the calorie counter above.</li>`;
    $("#foodResults")._items = items;
  }, 200);
});
$("#foodResults").addEventListener("click", (e) => {
  const li = e.target.closest("[data-food-idx]");
  if (!li) return;
  const f = $("#foodResults")._items[li.dataset.foodIdx];
  const form = $("#foodForm");
  ["name", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g"].forEach((k) => (form.elements[k].value = f[k] ?? 0));
  $("#foodResults").innerHTML = "";
  $("#foodSearch").value = "";
});
$("#foodForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  const s = Number(d.servings) || 1;
  try {
    await logFood({
      meal: d.meal, name: d.name, servings: s,
      calories: Number(d.calories) * s, protein_g: Number(d.protein_g) * s,
      carbs_g: Number(d.carbs_g) * s, fat_g: Number(d.fat_g) * s, fiber_g: Number(d.fiber_g) * s,
    });
    e.target.reset();
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- AI calorie counter
const ai = { photos: [], items: [] };

// Downscale photos in the browser: keeps uploads small and converts formats
// the browser can decode (e.g. iPhone HEIC in Safari) to JPEG.
async function resizeImage(file, maxDim = 1568, quality = 0.85) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error(`Couldn't read ${file.name}. Try a JPEG or PNG.`));
      i.src = url;
    });
    const scale = Math.min(1, maxDim / Math.max(img.naturalWidth, img.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
  } finally {
    URL.revokeObjectURL(url);
  }
}

$("#aiPhotos").addEventListener("change", async (e) => {
  const files = [...e.target.files].slice(0, 4);
  if (e.target.files.length > 4) toast("Only the first 4 photos will be used");
  ai.photos = [];
  $("#aiPreviews").innerHTML = "";
  for (const f of files) {
    try {
      const blob = await resizeImage(f);
      ai.photos.push(blob);
      const img = document.createElement("img");
      img.src = URL.createObjectURL(blob);
      img.alt = f.name;
      $("#aiPreviews").appendChild(img);
    } catch (err) { toast(err.message, true); }
  }
});

const AI_NUMS = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g"];
function renderAiItems() {
  $("#aiItems").innerHTML = ai.items.map((it, i) => `<tr data-i="${i}">
    <td><input type="checkbox" data-k="keep" ${it.keep ? "checked" : ""} aria-label="Include"></td>
    <td><input data-k="name" value="${esc(it.name)}" aria-label="Food"></td>
    <td><input data-k="portion" value="${esc(it.portion)}" aria-label="Portion"></td>
    ${AI_NUMS.map((k) => `<td><input type="number" min="0" step="1" data-k="${k}" value="${Math.round(it[k] ?? 0)}" aria-label="${k}"></td>`).join("")}
    <td><span class="conf ${it.confidence}" title="AI confidence">${it.confidence}</span></td></tr>`).join("")
    || `<tr><td colspan="9" class="muted">No foods recognised.</td></tr>`;
  updateAiTotals();
}
function updateAiTotals() {
  const kept = ai.items.filter((i) => i.keep);
  const sum = (k) => Math.round(kept.reduce((a, i) => a + (Number(i[k]) || 0), 0));
  $("#aiTotals").textContent = `${sum("calories")} kcal · P${sum("protein_g")} C${sum("carbs_g")} F${sum("fat_g")}`;
  $("#aiLog").disabled = kept.length === 0;
}
$("#aiItems").addEventListener("input", (e) => {
  const row = e.target.closest("tr[data-i]");
  if (!row) return;
  const item = ai.items[row.dataset.i];
  const k = e.target.dataset.k;
  item[k] = k === "keep" ? e.target.checked : e.target.type === "number" ? Number(e.target.value) : e.target.value;
  updateAiTotals();
});
function resetAi() {
  ai.items = [];
  ai.photos = [];
  $("#aiForm").reset();
  $("#aiPreviews").innerHTML = "";
  $("#aiResult").classList.add("hidden");
}
$("#aiForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const description = e.target.elements.description.value.trim();
  if (!description && !ai.photos.length) return toast("Describe your meal or add a photo", true);
  const fd = new FormData();
  fd.append("description", description);
  fd.append("meal", e.target.elements.meal.value);
  ai.photos.forEach((b, i) => fd.append("photos", b, `photo${i + 1}.jpg`));
  const btn = $("#aiSubmit");
  btn.disabled = true;
  btn.textContent = "Analysing…";
  try {
    const res = await fetch("/api/foods/analyze", { method: "POST", body: fd });
    if (res.status === 401) { location.href = "/login"; return; }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Analysis failed");
    ai.items = data.items.map((i) => ({ ...i, keep: true }));
    $("#aiMeal").value = data.meal_guess;
    $("#aiNotes").textContent = data.notes || "";
    renderAiItems();
    $("#aiResult").classList.remove("hidden");
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Estimate calories";
  }
});
$("#aiLog").addEventListener("click", (e) => withBusy(e.target, async () => {
  const meal = $("#aiMeal").value;
  const items = ai.items.filter((i) => i.keep && i.name.trim()).map((i) => ({
    day: state.day, meal, servings: 1,
    name: (i.portion ? `${i.name.trim()} (${i.portion.trim()})` : i.name.trim()).slice(0, 200),
    ...Object.fromEntries(AI_NUMS.map((k) => [k, Number(i[k]) || 0])),
  }));
  await api("/api/foods/bulk", { method: "POST", body: { items } });
  toast(`Logged ${items.length} item${items.length === 1 ? "" : "s"} to ${meal}`);
  resetAi();
  loaders.diet();
}));
$("#aiDiscard").addEventListener("click", resetAi);

// ================================================================ WORKOUTS
function addSetRow(v = {}) {
  const row = document.createElement("div");
  row.className = "set-row";
  row.innerHTML = `<input placeholder="Exercise" data-k="exercise" value="${esc(v.exercise || "")}" aria-label="Exercise">
    <input type="number" placeholder="Reps" data-k="reps" min="0" value="${esc(v.reps ?? "")}" aria-label="Reps">
    <input type="number" placeholder="kg" step="0.5" min="0" data-k="weight_kg" value="${esc(v.weight_kg ?? "")}" aria-label="Weight kg">
    <button type="button" class="icon" title="Remove set" aria-label="Remove set">✕</button>`;
  row.querySelector("button").onclick = () => row.remove();
  $("#setRows").appendChild(row);
}
$("#addSet").onclick = () => {
  const last = $$("#setRows .set-row").at(-1);
  addSetRow(last ? { exercise: $('[data-k="exercise"]', last).value, weight_kg: $('[data-k="weight_kg"]', last).value } : {});
};

function nowLocalInput() { return localIso().slice(0, 16); }

async function loadTodaysPlan() {
  const plan = await api("/api/plans/active");
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][new Date().getDay()];
  const session = plan?.days.find((d) => d.weekday === wd);
  if (!session) return toast(plan ? "Today is a rest day in your plan" : "No active plan. Build one in Plans", true);
  const f = $("#activityForm").elements;
  f.name.value = session.title;
  f.start_time.value = nowLocalInput();
  $("#setRows").innerHTML = "";
  if (session.type === "cardio") {
    f.activity_type.value = "running";
    f.minutes.value = session.minutes;
  } else {
    f.activity_type.value = "strength_training";
    f.minutes.value = 60;
    for (const ex of session.exercises) {
      const reps = parseInt(ex.reps, 10);
      for (let i = 0; i < ex.sets; i++) addSetRow({ exercise: ex.exercise, reps: Number.isNaN(reps) || /s$/.test(ex.reps) ? "" : reps });
    }
  }
  toast(`Loaded ${session.title}. Fill in your weights`);
}
$("#loadPlan").onclick = () => loadTodaysPlan().catch((e) => toast(e.message, true));

loaders.exercise = async () => {
  const f = $("#activityForm").elements.start_time;
  if (!f.value) f.value = nowLocalInput();
  const filter = $("#actFilter").value;
  const acts = (await api("/api/activities?limit=200")).filter((a) => !filter || a.source === filter);
  $("#activityList").innerHTML = acts.map((a) => {
    const sets = a.sets.length ? summarizeSets(a.sets) : "";
    const bits = [minutes(a.duration_s), a.distance_m && `${(a.distance_m / 1000).toFixed(2)} km`, a.calories && `${fmt(a.calories)} kcal`,
      a.avg_hr && `♥ ${fmt(a.avg_hr)}${a.max_hr ? `/${fmt(a.max_hr)}` : ""}`, a.aerobic_te != null && `TE ${a.aerobic_te.toFixed(1)}`].filter(Boolean).join(" · ");
    return `<li><div><strong>${esc(a.name)}</strong> <span class="tag ${a.source}">${a.source}</span>
      <div class="meta">${new Date(a.start_time).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} · ${bits}</div></div>
      <button class="icon" data-del-act="${a.id}" title="Delete" aria-label="Delete ${esc(a.name)}">✕</button>
      ${sets ? `<div class="sets">${sets}</div>` : ""}</li>`;
  }).join("") || `<li class="muted">No workouts yet. Log one here or connect Garmin in Settings.</li>`;
};
$("#actFilter").onchange = () => loaders.exercise();

function summarizeSets(sets) {
  const by = new Map();
  for (const s of sets) {
    const k = s.exercise;
    if (!by.has(k)) by.set(k, []);
    by.get(k).push(s.weight_kg ? `${s.reps ?? "?"}×${s.weight_kg}kg` : `${s.reps ?? "?"}`);
  }
  return [...by].map(([ex, v]) => `${esc(ex)}: ${esc(v.join(", "))}`).join(" · ");
}

$("#activityForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  const sets = $$("#setRows .set-row").map((r) => ({
    exercise: $('[data-k="exercise"]', r).value.trim(),
    reps: numOrNull($('[data-k="reps"]', r).value),
    weight_kg: numOrNull($('[data-k="weight_kg"]', r).value),
  })).filter((s) => s.exercise);
  try {
    await api("/api/activities", { method: "POST", body: {
      start_time: d.start_time, activity_type: d.activity_type,
      name: d.name || e.target.elements.activity_type.selectedOptions[0].text,
      duration_s: Number(d.minutes) * 60,
      distance_m: d.distance_km ? Number(d.distance_km) * 1000 : null,
      calories: numOrNull(d.calories), avg_hr: numOrNull(d.avg_hr), notes: d.notes, sets,
    } });
    e.target.reset();
    $("#setRows").innerHTML = "";
    toast("Workout saved 💪");
    loaders.exercise();
  } catch (err) { toast(err.message, true); }
});

// ================================================================ PLANS
function renderPlanDay(day, compact = false) {
  if (day.type === "rest") return `<div class="plan-day"><div class="wd">${day.weekday}</div><strong>Rest / mobility</strong><p class="muted small">Easy walk and stretching. Let your Garmin recovery time come down.</p></div>`;
  if (day.type === "cardio") return `<div class="plan-day cardio"><div class="wd">${day.weekday} · cardio</div><strong>${esc(day.title)}</strong>
    <p class="small">${day.minutes} min in <b>${esc(day.zone)}</b>. Set your fenix data screen to show HR zone.</p></div>`;
  const rest = (x) => (x.rest_s ? ` · ${x.rest_s}s rest` : "");
  const changes = !compact && day.changes?.length
    ? `<details class="small"><summary class="muted">${day.changes.length} adjustment${day.changes.length > 1 ? "s" : ""} for your goal</summary><ul class="tips">${day.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>` : "";
  return `<div class="plan-day strength"><div class="wd">${day.weekday} · strength${day.garmin_source_id ? " · from Garmin" : ""}</div><strong>${esc(day.title)}</strong>
    <table>${day.exercises.map((x) => `<tr><td>${esc(x.exercise)}</td><td>${x.sets}×${esc(x.reps)}${compact ? "" : rest(x)}</td></tr>`).join("")}</table>${changes}</div>`;
}

loaders.plans = async () => {
  const [plans, active, watch] = await Promise.all([api("/api/plans"), api("/api/plans/active"), api("/api/garmin/watch-plan").catch(() => null)]);
  renderWatchStatus(watch);
  $("#activePlan").innerHTML = active ? `<div class="card"><h3>Active plan: ${esc(active.name)}</h3>
    <div class="plan-days">${active.days.map((d) => renderPlanDay(d)).join("")}</div>
    <h4>Progression</h4><ul class="tips">${active.progression.map((p) => `<li><b>Week ${p.week}:</b> ${esc(p.note)}</li>`).join("")}</ul></div>` : "";
  $("#planList").innerHTML = plans.map((p) => `<li><span>${esc(p.name)} <span class="muted small">${p.weeks} wk · ${new Date(p.created_at).toLocaleDateString()}</span>
    ${p.active ? '<span class="tag garmin">active</span>' : ""}</span>
    <span>${p.active ? "" : `<button class="ghost small-btn" data-activate-plan="${p.id}">Activate</button>`}
    <button class="icon" data-del-plan="${p.id}" title="Delete" aria-label="Delete plan">✕</button></span></li>`).join("") || `<li class="muted">No plans yet. Pick a goal above and build one.</li>`;
};

function renderWatchStatus(w) {
  const el = $("#watchPlanStatus");
  if (!w?.sending) { el.innerHTML = ""; return; }
  el.innerHTML = `✓ Sending your plan to your fenix. Scheduled on your Garmin calendar through ${esc(w.scheduled_until || "–")}.
    <button type="button" class="ghost small-btn" id="stopWatch">Stop sending</button>`;
  $("#stopWatch").onclick = (e) => withBusy(e.target, async () => {
    if (!confirm("Remove this app's upcoming workouts from your Garmin calendar?")) return;
    const r = await api("/api/garmin/watch-plan/stop", { method: "POST" });
    toast(`Removed ${r.removed} scheduled workouts from Garmin`);
    loaders.plans();
  });
}

$("#loadGarminWorkouts").addEventListener("click", (e) => withBusy(e.target, async () => {
  const [list, goals] = await Promise.all([api("/api/garmin/workouts"), api("/api/goals")]);
  if (!list.length) { $("#garminPlanBody").innerHTML = `<p class="muted">No saved workouts found in your Garmin Connect account.</p>`; return; }
  const days = Math.min(6, Math.max(2, goals.workouts_per_week || 4));
  let picked = 0;
  $("#garminPlanBody").innerHTML = `<form class="form" id="garminPlanForm">
    <ul class="list">${list.map((w) => {
      const pre = ["strength_training", "hiit"].includes(w.sport) && picked++ < days;
      return `<li><label class="check"><input type="checkbox" name="w" value="${esc(w.id)}" ${pre ? "checked" : ""}>
        ${esc(w.name)}</label><span class="muted small">${esc(w.sport.replace(/_/g, " "))}${w.minutes ? ` · ${w.minutes} min` : ""}</span></li>`;
    }).join("")}</ul>
    <div class="row">
      <label>Training days / week <select name="days">${[2, 3, 4, 5, 6].map((n) => `<option ${n === days ? "selected" : ""}>${n}</option>`).join("")}</select></label>
    </div>
    <label class="check"><input type="checkbox" name="send" checked> Send to my fenix (Garmin calendar)</label>
    <button type="submit">Build my plan from these</button>
    <ul class="auto-result" id="garminPlanResult"></ul></form>`;
  $("#garminPlanForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.target;
    const ids = $$("input[name=w]:checked", f).map((x) => x.value);
    if (!ids.length) return toast("Pick at least one workout", true);
    const btn = $("button[type=submit]", f);
    withBusy(btn, async () => {
      btn.textContent = f.elements.send.checked ? "Building and sending to Garmin…" : "Building…";
      try {
        const r = await api("/api/garmin/plan-from-workouts", { method: "POST", body: { workout_ids: ids, days_per_week: Number(f.elements.days.value), send_to_watch: f.elements.send.checked } });
        const p = r.pushed;
        $("#garminPlanResult").innerHTML = [`Plan built from: ${r.used.join(", ")}`,
          ...r.changes.map((c) => `Adjusted: ${c}`),
          p ? `Sent to your fenix: ${p.saved.length} workouts in Garmin Connect, ${p.scheduled} sessions on your calendar` : "Not sent to Garmin",
          ...((p && p.errors) || []).map((x) => `⚠ ${x}`)].map((x) => `<li>${esc(x)}</li>`).join("");
        toast("Plan ready ✓");
        loaders.plans();
      } finally { btn.textContent = "Build my plan from these"; }
    });
  });
}));

$("#planForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  let days = numOrNull(d.days_per_week);
  if (days == null) {
    const g = await api("/api/goals");
    if (g.saved && g.workouts_per_week >= 2) days = Math.min(6, g.workouts_per_week);
  }
  try {
    await api("/api/plans/generate", { method: "POST", body: {
      goal: d.goal, weeks: Number(d.weeks), include_cardio: !!d.include_cardio,
      days_per_week: days, equipment: d.equipment || null,
    } });
    toast("Plan built and set as active");
    loaders.plans();
  } catch (err) { toast(err.message, true); }
});

// ================================================================ PROGRESS
$$("#rangeSeg button").forEach((b) => b.addEventListener("click", () => {
  $$("#rangeSeg button").forEach((x) => x.classList.toggle("active", x === b));
  state.progressDays = Number(b.dataset.days);
  loaders.progress();
}));

loaders.progress = async () => {
  const days = state.progressDays;
  const weeks = Math.max(4, Math.ceil(days / 7));
  const [series, weekly, goals, exercises] = await Promise.all([
    api(`/api/nutrition/trends?days=${days}`), api(`/api/nutrition/weekly?weeks=${Math.min(weeks, 52)}`),
    api("/api/goals"), api("/api/progress/exercises"),
  ]);
  const labels = series.map((x) => shortDay(x.day));
  const logged = series.filter((x) => x.logged);

  drawChart("calChart", {
    data: { labels, datasets: [
      barDs("Eaten", series.map((x) => (x.logged ? x.calories : null)), css("--series-1")),
      lineDs("Burned (Garmin)", series.map((x) => x.burned), css("--series-2")),
      targetDs("Target", series.map((x) => x.target_calories)),
    ] },
    options: { scales: { y: { title: { display: true, text: "kcal" } } } },
  });
  if (logged.length) {
    const avg = (k) => Math.round(logged.reduce((a, x) => a + x[k], 0) / logged.length);
    const onTarget = logged.filter((x) => Math.abs(x.calories - x.target_calories) <= 0.1 * x.target_calories).length;
    const nets = series.filter((x) => x.net != null);
    $("#calSummary").textContent = `Logged ${logged.length} of ${series.length} days · average ${fmt(avg("calories"))} kcal vs ${fmt(avg("target_calories"))} target · within ±10% on ${onTarget} days`
      + (nets.length ? ` · average balance ${fmt(Math.round(nets.reduce((a, x) => a + x.net, 0) / nets.length))} kcal/day` : "") + ".";
  } else $("#calSummary").textContent = "No food logged in this period yet.";

  drawChart("macroChart", {
    data: { labels, datasets: [
      lineDs("Protein", series.map((x) => (x.logged ? x.protein_g : null)), css("--protein"), { pointRadius: 2 }),
      lineDs("Carbs", series.map((x) => (x.logged ? x.carbs_g : null)), css("--carbs"), { pointRadius: 2 }),
      lineDs("Fat", series.map((x) => (x.logged ? x.fat_g : null)), css("--fat"), { pointRadius: 2 }),
    ] },
    options: { scales: { y: { title: { display: true, text: "grams" } } } },
  });

  const pct = (a, b) => (a == null || !b ? "" : ` <span class="muted small">${Math.round((a / b) * 100)}%</span>`);
  $("#weeklyTable tbody").innerHTML = weekly.slice().reverse().map((w) => `<tr>
    <td>${shortDay(w.week_start)}</td><td>${w.days_logged}/7</td>
    <td>${fmt(w.avg_calories)}</td><td>${fmt(w.avg_target)}</td><td>${w.days_logged ? `${w.days_on_target}/${w.days_logged}` : "–"}</td>
    <td>${fmt(w.avg_protein_g)}</td><td>${fmt(w.avg_carbs_g)}</td><td>${fmt(w.avg_fat_g)}</td><td>${fmt(w.avg_fiber_g)}</td>
    <td>${w.workouts}/${w.workouts_goal}${w.workouts >= w.workouts_goal && w.workouts_goal ? " ✓" : ""}</td>
    <td>${fmt(w.active_minutes)}${pct(w.active_minutes, w.active_minutes_goal)}</td>
    <td>${fmt(w.avg_steps)}</td><td>${w.avg_sleep_h ?? "–"}</td>
    <td>${w.weight_end != null ? fmt(w.weight_end, 1) + (w.weight_start != null && w.weight_end !== w.weight_start ? ` <span class="muted small">(${w.weight_end - w.weight_start > 0 ? "+" : ""}${(w.weight_end - w.weight_start).toFixed(1)})</span>` : "") : "–"}</td></tr>`).join("");

  // body weight
  const wpts = series.filter((x) => x.weight_kg != null);
  drawChart("weightChart", {
    data: { labels: wpts.map((x) => shortDay(x.day)), datasets: [
      lineDs("Weight", wpts.map((x) => x.weight_kg), css("--series-1"), { pointRadius: 3 }),
      ...(goals.target_weight_kg ? [targetDs("Target", wpts.map(() => goals.target_weight_kg))] : []),
    ] },
    options: { plugins: { legend: { display: !!goals.target_weight_kg } }, scales: { y: { beginAtZero: false, title: { display: true, text: "kg" } } } },
  });
  $("#weightSummary").textContent = wpts.length >= 2
    ? `${(wpts.at(-1).weight_kg - wpts[0].weight_kg > 0 ? "+" : "")}${(wpts.at(-1).weight_kg - wpts[0].weight_kg).toFixed(1)} kg over this period`
      + (goals.target_weight_kg ? ` · ${Math.abs(wpts.at(-1).weight_kg - goals.target_weight_kg).toFixed(1)} kg to target` : "") + "."
    : "Log a few weigh-ins (or sync a Garmin Index scale) to see your trend.";

  // workouts per week vs goal
  drawChart("volumeChart", {
    data: { labels: weekly.map((w) => shortDay(w.week_start)), datasets: [
      barDs("Workouts", weekly.map((w) => w.workouts), css("--series-1")),
      targetDs("Goal", weekly.map((w) => w.workouts_goal)),
    ] },
    options: {
      scales: { y: { ticks: { precision: 0 } } },
      plugins: { tooltip: { callbacks: { footer: (items) => `${fmt(weekly[items[0].dataIndex].active_minutes)} active minutes` } } },
    },
  });

  // strength progress
  const pick = $("#exercisePick");
  const prev = pick.value;
  pick.innerHTML = exercises.map((e) => `<option value="${esc(e.name)}">${esc(e.name)} (${e.sessions})</option>`).join("")
    || `<option value="">No sets logged yet</option>`;
  if (prev && exercises.some((e) => e.name === prev)) pick.value = prev;
  await drawStrength();

  // wellness: separate small charts (never dual-axis)
  drawChart("stepsChart", {
    data: { labels, datasets: [barDs("Steps", series.map((x) => x.steps), css("--series-1")), targetDs("Goal", series.map(() => goals.steps_target))] },
    options: { plugins: { legend: { display: false } } },
  });
  drawChart("rhrChart", {
    data: { labels, datasets: [lineDs("Resting HR (bpm)", series.map((x) => x.resting_hr), css("--series-2"), { pointRadius: 2 })] },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: false } } },
  });
  drawChart("sleepChart", {
    data: { labels, datasets: [barDs("Sleep (h)", series.map((x) => x.sleep_h), css("--series-1")), targetDs("Goal", series.map(() => goals.sleep_target_h))] },
    options: { plugins: { legend: { display: false } } },
  });
};

async function drawStrength() {
  const name = $("#exercisePick").value;
  if (!name) {
    charts.strengthChart?.destroy();
    $("#strengthSummary").textContent = "Log sets (exercise, reps, weight) with your workouts to track strength over time.";
    return;
  }
  const pts = await api(`/api/progress/exercise?name=${encodeURIComponent(name)}`);
  drawChart("strengthChart", {
    data: { labels: pts.map((p) => shortDay(p.day)), datasets: [
      lineDs("Estimated 1-rep max", pts.map((p) => p.est_1rm_kg), css("--series-1"), { pointRadius: 3 }),
      lineDs("Heaviest set", pts.map((p) => p.top_weight_kg), css("--series-2"), { pointRadius: 3 }),
    ] },
    options: {
      scales: { y: { beginAtZero: false, title: { display: true, text: "kg" } } },
      plugins: { tooltip: { callbacks: { footer: (items) => { const p = pts[items[0].dataIndex]; return `${p.sets} sets · ${p.reps} reps · ${fmt(p.volume_kg)} kg volume`; } } } },
    },
  });
  const first = pts.find((p) => p.est_1rm_kg), last = [...pts].reverse().find((p) => p.est_1rm_kg);
  $("#strengthSummary").textContent = first && last && first !== last
    ? `Estimated 1RM ${first.est_1rm_kg} → ${last.est_1rm_kg} kg (${last.est_1rm_kg >= first.est_1rm_kg ? "+" : ""}${(last.est_1rm_kg - first.est_1rm_kg).toFixed(1)} kg) across ${pts.length} sessions.`
    : `${pts.length} session${pts.length === 1 ? "" : "s"} logged.`;
}
$("#exercisePick").onchange = () => drawStrength().catch((e) => toast(e.message, true));

$("#weightForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  try {
    await api("/api/weights", { method: "POST", body: { day: isoDate(new Date()), weight_kg: Number(d.weight_kg), body_fat_pct: numOrNull(d.body_fat_pct) } });
    e.target.reset();
    toast("Weight logged");
    loaders.progress();
  } catch (err) { toast(err.message, true); }
});

// ================================================================ SETTINGS
const REMINDER_LABELS = {
  breakfast: "Log breakfast", lunch: "Log lunch", dinner: "Log dinner",
  workout: "Planned workout", weigh_in: "Weigh-in", evening_review: "Evening nutrition check-in",
};
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

loaders.settings = async () => {
  const [p, g, rem] = await Promise.all([api("/api/profile"), api("/api/goals"), api("/api/reminders")]);
  const pf = $("#profileForm");
  for (const [k, v] of Object.entries(p)) if (pf.elements[k]) pf.elements[k].value = Array.isArray(v) ? v.join(", ") : v;
  const gf = $("#goalsForm");
  for (const [k, v] of Object.entries(g)) if (gf.elements[k] && k !== "follow_garmin") gf.elements[k].value = v ?? "";
  gf.elements.follow_garmin.checked = !!g.follow_garmin;

  $("#reminderRows").innerHTML = rem.map((r) => `<div class="rem-row" data-key="${r.key}">
    <input type="checkbox" data-k="enabled" ${r.enabled ? "checked" : ""} aria-label="Enable ${REMINDER_LABELS[r.key]}">
    <span>${REMINDER_LABELS[r.key]}</span>
    <input type="time" data-k="time" value="${r.time}" aria-label="Time">
    <div class="rem-days">${DAYS.map((d, i) => `<label><input type="checkbox" data-day="${i}" ${r.days.includes(i) ? "checked" : ""}>${d}</label>`).join("")}</div>
  </div>`).join("");
  renderNotifyState();
  loadStrava();
  const gs = await loadGarmin();
  renderAutoSetup($("#goalsCard [data-auto-setup]"), gs.connected);
};

$("#profileForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  try {
    await api("/api/profile", { method: "PUT", body: {
      ...d,
      birth_year: Number(d.birth_year), height_cm: Number(d.height_cm), weight_kg: Number(d.weight_kg),
      training_days: Number(d.training_days),
      allergies: d.allergies.split(",").map((s) => s.trim()).filter(Boolean),
    } });
    toast("Profile saved");
  } catch (err) { toast(err.message, true); }
});

$("#goalsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  delete d.follow_garmin;
  const body = Object.fromEntries(Object.entries(d).map(([k, v]) => [k, numOrNull(v)]));
  for (const k of ["fiber_target_g", "steps_target", "sleep_target_h", "workouts_per_week", "active_minutes_per_week"]) if (body[k] == null) body[k] = 0;
  body.follow_garmin = e.target.elements.follow_garmin.checked;
  try {
    await api("/api/goals", { method: "PUT", body });
    toast("Goals saved");
  } catch (err) { toast(err.message, true); }
});

$("#remindersForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = $$("#reminderRows .rem-row").map((row) => ({
    key: row.dataset.key,
    enabled: $('[data-k="enabled"]', row).checked,
    time: $('[data-k="time"]', row).value || "12:00",
    days: $$("[data-day]", row).filter((x) => x.checked).map((x) => Number(x.dataset.day)),
  }));
  try {
    await api("/api/reminders", { method: "PUT", body });
    toast("Reminders saved");
    if (body.some((r) => r.enabled) && "Notification" in window && Notification.permission === "default") await askNotify();
    checkReminders();
  } catch (err) { toast(err.message, true); }
});

function renderNotifyState() {
  const el = $("#notifyState");
  if (!("Notification" in window)) {
    el.innerHTML = `<p class="muted">This browser doesn't support notifications. Reminders show as banners inside the app.</p>`;
    return;
  }
  const p = Notification.permission;
  el.innerHTML = p === "granted"
    ? `<p class="muted">✓ Browser notifications are on. You'll get them while the app is open in a tab or installed on your home screen.</p>`
    : p === "denied"
      ? `<p class="warn-text">Notifications are blocked for this site. Allow them in your browser's site settings, or rely on in-app banners.</p>`
      : `<p><button type="button" class="ghost small-btn" id="notifyBtn">Turn on browser notifications</button></p>`;
  $("#notifyBtn")?.addEventListener("click", askNotify);
}
async function askNotify() {
  try { await Notification.requestPermission(); } catch {}
  renderNotifyState();
}

// ---------------------------------------------------------------- Garmin
async function loadGarmin() {
  const s = await api("/api/garmin/status");
  $("#garminStatus").textContent = s.connected
    ? `✓ Connected. Last sync: ${s.last_sync ? new Date(s.last_sync).toLocaleString() : "never"}.`
    : s.mfa_pending ? "Waiting for verification code." : "Not connected.";
  $("#garminLogin").classList.toggle("hidden", s.connected || s.mfa_pending);
  $("#garminMfa").classList.toggle("hidden", !s.mfa_pending);
  $("#garminConnected").classList.toggle("hidden", !s.connected);
  return s;
}
$("#garminLogin").addEventListener("submit", (e) => {
  e.preventDefault();
  withBusy($("button", e.target), async () => {
    const r = await api("/api/garmin/login", { method: "POST", body: formData(e.target) });
    e.target.reset();
    toast(r.status === "needs_mfa" ? "Enter the code Garmin sent you" : "Connected to Garmin");
    await loadGarmin();
    if (r.status === "ok") await afterGarminConnected();
  });
});
$("#garminMfa").addEventListener("submit", (e) => {
  e.preventDefault();
  withBusy($("button", e.target), async () => {
    await api("/api/garmin/mfa", { method: "POST", body: formData(e.target) });
    e.target.reset();
    toast("Connected to Garmin");
    await loadGarmin();
    await afterGarminConnected();
  });
});
async function afterGarminConnected() {
  const p = await api("/api/profile");
  if (!p.setup_done) {
    // first connection: the one-tap setup pulls 30 days of history itself
    store.set("setupHidden", "0");
    toast("Garmin connected. Now tap “Set it all up for me”");
    show("dashboard");
    return;
  }
  $("#syncDays").value = 30;
  $("#syncBtn").click();
}

$("#syncBtn").addEventListener("click", (e) => withBusy(e.target, async () => {
  $("#syncResult").textContent = "Syncing…";
  const r = await api("/api/garmin/sync", { method: "POST", body: { days: Number($("#syncDays").value) || 7 } });
  $("#syncResult").textContent = `Workouts: ${r.activities_added} new, ${r.activities_updated} updated · Days of steps/HR/sleep: ${r.days_synced} · Weigh-ins: ${r.weights}`
    + (r.errors.length ? `\nWarnings:\n- ${r.errors.join("\n- ")}` : "");
  toast("Garmin sync complete");
  loadGarmin();
}));
$("#logoutBtn").addEventListener("click", async () => {
  await api("/api/garmin/logout", { method: "POST" });
  $("#syncResult").textContent = "";
  toast("Disconnected from Garmin");
  loadGarmin();
});

// ---------------------------------------------------------------- Strava
async function loadStrava() {
  const el = $("#stravaBody");
  let s;
  try { s = await api("/api/strava/status"); } catch { el.innerHTML = `<p class="muted">Couldn't check Strava.</p>`; return; }
  if (!s.configured) {
    const domain = esc(location.host);
    el.innerHTML = `<p class="small muted">Strava needs a free API app (one-time, about 2 minutes):</p>
      <ol class="steps-list">
        <li>Go to <a href="https://www.strava.com/settings/api" target="_blank" rel="noopener">strava.com/settings/api</a> and create an app.
          Name: <code>Health Tracker</code>, Category: <code>Training</code>, Website: <code>https://${domain}</code>.</li>
        <li><b>Authorization Callback Domain:</b> <code>${domain}</code></li>
        <li>Copy the <b>Client ID</b> and <b>Client Secret</b> into your Render service (Environment) as
          <code>STRAVA_CLIENT_ID</code> and <code>STRAVA_CLIENT_SECRET</code>, then save. Render redeploys automatically.</li>
        <li>Come back here and tap <b>Connect Strava</b>.</li>
      </ol>`;
    return;
  }
  if (!s.connected) {
    el.innerHTML = `<p class="small muted">Import your Strava activities. Sessions that also come from Garmin are only counted once.</p>
      <button type="button" id="stravaConnect">Connect Strava</button>`;
    $("#stravaConnect").onclick = () => { location.href = "/api/strava/connect"; };
    return;
  }
  el.innerHTML = `<p>✓ Connected${s.athlete ? ` as <b>${esc(s.athlete)}</b>` : ""}. Last sync: ${s.last_sync ? new Date(s.last_sync).toLocaleString() : "never"}.</p>
    <div class="row actions"><button type="button" id="stravaSync">Sync now</button><button type="button" class="ghost" id="stravaOff">Disconnect</button></div>
    <pre class="small" id="stravaResult"></pre>`;
  $("#stravaSync").onclick = (e) => withBusy(e.target, async () => {
    const r = await api("/api/strava/sync", { method: "POST", body: { days: 60 } });
    $("#stravaResult").textContent = `New: ${r.activities_added} · updated: ${r.activities_updated} · already from Garmin: ${r.duplicates_skipped}`
      + (r.errors.length ? `\n${r.errors.join("\n")}` : "");
    toast("Strava sync complete");
  });
  $("#stravaOff").onclick = (e) => withBusy(e.target, async () => {
    if (!confirm("Disconnect Strava? Imported activities stay in the app.")) return;
    await api("/api/strava/disconnect", { method: "POST" });
    loadStrava();
  });
}

// Coming back from Strava's approval page
(() => {
  const q = new URLSearchParams(location.search);
  if (q.has("strava")) toast("Strava connected ✓ Your activities are being imported");
  if (q.has("strava_error")) toast(q.get("strava_error"), true);
  if (q.has("strava") || q.has("strava_error")) history.replaceState(null, "", location.pathname + location.hash);
})();

// Sync quietly when the app opens (server skips if the last sync is recent).
async function autoSync() {
  api("/api/strava/sync-if-stale", { method: "POST" }).then((r) => {
    if (r.synced && r.activities_added && ["dashboard", "exercise", "progress"].includes(state.view)) loaders[state.view]?.();
  }).catch(() => {});
  try {
    const r = await api("/api/garmin/sync-if-stale", { method: "POST", body: { max_age_minutes: 60 } });
    if (!r.synced) return;
    const badge = $("#syncBadge");
    badge.textContent = "✓ Garmin synced";
    badge.classList.remove("hidden");
    setTimeout(() => badge.classList.add("hidden"), 5000);
    if (r.activities_added || r.days_synced) loaders[state.view]?.();
  } catch {}
}

// ================================================================ reminders
async function checkReminders() {
  let due;
  try { due = await api(`/api/reminders/due?now=${encodeURIComponent(localIso())}`); } catch { return; }
  if (!due.length) return;
  for (const r of due) {
    showBanner(r);
    if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
      try { new Notification(r.title, { body: r.body, icon: "/static/icon-192.png", tag: r.key }); } catch {}
    }
  }
  api("/api/reminders/ack", { method: "POST", body: { day: isoDate(new Date()), keys: due.map((r) => r.key) } }).catch(() => {});
}
function showBanner(r) {
  const target = { breakfast: "diet", lunch: "diet", dinner: "diet", evening_review: "diet", workout: "exercise", weigh_in: "progress" }[r.key];
  const action = { workout: "Start", weigh_in: "Log weight" }[r.key] || "Log now";
  const el = document.createElement("div");
  el.className = "banner";
  el.innerHTML = `<div class="txt"><strong>${esc(r.title)}</strong><span>${esc(r.body)}</span></div>
    <button class="small-btn" data-act>${action}</button><button class="icon" data-close aria-label="Dismiss">✕</button>`;
  $("[data-close]", el).onclick = () => el.remove();
  $("[data-act]", el).onclick = () => {
    el.remove();
    if (r.key === "weigh_in") return $("#weightDialog").showModal();
    if (r.key === "workout") { show("exercise"); return loadTodaysPlan().catch(() => {}); }
    show(target, "#aiForm textarea");
  };
  $("#banners").appendChild(el);
}

// ================================================================ global wiring
document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-del-food],[data-del-act],[data-del-plan],[data-activate-plan],[data-log-meal],[data-goto],[data-start-session]");
  if (!t) return;
  try {
    if (t.dataset.goto) { e.preventDefault(); show(t.dataset.goto, t.dataset.focus); }
    else if (t.hasAttribute("data-start-session")) { show("exercise"); await loadTodaysPlan(); }
    else if (t.dataset.delFood) { await api(`/api/foods/${t.dataset.delFood}`, { method: "DELETE" }); loaders.diet(); }
    else if (t.dataset.delAct && confirm("Delete this workout?")) { await api(`/api/activities/${t.dataset.delAct}`, { method: "DELETE" }); loaders.exercise(); }
    else if (t.dataset.delPlan && confirm("Delete this plan?")) { await api(`/api/plans/${t.dataset.delPlan}`, { method: "DELETE" }); loaders.plans(); }
    else if (t.dataset.activatePlan) { await api(`/api/plans/${t.dataset.activatePlan}/activate`, { method: "POST" }); loaders.plans(); }
    else if (t.dataset.logMeal) {
      const m = JSON.parse(t.dataset.logMeal);
      await logFood({ meal: m.meal, name: m.name, servings: 1, calories: m.calories, protein_g: m.protein_g, carbs_g: m.carbs_g, fat_g: m.fat_g, fiber_g: m.fiber_g || 0 });
    }
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- theme
function applyTheme(choice) {
  let t = choice;
  if (t === "auto") t = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  if (t === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  $('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#f3f5f8" : "#0b0f14");
  $$("[data-theme-choice]").forEach((b) => b.classList.toggle("active", b.dataset.themeChoice === choice));
}
const savedTheme = () => store.get("theme") || "dark";
$$("[data-theme-choice]").forEach((b) => b.addEventListener("click", () => {
  store.set("theme", b.dataset.themeChoice);
  applyTheme(b.dataset.themeChoice);
  loaders[state.view]?.(); // redraw charts with the new colours
}));
matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", () => {
  if (savedTheme() === "auto") { applyTheme("auto"); loaders[state.view]?.(); }
});
applyTheme(savedTheme());

$$("#tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
$("#day").addEventListener("change", (e) => e.target.value && setDay(e.target.value));
$("#prevDay").onclick = () => shiftDay(-1);
$("#nextDay").onclick = () => shiftDay(1);
$("#todayBtn").onclick = () => setDay(isoDate(new Date()));
$("#day").value = state.day;

$("#signOut").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  location.href = "/login";
});
api("/api/auth/status").then((s) => $("#accountCard").classList.toggle("hidden", !s.enabled)).catch(() => {});

(async () => {
  try {
    const { configured } = await api("/api/ai/status");
    if (!configured) {
      $("#aiForm").classList.add("hidden");
      $("#aiDisabled").classList.remove("hidden");
    }
  } catch {}
})();

const initial = location.hash.slice(1);
show(loaders[initial] ? initial : "dashboard");
autoSync();
checkReminders();
setInterval(checkReminders, 60_000);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  // coming back to the app: roll the date over if needed and refresh
  const today = isoDate(new Date());
  if (state.day === state.openedOn && today !== state.openedOn) { state.day = today; $("#day").value = today; }
  state.openedOn = today;
  loaders[state.view]?.();
  autoSync();
});
