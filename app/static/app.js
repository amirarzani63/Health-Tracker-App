"use strict";

// ---------------------------------------------------------------- helpers
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => (n == null ? "–" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const isoDate = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const minutes = (s) => { const m = Math.round(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`; };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
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
const numOrNull = (v) => (v === "" || v == null ? null : Number(v));

const charts = {};
function drawChart(id, config) {
  if (typeof Chart === "undefined") return; // charts are optional; never break the page
  charts[id]?.destroy();
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--border");
  charts[id] = new Chart($("#" + id), { ...config, options: { responsive: true, maintainAspectRatio: false, ...config.options } });
}

// ---------------------------------------------------------------- state & nav
const state = { day: isoDate(new Date()), view: "dashboard" };
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

function show(view) {
  state.view = view;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  $(".daybar").classList.toggle("hidden", !["dashboard", "diet"].includes(view));
  history.replaceState(null, "", "#" + view);
  loaders[view]?.();
}

// ---------------------------------------------------------------- dashboard
loaders.dashboard = async () => {
  const d = await api(`/api/dashboard?day=${state.day}`);
  const left = d.targets.calories - d.consumed.calories;
  $("#kCalLeft").textContent = fmt(left);
  $("#kCalSub").textContent = `${fmt(d.consumed.calories)} / ${fmt(d.targets.calories)} kcal${d.targets.source === "garmin" ? " · Garmin-adjusted" : ""}`;
  $("#kProtein").textContent = `${fmt(d.consumed.protein_g)} g`;
  $("#kProteinSub").textContent = `target ${fmt(d.targets.protein_g)} g`;
  const s = d.stats || {};
  $("#kSteps").textContent = fmt(s.steps);
  $("#kStepsSub").textContent = s.resting_hr ? `RHR ${s.resting_hr} bpm` : "sync Garmin for steps";
  $("#kSleep").textContent = s.sleep_s ? `${(s.sleep_s / 3600).toFixed(1)} h` : "–";
  $("#kSleepSub").textContent = [s.sleep_score && `score ${s.sleep_score}`, s.body_battery_high && `Body Battery ${s.body_battery_high}`].filter(Boolean).join(" · ");

  const r = $("#readiness");
  r.className = "pill " + d.readiness.level;
  r.textContent = d.readiness.message;

  const ts = d.today_session;
  $("#todaySession").innerHTML = !ts
    ? `<p class="muted">No active plan. <a href="#plans" data-goto="plans">Generate one</a>.</p>`
    : renderPlanDay(ts, true) + `<p class="muted small">${esc(d.plan_name)}</p>`;

  const w = d.week;
  $("#weekStats").innerHTML = [["Sessions", w.count], ["Time", minutes(w.duration_min * 60)], ["Distance", `${w.distance_km} km`], ["Active kcal", fmt(w.calories)]]
    .map(([l, v]) => `<div><span class="label">${l}</span><span class="value">${v}</span></div>`).join("");
  $("#recentActs").innerHTML = d.recent_activities.length
    ? d.recent_activities.map((a) => `<li><span>${esc(a.name)} <span class="tag ${a.source}">${a.source}</span></span><span class="muted small">${new Date(a.start_time).toLocaleDateString()} · ${minutes(a.duration_s)}${a.distance_m ? ` · ${(a.distance_m / 1000).toFixed(1)} km` : ""}</span></li>`).join("")
    : `<li class="muted">No activities this week yet.</li>`;

  drawChart("trendChart", {
    type: "bar",
    data: {
      labels: d.trend.map((t) => t.day.slice(5)),
      datasets: [
        { label: "Intake kcal", data: d.trend.map((t) => t.intake), backgroundColor: css("--accent") },
        { label: "Burned kcal (Garmin)", data: d.trend.map((t) => t.burned), backgroundColor: css("--carbs") },
      ],
    },
    options: { plugins: { legend: { position: "bottom" } } },
  });
};

// ---------------------------------------------------------------- diet
function macroBar(label, have, target, color, unit = "g") {
  const pct = target ? Math.min(100, (have / target) * 100) : 0;
  const over = target && have > target * 1.05;
  return `<div class="bar ${over ? "over" : ""}"><div class="top"><span>${label}</span><span>${fmt(have)} / ${fmt(target)} ${unit}</span></div>
    <div class="track"><div class="fill" style="width:${pct}%;${over ? "" : `background:${color}`}"></div></div></div>`;
}

loaders.diet = async () => {
  const [summary, foods, sugg] = await Promise.all([
    api(`/api/nutrition/summary?day=${state.day}`),
    api(`/api/foods?day=${state.day}`),
    api(`/api/nutrition/suggestions?day=${state.day}`),
  ]);
  const t = summary.targets, c = summary.consumed;
  $("#macroBars").innerHTML =
    macroBar("Calories", c.calories, t.calories, css("--accent"), "kcal") +
    macroBar("Protein", c.protein_g, t.protein_g, css("--protein")) +
    macroBar("Carbs", c.carbs_g, t.carbs_g, css("--carbs")) +
    macroBar("Fat", c.fat_g, t.fat_g, css("--fat"));
  $("#targetSource").textContent = t.source === "garmin"
    ? `Based on Garmin: BMR ${fmt(t.bmr)} + today's active calories → ~${fmt(t.tdee)} kcal burned.`
    : `Estimated from your profile: BMR ${fmt(t.bmr)} × activity level → ~${fmt(t.tdee)} kcal. Sync Garmin for measured burn.`;

  const byMeal = { breakfast: [], lunch: [], dinner: [], snack: [] };
  foods.forEach((f) => byMeal[f.meal].push(f));
  $("#foodLog").innerHTML = Object.entries(byMeal).map(([meal, items]) => `
    <h4 style="text-transform:capitalize">${meal} <span class="muted small">${fmt(items.reduce((a, f) => a + f.calories, 0))} kcal</span></h4>
    <ul class="list">${items.map((f) => `<li><span>${esc(f.name)}${f.servings !== 1 ? ` ×${f.servings}` : ""}</span>
      <span class="muted small">${fmt(f.calories)} kcal · P${fmt(f.protein_g)} C${fmt(f.carbs_g)} F${fmt(f.fat_g)}
      <button class="icon" data-del-food="${f.id}" title="Delete">✕</button></span></li>`).join("") || `<li class="muted small">Nothing logged</li>`}</ul>`).join("");

  $("#dietTips").innerHTML = sugg.tips.map((t) => `<li>${esc(t)}</li>`).join("");
  $("#mealSuggestions").innerHTML = Object.entries(sugg.meals).map(([meal, opts]) => `
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
      `<li data-food-idx="${i}"><span>${esc(f.name)}</span><span class="muted small">${f.calories} kcal · P${f.protein_g}</span></li>`).join("")
      || `<li class="muted small">No matches — enter it manually below.</li>`;
    $("#foodResults")._items = items;
  }, 200);
});
$("#foodResults").addEventListener("click", (e) => {
  const li = e.target.closest("[data-food-idx]");
  if (!li) return;
  const f = $("#foodResults")._items[li.dataset.foodIdx];
  const form = $("#foodForm");
  ["name", "calories", "protein_g", "carbs_g", "fat_g"].forEach((k) => (form.elements[k].value = f[k]));
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
      carbs_g: Number(d.carbs_g) * s, fat_g: Number(d.fat_g) * s,
    });
    e.target.reset();
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- exercise
function addSetRow(v = {}) {
  const row = document.createElement("div");
  row.className = "set-row";
  row.innerHTML = `<input placeholder="Exercise" data-k="exercise" value="${esc(v.exercise || "")}">
    <input type="number" placeholder="Reps" data-k="reps" min="0" value="${esc(v.reps ?? "")}">
    <input type="number" placeholder="kg" step="0.5" data-k="weight_kg" min="0" value="${esc(v.weight_kg ?? "")}">
    <button type="button" class="icon" title="Remove">✕</button>`;
  row.querySelector("button").onclick = () => row.remove();
  $("#setRows").appendChild(row);
}
$("#addSet").onclick = () => {
  const last = $$("#setRows .set-row").at(-1);
  addSetRow(last ? { exercise: $('[data-k="exercise"]', last).value, weight_kg: $('[data-k="weight_kg"]', last).value } : {});
};

function weekKey(dt) {
  const d = new Date(dt);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); // Monday
  return isoDate(d);
}

loaders.exercise = async () => {
  const f = $("#activityForm").elements.start_time;
  if (!f.value) f.value = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [acts, wellness] = await Promise.all([api("/api/activities?limit=300"), api("/api/daily-stats?days=30")]);

  $("#activityTable tbody").innerHTML = acts.slice(0, 60).map((a) => `<tr>
    <td>${new Date(a.start_time).toLocaleDateString()}</td>
    <td>${esc(a.name)}${a.sets.length ? ` <span class="muted small">(${a.sets.length} sets)</span>` : ""}</td>
    <td>${minutes(a.duration_s)}</td>
    <td>${a.distance_m ? (a.distance_m / 1000).toFixed(2) + " km" : "–"}</td>
    <td>${fmt(a.calories)}</td><td>${fmt(a.avg_hr)}</td>
    <td>${a.aerobic_te != null ? `${a.aerobic_te.toFixed(1)} / ${(a.anaerobic_te ?? 0).toFixed(1)}` : "–"}</td>
    <td><span class="tag ${a.source}">${a.source}</span></td>
    <td><button class="icon" data-del-act="${a.id}" title="Delete">✕</button></td></tr>`).join("")
    || `<tr><td colspan="9" class="muted">No activities yet — log one or sync Garmin.</td></tr>`;

  // weekly minutes, last 8 weeks, split by cardio vs strength
  const weeks = [];
  const start = new Date(); start.setDate(start.getDate() - 7 * 7);
  for (let i = 0; i < 8; i++) { const d = new Date(start); d.setDate(d.getDate() + i * 7); weeks.push(weekKey(d)); }
  const agg = Object.fromEntries(weeks.map((w) => [w, { strength: 0, cardio: 0 }]));
  acts.forEach((a) => {
    const k = weekKey(a.start_time);
    if (agg[k]) agg[k][/strength|yoga|pilates|hiit/.test(a.activity_type) ? "strength" : "cardio"] += a.duration_s / 60;
  });
  drawChart("volumeChart", {
    type: "bar",
    data: { labels: weeks.map((w) => w.slice(5)), datasets: [
      { label: "Cardio", data: weeks.map((w) => Math.round(agg[w].cardio)), backgroundColor: css("--protein") },
      { label: "Strength", data: weeks.map((w) => Math.round(agg[w].strength)), backgroundColor: css("--accent") },
    ] },
    options: { scales: { x: { stacked: true }, y: { stacked: true } }, plugins: { legend: { position: "bottom" } } },
  });
  drawChart("wellnessChart", {
    type: "line",
    data: { labels: wellness.map((w) => w.day.slice(5)), datasets: [
      { label: "Resting HR", data: wellness.map((w) => w.resting_hr), borderColor: css("--bad"), yAxisID: "y", tension: 0.3 },
      { label: "Sleep h", data: wellness.map((w) => (w.sleep_s ? +(w.sleep_s / 3600).toFixed(1) : null)), borderColor: css("--protein"), yAxisID: "y1", tension: 0.3 },
      { label: "Body Battery max", data: wellness.map((w) => w.body_battery_high), borderColor: css("--accent"), yAxisID: "y", tension: 0.3 },
    ] },
    options: { spanGaps: true, plugins: { legend: { position: "bottom" } }, scales: { y: { position: "left" }, y1: { position: "right", grid: { drawOnChartArea: false } } } },
  });
};

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
    toast("Workout saved");
    loaders.exercise();
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- plans
function renderPlanDay(day, compact = false) {
  if (day.type === "rest") return `<div class="plan-day"><div class="wd">${day.weekday}</div><strong>Rest / mobility</strong><p class="muted small">Easy walk, stretching, let your Garmin recovery time drop.</p></div>`;
  if (day.type === "cardio") return `<div class="plan-day cardio"><div class="wd">${day.weekday} · cardio</div><strong>${esc(day.title)}</strong>
    <p class="small">${day.minutes} min in <b>${esc(day.zone)}</b> — set your fenix data screen to HR zone.</p></div>`;
  return `<div class="plan-day strength"><div class="wd">${day.weekday} · strength</div><strong>${esc(day.title)}</strong>
    <table>${day.exercises.map((x) => `<tr><td>${esc(x.exercise)}</td><td>${x.sets}×${esc(x.reps)}${compact ? "" : ` · ${x.rest_s}s`}</td></tr>`).join("")}</table></div>`;
}

loaders.plans = async () => {
  const [plans, active] = await Promise.all([api("/api/plans"), api("/api/plans/active")]);
  $("#activePlan").innerHTML = active ? `<div class="card"><h3>Active plan: ${esc(active.name)}</h3>
    <div class="plan-days">${active.days.map((d) => renderPlanDay(d)).join("")}</div>
    <h4>Progression</h4><ul class="tips">${active.progression.map((p) => `<li><b>Week ${p.week}:</b> ${esc(p.note)}</li>`).join("")}</ul></div>` : "";
  $("#planList").innerHTML = plans.map((p) => `<li><span>${esc(p.name)} <span class="muted small">${p.weeks} wk · ${new Date(p.created_at).toLocaleDateString()}</span>
    ${p.active ? '<span class="tag garmin">active</span>' : ""}</span>
    <span>${p.active ? "" : `<button class="ghost" data-activate-plan="${p.id}">Activate</button>`}
    <button class="icon" data-del-plan="${p.id}" title="Delete">✕</button></span></li>`).join("") || `<li class="muted">No plans yet.</li>`;
};

$("#planForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  try {
    await api("/api/plans/generate", { method: "POST", body: {
      goal: d.goal, weeks: Number(d.weeks), include_cardio: !!d.include_cardio,
      days_per_week: numOrNull(d.days_per_week), equipment: d.equipment || null,
    } });
    toast("Plan generated");
    loaders.plans();
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- garmin
loaders.garmin = async () => {
  const s = await api("/api/garmin/status");
  $("#garminStatus").textContent = s.connected
    ? `Connected. Last sync: ${s.last_sync ? new Date(s.last_sync).toLocaleString() : "never"}.`
    : s.mfa_pending ? "Waiting for verification code." : "Not connected.";
  $("#garminLogin").classList.toggle("hidden", s.connected || s.mfa_pending);
  $("#garminMfa").classList.toggle("hidden", !s.mfa_pending);
  $("#garminConnected").classList.toggle("hidden", !s.connected);
};

async function withBusy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
}

$("#garminLogin").addEventListener("submit", (e) => {
  e.preventDefault();
  withBusy($("button", e.target), async () => {
    const r = await api("/api/garmin/login", { method: "POST", body: formData(e.target) });
    e.target.reset();
    toast(r.status === "needs_mfa" ? "Enter the code Garmin sent you" : "Connected to Garmin");
    await loaders.garmin();
    if (r.status === "ok") $("#syncBtn").click();
  });
});
$("#garminMfa").addEventListener("submit", (e) => {
  e.preventDefault();
  withBusy($("button", e.target), async () => {
    await api("/api/garmin/mfa", { method: "POST", body: formData(e.target) });
    e.target.reset();
    toast("Connected to Garmin");
    await loaders.garmin();
    $("#syncBtn").click();
  });
});
$("#syncBtn").addEventListener("click", (e) => withBusy(e.target, async () => {
  $("#syncResult").textContent = "Syncing…";
  const r = await api("/api/garmin/sync", { method: "POST", body: { days: Number($("#syncDays").value) || 7 } });
  $("#syncResult").textContent = `Activities: ${r.activities_added} new, ${r.activities_updated} updated · Days of wellness data: ${r.days_synced} · Weigh-ins: ${r.weights}`
    + (r.errors.length ? `\nWarnings:\n- ${r.errors.join("\n- ")}` : "");
  toast("Garmin sync complete");
  loaders.garmin();
}));
$("#logoutBtn").addEventListener("click", async () => {
  await api("/api/garmin/logout", { method: "POST" });
  $("#syncResult").textContent = "";
  toast("Disconnected from Garmin");
  loaders.garmin();
});

// ---------------------------------------------------------------- profile
loaders.profile = async () => {
  const [p, weights] = await Promise.all([api("/api/profile"), api("/api/weights")]);
  const form = $("#profileForm");
  for (const [k, v] of Object.entries(p)) if (form.elements[k]) form.elements[k].value = Array.isArray(v) ? v.join(", ") : v;
  drawChart("weightChart", {
    type: "line",
    data: { labels: weights.map((w) => w.day.slice(5)), datasets: [
      { label: "Weight kg", data: weights.map((w) => w.weight_kg), borderColor: css("--accent"), tension: 0.3, pointRadius: 2 },
    ] },
    options: { plugins: { legend: { display: false } } },
  });
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
$("#weightForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = formData(e.target);
  try {
    await api("/api/weights", { method: "POST", body: { day: isoDate(new Date()), weight_kg: Number(d.weight_kg), body_fat_pct: numOrNull(d.body_fat_pct) } });
    e.target.reset();
    toast("Weight logged");
    loaders.profile();
  } catch (err) { toast(err.message, true); }
});

// ---------------------------------------------------------------- global clicks
document.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-del-food],[data-del-act],[data-del-plan],[data-activate-plan],[data-log-meal],[data-goto]");
  if (!t) return;
  try {
    if (t.dataset.goto) { e.preventDefault(); show(t.dataset.goto); }
    else if (t.dataset.delFood) { await api(`/api/foods/${t.dataset.delFood}`, { method: "DELETE" }); loaders.diet(); }
    else if (t.dataset.delAct && confirm("Delete this activity?")) { await api(`/api/activities/${t.dataset.delAct}`, { method: "DELETE" }); loaders.exercise(); }
    else if (t.dataset.delPlan && confirm("Delete this plan?")) { await api(`/api/plans/${t.dataset.delPlan}`, { method: "DELETE" }); loaders.plans(); }
    else if (t.dataset.activatePlan) { await api(`/api/plans/${t.dataset.activatePlan}/activate`, { method: "POST" }); loaders.plans(); }
    else if (t.dataset.logMeal) {
      const m = JSON.parse(t.dataset.logMeal);
      await logFood({ meal: m.meal, name: m.name, servings: 1, calories: m.calories, protein_g: m.protein_g, carbs_g: m.carbs_g, fat_g: m.fat_g });
    }
  } catch (err) { toast(err.message, true); }
});

$$("#tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
$("#day").addEventListener("change", (e) => e.target.value && setDay(e.target.value));
$("#prevDay").onclick = () => shiftDay(-1);
$("#nextDay").onclick = () => shiftDay(1);
$("#todayBtn").onclick = () => setDay(isoDate(new Date()));
$("#day").value = state.day;

const initial = location.hash.slice(1);
show(loaders[initial] ? initial : "dashboard");
