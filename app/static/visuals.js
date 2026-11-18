// Visuals drawn entirely in the browser (SVG): car-style gauges, muscle body map,
// animated exercise demonstrations. No images or outside services.
"use strict";

// ================================================================ dashboard gauges
const Gauge = (() => {
  const SWEEP = 240, START = -120; // degrees, 0 = straight up
  const polar = (cx, cy, r, deg) => {
    const a = ((deg - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const arc = (cx, cy, r, a0, a1) => {
    const [x0, y0] = polar(cx, cy, r, a0), [x1, y1] = polar(cx, cy, r, a1);
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  const niceStep = (max) => {
    const raw = max / 8, p = 10 ** Math.floor(Math.log10(raw));
    return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw);
  };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  /**
   * Round dial with ticks, numbers, a red zone and a needle.
   * opts: value, max, target (red zone starts here, or "zone: good" marks the band to reach),
   *       label, unit, readout (big centre text), sub (small text), scale (divide tick labels), id
   */
  function dial(o) {
    const cx = 100, cy = 100, r = 84;
    const max = Math.max(1, o.max), step = niceStep(max), scale = o.scale || 1;
    const ang = (v) => START + (clamp(v, 0, max) / max) * SWEEP;
    let ticks = "", nums = "";
    for (let v = 0; v <= max + 1e-6; v += step / 2) {
      const major = Math.abs((v / step) % 1) < 1e-6;
      const [x0, y0] = polar(cx, cy, r - 2, ang(v)), [x1, y1] = polar(cx, cy, r - (major ? 14 : 8), ang(v));
      ticks += `<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" class="${major ? "tk-major" : "tk"}"/>`;
      if (major) {
        const [tx, ty] = polar(cx, cy, r - 26, ang(v));
        const n = v / scale;
        nums += `<text x="${tx.toFixed(1)}" y="${(ty + 4).toFixed(1)}" class="tk-num">${Number.isInteger(n) ? n : n.toFixed(1)}</text>`;
      }
    }
    const zones = [];
    if (o.target != null && o.target < max) {
      zones.push(`<path d="${arc(cx, cy, r - 5, ang(o.target), START + SWEEP)}" class="${o.zone === "good" ? "zone-good" : "zone-red"}"/>`);
    }
    const valAngle = ang(o.value || 0);
    const progress = o.value > 0 ? `<path d="${arc(cx, cy, r + 4, START, Math.max(START + 0.5, valAngle))}" class="g-progress ${o.state || ""}"/>` : "";
    const [nx, ny] = polar(cx, cy, r - 12, 0);
    return `<svg viewBox="0 0 200 178" class="dial" role="img" aria-label="${o.label}: ${o.readout} ${o.unit || ""}">
      <defs><radialGradient id="face-${o.id}" cx="50%" cy="45%" r="60%"><stop offset="0" stop-color="var(--g-face-1)"/><stop offset="1" stop-color="var(--g-face-2)"/></radialGradient></defs>
      <circle cx="${cx}" cy="${cy}" r="${r + 10}" class="g-bezel"/>
      <circle cx="${cx}" cy="${cy}" r="${r + 6}" fill="url(#face-${o.id})"/>
      <path d="${arc(cx, cy, r + 4, START, START + SWEEP)}" class="g-track"/>
      ${progress}${zones.join("")}${ticks}${nums}
      ${o.scaleLabel ? `<text x="${cx}" y="${cy + 22}" class="g-scale">${o.scaleLabel}</text>` : ""}
      <g class="needle" style="--to:${valAngle}deg">
        <polygon points="${cx - 3},${cy} ${nx},${ny} ${cx + 3},${cy}" class="g-needle"/>
      </g>
      <circle cx="${cx}" cy="${cy}" r="9" class="g-hub"/>
      <text x="${cx}" y="${cy + 38}" class="g-readout ${o.state || ""}">${o.readout}</text>
      <text x="${cx}" y="${cy + 54}" class="g-unit">${o.unit || ""}</text>
      <text x="${cx}" y="${cy + 72}" class="g-label">${o.label}</text>
    </svg>`;
  }

  /** Fuel gauge: half-dial from E to F. fraction 0..1 */
  function fuel(fraction, label, readout) {
    const cx = 70, cy = 62, r = 50, f = clamp(fraction, 0, 1);
    const ang = (x) => -90 + x * 180;
    let ticks = "";
    for (let i = 0; i <= 4; i++) {
      const [x0, y0] = polar(cx, cy, r, ang(i / 4)), [x1, y1] = polar(cx, cy, r - (i % 2 ? 6 : 10), ang(i / 4));
      ticks += `<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" class="tk-major"/>`;
    }
    const [nx, ny] = polar(cx, cy, r - 8, 0);
    const low = f < 0.15;
    return `<svg viewBox="0 0 140 92" class="fuel" role="img" aria-label="${label}: ${readout}">
      <path d="${arc(cx, cy, r, -90, -90 + 180 * 0.15)}" class="zone-red"/>
      <path d="${arc(cx, cy, r, -90, 90)}" class="g-track thin"/>
      ${ticks}
      <text x="${cx - r - 2}" y="${cy + 16}" class="tk-num ${low ? "bad" : ""}">E</text>
      <text x="${cx + r + 2}" y="${cy + 16}" class="tk-num">F</text>
      <g class="needle" style="--to:${ang(f)}deg"><polygon points="${cx - 2.5},${cy} ${nx},${ny} ${cx + 2.5},${cy}" class="g-needle"/></g>
      <circle cx="${cx}" cy="${cy}" r="6" class="g-hub"/>
      <text x="${cx}" y="${cy + 26}" class="g-readout small ${low ? "bad" : ""}">${readout}</text>
    </svg>`;
  }

  /** Odometer: rolling-digit style number */
  function odometer(value, digits = 6) {
    const s = String(Math.max(0, Math.round(value || 0))).padStart(digits, "0").slice(-digits);
    return `<span class="odo" aria-label="${Math.round(value || 0)}">${[...s].map((d) => `<span>${d}</span>`).join("")}</span>`;
  }

  /** Start needle animations after the SVG is in the page. */
  function animate(root) {
    requestAnimationFrame(() => requestAnimationFrame(() => root.querySelectorAll(".needle").forEach((n) => n.classList.add("go"))));
  }
  return { dial, fuel, odometer, animate };
})();

// ================================================================ exercise knowledge
// Pattern (how the body moves) + muscles, worked out from the exercise name.
const ExerciseInfo = (() => {
  const M = {
    chest: "Chest", front_delts: "Front shoulders", side_delts: "Side shoulders", rear_delts: "Rear shoulders",
    traps: "Traps", lats: "Lats", upper_back: "Upper back", lower_back: "Lower back", biceps: "Biceps",
    triceps: "Triceps", forearms: "Forearms", abs: "Abs", obliques: "Obliques", glutes: "Glutes",
    quads: "Quads", hamstrings: "Hamstrings", adductors: "Inner thighs", calves: "Calves", hip_flexors: "Hip flexors",
  };
  // [regex, pattern, primary[], secondary[]]  — first match wins
  const RULES = [
    [/side plank/, "plank", ["obliques"], ["abs", "side_delts"]],
    [/plank|hollow|dead ?bug|bird ?dog|pallof|stir the pot/, "plank", ["abs"], ["obliques", "front_delts", "glutes"]],
    [/mountain climber/, "climber", ["abs", "hip_flexors"], ["front_delts", "quads"]],
    [/burpee/, "burpee", ["quads", "chest"], ["glutes", "triceps", "abs"]],
    [/jumping jack|star jump/, "jack", ["calves", "side_delts"], ["glutes", "quads"]],
    [/push.?up|press.?up/, "pushup", ["chest"], ["triceps", "front_delts", "abs"]],
    [/\bdips?\b/, "dip", ["triceps"], ["chest", "front_delts"]],
    [/rear delt|reverse fly|face pull|pull.?apart/, "rear_fly", ["rear_delts"], ["upper_back", "traps"]],
    [/fly|flye|pec deck/, "fly", ["chest"], ["front_delts"]],
    [/pullover/, "pullover", ["lats"], ["chest", "triceps"]],
    [/bench|chest press|floor press|svend/, "bench", ["chest"], ["triceps", "front_delts"]],
    [/lateral raise|side raise|\by.?raise/, "lateral", ["side_delts"], ["traps"]],
    [/front raise/, "front_raise", ["front_delts"], ["side_delts", "chest"]],
    [/shrug/, "shrug", ["traps"], ["forearms"]],
    [/upright row/, "upright", ["side_delts", "traps"], ["biceps"]],
    [/overhead press|shoulder press|military|arnold|push press|\bpress\b.*(shoulder|overhead)|z press|landmine press/, "ohp", ["front_delts", "side_delts"], ["triceps", "traps"]],
    [/pull.?up|chin.?up|muscle.?up/, "pullup", ["lats"], ["biceps", "upper_back", "forearms"]],
    [/pull.?down|lat pull|straight.?arm/, "pulldown", ["lats"], ["biceps", "upper_back"]],
    [/\brow\b|rows\b|rowing pull/, "row", ["lats", "upper_back"], ["biceps", "rear_delts", "forearms"]],
    [/leg curl|hamstring curl|nordic|glute.?ham/, "leg_curl", ["hamstrings"], ["calves"]],
    [/wrist curl|reverse curl|farmer|carry/, "curl", ["forearms"], ["biceps", "traps"]],
    [/hammer/, "curl", ["biceps", "forearms"], []],
    [/curl/, "curl", ["biceps"], ["forearms"]],
    [/skull|kickback|push.?down|press.?down|tricep|french press|close.?grip/, "tri_ext", ["triceps"], []],
    [/leg extension|knee extension/, "leg_ext", ["quads"], []],
    [/back extension|hyperextension|superman|reverse hyper/, "superman", ["lower_back"], ["glutes", "hamstrings"]],
    [/hip thrust|bridge|frog pump/, "bridge", ["glutes"], ["hamstrings", "abs"]],
    [/deadlift|\brdl\b|romanian|good morning|hinge|swing|clean|snatch/, "hinge", ["hamstrings", "glutes"], ["lower_back", "forearms", "traps"]],
    [/step.?up|box step/, "stepup", ["quads", "glutes"], ["hamstrings", "calves"]],
    [/lunge|split squat|bulgarian|curtsy/, "lunge", ["quads", "glutes"], ["hamstrings", "adductors"]],
    [/squat|leg press|wall sit|sissy|thruster/, "squat", ["quads", "glutes"], ["adductors", "hamstrings", "abs"]],
    [/calf|heel raise|toe raise/, "calf", ["calves"], []],
    [/adduct|copenhagen/, "abduct", ["adductors"], []],
    [/abduct|clam|band walk|monster walk|lateral walk|fire hydrant|donkey kick|kickback.*glute|glute kickback/, "abduct", ["glutes"], ["hip_flexors"]],
    [/leg raise|knee raise|knee tuck|flutter|scissor|toes to bar/, "leg_raise", ["abs", "hip_flexors"], ["obliques"]],
    [/twist|woodchop|wood chop|side bend|windmill/, "crunch", ["obliques"], ["abs"]],
    [/crunch|sit.?up|v.?up|toe touch|jackknife|ab roll|rollout/, "crunch", ["abs"], ["obliques", "hip_flexors"]],
    [/run|sprint|jog|high knee|butt kick|skater|jump|hop|bound|skip|cardio|bike|cycle|elliptical|walk|stair/, "cardio", ["quads", "calves"], ["glutes", "hamstrings", "hip_flexors"]],
    [/stretch|mobility|yoga|foam/, "stand", [], []],
  ];
  // when the name doesn't say much, the body-part group from the exercise picker decides
  const BY_PART = {
    Chest: ["bench", ["chest"], ["triceps", "front_delts"]], Back: ["row", ["lats", "upper_back"], ["biceps"]],
    Shoulders: ["ohp", ["front_delts", "side_delts"], ["triceps"]], Arms: ["curl", ["biceps", "triceps"], ["forearms"]],
    Legs: ["squat", ["quads", "hamstrings"], ["glutes", "calves"]], "Glutes & hips": ["bridge", ["glutes"], ["hamstrings"]],
    Core: ["crunch", ["abs"], ["obliques"]], "Cardio & warm-up": ["cardio", ["quads", "calves"], ["glutes"]],
    "Full body": ["burpee", ["quads", "chest"], ["glutes", "abs"]], Bands: ["row", ["upper_back"], ["biceps"]],
  };
  const CUES = {
    squat: ["Feet shoulder-width, toes slightly out", "Sit back and down, knees track over toes", "Chest up; drive through your whole foot"],
    lunge: ["Long step, torso tall", "Lower until both knees are about 90°", "Push through the front heel to come up"],
    stepup: ["Whole foot on the box", "Drive up through the top leg, don't push off the bottom one", "Lower under control"],
    hinge: ["Soft knees, push hips back", "Keep the weights close to your legs and back flat", "Squeeze glutes to stand tall"],
    bridge: ["Feet flat, knees bent", "Drive hips up until body is straight from knees to shoulders", "Squeeze glutes for a second at the top"],
    calf: ["Rise onto the balls of your feet", "Pause at the top", "Lower slowly for a full stretch"],
    leg_curl: ["Keep thighs still", "Curl heel toward your glutes", "Lower slowly"],
    leg_ext: ["Sit tall", "Straighten the knee fully and squeeze the quads", "Lower with control"],
    abduct: ["Keep hips level and core braced", "Move from the hip, not the lower back", "Slow and controlled"],
    pushup: ["Hands under shoulders, body in one straight line", "Lower chest to just above the floor, elbows ~45°", "Press back up without sagging hips"],
    dip: ["Shoulders down, chest proud", "Lower until elbows reach about 90°", "Press back up to straight arms"],
    bench: ["Shoulder blades squeezed together, feet planted", "Lower to mid-chest, elbows ~45°", "Press up and slightly back"],
    fly: ["Slight bend in the elbows throughout", "Open arms wide until you feel a chest stretch", "Hug the weights back together"],
    pullover: ["Arms nearly straight", "Lower the weight behind your head", "Pull back over the chest using the lats"],
    ohp: ["Brace your core and squeeze glutes", "Press straight overhead, head through at the top", "Lower to shoulder height"],
    lateral: ["Slight bend in the elbows", "Raise out to the sides up to shoulder height", "Lead with the elbows, lower slowly"],
    front_raise: ["Arms nearly straight", "Raise in front to shoulder height", "Lower slowly, no swinging"],
    rear_fly: ["Hinge forward, back flat", "Open arms out wide, squeezing shoulder blades", "Lower with control"],
    shrug: ["Arms straight", "Lift shoulders up toward your ears", "Pause, then lower fully"],
    upright: ["Hands close, pull along the body", "Elbows lead and stay above the hands", "Stop at chest height"],
    row: ["Hinge forward, back flat", "Pull elbows back toward your hips", "Squeeze shoulder blades, lower slowly"],
    pullup: ["Hang with straight arms", "Pull chest toward the bar, elbows down", "Lower all the way with control"],
    pulldown: ["Chest up, slight lean back", "Pull elbows down to your sides", "Let arms straighten slowly"],
    curl: ["Elbows pinned to your sides", "Curl up without swinging", "Lower slowly to straight arms"],
    tri_ext: ["Keep upper arms still", "Straighten the elbows fully", "Lower slowly to a deep stretch"],
    superman: ["Lie face down", "Lift chest and legs together", "Hold briefly, lower slowly"],
    plank: ["Elbows under shoulders", "Body in a straight line, squeeze glutes", "Breathe; don't let hips sag"],
    climber: ["Start in a high plank", "Drive knees toward your chest one at a time", "Keep hips low and steady"],
    crunch: ["Lower back pressed down", "Curl ribs toward hips", "Exhale on the way up, lower slowly"],
    leg_raise: ["Lower back pressed into the floor", "Raise legs with control", "Lower slowly without arching"],
    burpee: ["Squat down, hands to floor", "Jump feet back to a plank, then forward", "Stand and jump"],
    jack: ["Land softly on the balls of your feet", "Arms overhead as feet go wide", "Keep a steady rhythm"],
    cardio: ["Stay light on your feet", "Keep a steady breathing rhythm", "Aim for a pace you can hold"],
    stand: ["Move slowly and breathe", "Stay within a comfortable range", "Hold stretches 20–30 seconds"],
  };
  function lookup(name, part) {
    const n = (name || "").toLowerCase().replace(/_/g, " ");
    let hit = RULES.find(([re]) => re.test(n));
    let pattern, primary, secondary;
    if (hit) [, pattern, primary, secondary] = hit;
    else if (BY_PART[part]) [pattern, primary, secondary] = BY_PART[part];
    else [pattern, primary, secondary] = ["stand", [], []];
    const equip = /band/.test(n) ? "band" : /barbell|\bbb\b|ez.?bar|bar\b/.test(n) ? "barbell"
      : /kettlebell|\bkb\b/.test(n) ? "kettlebell" : /dumbbell|\bdb\b/.test(n) ? "dumbbell"
      : /bodyweight|body weight|push.?up|plank|crunch|burpee|jack|mountain|pull.?up|chin.?up|dip|sit.?up/.test(n) ? "none"
      : ["bench", "ohp", "row", "curl", "tri_ext", "lateral", "front_raise", "rear_fly", "shrug", "fly", "hinge", "squat", "lunge"].includes(pattern) ? "dumbbell" : "none";
    return { name, pattern, primary, secondary, equip, cues: CUES[pattern] || CUES.stand,
      primaryNames: primary.map((m) => M[m]), secondaryNames: secondary.map((m) => M[m]) };
  }
  return { lookup, MUSCLES: M };
})();

// ================================================================ muscle body map (front + back)
const BodyMap = (() => {
  // [muscle, cx, cy, rx, ry, rotate] — each drawn on both sides (mirrored) unless x === 60
  const FRONT = [
    ["traps", 46, 50, 9, 4, 25], ["side_delts", 29, 63, 8, 10, 0], ["front_delts", 36, 64, 7, 9, 0],
    ["chest", 48, 77, 12, 9, 0], ["biceps", 27, 95, 6, 13, 8], ["forearms", 22, 127, 5, 15, 10],
    ["abs", 60, 113, 9, 22, 0], ["obliques", 44, 115, 5, 15, -6], ["hip_flexors", 50, 146, 6, 7, 20],
    ["quads", 48, 182, 9, 27, 4], ["adductors", 56, 172, 4, 16, 6], ["calves", 47, 232, 6, 17, 2],
  ];
  const BACK = [
    ["traps", 60, 58, 14, 14, 0], ["side_delts", 29, 63, 8, 10, 0], ["rear_delts", 36, 63, 7, 8, 0],
    ["upper_back", 60, 82, 12, 9, 0], ["lats", 44, 97, 9, 20, -10], ["triceps", 27, 95, 6, 14, 8],
    ["forearms", 22, 127, 5, 15, 10], ["lower_back", 60, 128, 8, 12, 0], ["glutes", 50, 156, 11, 12, 0],
    ["hamstrings", 49, 192, 9, 25, 3], ["calves", 47, 235, 7, 17, 2],
  ];
  const silhouette = `
    <circle cx="60" cy="22" r="13"/><rect x="54" y="32" width="12" height="12" rx="4"/>
    <path d="M30 50 Q60 40 90 50 L94 74 Q88 110 84 150 L36 150 Q32 110 26 74 Z"/>
    <path d="M24 56 Q16 60 18 76 L14 140 Q16 148 22 146 L32 104 L34 72 Z"/>
    <path d="M96 56 Q104 60 102 76 L106 140 Q104 148 98 146 L88 104 L86 72 Z"/>
    <path d="M36 146 L84 146 L82 168 L72 252 Q68 262 62 256 L60 176 L58 256 Q52 262 48 252 L38 168 Z"/>`;
  function view(regions, title, prim, sec) {
    const shapes = regions.map(([m, x, y, rx, ry, rot]) => {
      const cls = prim.includes(m) ? "mu prim" : sec.includes(m) ? "mu sec" : "mu";
      const one = (cx, r) => `<ellipse cx="${cx}" cy="${y}" rx="${rx}" ry="${ry}" transform="rotate(${r} ${cx} ${y})" class="${cls}"><title>${ExerciseInfo.MUSCLES[m]}</title></ellipse>`;
      return x === 60 ? one(60, rot) : one(x, rot) + one(120 - x, -rot);
    }).join("");
    return `<figure class="bodyview"><svg viewBox="0 0 120 266" role="img" aria-label="${title}"><g class="sil">${silhouette}</g>${shapes}</svg><figcaption>${title}</figcaption></figure>`;
  }
  function render(primary, secondary) {
    return `<div class="bodymap">${view(FRONT, "Front", primary, secondary)}${view(BACK, "Back", primary, secondary)}</div>`;
  }
  return { render };
})();

// ================================================================ animated exercise demo (stick figure)
const Demo = (() => {
  const L = { torso: 46, thigh: 36, shin: 36, uarm: 24, farm: 22, head: 9 };
  const rad = (d) => (d * Math.PI) / 180;
  const vec = (a, len) => [Math.sin(rad(a)) * len, Math.cos(rad(a)) * len];  // 0 = down, 90 = forward, 180 = up
  const add = (p, v) => [p[0] + v[0], p[1] + v[1]];
  const STAND = { torso: 180, thigh: 0, shin: 0, thigh2: 0, shin2: 0, uarm: 4, farm: 4, uarm2: 4, farm2: 4 };
  const GROUND = 214;
  // Side view poses. anchor: "foot" keeps the front foot planted; otherwise hip = [x, y].
  const P = (a, b, extra = {}) => ({ a: { ...STAND, ...a }, b: { ...STAND, ...a, ...b }, ...extra });
  const SIDE = {
    stand: P({ anchor: "foot" }, { uarm: 10, uarm2: -6 }),
    squat: P({ anchor: "foot", uarm: 30, farm: 150, uarm2: 30, farm2: 150 },
      { torso: 148, thigh: 88, shin: -28, thigh2: 88, shin2: -28, uarm: 50, farm: 160, uarm2: 50, farm2: 160 }),
    lunge: P({ anchor: "foot", thigh2: -14, shin2: -14 }, { thigh: 82, shin: -6, thigh2: -6, shin2: -88, torso: 176 }),
    stepup: P({ hip: [96, 120], thigh: 72, shin: -6, thigh2: -4, shin2: -4 }, { hip: [104, 92], thigh: 4, shin: 0, thigh2: 14, shin2: -70 }, { box: true }),
    hinge: P({ anchor: "foot" }, { torso: 98, thigh: 16, shin: -6, thigh2: 16, shin2: -6, uarm: -4, farm: -4, uarm2: -4, farm2: -4 }),
    bridge: P({ hip: [96, 206], torso: -84, thigh: 128, shin: 14, thigh2: 128, shin2: 14, uarm: -96, farm: -96, uarm2: -96, farm2: -96 },
      { hip: [96, 180], torso: -68, thigh: 104, shin: 8, thigh2: 104, shin2: 8, uarm: -88, farm: -88, uarm2: -88, farm2: -88 }),
    calf: P({ hip: [100, GROUND - 76] }, { hip: [100, GROUND - 84] }, { tiptoe: true }),
    leg_curl: P({ anchor: "foot", uarm: 20, uarm2: 20 }, { shin2: -110, thigh2: 8 }),
    leg_ext: P({ hip: [90, 166], thigh: 90, shin: 0, thigh2: 90, shin2: 0, uarm: 10, uarm2: 10 }, { shin: 88, shin2: 88 }, { seat: true }),
    abduct: P({ anchor: "foot", uarm: 30, farm: 120, uarm2: 30, farm2: 120 }, { thigh2: -40, shin2: -40 }),
    pushup: P({ hip: [96, 186], torso: 110, thigh: -70, shin: -70, thigh2: -70, shin2: -70, uarm: 0, farm: 0, uarm2: 0, farm2: 0 },
      { hip: [96, 204], torso: 98, thigh: -82, shin: -82, thigh2: -82, shin2: -82, uarm: -100, farm: 56, uarm2: -100, farm2: 56 }),
    climber: P({ hip: [96, 186], torso: 110, thigh: -70, shin: -70, thigh2: -70, shin2: -70, uarm: 0, farm: 0, uarm2: 0, farm2: 0 },
      { thigh: 30, shin: -50 }),
    burpee: P({ anchor: "foot", uarm: 175, farm: 178, uarm2: 175, farm2: 178 },
      { torso: 120, thigh: 96, shin: -40, thigh2: 96, shin2: -40, uarm: 10, farm: 10, uarm2: 10, farm2: 10 }),
    plank: P({ hip: [96, 199], torso: 102, thigh: -78, shin: -78, thigh2: -78, shin2: -78, uarm: 0, farm: 90, uarm2: 0, farm2: 90 },
      { hip: [96, 197] }),
    dip: P({ hip: [96, 140], torso: 176, thigh: 30, shin: -40, thigh2: 30, shin2: -40, uarm: 2, farm: 2, uarm2: 2, farm2: 2 },
      { hip: [96, 162], torso: 168, uarm: -60, farm: 30, uarm2: -60, farm2: 30 }, { bars: true }),
    bench: P({ hip: [70, 170], torso: 90, thigh: -72, shin: 0, thigh2: -72, shin2: 0, uarm: 180, farm: 180, uarm2: 180, farm2: 180 },
      { uarm: 24, farm: 172, uarm2: 24, farm2: 172 }, { bench: true }),
    fly: P({ hip: [70, 170], torso: 90, thigh: -72, shin: 0, thigh2: -72, shin2: 0, uarm: 180, farm: 176, uarm2: 180, farm2: 176 },
      { uarm: 40, farm: 30, uarm2: 40, farm2: 30 }, { bench: true }),
    pullover: P({ hip: [70, 170], torso: 90, thigh: -72, shin: 0, thigh2: -72, shin2: 0, uarm: 176, farm: 178, uarm2: 176, farm2: 178 },
      { uarm: 100, farm: 104, uarm2: 100, farm2: 104 }, { bench: true }),
    ohp: P({ anchor: "foot", uarm: 22, farm: 172, uarm2: 22, farm2: 172 }, { uarm: 176, farm: 178, uarm2: 176, farm2: 178 }),
    front_raise: P({ anchor: "foot", uarm: 6, farm: 8, uarm2: 6, farm2: 8 }, { uarm: 92, farm: 92 }),
    upright: P({ anchor: "foot", uarm: 6, farm: 6, uarm2: 6, farm2: 6 }, { uarm: -110, farm: 30, uarm2: -110, farm2: 30 }),
    row: P({ anchor: "foot", torso: 112, thigh: 18, shin: -8, thigh2: 18, shin2: -8, uarm: 0, farm: 0, uarm2: 0, farm2: 0 },
      { uarm: -76, farm: -6, uarm2: -76, farm2: -6 }),
    rear_fly: P({ anchor: "foot", torso: 112, thigh: 18, shin: -8, thigh2: 18, shin2: -8, uarm: 4, farm: 10, uarm2: 4, farm2: 10 },
      { uarm: -58, farm: -40 }),
    pulldown: P({ anchor: "foot", torso: 172, uarm: 168, farm: 176, uarm2: 168, farm2: 176 }, { uarm: -8, farm: 168, uarm2: -8, farm2: 168 }, { bar: true }),
    pullup: P({ hip: [100, 150], uarm: 176, farm: 178, uarm2: 176, farm2: 178, thigh: 10, shin: -20, thigh2: 10, shin2: -20 },
      { hip: [100, 120], uarm: -6, farm: 172, uarm2: -6, farm2: 172 }, { bar: true, hang: true }),
    curl: P({ anchor: "foot", uarm: 2, farm: 4, uarm2: 2, farm2: 4 }, { farm: 158, farm2: 158 }),
    tri_ext: P({ anchor: "foot", uarm: 174, farm: -28, uarm2: 174, farm2: -28 }, { farm: 178, farm2: 178 }),
    shrug: P({ anchor: "foot" }, { lift: 6 }),
    superman: P({ hip: [96, 204], torso: 92, thigh: -90, shin: -90, thigh2: -90, shin2: -90, uarm: 92, farm: 92, uarm2: 92, farm2: 92 },
      { torso: 108, thigh: -102, shin: -104, thigh2: -102, shin2: -104, uarm: 116, farm: 116, uarm2: 116, farm2: 116 }),
    crunch: P({ hip: [104, 203], torso: -90, thigh: 136, shin: 24, thigh2: 136, shin2: 24, uarm: -40, farm: 80, uarm2: -40, farm2: 80 },
      { torso: -128, uarm: -150, farm: 60, uarm2: -150, farm2: 60 }),
    leg_raise: P({ hip: [96, 206], torso: -90, thigh: 92, shin: 92, thigh2: 92, shin2: 92, uarm: -88, farm: -88, uarm2: -88, farm2: -88 },
      { thigh: 176, shin: 176, thigh2: 176, shin2: 176 }),
    cardio: P({ anchor: "foot", torso: 172, thigh: 40, shin: -50, thigh2: -24, shin2: -40, uarm: -30, farm: 70, uarm2: 34, farm2: 110 },
      { thigh: -24, shin: -40, thigh2: 40, shin2: -50, uarm: 34, farm: 110, uarm2: -30, farm2: 70 }, { anchorSwap: true }),
  };
  // Front view for side-to-side movements: arm & leg spread angles (0 = down)
  const FRONTV = {
    lateral: { a: { arm: 8, leg: 6 }, b: { arm: 86, leg: 6 } },
    jack: { a: { arm: 14, leg: 4 }, b: { arm: 168, leg: 18, hop: 8 } },
  };

  function solveSide(p) {
    let hip;
    if (p.hip) hip = p.hip;
    else {  // keep the front foot on the ground at x=100
      const leg = add(vec(p.thigh, L.thigh), vec(p.shin, L.shin));
      hip = [100 - leg[0], GROUND - leg[1] - (p.lift ? 0 : 0)];
    }
    const neck = add(hip, vec(p.torso, L.torso));
    const sh = p.lift ? [neck[0], neck[1] - p.lift] : neck;
    const head = add(neck, vec(p.torso, L.head + 4));
    const k1 = add(hip, vec(p.thigh, L.thigh)), a1 = add(k1, vec(p.shin, L.shin));
    const k2 = add(hip, vec(p.thigh2, L.thigh)), a2 = add(k2, vec(p.shin2, L.shin));
    const e1 = add(sh, vec(p.uarm, L.uarm)), h1 = add(e1, vec(p.farm, L.farm));
    const e2 = add(sh, vec(p.uarm2, L.uarm)), h2 = add(e2, vec(p.farm2, L.farm));
    return { hip, neck: sh, head, k1, a1, k2, a2, e1, h1, e2, h2 };
  }
  const lerp = (a, b, t) => a + (b - a) * t;
  function mix(a, b, t) {
    const o = {};
    for (const k of Object.keys(b)) {
      if (Array.isArray(b[k])) o[k] = [lerp(a[k][0], b[k][0], t), lerp(a[k][1], b[k][1], t)];
      else if (typeof b[k] === "number") o[k] = lerp(a[k] ?? b[k], b[k], t);
      else o[k] = b[k];
    }
    return o;
  }
  const line = (p, q, cls = "bone") => `<line x1="${p[0].toFixed(1)}" y1="${p[1].toFixed(1)}" x2="${q[0].toFixed(1)}" y2="${q[1].toFixed(1)}" class="${cls}"/>`;
  function prop(equip, hand, foot, angle) {
    if (equip === "dumbbell") return `<g transform="translate(${hand[0].toFixed(1)} ${hand[1].toFixed(1)}) rotate(${angle})"><rect x="-9" y="-2" width="18" height="4" rx="1" class="prop"/><rect x="-11" y="-5" width="5" height="10" rx="1.5" class="prop"/><rect x="6" y="-5" width="5" height="10" rx="1.5" class="prop"/></g>`;
    if (equip === "kettlebell") return `<circle cx="${hand[0].toFixed(1)}" cy="${(hand[1] + 7).toFixed(1)}" r="6" class="prop"/>`;
    if (equip === "barbell") return `<circle cx="${hand[0].toFixed(1)}" cy="${hand[1].toFixed(1)}" r="9" class="prop plate"/>`;
    if (equip === "band" && foot) return `<path d="M${hand[0].toFixed(1)} ${hand[1].toFixed(1)} Q${((hand[0] + foot[0]) / 2 + 10).toFixed(1)} ${((hand[1] + foot[1]) / 2).toFixed(1)} ${foot[0].toFixed(1)} ${foot[1].toFixed(1)}" class="band"/>`;
    return "";
  }
  function drawSide(p, def, equip) {
    const j = solveSide(p);
    let scene = `<line x1="0" y1="${GROUND + 2}" x2="200" y2="${GROUND + 2}" class="floor"/>`;
    if (def.bench) scene += `<rect x="40" y="176" width="88" height="8" rx="3" class="gear"/><line x1="56" y1="184" x2="56" y2="${GROUND}" class="gear-leg"/><line x1="112" y1="184" x2="112" y2="${GROUND}" class="gear-leg"/>`;
    if (def.box) scene += `<rect x="112" y="${GROUND - 40}" width="50" height="40" rx="3" class="gear"/>`;
    if (def.seat) scene += `<rect x="58" y="170" width="44" height="8" rx="3" class="gear"/><line x1="80" y1="178" x2="80" y2="${GROUND}" class="gear-leg"/>`;
    if (def.bars) scene += `<rect x="70" y="150" width="60" height="5" rx="2" class="gear"/><line x1="76" y1="155" x2="76" y2="${GROUND}" class="gear-leg"/><line x1="124" y1="155" x2="124" y2="${GROUND}" class="gear-leg"/>`;
    if (def.bar) scene += `<line x1="40" y1="${def.hang ? 52 : 40}" x2="160" y2="${def.hang ? 52 : 40}" class="gear-bar"/>`;
    const tiptoe = def.tiptoe ? (p.hip[1] < GROUND - 80 ? 1 : 0) : 0;
    const foot = (a, k) => { const dir = a[0] >= k[0] - 1 ? 1 : 1; return tiptoe ? line(a, [a[0] + 10, a[1] + 8], "bone thin") : line(a, [a[0] + 11 * dir, a[1] + 1], "bone thin"); };
    const ang = (a, b) => (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI + 90;
    return scene
      + `<g class="far">${line(j.hip, j.k2)}${line(j.k2, j.a2)}${foot(j.a2, j.k2)}${line(j.neck, j.e2)}${line(j.e2, j.h2)}${prop(equip, j.h2, j.a2, ang(j.e2, j.h2))}</g>`
      + `${line(j.hip, j.neck, "bone torso")}<circle cx="${j.head[0].toFixed(1)}" cy="${j.head[1].toFixed(1)}" r="${L.head}" class="head"/>`
      + `${line(j.hip, j.k1)}${line(j.k1, j.a1)}${foot(j.a1, j.k1)}${line(j.neck, j.e1)}${line(j.e1, j.h1)}${prop(equip, j.h1, j.a1, ang(j.e1, j.h1))}`
      + [j.hip, j.k1, j.e1, j.neck].map((q) => `<circle cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="3" class="joint"/>`).join("");
  }
  function drawFront(p, equip) {
    const hop = p.hop || 0, cx = 100, hipY = GROUND - 74 - hop, neckY = hipY - 50;
    const legs = [-1, 1].map((s) => { const k = [cx + s * 7 + Math.sin(rad(p.leg)) * 74 * s, GROUND - hop]; return line([cx + s * 7, hipY], k) + line(k, [k[0] + s * 8, k[1]], "bone thin"); }).join("");
    const arms = [-1, 1].map((s) => { const sh = [cx + s * 14, neckY + 4]; const h = [sh[0] + Math.sin(rad(p.arm)) * 46 * s, sh[1] + Math.cos(rad(p.arm)) * 46]; return line(sh, h) + prop(equip, h, [cx + s * 10, GROUND], p.arm * s); }).join("");
    return `<line x1="0" y1="${GROUND + 2}" x2="200" y2="${GROUND + 2}" class="floor"/>${legs}`
      + `${line([cx - 7, hipY], [cx + 7, hipY], "bone torso")}${line([cx, hipY], [cx, neckY], "bone torso")}${line([cx - 14, neckY + 4], [cx + 14, neckY + 4], "bone torso")}`
      + `<circle cx="${cx}" cy="${neckY - 13}" r="${L.head}" class="head"/>${arms}`;
  }
  const running = new WeakMap();
  /** Mount an animated demo into `el` (replaces content). */
  function mount(el, info) {
    stop(el);
    const front = FRONTV[info.pattern], def = SIDE[info.pattern] || SIDE.stand;
    el.innerHTML = `<svg viewBox="0 24 200 204" class="demo" role="img" aria-label="Animated demonstration of ${info.name}"><g></g></svg>`;
    const g = el.querySelector("g");
    const period = info.pattern === "cardio" || info.pattern === "jack" || info.pattern === "climber" ? 900 : 2600;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf;
    const frame = (ts) => {
      // ease in-out, pause briefly at each end
      const ph = ((ts % period) / period) * 2; let t = ph < 1 ? ph : 2 - ph;
      t = Math.min(1, Math.max(0, (t - 0.1) / 0.8)); t = t * t * (3 - 2 * t);
      if (reduce) t = 1;
      g.innerHTML = front ? drawFront(mix(front.a, front.b, t), info.equip) : drawSide(mix(def.a, def.b, t), def, info.equip);
      if (!reduce) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    running.set(el, () => cancelAnimationFrame(raf));
  }
  function stop(el) { running.get(el)?.(); running.delete(el); }
  function still(info, t) {  // one frame as SVG markup (used for previews)
    const front = FRONTV[info.pattern], def = SIDE[info.pattern] || SIDE.stand;
    return `<svg viewBox="0 0 200 228" class="demo">${front ? drawFront(mix(front.a, front.b, t), info.equip) : drawSide(mix(def.a, def.b, t), def, info.equip)}</svg>`;
  }
  return { mount, stop, still, patterns: [...Object.keys(SIDE), ...Object.keys(FRONTV)] };
})();
