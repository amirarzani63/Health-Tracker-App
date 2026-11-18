// 3D anatomy figure: a jointed body built from individually shaped muscles, posed and
// animated for each exercise pattern. Worked muscles glow (red = main, amber = supporting).
// Uses the bundled Three.js (vendor/three.min.js); no network or outside services.
"use strict";

const Anatomy3D = (() => {
  let T, renderer, scene, camera, figure, rig, muscles, props, raf, current, host, ro;
  const yaw = { value: 0.5, auto: true, lastTouch: 0, drag: null };

  // ---------------------------------------------------------------- loading
  function loadThree() {
    if (window.THREE) return Promise.resolve(window.THREE);
    return new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = "/static/vendor/three.min.js";
      s.onload = () => ok(window.THREE);
      s.onerror = () => fail(new Error("Couldn't load the 3D viewer"));
      document.head.appendChild(s);
    });
  }
  const supported = () => {
    try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch { return false; }
  };

  // ---------------------------------------------------------------- materials
  const MAT = {};
  function fiberTexture() {
    const c = document.createElement("canvas"); c.width = 256; c.height = 64;
    const g = c.getContext("2d");
    g.fillStyle = "#808080"; g.fillRect(0, 0, 256, 64);
    for (let x = 0; x < 256; x += 2) {
      const v = 100 + Math.random() * 90;
      g.fillStyle = `rgb(${v},${v},${v})`; g.fillRect(x, 0, 1 + Math.random() * 1.5, 64);
    }
    const t = new T.CanvasTexture(c); t.wrapS = t.wrapT = T.RepeatWrapping; t.repeat.set(3, 1);
    return t;
  }
  function makeMaterials() {
    const fib = fiberTexture();
    const base = { roughness: 0.55, metalness: 0.05, bumpMap: fib, bumpScale: 1.2 };
    MAT.idle = new T.MeshStandardMaterial({ ...base, color: 0x7d8a9b });
    MAT.prim = new T.MeshStandardMaterial({ ...base, color: 0xff3a24, emissive: 0xff2a10, emissiveIntensity: 0.6 });
    MAT.sec = new T.MeshStandardMaterial({ ...base, color: 0xffad2a, emissive: 0xff8a00, emissiveIntensity: 0.3 });
    MAT.under = new T.MeshStandardMaterial({ color: 0x8a95a3, roughness: 0.7 });
    MAT.tendon = new T.MeshStandardMaterial({ color: 0xc9ccd2, roughness: 0.35, metalness: 0.1 });
    MAT.iron = new T.MeshStandardMaterial({ color: 0x2b2f35, roughness: 0.35, metalness: 0.8 });
    MAT.plate = new T.MeshStandardMaterial({ color: 0xff6a2b, roughness: 0.45, metalness: 0.3 });
    MAT.gear = new T.MeshStandardMaterial({ color: 0x27303c, roughness: 0.7 });
    MAT.pad = new T.MeshStandardMaterial({ color: 0x3a1f1f, roughness: 0.9 });
    MAT.band = new T.MeshStandardMaterial({ color: 0xf5c242, roughness: 0.6, emissive: 0x5a4000, emissiveIntensity: 0.4 });
  }

  // ---------------------------------------------------------------- shapes
  // a muscle belly: spindle that tapers to tendons at both ends
  function spindle(len, r, flat = 1, bulge = 0.75) {
    const pts = [];
    for (let i = 0; i <= 18; i++) {
      const t = i / 18;
      pts.push(new T.Vector2(Math.max(r * 0.12, r * Math.pow(Math.sin(Math.PI * t), bulge)), (t - 0.5) * len));
    }
    const geo = new T.LatheGeometry(pts, 28);
    geo.scale(1, 1, flat);
    return geo;
  }
  const ellipsoid = (rx, ry, rz) => { const g = new T.SphereGeometry(1, 32, 20); g.scale(rx, ry, rz); return g; };
  const capsule = (r, len) => new T.CapsuleGeometry(r, len, 8, 20);

  function addMuscle(parent, group, geo, pos, rot = [0, 0, 0]) {
    const m = new T.Mesh(geo, MAT.idle);
    m.position.set(...pos); m.rotation.set(...rot.map((d) => (d * Math.PI) / 180));
    m.castShadow = true; m.userData.group = group;
    parent.add(m); muscles.push(m);
    return m;
  }
  function addPart(parent, geo, pos, mat = MAT.under, rot = [0, 0, 0]) {
    const m = new T.Mesh(geo, mat);
    m.position.set(...pos); m.rotation.set(...rot.map((d) => (d * Math.PI) / 180));
    m.castShadow = true; parent.add(m);
    return m;
  }
  const joint = (parent, pos) => { const j = new T.Object3D(); j.position.set(...pos); parent.add(j); return j; };
  const marker = (parent, pos, name) => { const m = joint(parent, pos); m.userData.contact = name; return m; };

  // ---------------------------------------------------------------- body
  function buildBody() {
    muscles = []; rig = {};
    const root = new T.Group(); root.name = "root";
    rig.root = root;
    const pelvis = joint(root, [0, 0, 0]); rig.pelvis = pelvis;
    addPart(pelvis, ellipsoid(0.16, 0.1, 0.11), [0, -0.02, 0]);
    // torso
    const spine = joint(pelvis, [0, 0.05, 0]); rig.spine = spine;
    addPart(spine, ellipsoid(0.135, 0.17, 0.095), [0, 0.13, 0]);
    const chest = joint(spine, [0, 0.24, 0]); rig.chest = chest;
    addPart(chest, ellipsoid(0.165, 0.17, 0.11), [0, 0.1, 0]);
    const neck = joint(chest, [0, 0.26, 0]); rig.neck = neck;
    addPart(neck, capsule(0.05, 0.06), [0, 0.03, 0]);
    const head = addPart(neck, ellipsoid(0.095, 0.12, 0.105), [0, 0.15, 0.01], MAT.under);
    marker(head, [0, 1, 0], "head"); marker(chest, [0, 0.12, -0.12], "back"); marker(pelvis, [0, -0.02, -0.12], "seat");
    marker(chest, [0, 0.1, 0.13], "front"); marker(pelvis, [0, -0.03, 0.12], "front");

    // chest
    for (const s of [1, -1]) {
      addMuscle(chest, "chest", ellipsoid(0.095, 0.07, 0.04), [s * 0.075, 0.13, 0.085], [8, 0, s * -14]);
      addMuscle(chest, "chest", ellipsoid(0.06, 0.035, 0.03), [s * 0.08, 0.06, 0.088], [0, 0, s * -20]);
      // lats (back, flaring)
      addMuscle(chest, "lats", ellipsoid(0.07, 0.17, 0.045), [s * 0.11, 0.02, -0.055], [0, s * 12, s * 14]);
      // serratus / obliques
      addMuscle(spine, "obliques", ellipsoid(0.04, 0.11, 0.06), [s * 0.115, 0.13, 0.04], [0, 0, s * 8]);
      // spinal erectors
      addMuscle(spine, "lower_back", spindle(0.32, 0.033, 0.8), [s * 0.035, 0.16, -0.085]);
      // glutes
      addMuscle(pelvis, "glutes", ellipsoid(0.085, 0.095, 0.07), [s * 0.075, -0.06, -0.075]);
      addMuscle(pelvis, "glutes", ellipsoid(0.05, 0.06, 0.05), [s * 0.12, -0.01, -0.03]);
      addMuscle(pelvis, "hip_flexors", ellipsoid(0.035, 0.06, 0.03), [s * 0.07, -0.06, 0.08], [0, 0, s * 20]);
    }
    // abs: six-pack + lower
    for (let row = 0; row < 3; row++) for (const s of [1, -1])
      addMuscle(spine, "abs", ellipsoid(0.034, 0.038, 0.022), [s * 0.037, 0.06 + row * 0.08, 0.09]);
    addMuscle(spine, "abs", ellipsoid(0.06, 0.05, 0.022), [0, -0.03, 0.088]);
    // traps + upper back
    addMuscle(chest, "traps", ellipsoid(0.13, 0.11, 0.04), [0, 0.2, -0.07], [-20, 0, 0]);
    addMuscle(chest, "traps", ellipsoid(0.04, 0.07, 0.035), [0, 0.06, -0.09]);
    addMuscle(chest, "upper_back", ellipsoid(0.095, 0.065, 0.03), [0, 0.11, -0.1]);

    // arms
    for (const side of ["L", "R"]) {
      const s = side === "L" ? 1 : -1;
      const sh = joint(chest, [s * 0.2, 0.2, 0]); rig["sh" + side] = sh;
      addPart(sh, capsule(0.045, 0.2), [0, -0.14, 0]);
      addMuscle(sh, "front_delts", ellipsoid(0.045, 0.075, 0.045), [s * 0.005, -0.04, 0.035], [10, 0, 0]);
      addMuscle(sh, "side_delts", ellipsoid(0.045, 0.08, 0.05), [s * 0.035, -0.045, 0]);
      addMuscle(sh, "rear_delts", ellipsoid(0.045, 0.07, 0.04), [s * 0.005, -0.04, -0.038], [-10, 0, 0]);
      addMuscle(sh, "biceps", spindle(0.2, 0.042, 0.95), [0, -0.16, 0.025]);
      addMuscle(sh, "triceps", spindle(0.23, 0.047, 0.9), [s * 0.005, -0.15, -0.032]);
      const el = joint(sh, [0, -0.3, 0]); rig["el" + side] = el;
      addPart(el, capsule(0.035, 0.2), [0, -0.13, 0]);
      addMuscle(el, "forearms", spindle(0.2, 0.042, 0.85), [0, -0.1, 0.01]);
      addMuscle(el, "forearms", spindle(0.16, 0.03, 0.9), [s * 0.02, -0.1, -0.015]);
      const hand = joint(el, [0, -0.28, 0]); rig["hand" + side] = hand;
      addPart(hand, ellipsoid(0.035, 0.06, 0.02), [0, -0.03, 0.005]);
      marker(hand, [0, -0.06, 0], "hand");

      // legs
      const hip = joint(pelvis, [s * 0.095, -0.06, 0]); rig["hip" + side] = hip;
      addPart(hip, capsule(0.07, 0.3), [0, -0.22, 0]);
      addMuscle(hip, "quads", spindle(0.36, 0.055, 0.85), [0, -0.21, 0.05]);
      addMuscle(hip, "quads", spindle(0.33, 0.055, 0.9), [s * 0.05, -0.22, 0.015]);
      addMuscle(hip, "quads", spindle(0.17, 0.05, 0.9), [s * -0.035, -0.33, 0.035]);
      addMuscle(hip, "adductors", spindle(0.28, 0.045, 0.9), [s * -0.05, -0.14, 0], [0, 0, s * 8]);
      addMuscle(hip, "hamstrings", spindle(0.34, 0.042, 0.9), [s * 0.025, -0.22, -0.05]);
      addMuscle(hip, "hamstrings", spindle(0.32, 0.04, 0.9), [s * -0.025, -0.23, -0.048]);
      const knee = joint(hip, [0, -0.44, 0]); rig["knee" + side] = knee;
      addPart(knee, ellipsoid(0.04, 0.035, 0.035), [0, 0, 0.04], MAT.tendon);
      addPart(knee, capsule(0.05, 0.3), [0, -0.2, 0]);
      addMuscle(knee, "calves", ellipsoid(0.042, 0.11, 0.05), [s * 0.022, -0.13, -0.035]);
      addMuscle(knee, "calves", ellipsoid(0.038, 0.1, 0.045), [s * -0.022, -0.12, -0.035]);
      addMuscle(knee, "calves", spindle(0.24, 0.025, 1), [s * 0.015, -0.18, 0.04]);
      marker(knee, [0, 0, 0.05], "knee");
      const ankle = joint(knee, [0, -0.42, 0]); rig["ankle" + side] = ankle;
      addPart(ankle, new T.BoxGeometry(0.08, 0.06, 0.22), [0, -0.035, 0.06]);
      marker(ankle, [0, -0.065, -0.04], "heel"); marker(ankle, [0, -0.065, 0.17], "toe");
    }
    return root;
  }

  // ---------------------------------------------------------------- equipment
  function dumbbell() {
    const g = new T.Group();
    const bar = new T.Mesh(new T.CylinderGeometry(0.014, 0.014, 0.2, 12), MAT.iron); bar.rotation.z = Math.PI / 2; g.add(bar);
    for (const x of [-0.085, 0.085]) {
      const w = new T.Mesh(new T.CylinderGeometry(0.05, 0.05, 0.05, 20), MAT.plate); w.rotation.z = Math.PI / 2; w.position.x = x; w.castShadow = true; g.add(w);
    }
    return g;
  }
  function kettlebell() {
    const g = new T.Group();
    const b = new T.Mesh(new T.SphereGeometry(0.075, 24, 16), MAT.plate); b.position.y = -0.09; b.castShadow = true; g.add(b);
    const h = new T.Mesh(new T.TorusGeometry(0.045, 0.012, 8, 24, Math.PI), MAT.iron); h.position.y = -0.02; g.add(h);
    return g;
  }
  function barbell() {
    const g = new T.Group();
    const bar = new T.Mesh(new T.CylinderGeometry(0.014, 0.014, 1.6, 12), MAT.iron); bar.rotation.z = Math.PI / 2; g.add(bar);
    for (const x of [-0.62, 0.62]) {
      const w = new T.Mesh(new T.CylinderGeometry(0.2, 0.2, 0.05, 32), MAT.plate); w.rotation.z = Math.PI / 2; w.position.x = x; w.castShadow = true; g.add(w);
    }
    return g;
  }
  function clearProps() { for (const p of props) p.parent?.remove(p); props = []; }
  function addScenery(def) {
    const add = (mesh) => { mesh.castShadow = mesh.receiveShadow = true; scene.add(mesh); props.push(mesh); return mesh; };
    if (def.bench) {
      add(new T.Mesh(new T.BoxGeometry(0.32, 0.08, 1.15), MAT.pad)).position.set(0, 0.42, -0.3);
      for (const z of [-0.75, 0.15]) add(new T.Mesh(new T.BoxGeometry(0.06, 0.38, 0.06), MAT.gear)).position.set(0, 0.19, z);
    }
    if (def.seat) {
      add(new T.Mesh(new T.BoxGeometry(0.4, 0.08, 0.45), MAT.pad)).position.set(0, 0.46, -0.1);
      add(new T.Mesh(new T.BoxGeometry(0.06, 0.42, 0.06), MAT.gear)).position.set(0, 0.21, -0.1);
    }
    if (def.box) add(new T.Mesh(new T.BoxGeometry(0.45, 0.3, 0.4), MAT.gear)).position.set(0.12, 0.15, 0.3);
    if (def.bar) {
      const b = add(new T.Mesh(new T.CylinderGeometry(0.016, 0.016, 1.3, 12), MAT.iron)); b.rotation.z = Math.PI / 2;
      b.userData.follow = "bar";
    }
    if (def.bars) for (const x of [-0.28, 0.28]) {
      const b = add(new T.Mesh(new T.CylinderGeometry(0.02, 0.02, 0.8, 12), MAT.iron)); b.rotation.x = Math.PI / 2;
      b.userData.follow = "bars"; b.userData.x = x;
      const leg = add(new T.Mesh(new T.CylinderGeometry(0.02, 0.02, 1, 8), MAT.gear)); leg.userData.follow = "barsLeg"; leg.userData.x = x;
    }
  }
  function addEquipment(equip) {
    const hold = (obj, side) => { rig["hand" + side].add(obj); obj.position.set(0, -0.04, 0.01); props.push(obj); };
    if (equip === "dumbbell") { hold(dumbbell(), "L"); hold(dumbbell(), "R"); }
    if (equip === "kettlebell") { hold(kettlebell(), "L"); hold(kettlebell(), "R"); }
    if (equip === "barbell") { const b = barbell(); b.userData.follow = "barbell"; scene.add(b); props.push(b); }
    if (equip === "band") for (const side of ["L", "R"]) {
      const band = new T.Mesh(new T.CylinderGeometry(0.008, 0.008, 1, 8), MAT.band);
      band.userData.follow = "band"; band.userData.side = side; scene.add(band); props.push(band);
    }
  }

  // ---------------------------------------------------------------- poses
  const D = { pitch: 0, roll: 0, spine: 0, lift: 0, shUp: 0 };
  for (const k of ["hip", "abd", "knee", "ankle", "sh", "sab", "tw", "el"]) for (const s of ["L", "R"]) D[k + s] = { sab: 8, el: 6 }[k] ?? 0;
  const expand = (p) => {
    const o = {};
    for (const [k, v] of Object.entries(p)) {
      if (k + "L" in D) { o[k + "L"] = v; o[k + "R"] = v; } else o[k] = v;
    }
    return o;
  };
  const HINGE = { pitch: 62, hip: 76, knee: 22 };
  const LIE_UP = { pitch: -90 }, BENCH = { pitch: -90, hip: 8, knee: 92, rootY: 0.56, lock: "none" };
  const PUSH_TOP = { pitch: 72, sh: 72, el: 0, sab: 12 };
  // [a, b, options]
  const PAT = {
    stand: [{}, { shL: 12, shR: -8 }],
    squat: [{ sh: 45, el: 125, sab: 18 }, { hip: 100, knee: 112, spine: 22, sh: 60, el: 128, sab: 18 }, { lock: "feet" }],
    lunge: [{ hipR: -12, kneeR: 12 }, { hipL: 82, kneeL: 88, hipR: -22, kneeR: 95, spine: -4 }, { lock: "footL" }],
    stepup: [{ hipL: 78, kneeL: 82 }, { hipL: 4, kneeL: 4, hipR: 12, kneeR: 75, lift: 0.3 }, { box: true }],
    hinge: [{}, { ...HINGE, sh: 62 }, { lock: "feet" }],
    bridge: [{ ...LIE_UP, hip: 55, knee: 110, sh: -8 }, { pitch: -112, hip: 12, knee: 80, sh: -8 }, { lock: "feet" }],
    calf: [{}, { ankle: 38 }, { lock: "feet" }],
    leg_curl: [{ sh: 15, el: 40 }, { kneeR: 105, hipR: -5 }, { lock: "footL" }],
    leg_ext: [{ hip: 90, knee: 88, sh: 10, sab: 25, rootY: 0.56, lock: "none" }, { knee: 5 }, { seat: true }],
    abduct: [{ sh: 30, el: 100, sab: 10 }, { abdR: 38 }, { lock: "footL" }],
    pushup: [{ ...PUSH_TOP }, { pitch: 84, sh: 42, sab: 38, el: 98 }, {}],
    climber: [{ ...PUSH_TOP }, { hipL: 100, kneeL: 115 }, { fast: true }],
    burpee: [{ sh: 172, sab: 8 }, { hip: 118, knee: 128, spine: 32, sh: 80, el: 0 }, { lock: "feet" }],
    plank: [{ pitch: 81, sh: 81, el: 92, sab: 10 }, { pitch: 80 }, {}],
    dip: [{ sh: -5, el: 0, hip: 40, knee: 85, lock: "handsY", handY: 1.1 }, { sh: -38, el: 95 }, { bars: true }],
    bench: [{ ...BENCH, sh: 90, el: 0 }, { sh: 14, sab: 62, el: 96 }, { bench: true }],
    fly: [{ ...BENCH, sh: 90, el: 14 }, { sh: 8, sab: 84, el: 22 }, { bench: true }],
    pullover: [{ ...BENCH, sh: 90, el: 12 }, { sh: 185, el: 18 }, { bench: true }],
    ohp: [{ sab: 82, tw: 90, el: 105 }, { sab: 172, tw: 90, el: 6 }, { lock: "feet" }],
    front_raise: [{ sh: 6, el: 8 }, { sh: 92, el: 8 }, { lock: "feet" }],
    lateral: [{ sab: 10, el: 14 }, { sab: 86, el: 14 }, { lock: "feet" }],
    jack: [{ sab: 14, abd: 3 }, { sab: 166, abd: 17, lift: 0.07 }, { fast: true }],
    rear_fly: [{ ...HINGE, sh: 62, sab: 8, el: 14 }, { ...HINGE, sh: 62, sab: 72, el: 20 }, { lock: "feet" }],
    shrug: [{}, { shUp: 0.05 }, { lock: "feet" }],
    upright: [{ sh: 4, el: 6 }, { sab: 70, el: 115, tw: 90 }, { lock: "feet" }],
    row: [{ ...HINGE, sh: 62, el: 4, sab: 10 }, { ...HINGE, sh: -8, el: 98, sab: 16 }, { lock: "feet" }],
    pulldown: [{ sh: 172, sab: 18, el: 10, hip: 85, knee: 95, rootY: 0.56, lock: "none" }, { sh: 25, sab: 40, el: 128 }, { seat: true, bar: true }],
    pullup: [{ sh: 176, sab: 14, el: 4, hip: 15, knee: 70, lock: "handsY", handY: 2.15 }, { sh: 30, sab: 40, el: 132 }, { bar: true }],
    curl: [{ el: 6 }, { el: 142 }, { lock: "feet" }],
    tri_ext: [{ sh: 168, el: 145 }, { sh: 168, el: 8 }, { lock: "feet" }],
    superman: [{ pitch: 90, sh: 170, el: 4 }, { spine: -22, hip: -18, sh: 160 }, {}],
    crunch: [{ ...LIE_UP, hip: 60, knee: 105, sh: 155, sab: 50, el: 145 }, { spine: 38 }, { lock: "seat" }],
    leg_raise: [{ ...LIE_UP, hip: 4, sh: -6 }, { hip: 92 }, { lock: "seat" }],
    cardio: [{ hipL: 40, kneeL: 70, hipR: -25, kneeR: 60, shL: -40, shR: 42, el: 90, spine: 6 },
      { hipL: -25, kneeL: 60, hipR: 40, kneeR: 70, shL: 42, shR: -40, el: 90, spine: 6 }, { fast: true }],
  };

  function poseAt(pattern, t) {
    const [a, b, opts = {}] = PAT[pattern] || PAT.stand;
    const A = { ...D, ...expand(a) }, B = { ...A, ...expand(b) };
    const o = {};
    for (const k of Object.keys(B)) o[k] = typeof B[k] === "number" && typeof A[k] === "number" ? A[k] + (B[k] - A[k]) * t : B[k];
    return { pose: o, opts };
  }
  const R = Math.PI / 180;
  function applyPose(p) {
    rig.root.rotation.set(p.pitch * R, 0, p.roll * R);
    rig.spine.rotation.set(p.spine * 0.5 * R, 0, 0);
    rig.chest.rotation.set(p.spine * 0.5 * R, 0, 0);
    for (const side of ["L", "R"]) {
      const s = side === "L" ? 1 : -1;
      rig["hip" + side].rotation.set(-p["hip" + side] * R, 0, s * p["abd" + side] * R, "ZXY");
      rig["knee" + side].rotation.set(p["knee" + side] * R, 0, 0);
      rig["ankle" + side].rotation.set(p["ankle" + side] * R, 0, 0);
      rig["sh" + side].rotation.set(-p["sh" + side] * R, s * p["tw" + side] * R, s * p["sab" + side] * R, "ZXY");
      rig["sh" + side].position.y = 0.2 + p.shUp;
      rig["el" + side].rotation.set(-p["el" + side] * R, 0, 0);
    }
  }
  const tmp = () => new T.Vector3();
  function contacts() {
    const out = [];
    rig.root.traverse((o) => { if (o.userData.contact) out.push([o.userData.contact, o.getWorldPosition(tmp())]); });
    return out;
  }
  function placeOnGround(p, opts) {
    const root = rig.root;
    root.position.set(0, 1, 0);
    root.updateMatrixWorld(true);
    const lock = p.lock || opts.lock || "ground";
    if (p.rootY != null) { root.position.y = p.rootY; root.updateMatrixWorld(true); }
    else if (lock === "handsY") {
      const hands = contacts().filter(([n]) => n === "hand");
      const y = (hands[0][1].y + hands[1][1].y) / 2;
      root.position.y += (p.handY ?? 1.1) - y;
    } else {
      const pts = contacts();
      const min = Math.min(...pts.map(([, v]) => v.y));
      root.position.y += -min;
      if (lock !== "none") {
        const want = { feet: ["heel", "toe"], footL: ["heel", "toe"], seat: ["seat"], ground: ["heel", "toe"] }[lock] || ["heel", "toe"];
        const sel = pts.filter(([n, v]) => want.includes(n) && (lock !== "footL" || v.x > 0));
        if (sel.length) {
          const cz = sel.reduce((a, [, v]) => a + v.z, 0) / sel.length;
          if (lock !== "ground") root.position.z -= cz - 0.05;
        }
      }
    }
    root.position.y += p.lift || 0;
    root.updateMatrixWorld(true);
  }
  function updateFollowers() {
    const hl = rig.handL.getWorldPosition(tmp()), hr = rig.handR.getWorldPosition(tmp());
    for (const p of props) {
      const f = p.userData.follow;
      if (f === "barbell" || f === "bar") {
        p.position.copy(hl).add(hr).multiplyScalar(0.5);
        if (f === "bar") p.position.y += 0.06;
        else p.position.y -= 0.04;
      }
      if (f === "bars" || f === "barsLeg") {
        const mid = hl.clone().add(hr).multiplyScalar(0.5);
        p.position.set(p.userData.x, f === "bars" ? mid.y - 0.06 : (mid.y - 0.06) / 2, mid.z);
        if (f === "barsLeg") p.scale.y = Math.max(0.1, mid.y - 0.06);
      }
      if (f === "band") {
        const hand = p.userData.side === "L" ? hl : hr;
        const foot = rig["ankle" + p.userData.side].getWorldPosition(tmp()); foot.y = 0.02;
        const mid = hand.clone().add(foot).multiplyScalar(0.5);
        p.position.copy(mid);
        const dir = hand.clone().sub(foot); p.scale.set(1, dir.length(), 1);
        p.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), dir.normalize());
      }
    }
  }

  // ---------------------------------------------------------------- scene
  function init() {
    T = window.THREE;
    makeMaterials();
    renderer = new T.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFSoftShadowMap;
    renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
    scene = new T.Scene();
    camera = new T.PerspectiveCamera(32, 1, 0.05, 30);
    scene.add(new T.HemisphereLight(0xcfe3ff, 0x1a1410, 0.9));
    const key = new T.DirectionalLight(0xffffff, 2.2); key.position.set(1.6, 3.2, 2.2); key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024); key.shadow.camera.left = key.shadow.camera.bottom = -1.6; key.shadow.camera.right = key.shadow.camera.top = 1.6;
    key.shadow.radius = 4; scene.add(key);
    const rim = new T.DirectionalLight(0x5ee6cb, 1.6); rim.position.set(-2, 1.5, -2.5); scene.add(rim);
    const fill = new T.DirectionalLight(0xffb48a, 0.5); fill.position.set(-2, 0.5, 2); scene.add(fill);
    const floor = new T.Mesh(new T.CircleGeometry(1.5, 64), new T.MeshStandardMaterial({ color: 0x10161d, roughness: 0.95 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
    const ring = new T.Mesh(new T.RingGeometry(1.42, 1.46, 96), new T.MeshBasicMaterial({ color: 0x34d3b4, transparent: true, opacity: 0.35 }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.002; scene.add(ring);
    figure = new T.Group(); scene.add(figure);
    figure.add(buildBody());
    props = [];
    const cv = renderer.domElement;
    cv.style.touchAction = "none";
    cv.addEventListener("pointerdown", (e) => { yaw.drag = { x: e.clientX, v: yaw.value }; yaw.auto = false; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener("pointermove", (e) => { if (yaw.drag) yaw.value = yaw.drag.v + (e.clientX - yaw.drag.x) * 0.012; });
    const up = () => { yaw.drag = null; yaw.lastTouch = performance.now(); };
    cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
  }
  function resize() {
    const w = host.clientWidth || 300, h = host.clientHeight || 300;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  function frame(ts) {
    const { pattern, period } = current;
    const ph = ((ts % period) / period) * 2;
    let t = ph < 1 ? ph : 2 - ph;
    t = Math.min(1, Math.max(0, (t - 0.08) / 0.84)); t = t * t * (3 - 2 * t);
    if (current.reduce) t = 0.7;
    const { pose, opts } = poseAt(pattern, t);
    applyPose(pose); placeOnGround(pose, opts); updateFollowers();
    if (!yaw.drag && !yaw.auto && ts - yaw.lastTouch > 4000) yaw.auto = true;
    if (yaw.auto && !current.reduce) yaw.value += 0.0035;
    figure.rotation.y = yaw.value;
    // frame the body: look at its middle
    const box = new T.Box3().setFromObject(rig.root), c = box.getCenter(tmp()), size = box.getSize(tmp());
    const dist = Math.max(size.y, size.z, size.x, 1.1) * 1.9 + 0.7;
    camera.position.set(0, c.y + 0.35, dist); camera.lookAt(0, c.y, 0);
    const pulse = 0.55 + 0.35 * Math.sin(ts / 260);
    MAT.prim.emissiveIntensity = pulse; MAT.sec.emissiveIntensity = 0.18 + pulse * 0.2;
    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- public
  async function mount(el, info) {
    stop();
    await loadThree();
    if (!renderer) init();
    host = el;
    el.innerHTML = "";
    el.appendChild(renderer.domElement);
    el.insertAdjacentHTML("beforeend", `<div class="v3d-hint">Drag to turn</div>
      <div class="v3d-views"><button data-yaw="0">Front</button><button data-yaw="1.5708">Side</button><button data-yaw="3.1416">Back</button></div>`);
    el.querySelector(".v3d-views").onclick = (e) => {
      const b = e.target.closest("[data-yaw]"); if (!b) return;
      yaw.value = Number(b.dataset.yaw); yaw.auto = false; yaw.lastTouch = performance.now() + 4000;
    };
    clearProps();
    const prim = new Set(info.primary), sec = new Set(info.secondary);
    for (const m of muscles) m.material = prim.has(m.userData.group) ? MAT.prim : sec.has(m.userData.group) ? MAT.sec : MAT.idle;
    const def = PAT[info.pattern] || PAT.stand, opts = def[2] || {};
    addScenery(opts);
    addEquipment(info.equip);
    // start facing the most useful side: the back for back-dominant work, otherwise a 3/4 front view
    const backFirst = info.primary.some((m) => ["lats", "upper_back", "lower_back", "glutes", "hamstrings", "rear_delts", "traps", "triceps", "calves"].includes(m));
    yaw.value = backFirst ? Math.PI * 0.8 : 0.55; yaw.auto = true; yaw.lastTouch = 0;
    current = { pattern: PAT[info.pattern] ? info.pattern : "stand", period: opts.fast ? 1000 : 2800,
      reduce: matchMedia("(prefers-reduced-motion: reduce)").matches };
    ro = new ResizeObserver(resize); ro.observe(el); resize();
    raf = requestAnimationFrame(frame);
  }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = null; ro?.disconnect(); ro = null; }
  return { mount, stop, supported, patterns: () => Object.keys(PAT) };
})();
