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

// ---------------------------------------------------------------- units (stored metric, shown either way)
const U = {
  imperial: (() => { try { return localStorage.getItem("units") === "imperial"; } catch { return false; } })(),
  defs: { mass: ["kg", "lb", 2.20462], length: ["cm", "in", 1 / 2.54], distance: ["km", "mi", 0.621371] },
  label(kind) { const d = U.defs[kind]; return U.imperial ? d[1] : d[0]; },
  show(kind, metric, digits = 1) {  // metric number -> number in the chosen units
    if (metric == null || metric === "") return metric;
    const v = U.imperial ? Number(metric) * U.defs[kind][2] : Number(metric);
    return Math.round(v * 10 ** digits) / 10 ** digits;
  },
  toMetric(kind, v) {
    if (v == null || v === "") return v;
    return U.imperial ? Number(v) / U.defs[kind][2] : Number(v);
  },
  fmt(kind, metric, digits = 1) { return metric == null ? "–" : `${U.show(kind, metric, digits)} ${U.label(kind)}`; },
  height(cm) {
    if (!U.imperial) return `${Math.round(cm)} cm`;
    const inch = Math.round(cm / 2.54);
    return `${Math.floor(inch / 12)}′${inch % 12}″`;
  },
  food(text) {  // "150 g" -> "5.3 oz", "240 ml" -> "8.1 fl oz" when imperial
    if (!U.imperial || !text) return text;
    return String(text).replace(/(\d+(?:\.\d+)?)\s?(g|ml)\b/g, (_, n, u) =>
      u === "g" ? `${(n / 28.35).toFixed(1)} oz` : `${(n / 29.57).toFixed(1)} fl oz`);
  },
  set(imperial) {
    U.imperial = imperial;
    try { localStorage.setItem("units", imperial ? "imperial" : "metric"); } catch {}
    U.apply();
  },
  apply(root = document) {
    for (const el of root.querySelectorAll("[data-ulabel]")) el.textContent = U.label(el.dataset.ulabel);
    for (const el of root.querySelectorAll("input[data-unit]")) {
      if (el.dataset.unit === "length") {
        el.placeholder = U.imperial ? "inches, e.g. 71 = 5′11″" : "";
        el.min = U.imperial ? 40 : 100; el.max = U.imperial ? 100 : 250;
      }
      if (el.dataset.unit === "mass") { el.min = U.imperial ? 45 : 20; el.max = U.imperial ? 880 : 400; }
      else if (el.dataset.unit === "mass") el.placeholder = el.placeholder && /^(kg|lb)$/.test(el.placeholder) ? U.label("mass") : el.placeholder;
    }
  },
};

function formData(form) {
  const out = {};
  for (const [k, v] of new FormData(form)) {
    const el = form.elements[k];
    out[k] = el?.dataset?.unit && v !== "" ? String(U.toMetric(el.dataset.unit, v)) : v;
  }
  return out;
}
function setField(el, metric) {  // put a stored (metric) value into an input, converting if needed
  el.value = el.dataset.unit && metric != null && metric !== "" ? U.show(el.dataset.unit, metric) : (metric ?? "");
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
  if (view === "plans") view = "exercise"; // plans now live in the Workouts tab
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

const DAY_NAMES = { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday", Sun: "Sunday" };
function whenLabel(n) {
  if (!n) return "";
  return n.in_days === 1 ? "tomorrow" : DAY_NAMES[n.weekday] || n.weekday;
}
function sessionSummary(x) {
  const kcal = x.est_kcal ? ` · ~${x.est_kcal} kcal` : "";
  if (x.type === "cardio") return `${x.minutes} min · ${esc(x.zone)}${kcal}`;
  const n = (x.exercises || []).length;
  return `${n} exercises${x.minutes ? ` · ${x.minutes} min` : ""}${kcal}`;
}

function renderHero(d) {
  const el = $("#workoutHero");
  const ts = d.today_session, next = d.next_session;
  const isToday = state.day === isoDate(new Date());
  if (!d.plan_name) {
    el.innerHTML = `<span class="eyebrow">Today's workout</span>
      <h2>No workout plan yet</h2>
      <p class="muted">Let the app build one from your Garmin workouts and goals. It takes a minute.</p>
      <button class="hero-btn" data-show-setup>Set up my plan</button>`;
    return;
  }
  if (ts && ts.type !== "rest") {
    if (d.today_done) {
      el.innerHTML = `<span class="eyebrow">Today's workout</span><h2>✓ Done: ${esc(sessionTitle(ts))}</h2>
        <p class="muted">Nice work.${next ? ` Next up: <b>${esc(sessionTitle(next))}</b> ${whenLabel(next)}.` : ""}</p>`;
      return;
    }
    const list = ts.type === "strength"
      ? posterHTML("", ts.exercises, { compact: true })
      : `<p class="hero-big">${ts.minutes} min <span class="muted">in ${esc(ts.zone)}</span></p>
         <p class="muted small">Brisk walk, bike or cross-trainer. You should be able to talk in full sentences.</p>`;
    const ready = d.readiness && d.readiness.level !== "unknown" && d.readiness.level !== "good"
      ? `<p class="pill ${d.readiness.level}">${esc(d.readiness.message)}</p>` : "";
    el.innerHTML = `<span class="eyebrow">${isToday ? "Today's workout" : "Planned"} · ${ts.type}</span>
      <h2>${esc(sessionTitle(ts))}</h2>${ready}${list}
      ${isToday ? `<button class="hero-btn" data-start-session>${ts.type === "cardio" ? "Log it when done" : "Start workout"}</button>` : ""}`;
    return;
  }
  el.innerHTML = `<span class="eyebrow">${isToday ? "Today" : "This day"}</span>
    <h2>Rest day</h2>
    <p class="muted">Recovery is part of the plan: an easy walk and some stretching are perfect.</p>
    ${next ? `<div class="next-up"><span class="muted small">Next up · ${whenLabel(next)}</span>
      <b>${esc(sessionTitle(next))}</b><span class="muted small">${sessionSummary(next)}</span></div>
      ${isToday ? `<button class="ghost" data-do-today="${WD[new Date().getDay()]}" data-from="${next.weekday}" data-plan="${d.plan_id}">Do ${esc(sessionTitle(next))} today instead</button>` : ""}` : ""}`;
}

loaders.dashboard = async () => {
  const d = await api(`/api/dashboard?day=${state.day}`);
  const t = d.targets, c = d.consumed, g = d.goals;
  renderSetup(d.setup);
  renderHero(d);

  renderCluster(d);

  const chip = (label, value, sub, attrs = "") => `<div class="chip" ${attrs}><span class="label">${label}</span><span class="value">${value}</span><span class="sub">${sub}</span></div>`;
  $("#dayChips").innerHTML = [
    chip("Sleep", g.sleep_h.value == null ? "–" : `${g.sleep_h.value} h`, `goal ${g.sleep_h.goal} h`),
    chip("Workouts", `${g.workouts_week.value}/${g.workouts_week.goal}`, "this week"),
    chip("Weight", g.weight.value == null ? "+ Log" : `${U.show("mass", g.weight.value)}`, g.weight.value == null ? "tap to add" : `${U.label("mass")} · tap to log`,
      'role="button" tabindex="0" data-log-weight'),
  ].join("");

  const tip = (d.recommendations || []).find((r) => r.level !== "good") || (d.recommendations || [])[0];
  $("#topTip").classList.toggle("hidden", !tip);
  if (tip) $("#topTip").innerHTML = `<ul class="recs">${renderRecs([tip])}</ul>`;
};

// ---------------------------------------------------------------- car-style dashboard
function renderCluster(d) {
  const t = d.targets, c = d.consumed, g = d.goals;
  const eaten = c.calories, target = t.calories, left = Math.round(target - eaten);
  const burned = d.burned ?? null;  // full-day burn from the fenix (resting + active)
  const burnGoal = Math.max(t.tdee || 0, burned || 0, 2000);
  const protGoal = t.protein_g || 1;
  const net = burned != null ? Math.round(eaten - burned) : null;
  const steps = g.steps.value || 0;
  const eatState = eaten > target ? "bad" : eaten > target * 0.9 ? "warn" : "";
  const lights = [
    { on: eaten > target, cls: "bad", icon: "⚠", text: "Over calories" },
    { on: eaten > 0 && c.protein_g < protGoal * 0.5 && new Date().getHours() >= 15, cls: "warn", icon: "P", text: "Protein low" },
    { on: !!d.today_session && !d.today_done, cls: "info", icon: "🏋", text: "Workout due" },
    { on: d.today_done, cls: "good", icon: "✓", text: "Workout done" },
    { on: g.steps.goal && steps >= g.steps.goal, cls: "good", icon: "👟", text: "Steps goal hit" },
    { on: eaten === 0, cls: "muted", icon: "⛽", text: "Nothing logged yet" },
  ].filter((l) => l.on);

  $("#cluster").innerHTML = `
    <div class="cluster">
      <div class="g-main">${Gauge.dial({ id: "eat", value: eaten, max: Math.max(target * 1.3, eaten * 1.05), target,
        label: "EATEN", unit: `of ${fmt(target)} kcal`, readout: fmt(eaten), scale: 100, scaleLabel: "×100 kcal", state: eatState })}</div>
      <div class="g-side">${Gauge.dial({ id: "burn", value: burned || 0, max: burnGoal * 1.2, target: t.tdee || null, zone: "good",
        label: "BURNED", unit: burned == null ? "sync Garmin" : "kcal", readout: burned == null ? "–" : fmt(burned), scale: 1000, scaleLabel: "×1000" })}</div>
      <div class="g-side">${Gauge.dial({ id: "prot", value: c.protein_g, max: protGoal * 1.25, target: protGoal, zone: "good",
        label: "PROTEIN", unit: `of ${fmt(protGoal)} g`, readout: fmt(c.protein_g), state: c.protein_g >= protGoal ? "good" : "" })}</div>
    </div>
    <div class="cluster-strip">
      <div class="strip-cell">${Gauge.fuel(Math.max(0, left) / target, "Calories left", `${fmt(Math.abs(left))} ${left >= 0 ? "left" : "over"}`)}
        <span class="strip-label">CALORIES LEFT</span></div>
      <div class="strip-cell">
        <span class="strip-label">STEPS</span>${Gauge.odometer(steps, 5)}
        <span class="strip-sub">${g.steps.goal ? `goal ${fmt(g.steps.goal)}` : ""}</span>
        <span class="strip-label">NET ENERGY</span>
        <span class="lcd ${net == null ? "" : net > 0 ? "warn" : "good"}">${net == null ? "– –" : `${net > 0 ? "+" : ""}${fmt(net)}`}<small> kcal</small></span>
        <span class="strip-sub">${net == null ? "eaten − burned" : net < 0 ? "deficit (burning fat)" : "surplus"}</span>
      </div>
    </div>
    <div class="macro-bars">${[["Carbs", c.carbs_g, t.carbs_g, "carbs"], ["Fat", c.fat_g, t.fat_g, "fat"], ["Fibre", c.fiber_g || 0, t.fiber_g, "fiber"]]
      .map(([n, v, goal, k]) => `<div class="mbar"><span>${n}</span><div class="mtrack"><div class="mfill ${k}" style="width:${Math.min(100, goal ? (v / goal) * 100 : 0)}%"></div></div><span class="muted">${fmt(v)}/${fmt(goal)} g</span></div>`).join("")}</div>
    ${lights.length ? `<div class="lights">${lights.map((l) => `<span class="light ${l.cls}"><b>${l.icon}</b>${l.text}</span>`).join("")}</div>` : ""}`;
  Gauge.animate($("#cluster"));
}

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

document.addEventListener("click", (e) => {
  if (!e.target.closest("[data-show-setup]")) return;
  store.set("setupHidden", "0");
  const card = $("#setupCard");
  card.classList.remove("hidden");
  renderAutoSetup($("[data-auto-setup]", card), true);
  card.scrollIntoView({ behavior: "smooth" });
});
$("#setupDismiss").onclick = () => { store.set("setupHidden", "1"); $("#setupCard").classList.add("hidden"); };

// quick weight dialog
document.addEventListener("click", (e) => { if (e.target.closest("[data-log-weight]")) $("#weightDialog").showModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.closest?.("[data-log-weight]")) $("#weightDialog").showModal(); });
$("#weightDialog").addEventListener("close", async () => {
  const dlg = $("#weightDialog");
  const v = U.toMetric("mass", $("#weightQuick").elements.weight_kg.value);
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
    <ul class="list">${items.map((f) => `<li><span>${esc(U.food(f.name))}${f.servings !== 1 ? ` ×${f.servings}` : ""}</span>
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

// ---------------------------------------------------------------- log food by amount (servings, pieces, g, oz, lb, ml, fl oz, cups, spoons)
const pick = { food: null, items: [] };
const MASS_UNITS = { g: 1, kg: 1000, oz: 28.3495, lb: 453.592 };
const VOL_UNITS = { ml: 1, "fl oz": 29.5735, cup: 240, tbsp: 15, tsp: 5 };
const QUICK = { serving: [0.5, 1, 1.5, 2, 3], g: [50, 100, 150, 200, 250], kg: [0.25, 0.5, 1], oz: [2, 4, 6, 8, 12], lb: [0.25, 0.5, 1],
  ml: [100, 250, 330, 500], "fl oz": [4, 8, 12, 16], cup: [0.5, 1, 1.5, 2], tbsp: [1, 2, 3], tsp: [1, 2, 3] };
const defaultMeal = () => { const h = new Date().getHours(); return h < 11 ? "breakfast" : h < 15 ? "lunch" : h >= 17 && h < 22 ? "dinner" : "snack"; };

function gramsPer(food, unit) {  // grams in one of `unit` for this food (null = unit not usable)
  if (unit === "serving") return food.grams || null;
  if (!food.grams) return null;
  if (MASS_UNITS[unit]) return MASS_UNITS[unit];
  // the food's own label may say how much a cup/tbsp weighs, e.g. "1 cup cooked (160 g)"
  const m = /^\s*(\d+(?:\/\d+)?|\d*\.\d+)\s+(cups?|tbsp|tsp)\b/i.exec(food.unit);
  if (m && m[2].toLowerCase().replace(/s$/, "") === unit) {
    const n = m[1].includes("/") ? m[1].split("/").reduce((a, b) => a / b) : Number(m[1]);
    return food.grams / n;
  }
  return VOL_UNITS[unit] || null;  // liquids & most foods: 1 ml ≈ 1 g
}
function pickUnits(food) {
  if (!food.grams) return ["serving"];
  const base = ["serving", "g", "oz", "lb", "kg"];
  return [...base, ...Object.keys(VOL_UNITS)];
}
function unitLabel(unit, food) {
  return unit === "serving" ? `× ${food.unit}` : unit;
}
function openPick(food) {
  pick.food = food;
  $("#pickResults").innerHTML = "";
  $("#pickPanel").classList.remove("hidden");
  $("#pickName").textContent = food.food || food.name;
  $("#pickBase").textContent = `${food.unit}: ${fmt(food.calories)} kcal · P ${food.protein_g} g · C ${food.carbs_g} g · F ${food.fat_g} g`;
  const units = pickUnits(food);
  $("#pickUnit").innerHTML = units.map((u) => `<option value="${u}">${esc(unitLabel(u, food))}</option>`).join("");
  const start = U.imperial && units.includes("oz") && /\b\d+ g\b/.test(food.unit) ? "oz" : "serving";
  $("#pickUnit").value = start;
  $("#pickAmount").value = start === "oz" ? Math.round(food.grams / 28.35) || 1 : 1;
  $("#pickMeal").value = defaultMeal();
  updatePick();
  $("#pickAmount").focus();
}
function pickTotals() {
  const f = pick.food, unit = $("#pickUnit").value, amt = Number($("#pickAmount").value) || 0;
  const per = gramsPer(f, unit);
  const factor = unit === "serving" ? amt : per && f.grams ? (amt * per) / f.grams : 0;
  const out = { factor, grams: f.grams ? factor * f.grams : null };
  for (const k of ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g"]) out[k] = (f[k] || 0) * factor;
  return out;
}
function updatePick() {
  const t = pickTotals(), unit = $("#pickUnit").value;
  $("#pickQuick").innerHTML = (QUICK[unit] || []).map((q) => `<button type="button" class="chip-btn" data-q="${q}">${q}</button>`).join("");
  const w = t.grams != null && unit !== "g" ? `≈ ${U.imperial ? `${(t.grams / 28.35).toFixed(1)} oz` : `${Math.round(t.grams)} g`}` : "";
  $("#pickResult").innerHTML = `<span class="kcal">${fmt(t.calories)}<small> kcal</small></span>
    <span class="macros"><b class="p">P ${t.protein_g.toFixed(1)}</b><b class="c">C ${t.carbs_g.toFixed(1)}</b><b class="f">F ${t.fat_g.toFixed(1)}</b></span>
    <span class="muted small">${w}</span>`;
  $("#pickAdd").disabled = !(t.factor > 0);
}
$("#pickAmount").addEventListener("input", updatePick);
$("#pickUnit").addEventListener("change", () => {
  // keep roughly the same quantity when switching units
  const f = pick.food, prev = pick.lastGrams, unit = $("#pickUnit").value, per = gramsPer(f, unit);
  if (prev && per) { const v = prev / per; $("#pickAmount").value = v >= 10 ? Math.round(v) : Math.round(v * 4) / 4 || 0.25; }
  updatePick();
});
$("#pickAmount").addEventListener("change", () => (pick.lastGrams = pickTotals().grams));
$("#pickPanel").addEventListener("click", (e) => {
  const q = e.target.closest("[data-q]"), st = e.target.closest("[data-step]");
  if (q) $("#pickAmount").value = q.dataset.q;
  if (st) {
    const unit = $("#pickUnit").value, inc = { g: 25, ml: 50, kg: 0.1, lb: 0.25, oz: 1, "fl oz": 1, tsp: 1, tbsp: 1 }[unit] || 0.5;
    $("#pickAmount").value = Math.max(0, Math.round(((Number($("#pickAmount").value) || 0) + Number(st.dataset.step) * inc) * 100) / 100);
  }
  if (q || st) { pick.lastGrams = pickTotals().grams; updatePick(); }
});
$("#pickClose").onclick = () => { $("#pickPanel").classList.add("hidden"); pick.food = null; };
$("#pickAdd").addEventListener("click", (e) => withBusy(e.target, async () => {
  const f = pick.food, t = pickTotals(), unit = $("#pickUnit").value, amt = Number($("#pickAmount").value);
  const qty = unit === "serving" ? `${amt} × ${f.unit}` : `${amt} ${unit}`;
  await api("/api/foods", { method: "POST", body: { day: state.day, meal: $("#pickMeal").value,
    name: `${f.food || f.name} — ${qty}`.slice(0, 200), servings: 1,
    calories: Math.round(t.calories), protein_g: +t.protein_g.toFixed(1), carbs_g: +t.carbs_g.toFixed(1),
    fat_g: +t.fat_g.toFixed(1), fiber_g: +t.fiber_g.toFixed(1) } });
  toast(`Logged ${f.food || f.name} · ${fmt(t.calories)} kcal`);
  $("#pickPanel").classList.add("hidden"); $("#foodPick").value = ""; pick.food = null; pick.lastGrams = null;
  loaders.diet();
}));
let pickTimer;
$("#foodPick").addEventListener("input", (e) => {
  clearTimeout(pickTimer);
  const q = e.target.value.trim();
  if (!q) return ($("#pickResults").innerHTML = "");
  pickTimer = setTimeout(async () => {
    pick.items = await api(`/api/food-library?q=${encodeURIComponent(q)}`);
    $("#pickResults").innerHTML = pick.items.slice(0, 12).map((f, i) =>
      `<li data-pick="${i}" tabindex="0"><span>${f.custom ? "★ " : ""}${esc(f.food || f.name)} <span class="muted small">${esc(U.food(f.unit || ""))}</span></span><span class="muted small">${fmt(f.calories)} kcal</span></li>`).join("")
      || `<li class="muted small">Not in the database yet. Add it below under "Add food manually" and it'll be remembered.</li>`;
  }, 150);
});
$("#pickResults").addEventListener("click", (e) => { const li = e.target.closest("[data-pick]"); if (li) { openPick(pick.items[li.dataset.pick]); pick.lastGrams = pickTotals().grams; } });

let searchTimer;
$("#foodSearch").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) return ($("#foodResults").innerHTML = "");
  searchTimer = setTimeout(async () => {
    const items = await api(`/api/food-library?q=${encodeURIComponent(q)}`);
    $("#foodResults").innerHTML = items.slice(0, 8).map((f, i) =>
      `<li data-food-idx="${i}" tabindex="0"><span>${f.custom ? "★ " : ""}${esc(U.food(f.name))}</span><span class="muted small">${f.calories} kcal · P${f.protein_g}</span></li>`).join("")
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
  form._fromDb = true;
  $("#foodResults").innerHTML = "";
  $("#foodSearch").value = "";
});
$("#foodForm").elements.name.addEventListener("input", () => ($("#foodForm")._fromDb = false));
api("/api/food-db/stats").then((s) => { for (const id of ["#foodDbCount", "#foodDbCount2"]) $(id).textContent = `${s.builtin} foods${s.mine ? ` + ${s.mine} of yours` : ""}`; }).catch(() => {});
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
    if (e.target.elements.remember.checked && !e.target._fromDb) {
      await api("/api/my-foods", { method: "POST", body: {
        name: d.name.trim(), calories: Number(d.calories) || 0, protein_g: Number(d.protein_g) || 0,
        carbs_g: Number(d.carbs_g) || 0, fat_g: Number(d.fat_g) || 0, fiber_g: Number(d.fiber_g) || 0 } }).catch(() => {});
    }
    e.target.reset();
    e.target._fromDb = false;
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- AI calorie counter
const ai = { items: [] };


const AI_NUMS = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g"];
function renderAiItems() {
  $("#aiItems").innerHTML = ai.items.map((it, i) => `<tr data-i="${i}">
    <td><input type="checkbox" data-k="keep" ${it.keep ? "checked" : ""} aria-label="Include"></td>
    <td><input data-k="name" value="${esc(it.name)}" aria-label="Food"></td>
    <td><input data-k="portion" value="${esc(U.food(it.portion))}" aria-label="Portion"></td>
    ${AI_NUMS.map((k) => `<td><input type="number" min="0" step="1" data-k="${k}" value="${Math.round(it[k] ?? 0)}" aria-label="${k}"></td>`).join("")}
    <td><span class="conf ${it.confidence}" title="How sure the estimate is">${it.confidence}</span></td></tr>`).join("")
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
  $("#aiForm").reset();
  $("#aiResult").classList.add("hidden");
}
$("#aiForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const description = e.target.elements.description.value.trim();
  if (!description) return toast("Type what you ate", true);
  const fd = new FormData();
  fd.append("description", description);
  const h = new Date().getHours();
  fd.append("meal", e.target.elements.meal.value || (h < 11 ? "breakfast" : h < 15 ? "lunch" : h >= 17 && h < 22 ? "dinner" : "snack"));
  const btn = $("#aiSubmit");
  btn.disabled = true;
  btn.textContent = "Counting…";
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
// ---------------------------------------------------------------- exercise demo pop-up + guide
async function openExercise(name, part) {
  part = part || picker.lookup?.[(name || "").toLowerCase()];
  const info = ExerciseInfo.lookup(name, part);
  $("#exTitle").textContent = name;
  $("#exPic").classList.add("hidden"); $("#exTips").innerHTML = ""; $("#exCredit").innerHTML = "";
  const lib = (await exlibLookup([name]))[name];
  if (lib) {
    if (lib.primary.length && !lib.similar) { info.primary = lib.primary; info.secondary = lib.secondary; }
    info.primaryNames = info.primary.map((m) => MUSCLE_NAMES[m]); info.secondaryNames = info.secondary.map((m) => MUSCLE_NAMES[m]);
    if (lib.instructions.length && !lib.similar) info.cues = lib.instructions;
    if (lib.images.length) {
      $("#exPic").innerHTML = `<div class="pimg big${lib.images.length > 1 ? " anim" : ""}">${lib.images.map((src, i) => `<img src="${src}" alt="${esc(lib.name)}${i ? " (end position)" : " (start position)"}" class="${i ? "peak" : "start"}">`).join("")}</div>
        ${lib.images.length > 1 ? `<div class="pic-steps"><span>Start</span><span>Finish</span></div>` : ""}
        ${lib.similar ? `<p class="muted small">No photo of this exact exercise. Shown: ${esc(lib.name)}, a similar movement.</p>` : ""}`;
      $("#exPic").classList.remove("hidden");
    }
    $("#exTips").innerHTML = lib.tips.map((t) => `<li>💡 ${esc(t)}</li>`).join("");
    $("#exCredit").textContent = `${lib.similar ? "Photo" : "Photos & instructions"}: ${lib.name} (free-exercise-db, public domain)`;
  }
  $("#exMuscles").innerHTML = (info.primaryNames.length
    ? `<span class="mtag prim">Main: ${info.primaryNames.map(esc).join(", ")}</span>` : `<span class="mtag">General movement</span>`)
    + (info.secondaryNames.length ? `<span class="mtag sec">Also: ${info.secondaryNames.map(esc).join(", ")}</span>` : "");
  $("#exCues").innerHTML = info.cues.map((c) => `<li>${esc(c)}</li>`).join("");
  $("#exDialog").showModal();
}
$("#exClose").onclick = () => $("#exDialog").close();
$("#exDialog").addEventListener("click", (e) => { if (e.target === $("#exDialog")) $("#exDialog").close(); });
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-ex]");
  if (!b) return;
  e.preventDefault();
  openExercise(b.dataset.ex, b.dataset.part);
});
async function renderGuide() {
  if (!picker.parts.length) await loadPicker();
  const sel = $("#guidePart");
  if (!sel.options.length) sel.innerHTML = `<option value="">Your plan</option>` + picker.parts.map((p) => `<option>${esc(p)}</option>`).join("");
  const norm = (x) => x.toLowerCase().replace(/[-_\s]+/g, "");
  const q = norm($("#guideSearch").value.trim()), part = sel.value;
  let rows;
  if (!part && !q) rows = Object.entries(picker.mine).flatMap(([p, names]) => names.map((n) => [n, p]));
  else rows = Object.entries(picker.groups).filter(([p]) => !part || p === part)
    .flatMap(([p, names]) => names.map((n) => [n, p])).filter(([n]) => !q || norm(n).includes(q));
  const shown = rows.slice(0, 80);
  $("#guideList").innerHTML = shown.map(([n, p]) => {
    const info = ExerciseInfo.lookup(n, p);
    return `<li><button class="ex-row" data-ex="${esc(n)}" data-part="${esc(p)}"><span>${esc(n)}</span><span class="muted small">${esc(info.primaryNames.join(", ") || p)}</span></button></li>`;
  }).join("") + (rows.length > shown.length ? `<li class="muted small">${rows.length - shown.length} more — search to narrow down</li>` : "")
    || `<li class="muted small">${part || q ? "No matches" : "No plan exercises yet — pick a body part above"}</li>`;
}
$("#exGuide").addEventListener("toggle", () => { if ($("#exGuide").open) renderGuide().catch((e) => toast(e.message, true)); });
$("#guidePart").addEventListener("change", () => renderGuide());
let guideTimer;
$("#guideSearch").addEventListener("input", () => { clearTimeout(guideTimer); guideTimer = setTimeout(renderGuide, 200); });

// ---------------------------------------------------------------- exercise picker (body part -> exercise)
const picker = { groups: {}, parts: [], mine: {}, sessions: [], lookup: {} };
async function loadPicker() {
  const r = await api("/api/exercises");
  Object.assign(picker, { groups: r.groups, parts: r.body_parts, mine: r.plan_exercises, sessions: r.plan_sessions });
  picker.lookup = {};
  for (const [part, names] of Object.entries(r.groups)) for (const n of names) picker.lookup[n.toLowerCase()] = part;
  const sel = $("#workoutName"), keep = sel.value;
  const common = ["Strength", "Run", "Ride", "Walk", "Hike", "Swim", "HIIT", "Yoga", "Mobility"];
  sel.innerHTML = `<option value="">Pick a workout…</option>`
    + (r.plan_sessions.length ? `<optgroup label="Your plan">${r.plan_sessions.map((n) => `<option>${esc(n)}</option>`).join("")}</optgroup>` : "")
    + `<optgroup label="Other">${common.map((n) => `<option>${n}</option>`).join("")}</optgroup>`;
  if (keep) setWorkoutName(keep);
}
function setWorkoutName(name) {
  const sel = $("#workoutName");
  if (name && ![...sel.options].some((o) => o.value === name)) sel.insertAdjacentHTML("beforeend", `<option>${esc(name)}</option>`);
  sel.value = name || "";
}
function exerciseOptions(part, current) {
  const mine = (picker.mine[part] || []);
  const all = (picker.groups[part] || []).filter((n) => !mine.includes(n));
  let html = `<option value="">Exercise…</option>`;
  if (mine.length) html += `<optgroup label="In your plan">${mine.map((n) => `<option>${esc(n)}</option>`).join("")}</optgroup>`;
  html += `<optgroup label="All ${esc(part.toLowerCase())}">${all.map((n) => `<option>${esc(n)}</option>`).join("")}</optgroup>`;
  if (current && !mine.includes(current) && !all.includes(current)) html += `<option>${esc(current)}</option>`;
  return html;
}

function addSetRow(v = {}) {
  const row = document.createElement("div");
  row.className = "set-row";
  const part = v.part || picker.lookup[(v.exercise || "").toLowerCase()] || Object.keys(picker.mine)[0] || picker.parts[0] || "Chest";
  row.innerHTML = `<select data-k="part" aria-label="Body part">${picker.parts.map((p) => `<option ${p === part ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
    <select data-k="exercise" aria-label="Exercise">${exerciseOptions(part, v.exercise)}</select>
    <input type="number" placeholder="Reps" data-k="reps" min="0" value="${esc(v.reps ?? "")}" aria-label="Reps">
    <input type="number" placeholder="${U.label("mass")}" step="0.5" min="0" data-k="weight_kg" value="${esc(U.show("mass", v.weight_kg) ?? "")}" aria-label="Weight ${U.label("mass")}">
    <button type="button" class="icon" title="Remove set" aria-label="Remove set">✕</button>
    <button type="button" class="icon ex-info" title="How to do it" aria-label="Show how to do this exercise">ⓘ</button>`;
  row.querySelector("button").onclick = () => row.remove();
  row.querySelector(".ex-info").onclick = () => { const n = $('[data-k="exercise"]', row).value; n ? openExercise(n, $('[data-k="part"]', row).value) : toast("Pick an exercise first", true); };
  $('[data-k="exercise"]', row).value = v.exercise || "";
  $('[data-k="part"]', row).onchange = (e) => { $('[data-k="exercise"]', row).innerHTML = exerciseOptions(e.target.value); };
  $("#setRows").appendChild(row);
}
$("#addSet").onclick = () => {
  const last = $$("#setRows .set-row").at(-1);
  addSetRow(last ? { part: $('[data-k="part"]', last).value, exercise: $('[data-k="exercise"]', last).value,
                     reps: $('[data-k="reps"]', last).value, weight_kg: U.toMetric("mass", $('[data-k="weight_kg"]', last).value) } : {});
};

function nowLocalInput() { return localIso().slice(0, 16); }

async function loadTodaysPlan() {
  $("#logWorkoutCard").open = true;
  const plan = await api("/api/plans/active");
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][new Date().getDay()];
  const session = plan?.days.find((d) => d.weekday === wd);
  if (!session) return toast(plan ? "Today is a rest day in your plan" : "No active plan. Build one in Plans", true);
  const f = $("#activityForm").elements;
  if (!picker.parts.length) await loadPicker();
  setWorkoutName(`${dayName(session.weekday)} · ${sessionTitle(session)}`);
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
  loaders.plans().catch((e) => toast(e.message, true));
  loadPicker().catch(() => {});
  const f = $("#activityForm").elements.start_time;
  if (!f.value) f.value = nowLocalInput();
  const filter = $("#actFilter").value;
  const acts = (await api("/api/activities?limit=200")).filter((a) => !filter || a.source === filter);
  $("#activityList").innerHTML = acts.map((a) => {
    const sets = a.sets.length ? summarizeSets(a.sets) : "";
    const bits = [minutes(a.duration_s), a.distance_m && U.fmt("distance", a.distance_m / 1000, 2), a.calories && `${fmt(a.calories)} kcal`,
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
    by.get(k).push(s.weight_kg ? `${s.reps ?? "?"}×${U.show("mass", s.weight_kg)}${U.label("mass")}` : `${s.reps ?? "?"}`);
  }
  return [...by].map(([ex, v]) => `${esc(ex)}: ${esc(v.join(", "))}`).join(" · ");
}

$("#activityForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  const sets = $$("#setRows .set-row").map((r) => ({
    exercise: $('[data-k="exercise"]', r).value.trim(),
    reps: numOrNull($('[data-k="reps"]', r).value),
    weight_kg: numOrNull(U.toMetric("mass", $('[data-k="weight_kg"]', r).value)),
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

// ================================================================ workout posters (illustrated, like a gym poster)
const exlib = { cache: new Map(), pending: null };
async function exlibLookup(names) {
  const need = [...new Set(names)].filter((n) => !exlib.cache.has(n));
  if (need.length) {
    try {
      const r = await api("/api/exlib/match", { method: "POST", body: { names: need } });
      for (const n of need) exlib.cache.set(n, r.items[n] || null);
    } catch { for (const n of need) exlib.cache.set(n, null); }
  }
  return Object.fromEntries(names.map((n) => [n, exlib.cache.get(n)]));
}
const MUSCLE_NAMES = ExerciseInfo.MUSCLES;
const DAY_LONG = { Sun: "Sunday", Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday" };
const FOCUS = { chest: "Chest", front_delts: "Shoulders", side_delts: "Shoulders", rear_delts: "Shoulders", traps: "Back",
  lats: "Back", upper_back: "Back", lower_back: "Back", biceps: "Arms", triceps: "Arms", forearms: "Arms",
  abs: "Core", obliques: "Core", hip_flexors: "Core", glutes: "Legs", quads: "Legs", hamstrings: "Legs", adductors: "Legs", calves: "Legs" };
// Session name from the weekday and the muscles it trains, never "Day 1".
function sessionTitle(s) {
  if (!s) return "";
  const raw = (s.title || "").trim();
  if (s.type !== "strength") return raw.replace(/^day\s*\d+\s*[-:·]?\s*/i, "") || "Cardio";
  const count = {};
  for (const x of s.exercises || []) for (const m of ExerciseInfo.lookup(x.exercise).primary) {
    const g = FOCUS[m]; if (g) count[g] = (count[g] || 0) + 1;
  }
  const groups = Object.entries(count).sort((a, b) => b[1] - a[1]).map(([g]) => g);
  const legs = groups.includes("Legs"), upper = groups.filter((g) => ["Chest", "Back", "Shoulders", "Arms"].includes(g));
  let focus = groups.length >= 4 && legs && upper.length >= 2 ? "Full body"
    : !legs && upper.length >= 3 ? "Upper body" : groups.slice(0, 2).join(" & ");
  const custom = raw && !/^(day|workout|session)\s*\d+/i.test(raw) ? raw.replace(/\s+[A-D]$/, "") : "";
  const nice = { upper: "Upper body", lower: "Lower body", full: "Full body", "full body": "Full body" }[custom.toLowerCase()];
  return nice || custom || focus || "Strength";
}
const dayName = (wd) => DAY_LONG[wd] || wd;

function posterHTML(title, exercises, { sub = "", compact = false } = {}) {
  return `<div class="exlist${compact ? " compact" : ""}">
    ${title ? `<h3 class="poster-title">${esc(title)}</h3>` : ""}${sub ? `<p class="poster-sub">${sub}</p>` : ""}
    ${exercises.map((x, i) => `<article class="excard" data-poster="${esc(x.exercise)}" data-compact="${compact ? 1 : ""}">
      <header><span class="exnum">${i + 1}</span><h4>${esc(x.exercise)}</h4></header>
      <div class="pimg"><span class="pimg-ph">${esc(x.exercise.slice(0, 1))}</span></div>
      <dl class="exstats"><div><dt>Sets</dt><dd>${x.sets}</dd></div><div><dt>Reps</dt><dd>${esc(x.reps)}</dd></div>
        ${x.rest_s ? `<div><dt>Rest</dt><dd>${x.rest_s}s</dd></div>` : ""}</dl>
      <div class="exmus"></div>
      <ol class="exsteps"></ol>
      <button class="ghost small" data-ex="${esc(x.exercise)}">How to do it</button>
    </article>`).join("")}</div>`;
}
async function hydratePosters(root = document) {
  const tiles = [...root.querySelectorAll("[data-poster]")].filter((t) => !t.dataset.done);
  if (!tiles.length) return;
  const info = await exlibLookup(tiles.map((t) => t.dataset.poster));
  for (const t of tiles) {
    t.dataset.done = "1";
    const m = info[t.dataset.poster];
    const local = ExerciseInfo.lookup(t.dataset.poster);
    const own = m && !m.similar;
    const prim = own && m.primary.length ? m.primary : local.primary;
    const sec = (own && m.secondary.length ? m.secondary : local.secondary).filter((k) => !prim.includes(k));
    t.querySelector(".exmus").innerHTML = `<span class="lbl">Works</span>${prim.map((k) => `<i class="p">${esc(MUSCLE_NAMES[k] || k)}</i>`).join("")}`
      + (sec.length ? `<span class="lbl">Helps</span>${sec.slice(0, 3).map((k) => `<i>${esc(MUSCLE_NAMES[k] || k)}</i>`).join("")}` : "");
    const steps = (own && m.instructions.length ? m.instructions : local.cues || []).slice(0, t.dataset.compact ? 2 : 3);
    t.querySelector(".exsteps").innerHTML = steps.map((s) => `<li>${esc(s)}</li>`).join("");
    if (m?.images?.length) {
      t.querySelector(".pimg").innerHTML = m.images.map((src, i) => `<img src="${src}" alt="${esc(t.dataset.poster)} ${i ? "finish" : "start"} position" loading="lazy" class="${i ? "peak" : "start"}">`).join("");
      t.querySelector(".pimg").classList.toggle("anim", m.images.length > 1);
      if (m.similar) t.querySelector(".pimg").insertAdjacentHTML("beforeend", `<span class="pimg-note">Similar movement</span>`);
    } else {
      t.querySelector(".pimg").innerHTML = `<div class="pimg-map">${BodyMap.render(local.primary, local.secondary)}</div>`;
    }
  }
}
new MutationObserver(() => { clearTimeout(exlib.pending); exlib.pending = setTimeout(() => hydratePosters(), 30); })
  .observe(document.body, { childList: true, subtree: true });

// ================================================================ PLANS
function renderPlanDay(day, compact = false) {
  if (day.type === "rest") return `<div class="plan-day"><div class="wd">${dayName(day.weekday)}</div><strong>Rest / mobility</strong><p class="muted small">Easy walk and stretching. Let your Garmin recovery time come down.</p></div>`;
  if (day.type === "cardio") return `<div class="plan-day cardio"><div class="wd">${dayName(day.weekday)} · cardio</div><strong>${esc(sessionTitle(day))}</strong>
    <p class="small">${day.minutes} min in <b>${esc(day.zone)}</b>${day.est_kcal ? ` · 🔥 about <b>${day.est_kcal} kcal</b>` : ""}. Set your fenix data screen to show HR zone.</p></div>`;
  const changes = !compact && day.changes?.length
    ? `<details class="small"><summary class="muted">${day.changes.length} adjustment${day.changes.length > 1 ? "s" : ""} for your goal</summary><ul class="tips">${day.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>` : "";
  return `<div class="plan-day strength"><div class="wd">${dayName(day.weekday)}${day.garmin_source_id ? " · from your Garmin workout" : ""}</div><strong>${esc(sessionTitle(day))}</strong>
    ${day.est_kcal ? `<p class="burn">🔥 About <b>${day.est_kcal} kcal</b> · ${day.minutes} min · strength first, then the cardio block</p>` : ""}
    ${posterHTML("", day.exercises, { compact })}${changes}</div>`;
}

const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// Month calendar: tap a day to see that day's workout underneath.
const cal = { plan: null, month: null, sel: null, marks: {} };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function sessionOn(plan, d) {
  const start = new Date(plan.created_at); start.setHours(0, 0, 0, 0);
  const end = new Date(start); end.setDate(start.getDate() + plan.weeks * 7);
  if (d < start || d >= end) return null;
  return plan.days.find((x) => x.weekday === WD[d.getDay()] && x.type !== "rest") || { type: "rest" };
}
function renderWeek(plan) {
  cal.plan = plan;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  cal.month ||= new Date(today.getFullYear(), today.getMonth(), 1);
  cal.sel ||= iso(today);
  const m = cal.month, first = new Date(m), lead = (first.getDay() + 6) % 7;
  const days = new Date(m.getFullYear(), m.getMonth() + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(`<span class="cal-cell empty"></span>`);
  for (let n = 1; n <= days; n++) {
    const d = new Date(m.getFullYear(), m.getMonth(), n), s = sessionOn(plan, d), key = iso(d);
    const kind = s ? s.type : "none";
    const icon = kind === "strength" ? "💪" : kind === "cardio" ? "🏃" : "";
    const mark = cal.marks[key] === true ? `<span class="cal-mark yes" aria-label="done">✓</span>`
      : cal.marks[key] === false ? `<span class="cal-mark no" aria-label="missed">✕</span>` : "";
    cells.push(`<button type="button" class="cal-cell ${kind}${key === iso(today) ? " today" : ""}${key === cal.sel ? " sel" : ""}${d < today ? " past" : ""}" data-cal-day="${key}">
      <span class="cal-n">${n}</span><span class="cal-i">${icon}</span>${mark}</button>`);
  }
  const sd = new Date(cal.sel + "T12:00:00"), ss = sessionOn(plan, sd);
  const wd = WD[sd.getDay()];
  const label = sd.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const options = WD.filter((x) => x !== wd).map((x) => `<option value="${x}">${dayName(x)}</option>`).join("");
  const detail = !ss ? `<p class="muted">Outside your ${plan.weeks}-week plan.</p>`
    : ss.type === "rest" ? `<p class="muted">Rest day. An easy walk and some stretching are perfect.</p>`
    : `${checkinHTML(cal.sel, sd)}${renderPlanDay(ss)}<label class="move">Move ${dayName(wd)}'s session to <select data-move-from="${wd}" data-plan="${plan.id}"><option value="">Pick a day…</option>${options}</select></label>`;
  return `<div class="card cal-card">
    <div class="cal-head"><button type="button" class="icon" data-cal-nav="-1" aria-label="Previous month">‹</button>
      <h3>${m.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h3>
      <button type="button" class="icon" data-cal-nav="1" aria-label="Next month">›</button></div>
    <div class="cal-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((x) => `<span class="cal-dow">${x.slice(0, 1)}</span>`).join("")}${cells.join("")}</div>
    <p class="cal-key muted small">💪 Strength · 🏃 Cardio · blank = rest</p>
  </div>
  <div class="card cal-day"><h3>${label}</h3>${detail}</div>`;
}
function checkinHTML(key, d) {
  const today = new Date(); today.setHours(23, 59, 59);
  if (d > today) return "";
  const v = cal.marks[key];
  return `<div class="checkin"><span>Did you complete this workout?</span>
    <div class="checkin-btns"><button type="button" class="ck yes${v === true ? " on" : ""}" data-checkin="1">✓ Yes</button>
    <button type="button" class="ck no${v === false ? " on" : ""}" data-checkin="0">✕ No</button></div></div>`;
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-checkin]");
  if (!b) return;
  const want = b.dataset.checkin === "1";
  const done = cal.marks[cal.sel] === want ? null : want;  // tap again to clear
  try {
    cal.marks = await api("/api/plans/checkins/all", { method: "POST", body: { day: cal.sel, done } });
    $("#activePlan").innerHTML = renderWeek(cal.plan);
    if (done !== null) toast(done ? "Marked as done ✓" : "Marked as missed");
  } catch (err) { toast(err.message, true); }
});
document.addEventListener("click", (e) => {
  const d = e.target.closest("[data-cal-day]"), n = e.target.closest("[data-cal-nav]");
  if (!d && !n) return;
  if (d) cal.sel = d.dataset.calDay;
  if (n) cal.month = new Date(cal.month.getFullYear(), cal.month.getMonth() + Number(n.dataset.calNav), 1);
  $("#activePlan").innerHTML = renderWeek(cal.plan);
  if (d) $(".cal-day")?.scrollIntoView({ behavior: "smooth", block: "start" });
});
let _watchSending = false;
const watchNote = () => (_watchSending ? " and on your fenix" : "");

async function moveSession(planId, from, to) {
  await api(`/api/plans/${planId}/move`, { method: "POST", body: { from_day: from, to_day: to } });
  toast(`Moved to ${to}${watchNote()}`);
  loaders[state.view]?.();
}
document.addEventListener("change", (e) => {
  const sel = e.target.closest("[data-move-from]");
  if (!sel || !sel.value) return;
  moveSession(sel.dataset.plan, sel.dataset.moveFrom, sel.value).catch((err) => toast(err.message, true));
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-do-today]");
  if (!b) return;
  b.disabled = true;
  moveSession(b.dataset.plan, b.dataset.from, b.dataset.doToday).catch((err) => { toast(err.message, true); b.disabled = false; });
});

loaders.plans = async () => {
  const [plans, active, watch] = await Promise.all([api("/api/plans"), api("/api/plans/active"), api("/api/garmin/watch-plan").catch(() => null)]);
  renderWatchStatus(watch);
  _watchSending = !!(watch && watch.sending);
  cal.marks = await api("/api/plans/checkins/all").catch(() => ({}));
  $("#activePlan").innerHTML = active ? renderWeek(active) : `<div class="card hero"><span class="eyebrow">Your plan</span>
    <h2>No workout plan yet</h2><p class="muted">Build one from your Garmin workouts and goals.</p>
    <button class="hero-btn" data-goto="dashboard" data-show-setup>Set up my plan</button></div>`;
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
  api("/api/recommendations").then((r) => { $("#dashRecs").innerHTML = renderRecs(r.slice(0, 2)); }).catch(() => {});
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
      lineDs("Weight", wpts.map((x) => U.show("mass", x.weight_kg)), css("--series-1"), { pointRadius: 3 }),
      ...(goals.target_weight_kg ? [targetDs("Target", wpts.map(() => U.show("mass", goals.target_weight_kg)))] : []),
    ] },
    options: { plugins: { legend: { display: !!goals.target_weight_kg } }, scales: { y: { beginAtZero: false, title: { display: true, text: U.label("mass") } } } },
  });
  $("#weightSummary").textContent = wpts.length >= 2
    ? `${(wpts.at(-1).weight_kg - wpts[0].weight_kg > 0 ? "+" : "")}${U.fmt("mass", wpts.at(-1).weight_kg - wpts[0].weight_kg)} over this period`
      + (goals.target_weight_kg ? ` · ${U.fmt("mass", Math.abs(wpts.at(-1).weight_kg - goals.target_weight_kg))} to target` : "") + "."
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
    $("#strengthChart").closest(".chart").hidden = true;
    $("#strengthSummary").textContent = "Log sets (exercise, reps, weight) with your workouts to track strength over time.";
    return;
  }
  const pts = await api(`/api/progress/exercise?name=${encodeURIComponent(name)}`);
  $("#strengthChart").closest(".chart").hidden = false;
  drawChart("strengthChart", {
    data: { labels: pts.map((p) => shortDay(p.day)), datasets: [
      lineDs("Estimated 1-rep max", pts.map((p) => U.show("mass", p.est_1rm_kg)), css("--series-1"), { pointRadius: 3 }),
      lineDs("Heaviest set", pts.map((p) => U.show("mass", p.top_weight_kg)), css("--series-2"), { pointRadius: 3 }),
    ] },
    options: {
      scales: { y: { beginAtZero: false, title: { display: true, text: U.label("mass") } } },
      plugins: { tooltip: { callbacks: { footer: (items) => { const p = pts[items[0].dataIndex]; return `${p.sets} sets · ${p.reps} reps · ${U.fmt("mass", p.volume_kg, 0)} volume`; } } } },
    },
  });
  const first = pts.find((p) => p.est_1rm_kg), last = [...pts].reverse().find((p) => p.est_1rm_kg);
  $("#strengthSummary").textContent = first && last && first !== last
    ? `Estimated 1RM ${U.show("mass", first.est_1rm_kg)} → ${U.fmt("mass", last.est_1rm_kg)} (${last.est_1rm_kg >= first.est_1rm_kg ? "+" : ""}${U.fmt("mass", last.est_1rm_kg - first.est_1rm_kg)}) across ${pts.length} sessions.`
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
  U.set(p.units === "imperial");
  for (const [k, v] of Object.entries(p)) if (pf.elements[k]) Array.isArray(v) ? (pf.elements[k].value = v.join(", ")) : setField(pf.elements[k], v);
  const gf = $("#goalsForm");
  for (const [k, v] of Object.entries(g)) if (gf.elements[k] && k !== "follow_garmin") setField(gf.elements[k], v);
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
  $('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#f4f6fb" : "#0b1426");
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


U.apply();
$("#unitsSelect").addEventListener("change", async (e) => {
  // keep what's typed in the form correct when switching units
  const pf = $("#profileForm"), gf = $("#goalsForm");
  const metric = [...pf.querySelectorAll("input[data-unit]"), ...gf.querySelectorAll("input[data-unit]")]
    .map((el) => [el, U.toMetric(el.dataset.unit, el.value)]);
  U.set(e.target.value === "imperial");
  for (const [el, v] of metric) setField(el, v);
  try {
    const p = await api("/api/profile");
    await api("/api/profile", { method: "PUT", body: { ...p, units: e.target.value } });
    toast(e.target.value === "imperial" ? "Showing lb, ft/in, miles and oz" : "Showing kg, cm, km and grams");
  } catch (err) { toast(err.message, true); }
});
api("/api/profile").then((p) => {
  if ((p.units === "imperial") !== U.imperial) { U.set(p.units === "imperial"); show(state.view || "dashboard"); }
}).catch(() => {});
const initial = location.hash.slice(1) === "plans" ? "exercise" : location.hash.slice(1);
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


// Every popup: closes with its Back button, the phone's back gesture, a tap outside, or Escape.
(function dialogsBack() {
  let open = null;
  const show = HTMLDialogElement.prototype.showModal;
  HTMLDialogElement.prototype.showModal = function () {
    show.call(this);
    open = this;
    document.body.classList.add("dlg-open");
    history.pushState({ dlg: this.id }, "");
  };
  document.addEventListener("close", (e) => {
    if (e.target.tagName !== "DIALOG") return;
    document.body.classList.remove("dlg-open");
    if (open === e.target) { open = null; if (history.state?.dlg) history.back(); }
  }, true);
  window.addEventListener("popstate", () => { if (open) { const d = open; open = null; d.close(); } });
  document.addEventListener("click", (e) => { if (e.target.tagName === "DIALOG" && e.target.open) e.target.close(); });
})();
