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
// per-person browser settings: keys are prefixed with the chosen person's id
const WHO_SET = (() => { try { return !!localStorage.getItem("who"); } catch { return false; } })();
const WHO = (() => { try { return localStorage.getItem("who") || "1"; } catch { return "1"; } })();
const store = {
  get(k) { try { return localStorage.getItem(WHO === "1" ? k : `u${WHO}:${k}`); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(WHO === "1" ? k : `u${WHO}:${k}`, v); } catch {} },
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(WHO_SET ? { "X-HT-User": WHO } : {}) },
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
// every part of the day's burn, one row each
function burnRows(bp, eaten, burned) {
  if (!bp) return "";
  const max = Math.max(eaten, burned, 1);
  const row = (label, v, sub) => `<div class="vs-row"><span>${label}${sub ? `<small class="muted"> ${sub}</small>` : ""}</span>
    <div class="ibar"><div class="ibar-fill burn" style="width:${Math.min(100, (v / max) * 100)}%"></div></div><b>${fmt(v)}</b></div>`;
  return [
    row("Resting", bp.resting),
    row("Digestion", bp.digestion),
    bp.steps_counted != null ? row("Steps", bp.steps, `${fmt(bp.steps_counted)}`) : row("Daily movement", bp.movement, "estimate"),
    row("Workouts", bp.workouts),
    row("Cardio & sports", bp.cardio),
    bp.other ? row("Other logged", bp.other) : "",
  ].join("");
}
function burnHint(bp) {
  if (!bp) return "";
  return `Resting = what your body uses just to stay alive (from age, height, weight). Digestion = ~10% of energy used to process food.
    ${bp.steps_counted != null ? `Steps = your steps × your stride (from height) × your weight (walking ≈ 0.5 kcal per kg per km); steps inside logged walks/runs aren't counted twice.`
      : `Daily movement is an estimate: log today's steps (tap Steps) for an exact number.`}
    Workouts = planned workouts marked done ✓. Cardio & sports = everything logged in Workouts, by activity and minutes.`;
}
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
// Plain-language effort levels (the watch calls these heart-rate zones).
function pace(zone) {
  const z = String(zone || "");
  if (/4.?5|5/.test(z)) return { short: "hard pace", long: "hard: you're breathing hard and can't really talk", watch: z };
  if (/3/.test(z)) return { short: "medium-hard pace", long: "medium-hard: you can only say a few words at a time", watch: z };
  return { short: "easy pace", long: "easy and steady: you breathe a bit harder but can still talk in full sentences", watch: z || "Zone 2" };
}
function sessionSummary(x) {
  const kcal = x.est_kcal ? ` · ~${x.est_kcal} kcal` : "";
  if (x.type === "cardio") return `${x.minutes} min · ${pace(x.zone).short}${kcal}`;
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
      : `<p class="hero-big">${ts.minutes} minutes <span class="muted">· ${pace(ts.zone).short}</span></p>
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
  const w = await api(`/api/water?day=${state.day}`).catch(() => null);
  $("#dayChips").innerHTML = [
    w ? chip("💧 Water", `${w.glasses}/${w.goal} glasses`, `${waterLine(w)} · tap to log`, 'role="button" tabindex="0" data-quick="water"') : "",
    chip("😴 Sleep", g.sleep_h.value == null ? "–" : hm(g.sleep_h.value), `goal ${g.sleep_h.goal} h · tap to log`, 'role="button" tabindex="0" data-quick="sleep"'),
    chip("Workouts", `${g.workouts_week.value}/${g.workouts_week.goal}`, "this week · tap to open", 'role="button" tabindex="0" data-goto="exercise"'),
    chip("⚖️ Weight", g.weight.value == null ? "–" : `${U.show("mass", g.weight.value)}`, `${g.weight.value == null ? "" : U.label("mass") + " · "}tap to log`, 'role="button" tabindex="0" data-log-weight'),
    chip("Workout", d.today_session && d.today_session.type !== "rest" ? esc(sessionTitle(d.today_session)) : "Rest", d.today_done ? "✓ done" : "today · tap to open", 'role="button" tabindex="0" data-goto="exercise"'),
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
  const typedBurn = d.burn_source === "typed", bp = d.burn_parts || {}, exKcal = Math.round(bp.exercise ?? d.cardio_kcal ?? 0), restKcal = burned != null ? Math.round(burned - exKcal) : 0;
  const steps = g.steps.value || 0;
  const eatState = eaten > target ? "bad" : "good";
  const lights = [
    { on: eaten > target, cls: "bad", icon: "⚠", text: "Over calories" },
    { on: eaten > 0 && c.protein_g < protGoal * 0.5 && new Date().getHours() >= 15, cls: "warn", icon: "P", text: "Protein low" },
    { on: d.today_done, cls: "good", icon: "✓", text: "Workout done" },
    { on: g.steps.goal && steps >= g.steps.goal, cls: "good", icon: "👟", text: "Steps goal hit" },
    { on: eaten === 0, cls: "muted", icon: "⛽", text: "Nothing logged yet" },
  ].filter((l) => l.on);

  $("#cluster").innerHTML = `
    <div class="cluster">
      <div class="g-main tap" role="button" tabindex="0" data-goto="diet" title="Log food">${Gauge.dial({ id: "eat", value: eaten, max: Math.max(target * 1.3, eaten * 1.05), target,
        label: "EATEN", unit: `of ${fmt(target)} kcal`, readout: fmt(eaten), ticks: 6, state: eatState })}</div>
      <div class="g-side tap" role="button" tabindex="0" data-goto="exercise" data-focus="#cardioAct" title="Log cardio">${Gauge.dial({ id: "burn", value: burned || 0, max: burnGoal * 1.2, target: t.tdee || null, zone: "good",
        label: "BURNED", unit: burned == null ? "tap to log" : typedBurn ? "from your watch" : `body ${fmt(restKcal)} + activity ${fmt(exKcal)}`, readout: burned == null ? "–" : fmt(burned), ticks: 5,
        state: burned != null && t.tdee && burned >= t.tdee ? "good" : "" })}</div>
      <div class="g-side tap" role="button" tabindex="0" data-goto="diet" title="Log food">${Gauge.dial({ id: "prot", value: c.protein_g, max: protGoal * 1.25, target: protGoal, zone: "good",
        label: "PROTEIN", unit: `of ${fmt(protGoal)} g`, readout: fmt(c.protein_g), ticks: 4, state: c.protein_g >= protGoal ? "good" : "" })}</div>
    </div>
    <div class="info-boxes">
      <div class="ibox tap" role="button" tabindex="0" data-goto="diet">
        <span class="ibox-title">🍽 Food left for today</span>
        <span class="ibox-big ${left >= 0 ? "good" : "bad"}">${left >= 0 ? `${fmt(left)} calories` : `${fmt(-left)} calories over`}</span>
        <div class="ibar"><div class="ibar-fill ${left >= 0 ? "good" : "bad"}" style="width:${Math.min(100, (eaten / target) * 100)}%"></div></div>
        <span class="ibox-sum">Your daily limit <b>${fmt(target)}</b> − eaten so far <b>${fmt(eaten)}</b> = <b>${left >= 0 ? `${fmt(left)} left` : `${fmt(-left)} over`}</b></span>
        <span class="ibox-hint">${left >= 0 ? "This is how much more you can eat today and still lose weight." : "You've eaten more than your limit today, so you'll lose less than planned. Try a walk and a lighter dinner."}</span>
      </div>
      <div class="ibox tap" role="button" tabindex="0" data-goto="exercise" data-focus="#cardioAct">
        <span class="ibox-title">⚖️ Eaten vs. burned today</span>
        ${burned == null ? `<span class="ibox-big">–</span><span class="ibox-hint">Tap to log the calories your watch says you burned today. Then you'll see if you ate less than you burned.</span>` : `
        <div class="vs-row"><span>Eaten</span><div class="ibar"><div class="ibar-fill eat" style="width:${Math.min(100, (eaten / Math.max(eaten, burned)) * 100)}%"></div></div><b>${fmt(eaten)}</b></div>
        ${typedBurn ? `<div class="vs-row"><span>Burned</span><div class="ibar"><div class="ibar-fill burn" style="width:${Math.min(100, (burned / Math.max(eaten, burned)) * 100)}%"></div></div><b>${fmt(burned)}</b></div>` : `
        ${burnRows(d.burn_parts, eaten, burned)}`}
        ${eaten > 0 ? `<span class="ibox-big ${net <= 0 ? "good" : "bad"}">${net <= 0 ? `You burned ${fmt(-net)} more than you ate` : `You ate ${fmt(net)} more than you burned`}</span>` : `<span class="ibox-big">Nothing eaten logged yet</span>`}
        <span class="ibox-hint">${d.burn_source === "typed" ? "Burned = the total you typed from your watch." : burnHint(d.burn_parts)}</span>
        <span class="ibox-hint">${net <= 0 ? "Good: burning more than you eat is what makes you lose weight." : "To lose weight, you need to burn more than you eat."}</span>`}
      </div>
      <div class="ibox tap" role="button" tabindex="0" data-quick="steps">
        <span class="ibox-title">👟 Steps today <small>· tap to log</small></span>
        <span class="ibox-row">${Gauge.odometer(steps, 5)}<span class="ibox-goal">of ${fmt(g.steps.goal || 10000)}</span></span>
        <div class="ibar"><div class="ibar-fill ${steps >= (g.steps.goal || 10000) ? "good" : "eat"}" style="width:${Math.min(100, (steps / (g.steps.goal || 10000)) * 100)}%"></div></div>
        <span class="ibox-hint">${steps >= (g.steps.goal || 10000) ? "Goal reached ✓" : `${fmt((g.steps.goal || 10000) - steps)} more steps to reach your goal`}</span>
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
  loadWater(); loadWeekly();
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

  const byMeal = { breakfast: [], lunch: [], snack: [], dinner: [] };
  foods.forEach((f) => (byMeal[f.meal] || byMeal.snack).push(f));
  const icons = { breakfast: "🌅", lunch: "🥗", snack: "🍎", dinner: "🍽" };
  const sum = (items, k) => items.reduce((a, f) => a + (f[k] || 0), 0);
  $("#foodLog").innerHTML = Object.entries(byMeal).map(([meal, items]) => `
    <section class="meal-box">
      <h4 class="meal-title">${icons[meal]} <span style="text-transform:capitalize">${meal}</span></h4>
      ${items.length ? `<ul class="meal-items">${items.map((f) => `<li>
        <div class="mi-top"><span class="mi-name">${esc(U.food(f.name))}${f.servings !== 1 ? ` <span class="muted">×${f.servings}</span>` : ""}</span>
          <button class="icon" data-del-food="${f.id}" title="Delete" aria-label="Delete ${esc(f.name)}">✕</button></div>
        <div class="mi-nums"><b>${fmt(f.calories)} kcal</b><span>Protein ${fmt(f.protein_g)} g</span><span>Carbs ${fmt(f.carbs_g)} g</span><span>Fat ${fmt(f.fat_g)} g</span></div>
      </li>`).join("")}</ul>` : `<p class="muted small meal-empty">Nothing logged yet</p>`}
      <div class="meal-total"><span>Total</span><b>${fmt(sum(items, "calories"))} kcal</b>
        <small>P ${fmt(sum(items, "protein_g"))} g · C ${fmt(sum(items, "carbs_g"))} g · F ${fmt(sum(items, "fat_g"))} g</small></div>
    </section>`).join("")
    + (() => {
      const eaten = sum(foods, "calories"), limit = t.calories, over = eaten > limit, left = Math.round(limit - eaten);
      const msg = !foods.length ? "Log your first meal to start the day."
        : over ? `⚠️ You're ${fmt(eaten - limit)} calories over your ${fmt(limit)} limit. Don't give up: take an extra walk and keep the next meal light. Tomorrow is a fresh start! 💪`
        : left <= limit * 0.1 ? `👏 Good job! Only ${fmt(left)} calories left. You're right on target, so keep it light for the rest of the day.`
        : `✅ Good job, you're within your limit! ${fmt(left)} calories left for today. Keep it up! 🔥`;
      // alert once when a new entry pushes the day over the limit
      const key = `over-${state.day}`;
      if (over && foods.length && !sessionStorage.getItem(key)) { try { sessionStorage.setItem(key, "1"); } catch {} toast(`⚠️ Over your daily limit by ${fmt(eaten - limit)} calories. You've got this: a walk helps!`, true); }
      if (!over) try { sessionStorage.removeItem(key); } catch {}
      return `<div class="meal-total day ${over ? "over" : "ok"}"><span>Today's total</span><b>${fmt(eaten)} <small class="of">/ ${fmt(limit)} kcal</small></b>
        <small>P ${fmt(sum(foods, "protein_g"))} g · C ${fmt(sum(foods, "carbs_g"))} g · F ${fmt(sum(foods, "fat_g"))} g</small>
        <p class="day-msg">${msg}</p></div>`;
    })();

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
function kcalPer(food, unit) {  // calories in one of `unit`
  if (unit === "serving") return food.calories;
  const g = gramsPer(food, unit);
  return g && food.grams ? (food.calories * g) / food.grams : null;
}
function unitLabel(unit, food) {
  const k = kcalPer(food, unit);
  const per = k == null ? "" : unit === "g" ? ` — ${fmt(k * 100)} kcal per 100 g` : ` — ${fmt(k, k < 10 ? 1 : 0)} kcal per ${unit === "serving" ? "serving" : unit}`;
  return unit === "serving" ? `servings of ${food.unit}${per}` : `${unit}${per}`;
}
function openPick(food) {
  pick.food = food;
  $("#pickResults").innerHTML = "";
  $("#pickPanel").classList.remove("hidden");
  $("#pickName").textContent = food.food || food.name;
  const per = [[food.unit, food.calories, ""]].concat(food.grams ? [["100 g", kcalPer(food, "g") * 100], ["1 oz", kcalPer(food, "oz")]] : []);
  $("#pickBase").innerHTML = `<span class="per-grid">${per.map(([u, k, sub]) => `<span><b>${fmt(k)} kcal</b><small>per ${u}${sub ? ` (${esc(sub)})` : ""}</small></span>`).join("")}</span>
    <span class="small muted">1 serving: protein ${food.protein_g} g · carbs ${food.carbs_g} g · fat ${food.fat_g} g · fibre ${food.fiber_g ?? 0} g</span>`;
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
  const can = pick.food && pick.food.grams;
  document.querySelectorAll("#unitSeg [data-seg]").forEach((b) => { b.classList.toggle("on", b.dataset.seg === unit); b.hidden = b.dataset.seg !== "serving" && !can; });
  $("#pickQuick").innerHTML = (QUICK[unit] || []).map((q) => `<button type="button" class="chip-btn" data-q="${q}">${q}</button>`).join("");
  const w = t.grams != null && unit !== "g" ? `≈ ${U.imperial ? `${(t.grams / 28.35).toFixed(1)} oz` : `${Math.round(t.grams)} g`}` : "";
  $("#pickResult").innerHTML = `<span class="kcal">${fmt(t.calories)}<small> kcal</small></span>
    <span class="macros"><b class="p">P ${t.protein_g.toFixed(1)}</b><b class="c">C ${t.carbs_g.toFixed(1)}</b><b class="f">F ${t.fat_g.toFixed(1)}</b></span>
    <span class="muted small">${w}</span>`;
  $("#pickAdd").disabled = !(t.factor > 0);
}
$("#pickAmount").addEventListener("input", updatePick);
$("#unitSeg").addEventListener("click", (e) => {
  const b = e.target.closest("[data-seg]");
  if (!b) return;
  pick.lastGrams = pickTotals().grams;
  $("#pickUnit").value = b.dataset.seg;
  $("#pickUnit").dispatchEvent(new Event("change"));
});
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
  $("#pickPanel").classList.add("hidden"); $("#foodPick").value = ""; $("#foodSearch").value = ""; pick.food = null; pick.lastGrams = null;
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
      `<li data-pick="${i}" tabindex="0"><span>${f.custom ? "★ " : ""}${esc(f.food || f.name)} <span class="muted small">${esc(U.food(f.unit || ""))}</span></span><span class="muted small">${fmt(f.calories)} kcal per serving</span></li>`).join("")
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
      `<li data-food-idx="${i}" tabindex="0"><span>${f.custom ? "★ " : ""}${esc(U.food(f.name))}</span><span class="muted small">${fmt(f.calories)} kcal per serving</span></li>`).join("")
      || `<li class="muted small">Not found. Enter it yourself below and the app will remember it.</li>`;
    $("#foodResults")._items = items;
  }, 200);
});
$("#foodResults").addEventListener("click", (e) => {
  const li = e.target.closest("[data-food-idx]");
  if (!li) return;
  const f = $("#foodResults")._items[li.dataset.foodIdx];
  $("#foodResults").innerHTML = "";
  openPick(f); pick.lastGrams = pickTotals().grams;
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
  // one block per food found: its numbers, then (for dishes) every ingredient right underneath
  const lbl = { calories: "kcal", protein_g: "Protein g", carbs_g: "Carbs g", fat_g: "Fat g", fiber_g: "Fibre g" };
  $("#aiItems").innerHTML = ai.items.map((it, i) => `<section class="ai-item" data-i="${i}">
      <div class="ai-head"><label class="ai-keep"><input type="checkbox" data-k="keep" ${it.keep ? "checked" : ""} aria-label="Include"></label>
        <input class="ai-name" data-k="name" value="${esc(it.name)}" aria-label="Food">
        <span class="conf ${it.confidence}" title="How sure the estimate is">${it.confidence}</span></div>
      <label class="ai-portion">Portion <input data-k="portion" value="${esc(U.food(it.portion))}"></label>
      <div class="ai-nums">${AI_NUMS.map((k) => `<label>${lbl[k]}<input type="number" min="0" step="1" data-k="${k}" value="${Math.round(it[k] ?? 0)}"></label>`).join("")}</div>
      ${it.ingredients?.length ? `<div class="ing-card">
        <p class="ing-total"><b>What's in it · total ${fmt(it.calories)} kcal</b> · protein ${fmt(it.protein_g, 1)} g · carbs ${fmt(it.carbs_g, 1)} g · fat ${fmt(it.fat_g, 1)} g</p>
        <ul class="ing-list">${it.ingredients.map((g) => `<li><b>${esc(g.name)}</b>: ${fmt(g.grams)} g → ${fmt(g.calories)} kcal · P ${fmt(g.protein_g, 1)} · C ${fmt(g.carbs_g, 1)} · F ${fmt(g.fat_g, 1)}</li>`).join("")}</ul>
        <p class="muted small">USDA values per ingredient; amounts are a typical home recipe scaled to your portion.</p></div>` : ""}
    </section>`).join("") || `<p class="muted">No foods recognised.</p>`;
  updateAiTotals();
}
function updateAiTotals() {
  const kept = ai.items.filter((i) => i.keep);
  const sum = (k) => Math.round(kept.reduce((a, i) => a + (Number(i[k]) || 0), 0));
  $("#aiTotals").textContent = `${sum("calories")} kcal · P${sum("protein_g")} C${sum("carbs_g")} F${sum("fat_g")}`;
  $("#aiLog").disabled = kept.length === 0;
}
$("#aiItems").addEventListener("input", (e) => {
  const row = e.target.closest("[data-i]");
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
    const res = await fetch("/api/foods/analyze", { method: "POST", body: fd, headers: WHO_SET ? { "X-HT-User": WHO } : {} });
    if (res.status === 401) { location.href = "/login"; return; }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Analysis failed");
    ai.items = data.items.map((i) => ({ ...i, keep: true }));
    $("#aiMeal").value = data.meal_guess;
    // "last night" / "yesterday": log to the day before (when looking at today)
    ai.day = data.day_offset === -1 && state.day === today() ? isoDate(new Date(Date.now() - 864e5)) : state.day;
    $("#aiNotes").dataset.day = ai.day;
    $("#aiNotes").textContent = (ai.day !== today() ? `Logging to ${shortDay(ai.day)}. ` : "") + (data.notes || "");
    renderAiItems();
    $("#aiResult").classList.remove("hidden");
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Find the foods";
  }
});
$("#aiLog").addEventListener("click", (e) => withBusy(e.target, async () => {
  const meal = $("#aiMeal").value;
  const items = ai.items.filter((i) => i.keep && i.name.trim()).map((i) => ({
    day: ai.day || state.day, meal, servings: 1,
    name: (i.portion ? `${i.name.trim()} (${i.portion.trim()})` : i.name.trim()).slice(0, 200),
    ...Object.fromEntries(AI_NUMS.map((k) => [k, Number(i[k]) || 0])),
  }));
  await api("/api/foods/bulk", { method: "POST", body: { items } });
  toast(`Logged ${items.length} item${items.length === 1 ? "" : "s"} to ${meal}${(ai.day || state.day) !== today() ? `, ${shortDay(ai.day || state.day)}` : ""}`);
  resetAi();
  loaders.diet();
}));
$("#aiDiscard").addEventListener("click", resetAi);

// ---- voice: speak the meal; it's written into the box and the foods are found automatically.
// Free: uses the phone's own speech recognition, or the keyboard's dictation microphone.
// iPhone home-screen apps often block in-page speech recognition, so there the 🎤 button opens the
// keyboard and you speak with its microphone; the foods are found as soon as you stop.
(() => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = $("#voiceBtn"), box = $("#aiForm").elements.description, hint = $("#voiceHint");
  const iosApp = navigator.standalone === true || (/iPhone|iPad/.test(navigator.userAgent) && matchMedia("(display-mode: standalone)").matches);
  let keyboardMode = !SR || iosApp || store.get("voiceKeyboard") === "1";
  const lang = "en-US";

  // keyboard dictation: when the text stops changing for 2 seconds, find the foods
  let typingTimer = null, viaVoice = false;
  box.addEventListener("input", () => {
    if (!viaVoice) return;
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => { if (box.value.trim()) { viaVoice = false; $("#aiForm").requestSubmit(); } }, 2000);
  });
  function useKeyboard(msg) {
    keyboardMode = true;
    hint.innerHTML = `🎙️ <b>Tap the microphone on your keyboard</b> (bottom right) and say what you ate. The foods appear as soon as you stop.`;
    hint.classList.remove("hidden");
    viaVoice = true;
    box.focus();
    if (msg) toast(msg);
  }

  let rec = null, heard = "", silence = null;
  btn.addEventListener("click", () => {
    if (keyboardMode) return useKeyboard();
    if (rec) { rec.stop(); return; }
    rec = new SR();
    rec.lang = lang;
    rec.interimResults = true;
    rec.continuous = true;            // don't give up after a short pause
    const before = box.value.trim();
    heard = "";
    const stopSoon = () => { clearTimeout(silence); silence = setTimeout(() => rec && rec.stop(), 2500); };
    rec.onresult = (e) => {
      heard = [...e.results].map((r) => r[0].transcript).join(" ");
      box.value = (before ? before + ", " : "") + heard;
      stopSoon();                     // stop 2.5 s after you finish talking
    };
    rec.onerror = (e) => {
      const why = {
        "no-speech": "I didn't hear anything. Tap 🎤 and start talking right away, close to the phone.",
        "audio-capture": "No microphone found. Using the keyboard microphone instead.",
        "network": "Voice needs an internet connection. Using the keyboard microphone instead.",
      }[e.error];
      if (["not-allowed", "service-not-allowed", "audio-capture", "network", "language-not-supported"].includes(e.error)) {
        store.set("voiceKeyboard", "1");
        useKeyboard(why || "Voice isn't available inside this app. Use the 🎙️ on your keyboard instead.");
      } else if (why) toast(why, true);
    };
    rec.onend = () => {
      clearTimeout(silence);
      rec = null; btn.classList.remove("listening"); btn.textContent = "🎤 Speak";
      if (heard.trim()) $("#aiForm").requestSubmit();  // find the foods straight away
    };
    btn.classList.add("listening"); btn.textContent = "● Listening… tap to stop";
    try { rec.start(); } catch { rec = null; useKeyboard(); }
  });
  if (keyboardMode) hint.innerHTML = `🎙️ Tap <b>🎤 Speak</b>, then the <b>microphone on your keyboard</b>, and say what you ate.`, hint.classList.remove("hidden");
})();

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
    $("#exCredit").textContent = lib.credit || `${lib.similar ? "Photo" : "Photos & instructions"}: ${lib.name} (free-exercise-db, public domain)`;
  }
  $("#exMuscles").innerHTML = (info.primaryNames.length
    ? `<span class="mtag prim">Main: ${info.primaryNames.map(esc).join(", ")}</span>` : `<span class="mtag">General movement</span>`)
    + (info.secondaryNames.length ? `<span class="mtag sec">Also: ${info.secondaryNames.map(esc).join(", ")}</span>` : "");
  $("#exCues").innerHTML = info.cues.map((c) => `<li>${esc(c)}</li>`).join("")
    + `<li class="vid-li">${videoButton(name, "▶ Watch the video for this exercise")}</li>`;
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
  loadSteps(); loadCardioLog();
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

// one exact demonstration video per exercise, played in YouTube's free privacy-enhanced player
const VIDEOS = { map: null };
api("/api/exercise-videos").then((m) => { VIDEOS.map = m; }).catch(() => {});
const videoUrl = (name) => "https://www.youtube.com/results?search_query=" + encodeURIComponent(`how to do ${name.replace(/\s*\(.*?\)/g, "")} exercise proper form`);
function videoButton(name, label = "▶ Watch video") {
  return `<button type="button" class="vid-link" data-video="${esc(name)}">${label}</button>`;
}
async function playVideo(name) {
  if (!VIDEOS.map) { try { VIDEOS.map = await api("/api/exercise-videos"); } catch { VIDEOS.map = {}; } }
  const id = VIDEOS.map[name];
  if (!id) { window.open(videoUrl(name), "_blank", "noopener"); return; }
  const dlg = $("#videoDialog");
  $("#videoTitle").textContent = name;
  $("#videoFrame").innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0&playsinline=1&modestbranding=1"
    title="${esc(name)}" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`;
  $("#videoOpen").href = `https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;
  dlg.showModal();
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-video]");
  if (!b) return;
  e.preventDefault(); playVideo(b.dataset.video);
});
function posterHTML(title, exercises, { sub = "", compact = false } = {}) {
  return `<div class="exlist${compact ? " compact" : ""}">
    ${title ? `<h3 class="poster-title">${esc(title)}</h3>` : ""}${sub ? `<p class="poster-sub">${sub}</p>` : ""}
    ${exercises.map((x, i) => `<article class="excard" data-poster="${esc(x.photo || x.exercise)}" data-cardio="${x.pattern === "cardio" ? 1 : ""}" data-compact="${compact ? 1 : ""}">
      <header><span class="exnum">${i + 1}</span><h4>${esc(x.exercise)}</h4></header>
      <div class="pimg"><span class="pimg-ph">${esc(x.exercise.slice(0, 1))}</span></div>
      ${x.pattern === "cardio" ? `<dl class="exstats one"><div><dt>How long</dt><dd>${esc(x.reps)}</dd></div></dl>` : `<dl class="exstats"><div><dt>Rounds</dt><dd>${x.sets}</dd></div><div><dt>Times each round</dt><dd>${esc(x.reps)}</dd></div>
        ${x.rest_s ? `<div><dt>Rest between rounds</dt><dd>${x.rest_s} sec</dd></div>` : ""}</dl>
        ${x.load ? `<p class="exload">🏋️ Start with <b>${U.imperial ? `${fmt(x.load.lb)} lb` : `${fmt(x.load.kg, 1)} kg`}</b> ${esc(x.load.per)}
          <span class="muted small">· too easy (3+ reps left)? go up next time. Can't finish the reps? go down.</span></p>` : ""}`}
      <div class="exmus"></div>
      <ol class="exsteps"${x.howto ? ' data-own="1"' : ""}>${(x.howto || []).map((h) => `<li>${esc(h)}</li>`).join("")}</ol>
      <div class="exbtns"><button class="ghost small" data-ex="${esc(x.photo || x.exercise)}">How to do it</button>
      ${x.pattern === "cardio" ? "" : videoButton(x.exercise)}</div>
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
    const steps = t.dataset.cardio ? (/1 minute fast/.test(t.dataset.poster)
      ? ["Walk fast for 1 minute, as if you're late for a bus.", "Then walk slowly for 2 minutes to catch your breath.", "Repeat this 8 times. Use your phone or watch as a timer."]
      : ["Walk fast outside or on a treadmill, or ride a bike (an exercise bike is fine).", "Keep going without stopping for the whole time.", "Go at a pace where you breathe harder but can still talk in full sentences."])
      : (own && m.instructions.length ? m.instructions : local.cues || []).slice(0, t.dataset.compact ? 2 : 3);
    if (!t.querySelector(".exsteps").dataset.own) t.querySelector(".exsteps").innerHTML = steps.map((s) => `<li>${esc(s)}</li>`).join("");
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


// ---------------------------------------------------------------- choose your cardio machine/activity
// met = effort at a steady, can-still-talk pace (Compendium of Physical Activities)
const CARDIO_OPTS = {
  treadmill_walk_flat: { label: "Treadmill walk (flat, brisk)", machine: true, photo: "Walking, Treadmill", met: 4.3,
    how: ["Incline 0–1%, speed about 5.5–6.5 km/h (3.5–4 mph): walk briskly.", "Don't hold the handrails; swing your arms."] },
  treadmill_walk: { label: "Treadmill walk (incline)", machine: true, photo: "Walking, Treadmill", met: 5.0,
    how: ["Set speed 5–6 km/h (3–3.7 mph) and incline 5–8%.", "Don't hold the handrails; swing your arms."] },
  run: { label: "Jog / run outside", photo: "Trail Running/Walking", met: 7.0,
    how: ["Jog slowly enough that you can still talk.", "If you get out of breath, walk for a minute, then jog again."] },
  treadmill_run: { label: "Treadmill jog", machine: true, photo: "Jogging, Treadmill", met: 7.0,
    how: ["Start at 7–8 km/h (4.5–5 mph), flat or 1% incline.", "Slow down to a fast walk if you can't talk."] },
  bike: { label: "Upright exercise bike", machine: true, photo: "Bicycling, Stationary", met: 6.8,
    how: ["Seat height: your knee is only slightly bent at the bottom.", "Medium resistance; pedal at a steady pace you can keep."] },
  recumbent: { label: "Recumbent bike (with back rest)", machine: true, photo: "Recumbent Bike", met: 5.5,
    how: ["Easy on knees and back.", "Medium resistance; pedal at a steady pace you can keep."] },
  elliptical: { label: "Elliptical / cross-trainer", machine: true, photo: "Elliptical Trainer", met: 5.0,
    how: ["Stand tall, push and pull the handles.", "Medium resistance; keep a smooth, steady rhythm."] },
  jump_rope: { label: "Rope skipping", photo: "Rope Jumping", met: 8.8,
    how: ["Small, low hops on the balls of your feet; turn the rope with your wrists.", "Beginners: skip 30 seconds, rest 30 seconds, and repeat. Count only the time you skip."] },
  // sports: pick any of them on any day; effort values from the Compendium of Physical Activities
  yoga_hatha: { label: "Yoga: Hatha (gentle)", group: "Yoga", met: 2.5, how: ["Count the whole class or session."] },
  yoga_vinyasa: { label: "Yoga: Vinyasa / flow (sun salutations)", group: "Yoga", met: 3.3, how: ["Flowing from pose to pose."] },
  yoga_power: { label: "Yoga: Power / Ashtanga", group: "Yoga", met: 4.0, how: ["Strong, sweaty, continuous practice."] },
  yoga_yin: { label: "Yoga: Yin / restorative", group: "Yoga", met: 2.0, how: ["Long, relaxed holds and breathing."] },
  tennis_singles: { label: "Tennis (singles)", group: "Racquet sports", met: 8.0, how: ["Count only the time you're playing, not long breaks."] },
  tennis_doubles: { label: "Tennis (doubles)", group: "Racquet sports", met: 6.0, how: ["Count only the time you're playing, not long breaks."] },
  padel: { label: "Padel", group: "Racquet sports", met: 6.0, how: ["Count the time on court."] },
  pickleball: { label: "Pickleball", group: "Racquet sports", met: 4.5, how: ["Count the time on court."] },
  badminton: { label: "Badminton (casual)", group: "Racquet sports", met: 5.5, how: ["Pick 'competitive' if you played hard rallies."] },
  badminton_hard: { label: "Badminton (competitive)", group: "Racquet sports", met: 7.0, how: ["Hard, fast rallies."] },
  squash: { label: "Squash", group: "Racquet sports", met: 7.3, how: ["Count the time on court."] },
  racquetball: { label: "Racquetball", group: "Racquet sports", met: 7.0, how: ["Count the time on court."] },
  table_tennis: { label: "Table tennis / ping pong", group: "Racquet sports", met: 4.0, how: ["Count the time playing."] },
  ski_downhill: { label: "Downhill skiing", group: "Winter sports", met: 5.3, how: ["Count time skiing, not lifts or breaks."] },
  ski_cross_country: { label: "Cross-country skiing", group: "Winter sports", met: 9.0, how: ["Steady pace; count the time moving."] },
  snowboarding: { label: "Snowboarding", group: "Winter sports", met: 5.3, how: ["Count time riding, not lifts or breaks."] },
  ice_skating: { label: "Ice skating", group: "Winter sports", met: 7.0, how: ["Steady skating; count the time on the ice."] },
  ice_hockey: { label: "Ice hockey", group: "Winter sports", met: 8.0, how: ["Count your time on the ice."] },
  snowshoeing: { label: "Snowshoeing", group: "Winter sports", met: 5.3, how: ["Count the time walking."] },
  sledding: { label: "Sledding / tobogganing", group: "Winter sports", met: 7.0, how: ["Includes walking back up the hill."] },
  snow_shoveling: { label: "Shoveling snow", group: "Winter sports", met: 5.3, how: ["Count the time shoveling."] },
  swim_freestyle: { label: "Swimming: front crawl (easy–moderate)", group: "Water sports", met: 5.8, how: ["Count the time swimming, not resting at the wall."] },
  swim_hard: { label: "Swimming: laps, fast", group: "Water sports", met: 9.8, how: ["Hard, continuous laps."] },
  swim_breaststroke: { label: "Swimming: breaststroke", group: "Water sports", met: 5.3, how: ["Count the time swimming."] },
  swim_backstroke: { label: "Swimming: backstroke", group: "Water sports", met: 4.8, how: ["Count the time swimming."] },
  swim_leisure: { label: "Swimming: leisurely / playing", group: "Water sports", met: 6.0, how: ["Splashing around, not laps."] },
  water_aerobics: { label: "Water aerobics / aqua fit", group: "Water sports", met: 5.5, how: ["Count the class time."] },
  kayaking: { label: "Kayaking", group: "Water sports", met: 5.0, how: ["Steady paddling."] },
  canoeing: { label: "Canoeing", group: "Water sports", met: 5.8, how: ["Steady paddling."] },
  paddleboarding: { label: "Stand-up paddleboarding", group: "Water sports", met: 6.0, how: ["Count the time paddling."] },
  rowing_boat: { label: "Rowing (boat)", group: "Water sports", met: 7.0, how: ["Steady rowing."] },
  surfing: { label: "Surfing", group: "Water sports", met: 3.0, how: ["Count the time in the water."] },
  snorkeling: { label: "Snorkeling", group: "Water sports", met: 5.0, how: ["Count the time swimming."] },
  water_polo: { label: "Water polo", group: "Water sports", met: 10.0, how: ["Count your playing time."] },
  water_skiing: { label: "Water skiing / wakeboarding", group: "Water sports", met: 6.0, how: ["Count the time on the water."] },
};
const SPORT_ICON = { Yoga: "🧘", "Racquet sports": "🎾", "Winter sports": "⛷️", "Water sports": "🏊" };
const cardioThumb = (k) => CARDIO_OPTS[k]?.photo ? `<img class="cl-thumb" data-cl-photo="${esc(CARDIO_OPTS[k].photo)}" alt="">`
  : `<span class="cl-thumb cl-emoji">${SPORT_ICON[CARDIO_OPTS[k]?.group] || "🏃"}</span>`;
// dropdown options grouped: gym cardio first, then each sport family
function cardioOptions(cur) {
  const groups = {};
  for (const [k, o] of Object.entries(CARDIO_OPTS)) (groups[o.group || "Cardio"] ||= []).push([k, o]);
  return Object.entries(groups).map(([g, items]) => `<optgroup label="${esc(g)}">${items.map(([k, o]) =>
    `<option value="${k}"${k === cur ? " selected" : ""}>${esc(o.label)}</option>`).join("")}</optgroup>`).join("");
}
const cardioState = { picks: {}, kg: 105 };
const LEGACY_CARDIO = { walk: "treadmill_walk_flat", rower: "bike", stairs: "elliptical" };
const fixCardio = (k) => LEGACY_CARDIO[k] || k;
const cardioFor = (iso) => { const v = cardioState.picks[iso]; return typeof v === "string" ? v : Array.isArray(v) ? v[0].activity : cardioState.picks.default || "treadmill_walk"; };
// The day's cardio as a list of {activity, minutes}; planned minutes go to one activity unless the user split them
const MACHINE_MAX = 30;  // building gym rule: cardio machines 30 minutes at a time
function cardioList(iso, planMin) {
  const v = cardioState.picks[iso];
  if (Array.isArray(v) && v.length) return v;
  const first = typeof v === "string" ? v : cardioState.picks.default || "treadmill_walk";
  if (!CARDIO_OPTS[first]?.machine || planMin <= MACHINE_MAX) return [{ activity: first, minutes: planMin }];
  // split long sessions across machines so none goes over 30 minutes
  const order = [first, ...["bike", "elliptical", "treadmill_walk_flat", "recumbent"].filter((k) => k !== first)], out = [];
  for (let left = planMin, i = 0; left > 0; i++) { const m = Math.min(MACHINE_MAX, left); out.push({ activity: order[i % order.length], minutes: m }); left -= m; }
  return out;
}
const kcalFor = (key, min) => Math.round((CARDIO_OPTS[key].met * 3.5 * cardioState.kg / 200) * min);
const plannedCardioMin = (d) => d.type === "cardio" ? d.minutes
  : (d.exercises || []).filter((x) => x.pattern === "cardio").reduce((t, x) => t + (parseInt(x.reps, 10) || 0), 0);
async function loadCardio() {
  try {
    const [p, prof] = await Promise.all([api("/api/plans/cardio/all"), api("/api/profile")]);
    for (const [k, v] of Object.entries(p)) p[k] = Array.isArray(v) ? v.map((x) => ({ ...x, activity: fixCardio(x.activity) })) : fixCardio(v);
    cardioState.picks = p; cardioState.kg = prof.weight_kg || 105;
  } catch {}
}
function cardioPicker(iso, day) {
  const list = cardioList(iso, plannedCardioMin(day)), total = list.reduce((t, x) => t + x.minutes, 0);
  const isDefault = list.length === 1 && (cardioState.picks.default || "treadmill_walk") === list[0].activity;
  const opts = (cur) => cardioOptions(cur);
  return `<div class="cardio-pick" data-cardio-day="${iso}"><span class="cp-title">🏃 Your cardio for this day</span>
    ${list.map((x, i) => `<div class="cp-row" data-cr="${i}">
      <select data-cr-act aria-label="Activity">${opts(x.activity)}</select>
      <input data-cr-min type="number" inputmode="numeric" min="1" max="300" value="${x.minutes}" aria-label="Minutes"><span class="muted small">min</span>
      ${list.length > 1 ? `<button type="button" class="icon" data-cr-del aria-label="Remove">✕</button>` : ""}</div>`).join("")}
    <button type="button" class="ghost small-btn" data-cr-add>＋ Add another activity</button>
    ${list.some((x) => CARDIO_OPTS[x.activity]?.machine && x.minutes > MACHINE_MAX) ? `<span class="warn-text small">⚠ Your gym allows 30 minutes per cardio machine. Split it: tap "＋ Add another activity".</span>` : ""}
    <span class="small">Total: <b>${total} minutes</b> · about <b>${list.reduce((t, x) => t + kcalFor(x.activity, x.minutes), 0)} calories</b></span>
    ${iso <= isoDate(new Date()) ? `<button type="button" data-cr-log>✓ I did this: log it</button>` : `<span class="muted small">On the day, tap "I did this" to log it.</span>`}
    <div id="dayCardioLogs"></div>
    ${isDefault ? `<span class="muted small">${esc(CARDIO_OPTS[list[0].activity].label)} is your usual choice for all cardio days.</span>`
      : list.length === 1 ? `<button type="button" class="ghost small-btn" data-cardio-default="${list[0].activity}">Use ${esc(CARDIO_OPTS[list[0].activity].label)} for all cardio days</button>` : ""}</div>`;
}
// Swap the plan's generic walk/bike parts for the chosen activity
function withCardio(day, iso) {
  if (!iso || !day || !hasCardio(day)) return day;
  const planMin = plannedCardioMin(day), list = cardioList(iso, planMin);
  const card = (x, intervals) => {
    const o = CARDIO_OPTS[x.activity];
    return { exercise: intervals ? `${o.label}: 1 minute fast, 2 minutes easy` : `${o.label} (no stopping)`, photo: o.photo,
      pattern: "cardio", sets: 1, reps: `${x.minutes} minutes`,
      howto: intervals ? ["Go faster (or add resistance) for 1 minute.", "Then go easy for 2 minutes to catch your breath.", "Repeat until the time is up."]
        : [...o.how, "Go at a pace where you breathe harder but can still talk."] };
  };
  const intervals = (day.exercises || []).some((x) => x.pattern === "cardio" && /1 minute fast/i.test(x.exercise));
  const cards = list.map((x, i) => card(x, intervals && i === 0));
  const cardioKcal = list.reduce((t, x) => t + kcalFor(x.activity, x.minutes), 0);
  const total = list.reduce((t, x) => t + x.minutes, 0);
  if (day.type === "cardio") return { ...day, cardioKey: list[0].activity, cardioCards: cards, minutes: total, est_kcal: cardioKcal };
  const walkKcal = Math.round((4.3 * 3.5 * cardioState.kg / 200) * planMin);
  return { ...day, exercises: [...day.exercises.filter((x) => x.pattern !== "cardio"), ...cards],
    minutes: day.minutes ? day.minutes - planMin + total : day.minutes,
    est_kcal: day.est_kcal ? day.est_kcal - walkKcal + cardioKcal : day.est_kcal };
}
async function saveCardio(box) {
  setTimeout(loadDayLogs, 50);
  const items = [...box.querySelectorAll("[data-cr]")].map((r) => ({
    activity: r.querySelector("[data-cr-act]").value, minutes: Math.max(1, Math.min(300, Number(r.querySelector("[data-cr-min]").value) || 1)) }));
  cardioState.picks = await api("/api/plans/cardio/all", { method: "POST", body: { day: box.dataset.cardioDay, activity: items } });
  $("#activePlan").innerHTML = renderWeek(cal.plan);
}
document.addEventListener("change", (e) => {
  const box = e.target.closest("[data-cardio-day]");
  if (box && e.target.matches("[data-cr-act],[data-cr-min]")) saveCardio(box).catch((err) => toast(err.message, true));
});
document.addEventListener("click", async (e) => {
  const box = e.target.closest("[data-cardio-day]");
  if (!box) return;
  if (e.target.closest("[data-cr-del]")) e.target.closest("[data-cr]").remove();
  else if (e.target.closest("[data-cr-add]")) {
    const first = box.querySelector("[data-cr]"), clone = first.cloneNode(true);
    clone.querySelector("[data-cr-act]").value = first.querySelector("[data-cr-act]").value === "bike" ? "elliptical" : "bike";
    clone.querySelector("[data-cr-min]").value = 15;
    first.parentNode.insertBefore(clone, box.querySelector("[data-cr-add]"));
  } else return;
  try { await saveCardio(box); } catch (err) { toast(err.message, true); }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cardio-default]");
  if (!b) return;
  try {
    cardioState.picks = await api("/api/plans/cardio/all", { method: "POST", body: { day: "default", activity: b.dataset.cardioDefault } });
    $("#activePlan").innerHTML = renderWeek(cal.plan);
    toast(`${CARDIO_OPTS[b.dataset.cardioDefault].label} is now your usual cardio`);
  } catch (err) { toast(err.message, true); }
});

// ================================================================ PLANS
function renderPlanDay(day, compact = false) {
  if (day.type === "rest") return `<div class="plan-day"><div class="wd">${dayName(day.weekday)}</div><strong>Rest / mobility</strong><p class="muted small">Easy walk and stretching. Let your Garmin recovery time come down.</p></div>`;
  if (day.type === "cardio") {
    const o = day.cardioKey ? CARDIO_OPTS[day.cardioKey] : null;
    return `<div class="plan-day cardio"><div class="wd">${dayName(day.weekday)} · cardio</div><strong>${esc(day.cardioCards && day.cardioCards.length > 1 ? "Cardio mix" : o ? o.label : sessionTitle(day))}</strong>
    ${day.cardioCards ? posterHTML("", day.cardioCards) : ""}
    <p>${day.cardioCards ? (day.cardioCards.length > 1 ? "Do these one after the other" : esc(o.label)) : "Walk fast or ride a bike"} for <b>${day.minutes} minutes</b> in total.</p>
    <p class="small"><b>How hard:</b> ${pace(day.zone).long}. (Your watch calls this heart-rate ${esc(pace(day.zone).watch)}.)</p>
    ${day.est_kcal ? `<p class="burn">🔥 You'll burn about <b>${day.est_kcal} calories</b>.</p>` : ""}</div>`;
  }
  const changes = !compact && day.changes?.length
    ? `<details class="small"><summary class="muted">${day.changes.length} adjustment${day.changes.length > 1 ? "s" : ""} for your goal</summary><ul class="tips">${day.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>` : "";
  return `<div class="plan-day strength"><div class="wd">${dayName(day.weekday)}</div><strong>${esc(sessionTitle(day))}</strong>
    ${day.est_kcal ? `<p class="burn">🔥 About <b>${day.est_kcal} calories</b> · ${day.minutes} minutes in total. Do the exercises in order, then finish with your cardio.</p>` : ""}
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
    : `${checkinHTML(cal.sel, sd)}${hasCardio(ss) ? cardioPicker(cal.sel, ss) : ""}${renderPlanDay(withCardio(ss, cal.sel))}<label class="move">Move ${dayName(wd)}'s session to <select data-move-from="${wd}" data-plan="${plan.id}"><option value="">Pick a day…</option>${options}</select></label>`;
  return `<div class="card cal-card">
    <div class="cal-head"><button type="button" class="icon" data-cal-nav="-1" aria-label="Previous month">‹</button>
      <h3>${m.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h3>
      <button type="button" class="icon" data-cal-nav="1" aria-label="Next month">›</button></div>
    <div class="cal-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((x) => `<span class="cal-dow">${x.slice(0, 1)}</span>`).join("")}${cells.join("")}</div>
    <p class="cal-key muted small">💪 Strength · 🏃 Cardio · blank = rest</p>
  </div>
  <div class="card cal-day"><h3>${label}</h3>${detail}</div>`;
}
const hasCardio = (d) => d.type === "cardio" || (d.exercises || []).some((x) => x.pattern === "cardio");
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
  loadDayLogs();
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
  await loadCardio();
  $("#activePlan").innerHTML = active ? renderWeek(active) : `<div class="card hero"><span class="eyebrow">Your plan</span>
    <h2>No workout plan yet</h2><p class="muted">Build one from your Garmin workouts and goals.</p>
    <button class="hero-btn" data-goto="dashboard" data-show-setup>Set up my plan</button></div>`;
  loadDayLogs();
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
  loadWeekly();
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
    loadWho(false);
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
  return;  // the user logs everything by hand; no Garmin or Strava syncing
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
  $('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#f4f6fb" : "#050816");
  if (window.curScheme) applyScheme(window.curScheme, window.curColor);
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
// ---------------------------------------------------------------- people: who's tracking?
// each person has their own colour scheme
const SCHEME_NAMES = { orange: "Orange & navy", pink: "Pink & plum", emerald: "Emerald & teal", violet: "Violet & indigo", red: "Red & charcoal", gold: "Gold & blue", sky: "Light blue", navy: "Navy", forest: "Dark green" };
const SCHEME_BG = { orange: "#050816", pink: "#0e0618", emerald: "#03120f", violet: "#0b0820", red: "#120607", gold: "#080b14", sky: "#04101c", navy: "#020616", forest: "#030d07" };
function applyScheme(scheme, color) {
  scheme = scheme || "orange";
  window.curScheme = scheme; window.curColor = color;
  if (scheme === "orange") document.documentElement.removeAttribute("data-scheme");
  else document.documentElement.setAttribute("data-scheme", scheme);
  window.favPalette?.apply(scheme === "custom" ? color : null);  // favourite colour: the whole theme in its shades
  try { localStorage.setItem("scheme", scheme); if (scheme === "custom") localStorage.setItem("favColor", color); } catch {}
  const bg = scheme === "custom" ? window.favPalette?.bg(color) : SCHEME_BG[scheme];
  if (document.documentElement.getAttribute("data-theme") !== "light") $('meta[name="theme-color"]')?.setAttribute("content", bg || "#050816");
}
function renderSchemes(r) {
  const me = r.users.find((u) => u.current);
  const taken = Object.fromEntries(r.users.filter((u) => !u.current).map((u) => [u.scheme, u.name]));
  $("#schemePicks").innerHTML = Object.entries(r.schemes).map(([k, c]) => `<button type="button" data-scheme-pick="${k}"
    class="${me?.scheme === k ? "on" : ""}" style="background:radial-gradient(circle at 35% 35%, ${c}, ${SCHEME_BG[k]} 85%)"
    title="${esc(SCHEME_NAMES[k])}${taken[k] ? " (" + esc(taken[k]) + ")" : ""}" aria-label="${esc(SCHEME_NAMES[k])}" ${taken[k] ? "disabled" : ""}></button>`).join("");
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-scheme-pick]");
  if (!b) return;
  try {
    await api("/api/users/me/scheme", { method: "PUT", body: { scheme: b.dataset.schemePick } });
    applyScheme(b.dataset.schemePick);
    toast(`🎨 ${SCHEME_NAMES[b.dataset.schemePick]}`);
    loadWho(false);
  } catch (err) { toast(err.message, true); }
});
async function loadWho(openIfUnchosen = true) {
  let r;
  try { r = await api("/api/users"); } catch { return; }
  const me = r.users.find((u) => u.current) || r.users[0];
  try { localStorage.setItem("who", String(r.current)); } catch {}
  if (String(r.current) !== WHO) { location.reload(); return; }
  $("#whoBtn .who-name").textContent = me.name;
  applyScheme(me.scheme, me.color);
  $("#whoBtn .who-dot").style.background = me.color;
  renderSchemes(r);
  $("#whoBtn .who-dot").style.background = me.color;
  $("#whoBtn .who-dot").textContent = me.name.slice(0, 1).toUpperCase();
  $("#whoList").innerHTML = r.users.map((u) => `<button type="button" class="who-item${u.current ? " on" : ""}" data-who="${u.id}">
    <span class="who-dot" style="background:${esc(u.color)}">${esc(u.name.slice(0, 1).toUpperCase())}</span><span>${esc(u.name)}</span>${u.current ? `<span class="small muted">· now</span>` : ""}</button>`).join("");
  if (openIfUnchosen && r.users.length > 1 && !r.chosen) { $("#whoDialog").showModal(); return; }
  // profiles made before the full questionnaire: ask the missing questions (once per visit)
  try {
    const p = await api("/api/profile");
    if (!p.details_done && state.view !== "about") show("about");
  } catch {}
}
$("#whoBtn").addEventListener("click", () => {
  if ($("#whoAddForm").closest("dialog")) { $("#whoAddForm").classList.add("hidden"); $("#whoResult").classList.add("hidden"); }
  $(".who-pick").classList.remove("hidden"); $("#whoDialog").showModal();
});
$("#whoList").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-who]");
  if (!b) return;
  try {
    await api("/api/users/select", { method: "POST", body: { id: Number(b.dataset.who) } });
    try { localStorage.setItem("who", b.dataset.who); } catch {}
    location.hash = ""; location.reload();
  } catch (err) { toast(err.message, true); }
});
$("#whoClose").addEventListener("click", () => $("#whoDialog").close());
function openWhoForm(mode) {
  const f = $("#whoAddForm");
  f.dataset.mode = mode; f.reset();
  $$("[data-group] input", f).forEach((c) => { c.checked = false; });
  $("#whoFormTitle").textContent = mode === "edit" ? "My profile" : "Add a person";
  $("#whoFormNote").textContent = mode === "edit"
    ? "Check every answer. Your calories, protein and targets are worked out exactly from them when you save."
    : "Answer everything: calories, protein and the workout plan are worked out exactly from these answers. Nothing is guessed.";
  $("#whoSubmit").textContent = mode === "edit" ? "Save changes" : "Create profile";
  $("#whoRebuild").classList.toggle("hidden", mode !== "edit");
  $(".who-pick").classList.add("hidden"); $("#whoResult").classList.add("hidden"); f.classList.remove("hidden");
  syncWeightGoal();
}
function syncWeightGoal() {
  const f = $("#whoAddForm"), keep = f.elements.weight_goal.value === "maintain" || !f.elements.weight_goal.value;
  $(".wg-more", f).classList.toggle("hidden", keep);
}
$("#whoAddForm").elements.weight_goal.addEventListener("change", syncWeightGoal);
// "Where do you train?" fills in the equipment; the optional list fine-tunes it
const PLACE_KIT = {
  full_gym: ["dumbbells", "barbell", "bench", "cable", "machines", "pullup", "bands", "kettlebell", "cardio"],
  home_gym: ["dumbbells", "barbell", "bench", "pullup", "bands", "kettlebell"],
  home_light: ["dumbbells", "bands"],
  none: [],
};
document.addEventListener("change", (e) => {
  if (e.target.name !== "train_place") return;
  const want = PLACE_KIT[e.target.value] || [];
  $$('[data-group="equipment_list"] input').forEach((c) => { c.checked = want.includes(c.value); });
});
function placeFor(list) {
  const key = [...list].sort().join();
  return Object.keys(PLACE_KIT).find((k) => [...PLACE_KIT[k]].sort().join() === key);
}
$("#whoAddForm").addEventListener("change", (e) => {  // "None" and real choices can't both be ticked
  const g = e.target.closest('[data-group="injuries"]');
  if (!g || !e.target.checked) return;
  $$("input", g).forEach((c) => { if ((e.target.value === "none") !== (c.value === "none")) c.checked = false; });
});
$("#whoAddBtn").addEventListener("click", () => { mountWhoForm($("#whoDialog")); $("#whoAddBack").classList.remove("hidden"); openWhoForm("add"); $("#whoAddForm").elements.name.focus(); });
async function fillMyProfile() {
  openWhoForm("edit");
  const f = $("#whoAddForm").elements;
  try {
    const [p, g] = await Promise.all([api("/api/profile"), api("/api/goals")]);
    const r1 = (v) => Math.round(v * 10) / 10;
    f.name.value = p.name || "";
    const meU = (await api("/api/users")).users.find((u) => u.current);
    f.favorite_color.value = meU?.favorite_color || ""; favPreview(false);
    f.sex.value = p.sex; f.birth_year.value = p.birth_year;
    f.height_cm.value = r1(p.height_cm); f.weight_kg.value = r1(p.weight_kg);
    f.experience.value = p.experience; f.diet_type.value = p.diet_type;
    f.allergies.value = (p.allergies || []).join(", ");
    if (p.details_done) {  // answers given in the questionnaire before; older profiles must answer them now
      f.activity_level.value = p.activity_level; f.weight_goal.value = p.goal;
      f.target_weight_kg.value = g.target_weight_kg ?? ""; f.goal_weeks.value = p.goal_weeks ?? "";
      f.muscle_goal.value = p.muscle_goal || ""; f.training_days.value = String(p.training_days);
      f.session_minutes.value = String(p.session_minutes);
      if (p.split_style && p.split_style !== "auto") f.split_style.value = p.split_style;
      const tick = (grp, vals) => $$(`[data-group="${grp}"] input`).forEach((c) => { c.checked = vals.includes(c.value); });
      tick("focus_areas", p.focus_areas || []); tick("injuries", (p.injuries || []).length ? p.injuries : ["none"]);
      const kit = (p.equipment_list || []).length ? p.equipment_list : p.equipment === "bodyweight" ? [] : null;
      if (kit) {
        tick("equipment_list", kit);
        const place = placeFor(kit);
        if (place) f.train_place.value = place;
        else { f.train_place.value = kit.includes("barbell") || kit.includes("machines") || kit.includes("cable") ? "full_gym" : kit.length ? "home_gym" : "none"; $(".eq-fine").open = true; }
      }
    } else {
      $("#whoFormNote").textContent = "A few new questions need answering so your targets are exact (they're left blank on purpose).";
    }
    syncWeightGoal();
  } catch (err) { toast(err.message, true); }
}
// favourite colour: show the theme while typing; it's saved with the rest of the answers
let favTimer = null;
async function favPreview(live = true) {
  const el = $("#whoAddForm").elements.favorite_color, note = $("#favNote"), v = el.value.trim();
  if (!v) { note.textContent = ""; return; }
  try {
    const r = await api("/api/users/color?name=" + encodeURIComponent(v));
    $(".fav-pick").value = r.color;
    note.innerHTML = `<span class="fav-dot" style="background:${esc(r.color)}"></span> Your app will use this colour once you save.`;
    if (live && $("#whoAddForm").dataset.mode === "edit") applyScheme("custom", r.color);  // preview on your own app
  } catch (err) { note.textContent = err.message; }
}
$("#whoAddForm").elements.favorite_color.addEventListener("input", () => { clearTimeout(favTimer); favTimer = setTimeout(favPreview, 400); });
$(".fav-pick").addEventListener("input", (e) => { $("#whoAddForm").elements.favorite_color.value = e.target.value; favPreview(); });
// the questionnaire lives in the "About me" tab (and in the people dialog when adding someone)
function mountWhoForm(host) {
  const f = $("#whoAddForm"), r = $("#whoResult");
  if (f.parentElement !== host) { host.appendChild(f); host.appendChild(r); }
}
loaders.about = async () => {
  mountWhoForm($("#aboutHost"));
  api("/api/users/me/maths").then((r) => { $("#aboutMaths").innerHTML = r.lines.map((x) => `<li${x.startsWith("⚠") ? ' class="warn-text"' : ""}>${esc(x)}</li>`).join(""); }).catch(() => {});
  $("#whoAddBack").classList.add("hidden");
  await fillMyProfile();
};
$("#whoEditBtn").addEventListener("click", () => { $("#whoDialog").close(); show("about"); });
$("#whoAddBack").addEventListener("click", () => { $("#whoAddForm").classList.add("hidden"); $(".who-pick").classList.remove("hidden"); if (state.view === "about") loaders.about(); });
$("#whoDone").addEventListener("click", () => { location.hash = "#dashboard"; location.reload(); });
$("#whoAddForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, el = f.elements, btn = $("#whoSubmit");
  const picked = (grp) => $$(`[data-group="${grp}"] input:checked`, f).map((c) => c.value);
  // nothing is guessed: point at the first unanswered question
  const need = ["name", "favorite_color", "sex", "birth_year", "height_cm", "weight_kg", "activity_level", "weight_goal", "muscle_goal",
    "training_days", "session_minutes", "experience", "split_style", "diet_type"];
  if (el.weight_goal.value && el.weight_goal.value !== "maintain") need.push("target_weight_kg", "goal_weeks");
  const miss = need.find((k) => !String(el[k].value).trim());
  if (miss) { el[miss].scrollIntoView({ block: "center" }); el[miss].focus(); toast("Please answer every question.", true); return; }
  if (!f.querySelector('[name="train_place"]:checked')) { $('.place-cards', f).scrollIntoView({ block: "center" }); toast("Choose where you train.", true); return; }
  if (!picked("injuries").length) { $('[data-group="injuries"]', f).scrollIntoView({ block: "center" }); toast("Tick your injuries, or “None”.", true); return; }
  const body = {
    name: el.name.value.trim(), favorite_color: el.favorite_color.value.trim(), sex: el.sex.value, birth_year: Number(el.birth_year.value),
    height_cm: Number(el.height_cm.value), weight_kg: Number(el.weight_kg.value), activity_level: el.activity_level.value,
    weight_goal: el.weight_goal.value,
    target_weight_kg: el.weight_goal.value === "maintain" ? null : Number(el.target_weight_kg.value),
    goal_weeks: el.weight_goal.value === "maintain" ? null : Number(el.goal_weeks.value),
    muscle_goal: el.muscle_goal.value, focus_areas: picked("focus_areas"), training_days: Number(el.training_days.value),
    session_minutes: Number(el.session_minutes.value), experience: el.experience.value,
    equipment_list: picked("equipment_list"), split_style: el.split_style.value,
    injuries: picked("injuries"), diet_type: el.diet_type.value,
    allergies: el.allergies.value.split(",").map((x) => x.trim()).filter(Boolean),
    rebuild_plan: f.dataset.mode === "edit" ? el.rebuild_plan.checked : true,
  };
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "Working it out…";
  try {
    const r = await api(f.dataset.mode === "edit" ? "/api/users/me" : "/api/users", { method: f.dataset.mode === "edit" ? "PUT" : "POST", body });
    try { localStorage.setItem("who", String(r.id)); } catch {}
    f.classList.add("hidden");
    $("#whoResult .who-maths").innerHTML = r.summary.map((x) => `<li>${esc(x)}</li>`).join("");
    $("#whoResult").classList.remove("hidden");
    $("#whoDialog").scrollTop = 0;
  } catch (err) { toast(err.message, true); } finally { btn.disabled = false; btn.textContent = label; }
});
loadWho();

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


// ---------------------------------------------------------------- water (in glasses)
function waterLine(w) {
  const left = Math.max(0, w.goal - w.glasses);
  return left ? `${left} more to go` : "Goal reached ✓";
}
function renderWater(w) {
  $("#waterSub").textContent = `${w.glasses} of ${w.goal} glasses · ${waterLine(w)}`;
  const n = Math.max(w.goal, w.glasses);
  $("#waterGlasses").innerHTML = Array.from({ length: n }, (_, i) =>
    `<span class="glass${i < w.glasses ? " full" : ""}" aria-hidden="true"></span>`).join("")
    + `<span class="sr-only">${w.glasses} of ${w.goal} glasses</span>`;
}
async function loadWater() {
  try { renderWater(await api(`/api/water?day=${state.day}`)); } catch {}
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-water]");
  if (!b) return;
  try {
    const w = await api("/api/water", { method: "POST", body: { day: state.day, change: Number(b.dataset.water) } });
    renderWater(w);
    if (Number(b.dataset.water) > 0) toast(w.glasses >= w.goal ? "Water goal reached 💧" : `💧 ${w.glasses} of ${w.goal} glasses`);
  } catch (err) { toast(err.message, true); }
});


// ---------------------------------------------------------------- today's activity typed in by hand
const today = () => isoDate(new Date());
async function loadSteps() {
  try {
    for (const f of ["#stepsForm", "#burnForm"]) { const d = $(f)?.elements.day; if (d) { d.max = today(); if (!d.value) d.value = today(); } }
    const [st, lg] = await Promise.all([api(`/api/steps?day=${today()}`), api(`/api/day-log?day=${today()}`)]);
    const f = (id, typed, garmin, unit) => {
      $(id).textContent = typed != null ? `· saved: ${fmt(typed, 2)} ${unit}` : garmin != null ? `· watch says ${fmt(garmin, 1)} ${unit}` : "";
    };
    f("#stepsSub", st.typed, st.garmin, "steps"); f("#burnSub", lg.burned, lg.garmin_burned, "kcal");
    if (st.typed != null) $("#stepsForm").steps.value = st.typed;
    if (lg.burned != null) $("#burnForm").burned.value = lg.burned;
  } catch {}
}
function dayLogForm(id, url, key, msg) {
  $(id).addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = Number(e.target[key].value);
    try {
      const day = e.target.day?.value || today();
      await api(url, { method: "POST", body: { day, [key]: v } });
      toast(msg(v) + (day !== today() ? ` for ${shortDay(day)}` : ""));
      if (state.view === "dashboard") loaders.dashboard();
      loadSteps();
    } catch (err) { toast(err.message, true); }
  });
}
dayLogForm("#stepsForm", "/api/steps", "steps", (v) => `👟 ${fmt(v)} steps saved`);
dayLogForm("#burnForm", "/api/day-log", "burned", (v) => `🔥 ${fmt(v)} calories burned saved`);


// ---------------------------------------------------------------- tap a Dashboard item to log it
const hm = (h) => { const H = Math.floor(h), M = Math.round((h - H) * 60); return M ? `${H} h ${M} min` : `${H} h`; };
const QUICKLOG = {
  sleep: { title: "😴 Log sleep", help: "How long did you sleep last night?",
    field: `<span class="hm"><input name="h" type="number" inputmode="numeric" min="0" max="24" step="1" required placeholder="7" aria-label="Hours"><b>hours</b>
      <input name="m" type="number" inputmode="numeric" min="0" max="59" step="1" placeholder="30" aria-label="Minutes"><b>minutes</b></span>`,
    fill: (f, v) => { f.h.value = Math.floor(v); f.m.value = Math.round((v % 1) * 60); },
    read: (f) => Math.round(((Number(f.h.value) || 0) + (Number(f.m.value) || 0) / 60) * 100) / 100,
    load: async () => (await api(`/api/day-log?day=${state.day}`)).sleep_h,
    save: (v) => api("/api/day-log", { method: "POST", body: { day: state.day, sleep_h: v } }), done: (v) => `😴 ${hm(v)} saved` },
  steps: { title: "👟 Log steps", help: "Total steps you walked today, from your watch or phone.",
    field: `<input name="v" type="number" inputmode="numeric" min="0" max="200000" required placeholder="e.g. 8500">`,
    load: async () => (await api(`/api/steps?day=${state.day}`)).typed,
    save: (v) => api("/api/steps", { method: "POST", body: { day: state.day, steps: v } }), done: (v) => `👟 ${fmt(v)} steps saved` },
  burned: { title: "🔥 Log calories burned", help: "Total calories burned today, from your watch.",
    field: `<input name="v" type="number" inputmode="numeric" min="0" max="10000" required placeholder="e.g. 3100">`,
    load: async () => (await api(`/api/day-log?day=${state.day}`)).burned,
    save: (v) => api("/api/day-log", { method: "POST", body: { day: state.day, burned: v } }), done: (v) => `🔥 ${fmt(v)} calories saved` },
  water: { title: "💧 Water", help: "Tap once for each glass you drank (1 glass = a normal cup, about 250 ml).", water: true },
};
let quickKey = null;
async function openQuick(key) {
  const q = QUICKLOG[key]; quickKey = key;
  $("#quickTitle").textContent = q.title; $("#quickHelp").textContent = q.help;
  if (q.water) {
    $("#quickSave").textContent = "Done";
    $("#quickBody").innerHTML = `<div class="water-glasses" id="waterGlasses"></div><p class="small" id="waterSub"></p>
      <div class="water-btns"><button type="button" class="ghost" data-water="-1">− 1 glass</button><button type="button" data-water="1">＋ 1 glass</button></div>`;
    loadWater();
  } else {
    $("#quickSave").textContent = "Save";
    $("#quickBody").innerHTML = `<label>${q.field}</label>`;
    try { const v = await q.load(); if (v != null) (q.fill ? q.fill($("#quickForm"), v) : ($("#quickForm").v.value = v)); } catch {}
  }
  $("#quickDialog").showModal();
  if (!q.water) setTimeout(() => $("#quickForm").querySelector("input")?.focus(), 50);
}
$("#quickDialog").addEventListener("close", async () => {
  const q = QUICKLOG[quickKey];
  if ($("#quickDialog").returnValue === "save" && q && !q.water) {
    const v = q.read ? q.read($("#quickForm")) : Number($("#quickForm").v.value);
    try { await q.save(v); toast(q.done(v)); } catch (err) { toast(err.message, true); }
  }
  if (state.view === "dashboard") loaders.dashboard();
});
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-quick]");
  if (t) openQuick(t.dataset.quick);
});
document.addEventListener("keydown", (e) => { const t = e.key === "Enter" && e.target.closest?.("[data-quick]"); if (t) openQuick(t.dataset.quick); });


// ---------------------------------------------------------------- weekly review (Progress) + weekly meals (Food)
const weeklyState = { data: null, day: null };
const shortDate = (iso) => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
async function loadWeekly() {
  try { weeklyState.data = await api("/api/weekly"); } catch { return; }
  renderWeekly(); renderMealPlan();
}
function renderWeekly() {
  const r = weeklyState.data?.review, el = $("#weeklyCard");
  if (!el) return;
  if (!r) { el.innerHTML = `<h3>📋 Weekly review</h3><p class="muted">Your first review appears next Monday.</p>`; return; }
  const row = (label, v) => `<div class="wr"><span>${label}</span><b>${v ?? "–"}</b></div>`;
  el.innerHTML = `<h3>📋 Weekly review</h3><p class="muted small">${shortDate(r.week_start)} – ${shortDate(r.week_end)} · updated every Monday</p>
    <div class="wr-grid">
      ${row("Weight (average)", r.weight_avg != null ? `${U.show("mass", r.weight_avg)} ${U.label("mass")}` : null)}
      ${row("Change", r.weight_change != null ? `${r.weight_change > 0 ? "+" : ""}${U.show("mass", r.weight_change)} ${U.label("mass")}` : null)}
      ${row("Workouts", `${r.workouts_done} of ${r.workouts_planned}`)}
      ${row("Food logged", `${r.days_logged} of 7 days`)}
      ${row("Calories a day", r.avg_calories != null ? fmt(r.avg_calories) : null)}
      ${row("Protein a day", r.avg_protein != null ? `${fmt(r.avg_protein)} g` : null)}
      ${row("Steps a day", r.avg_steps != null ? fmt(r.avg_steps) : null)}
      ${row("Sleep a night", r.avg_sleep_h != null ? hm(r.avg_sleep_h) : null)}
      ${row("Water a day", r.avg_water != null ? `${r.avg_water} glasses` : null)}
    </div>
    <h4>This week</h4><ul class="tips">${r.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    <p class="small"><b>Daily calories this week: ${fmt(r.new_calorie_target)}</b></p>`;
}
function renderMealPlan() {
  const plan = weeklyState.data?.meal_plan, el = $("#mealPlanCard");
  if (!el || !plan) return;
  const todayIso = isoDate(new Date());
  weeklyState.day ||= plan.find((d) => d.day === todayIso)?.day || plan[0].day;
  const d = plan.find((x) => x.day === weeklyState.day);
  const names = { breakfast: "Breakfast", lunch: "Lunch", dinner: "Dinner", snack: "Snack" };
  el.innerHTML = `<h3>🍽 This week's meals</h3>
    <p class="muted small">A suggested menu that adds up to your daily calories. Changes every Monday. Eat these or anything similar, and log what you actually eat.</p>
    <div class="mp-days">${plan.map((x) => `<button type="button" class="mp-day${x.day === weeklyState.day ? " on" : ""}${x.day === todayIso ? " today" : ""}" data-mp-day="${x.day}">
      ${new Date(x.day + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" })}</button>`).join("")}</div>
    <ul class="mp-meals">${d.meals.map((m) => `<li><span class="mp-meal">${names[m.meal]}</span>
      <span class="mp-name">${esc(m.name)}${Math.abs(m.portion - 1) >= 0.1 ? ` <span class="muted small">(${m.portion > 1 ? "a bigger" : "a smaller"} portion, ×${m.portion})</span>` : ""}</span>
      <span class="mp-kcal">${fmt(m.calories)} kcal · ${fmt(m.protein_g)} g protein</span></li>`).join("")}</ul>
    <p class="small"><b>Day total: ${fmt(d.calories)} calories · ${fmt(d.protein_g)} g protein</b></p>`;
  renderShopping();
}
// ---- the week's shopping list: everything for the menu above, with amounts; tick items off in the store
function renderShopping() {
  const list = weeklyState.data?.shopping_list, el = $("#shoppingCard");
  if (!el || !list) return;
  const key = `shop:${weeklyState.data.meal_plan[0].day}`;
  let got = {};
  try { got = JSON.parse(store.get(key) || "{}"); } catch {}
  const n = list.reduce((t, s) => t + s.items.length, 0), done = list.reduce((t, s) => t + s.items.filter((i) => got[i.item]).length, 0);
  el.innerHTML = `<h3>🛒 Shopping list for this week</h3>
    <p class="muted small">Everything you need for this week's meals above, already added up for your portions. Tick items off as you shop.</p>
    <p class="small"><b>${done} of ${n} items in the basket</b></p>
    ${list.map((s) => `<h4 class="shop-sec">${esc(s.section)}</h4><ul class="shop-list">${s.items.map((i) => `<li>
      <label class="${got[i.item] ? "got" : ""}"><input type="checkbox" data-shop="${esc(i.item)}" ${got[i.item] ? "checked" : ""}>
      <span class="shop-item">${esc(i.item)}</span><span class="shop-amt">${esc(i.amount)}${i.hint ? ` <span class="muted small">(${esc(i.hint)})</span>` : ""}</span></label></li>`).join("")}</ul>`).join("")}
    <button type="button" class="ghost small-btn" data-shop-clear>Untick everything</button>`;
}
document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-shop]");
  if (!c) return;
  const key = `shop:${weeklyState.data.meal_plan[0].day}`;
  let got = {};
  try { got = JSON.parse(store.get(key) || "{}"); } catch {}
  if (c.checked) got[c.dataset.shop] = 1; else delete got[c.dataset.shop];
  store.set(key, JSON.stringify(got)); renderShopping();
});
document.addEventListener("click", (e) => {
  if (!e.target.closest("[data-shop-clear]")) return;
  store.set(`shop:${weeklyState.data.meal_plan[0].day}`, "{}"); renderShopping();
});
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-mp-day]");
  if (!b) return;
  weeklyState.day = b.dataset.mpDay; renderMealPlan();
});


// ---------------------------------------------------------------- cardio done: activity + minutes -> calories
function renderCardioLog(r, listEl, burnEl) {
  listEl.innerHTML = r.items.map((x) => `<li><span class="cl-act">${cardioThumb(x.activity)}${esc(x.label)} · ${x.minutes} min</span>
    <span><b>${fmt(x.calories)} kcal</b> <button type="button" class="icon" data-cl-del="${x.id}" aria-label="Delete">✕</button></span></li>`).join("")
    || `<li class="muted small">Nothing logged yet.</li>`;
  if (burnEl) burnEl.innerHTML = `Cardio &amp; sports today: <b>${fmt(r.total_calories)} kcal</b>. They're added to your burn along with your steps and finished workouts (see the full breakdown on the Dashboard).`;
}
async function loadCardioLog() {
  if (!$("#cardioAct").options.length) $("#cardioAct").innerHTML = cardioOptions();
  try { const dEl = $("#cardioLogForm").elements.day; dEl.max = today(); if (!dEl.value) dEl.value = today(); } catch {}
  cardioPreview();
  try { renderCardioLog(await api(`/api/cardio-log?day=${today()}`), $("#cardioLogList"), $("#cardioBurn")); } catch {}
}
$("#cardioLogForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    const day = f.day?.value || today();
    const r0 = await api("/api/cardio-log", { method: "POST", body: { day, activity: f.activity.value, minutes: Number(f.minutes.value) } });
    const r = day === today() ? r0 : await api(`/api/cardio-log?day=${today()}`);
    if (day !== today()) toast(`Saved for ${shortDay(day)}`);
    renderCardioLog(r, $("#cardioLogList"), $("#cardioBurn"));
    if (cal.plan) { cal.marks = await api("/api/plans/checkins/all"); $("#activePlan").innerHTML = renderWeek(cal.plan); loadDayLogs(); }
    toast(`🏃 ${CARDIO_OPTS[f.activity.value].label}: ${f.minutes.value} min · ${fmt(r0.items.at(-1).calories)} kcal`);
    f.minutes.value = "";
  } catch (err) { toast(err.message, true); }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cl-del]");
  if (!b) return;
  try {
    const r = await api(`/api/cardio-log/${b.dataset.clDel}`, { method: "DELETE" });
    renderCardioLog(r, $("#cardioLogList"), $("#cardioBurn"));
    if (cal.plan && $(".cal-day")) { cal.marks = await api("/api/plans/checkins/all"); $("#activePlan").innerHTML = renderWeek(cal.plan); loadDayLogs(); }
  } catch (err) { toast(err.message, true); }
});
// calendar: log the planned cardio for that date as done
async function loadDayLogs() {
  const el = $("#dayCardioLogs");
  if (!el) return;
  try {
    const r = await api(`/api/cardio-log?day=${cal.sel}`);
    el.innerHTML = r.items.length ? `<span class="small"><b>Logged for this day:</b></span><ul class="cl-list">${r.items.map((x) => `<li><span class="cl-act">${cardioThumb(x.activity)}${esc(x.label)} · ${x.minutes} min</span>
      <span><b>${fmt(x.calories)} kcal</b> <button type="button" class="icon" data-cl-del="${x.id}" aria-label="Delete">✕</button></span></li>`).join("")}</ul>
      <span class="small">Cardio total: <b>${r.total_minutes} min · ${fmt(r.total_calories)} kcal</b></span>` : "";
  } catch {}
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-cr-log]");
  if (!b) return;
  const box = b.closest("[data-cardio-day]");
  const rows = [...box.querySelectorAll("[data-cr]")].map((r) => ({ activity: r.querySelector("[data-cr-act]").value, minutes: Number(r.querySelector("[data-cr-min]").value) || 0 })).filter((x) => x.minutes > 0);
  b.disabled = true;
  try {
    for (const x of rows) await api("/api/cardio-log", { method: "POST", body: { day: box.dataset.cardioDay, ...x } });
    toast(`🏃 Logged ${rows.length} cardio ${rows.length > 1 ? "activities" : "activity"} · marked as done ✓`);
    cal.marks = await api("/api/plans/checkins/all");
    $("#activePlan").innerHTML = renderWeek(cal.plan); loadDayLogs();
  } catch (err) { toast(err.message, true); } finally { b.disabled = false; }
});

// fill cardio thumbnails and the preview photo next to the activity picker
async function fillCardioPhotos(root = document) {
  const imgs = [...root.querySelectorAll("img[data-cl-photo]:not([src])")];
  const names = [...new Set(imgs.map((i) => i.dataset.clPhoto).filter(Boolean))];
  if (!names.length) return;
  const info = await exlibLookup(names);
  imgs.forEach((i) => { const m = info[i.dataset.clPhoto]; if (m?.images?.length) i.src = m.images[0]; else i.remove(); });
}
async function cardioPreview() {
  const o = CARDIO_OPTS[$("#cardioAct").value], el = $("#cardioPreview");
  if (!o || !el) return;
  const icon = SPORT_ICON[o.group];
  if (!o.photo) { el.innerHTML = `<span class="cl-icon">${icon || "🏃"}</span><span class="small">${esc(o.how[0])} About ${fmt(kcalFor($("#cardioAct").value, 60))} calories an hour for you.</span>`; return; }
  const m = (await exlibLookup([o.photo]))[o.photo];
  el.innerHTML = m?.images?.length ? `<img src="${m.images[0]}" alt="${esc(o.label)}"><span class="small">${esc(o.how[0])}</span>` : "";
}
new MutationObserver(() => fillCardioPhotos()).observe(document.body, { childList: true, subtree: true });
document.addEventListener("change", (e) => { if (e.target.id === "cardioAct") cardioPreview(); });

$("#videoClose").addEventListener("click", () => { $("#videoFrame").innerHTML = ""; $("#videoDialog").close(); });
$("#videoDialog").addEventListener("close", () => { $("#videoFrame").innerHTML = ""; });  // stop playback
