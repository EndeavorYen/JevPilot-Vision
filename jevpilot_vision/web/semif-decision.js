// What every decision request carries besides the bundle's own state (#63: split out of
// semif-layer.js so it can be driven in node, not matched as source text).
//
// SEMIF_DECISION.create({ win, params, now }) returns:
//   shape(body)        -> the request as it goes out (seed, lane offset, vision evidence, Vision's
//                         drive mode, stage, remembered light, candidate paths, localization error)
//   updateSeen()       -> refreshes win.SEMIF_SEEN_SENT / win.SEMIF_SEEN_SIGNAL from the evidence
//   candidatePaths(c)  -> the planner's own projection of each candidate
//   locNoise           -> { params, makeDrift, stage } (win.SEMIF_LOC_NOISE)
// `win` is the page's window (its SEMIF_* globals are read when called), `params` its
// URLSearchParams, `now` a millisecond clock (performance.now).
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SEMIF_DECISION = api;
})(typeof self !== "undefined" ? self : this, function () {
  const LOC_STAGE = 2; // the new Vision's stage from which its request carries localization error (#79)
  const LIGHT_STAGE = 3; // from which it reads perception's signal_read (#76)

  // Vision mode's signal colour: what the cameras read, counted from when the frame was taken. A
  // red or amber reading is kept 2.5 s; a green only 0.8 s, so with a decision taking effect up to
  // 1.2 s later a lost reading cannot carry a green past an amber phase (2 s). Evidence more than
  // 1.5 s old, or from the future (another page's clock), says nothing.
  // SEMIF_SEEN_SENT goes to the server: the reading, or null when there is none.
  // SEMIF_SEEN_SIGNAL goes to the planner (BUNDLE_PATCHES.md vision-plan): the same, red when null;
  // the planner applies it only at a signalled line, as the server does (jevpilot_vision/vision_mode.py).
  const SEEN_MEMORY_MS = { red: 2500, amber: 2500, green: 800 };

  function mulberry32(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Spread sigma, correlation time tau; called with the time (s) of each reading.
  function makeDrift(seed, sigma, tau) {
    const rand = mulberry32(seed);
    const gauss = () => {
      let u = 0;
      while (u === 0) u = rand();
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
    };
    let x = null;
    let at = null;
    return (now) => {
      if (!(sigma > 0)) return 0;
      if (x === null || !(now >= at)) {
        x = sigma * gauss(); // a fresh start (or a reload) is a draw from the spread itself
      } else {
        const keep = Math.exp(-(now - at) / tau);
        x = x * keep + sigma * Math.sqrt(1 - keep * keep) * gauss();
      }
      at = now;
      return x;
    };
  }

  function create({ win, params, now }) {
    // ---- Localization error (#79) ----------------------------------------------------------------
    // From stage 2 the new Vision's decision request carries a localization with a real one's error,
    // not the simulator's perfect pose: the lane offset and the stop-line distance each drift by
    // loc_sigma m (correlation time loc_tau s). First-order Markov (Ornstein-Uhlenbeck) drift on the
    // sim clock, from its own seeded generator: the planner's random stream is never drawn (#55). The
    // defaults are chosen at the issue's scale (0.2-0.5 m), not measured; benchmarks/closed_loop.py
    // --loc-sigma sweeps them. The position along the route is not in the request: the bundle's own
    // planner (route following, candidate paths, route error, off-road) still runs on the true pose,
    // which only patching the planner can change (#82, #83). Each candidate's end offset from the lane
    // centre (vector column 2) moves with the lane-offset error: a real car measures both from one
    // estimate, so "is this path centering?" stays a fair question. Still true: on_road, stop_reasons,
    // the stop column and the intersection's stop_completed / already_entered flags.
    function locParam(name, fallback, lo, hi) {
      const raw = params.get(name);
      const v = Number(raw);
      return raw !== null && raw.trim() !== "" && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : fallback;
    }
    const LOC = {
      sigma: locParam("loc_sigma", 0.3, 0, 5),
      tau: locParam("loc_tau", 5, 0.1, 600),
    };
    let locDrift = null;
    function localizationError(sim) {
      const seed = Number(sim.world && sim.world.seed) || 0;
      if (!locDrift || locDrift.seed !== seed) {
        locDrift = {
          seed,
          lateral: makeDrift(seed ^ 0x9e3779b9, LOC.sigma, LOC.tau),
          along: makeDrift(seed ^ 0x85ebca6b, LOC.sigma, LOC.tau),
        };
      }
      const t = Number(sim.time) || 0;
      return { lateral: locDrift.lateral(t), along: locDrift.along(t) };
    }
    // The bundle's objects in the request are copied before they are moved: its own state stays true.
    function addLocalizationError(state, sim) {
      const e = localizationError(sim);
      const moved = (v, by, digits) => +(v + by).toFixed(digits);
      if (Number.isFinite(state.lateral_offset_m)) state.lateral_offset_m = moved(state.lateral_offset_m, e.lateral, 2);
      if (state.candidates && typeof state.candidates === "object") {
        const moving = {};
        for (const [id, vec] of Object.entries(state.candidates)) {
          moving[id] = Array.isArray(vec) && Number.isFinite(vec[2]) ? [...vec.slice(0, 2), moved(vec[2], e.lateral, 2), ...vec.slice(3)] : vec;
        }
        state.candidates = moving;
      }
      const inter = state.intersection;
      if (inter && Number.isFinite(inter.distance_to_line_m)) {
        state.intersection = { ...inter, distance_to_line_m: moved(inter.distance_to_line_m, e.along, 2) };
      }
    }

    let lastSeen = null;
    function updateSeen() {
      const t = now();
      const vis = win.SEMIF_VISION;
      const p = vis && vis.perception;
      const taken = win.SEMIF_VISION_AT;
      const fresh = Number.isFinite(taken) && t >= taken && t - taken <= 1500;
      const ok = fresh && p && p.backend && p.backend !== "none" && (p.status || "ready") === "ready";
      // The new Vision reads which lamp cell is lit next to the hue threshold (#76); a server without
      // that reading leaves the hue threshold's.
      const lamp = win.SEMIF_MODE_ID === "vision" && win.SEMIF_VISION_STAGE >= LIGHT_STAGE && p && p.signal_read;
      const reading = lamp || (p && p.signal);
      const state = ok && reading && reading.state;
      if (["red", "amber", "green"].includes(state) && !(lastSeen && lastSeen.at > taken)) lastSeen = { state, at: taken };
      const held = ok && lastSeen && t >= lastSeen.at && t - lastSeen.at <= SEEN_MEMORY_MS[lastSeen.state] ? lastSeen.state : null;
      win.SEMIF_SEEN_SENT = held;
      win.SEMIF_SEEN_SIGNAL = held || "red";
    }

    // The planner's own projection of each candidate, so the server sweeps the path the car will
    // drive (it re-steers to follow its lane) rather than a constant steer. Candidates arrive under
    // aliases; each is matched to the plan's vector by speed and steer. [t s, ahead m, right m,
    // heading rad] in the car's frame at planning time, every 0.2 s for 3 s.
    function candidatePaths(candidates) {
      const plan = win.SEMIF_SIM && win.SEMIF_SIM.lastPlan;
      if (!plan || !plan.projections || !plan.vectors || !plan.origin || !candidates) return null;
      const { x: ox, z: oz, heading: oh } = plan.origin;
      const sin = Math.sin(oh), cos = Math.cos(oh);
      const keys = Object.keys(plan.vectors);
      const out = {};
      for (const [alias, vec] of Object.entries(candidates)) {
        if (!Array.isArray(vec)) continue;
        let best = null;
        let gap = Infinity;
        for (const key of keys) {
          const v = plan.vectors[key];
          const d = Math.abs(v.velocity_mps - vec[0]) + Math.abs(v.steering - vec[1]);
          if (d < gap) {
            gap = d;
            best = key;
          }
        }
        const points = best && gap <= 0.06 && plan.projections[best] && plan.projections[best].points;
        if (!points) continue;
        const path = [];
        for (let k = 4; k < points.length && k <= 60; k += 4) {
          const p = points[k];
          const dx = p.x - ox, dz = p.z - oz;
          path.push([
            Math.round(k * 5) / 100,
            Math.round((dx * sin - dz * cos) * 100) / 100,
            Math.round((dx * cos + dz * sin) * 100) / 100,
            Math.round((p.heading - oh) * 1000) / 1000,
          ]);
        }
        out[alias] = path;
      }
      return Object.keys(out).length ? out : null;
    }

    function shape(body) {
      body.raw_mode = !!win.SEMIF_RAW_MODE;
      if (win.SEMIF_SIM && win.SEMIF_SIM.world) {
        body.state = body.state || {};
        body.state.seed = win.SEMIF_SIM.world.seed;
        body.state.raw_mode = !!win.SEMIF_RAW_MODE;
      }
      const sim = win.SEMIF_SIM;
      // The lane offset is the planner's own (lane.offset_m), never recomputed from the car's x.
      const laneOffset =
        sim &&
        ((sim.lastDecisionState && sim.lastDecisionState.lane && sim.lastDecisionState.lane.offset_m) ??
          (sim.lastPlan && sim.lastPlan.lane && sim.lastPlan.lane.offset_m));
      if (typeof laneOffset === "number" && Number.isFinite(laneOffset)) {
        body.state = body.state || {};
        body.state.lateral_offset_m = laneOffset;
      }
      if (win.SEMIF_VISION) {
        body.state = body.state || {};
        body.state.vision = win.SEMIF_VISION;
        if (Number.isFinite(win.SEMIF_VISION_AT)) body.state.vision_age_ms = Math.round(now() - win.SEMIF_VISION_AT);
      }
      if (win.SEMIF_DRIVE_MODE === "vision") {
        body.drive_mode = "vision";
        // The new Vision names its stage; Vision (map) sends none and the server keeps its old rules.
        if (win.SEMIF_MODE_ID === "vision") body.vision_stage = win.SEMIF_VISION_STAGE;
        updateSeen();
        body.state = body.state || {};
        body.state.seen_signal = win.SEMIF_SEEN_SENT || null;
        const paths = candidatePaths(body.state.candidates);
        if (paths) body.state.candidate_paths = paths;
        if (win.SEMIF_MODE_ID === "vision" && win.SEMIF_VISION_STAGE >= LOC_STAGE && sim) addLocalizationError(body.state, sim);
      }
      return body;
    }

    return { shape, updateSeen, candidatePaths, locNoise: { params: LOC, makeDrift, stage: LOC_STAGE } };
  }

  return { create, makeDrift, LOC_STAGE, LIGHT_STAGE, SEEN_MEMORY_MS };
});
