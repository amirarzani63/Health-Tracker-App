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
