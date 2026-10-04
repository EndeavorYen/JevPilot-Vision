(function () {
  const params = new URLSearchParams(location.search);
  const rawParam = params.get("raw") === "1" || params.get("rawMode") === "1";
  window.SEMIF_RAW_MODE = window.SEMIF_RAW_MODE || rawParam;
  // Driving mode (#18, #21): what the decision reads. Vision: objects and signals from the onboard
  // cameras, with no map or localization privilege once its stages land (#78); until then it drives
  // as Vision (map), the old Vision kept as its baseline: cameras, the map still privileged.
  // Privileged: the simulator's state table (the ablation for a decision model). Heuristic: the
  // bundle's geometric rules. SEMIF_MODE_ID is the switch's choice (address, storage, reports);
  // SEMIF_DRIVE_MODE is how it drives, which the planner patches read: both Visions drive "vision".
  // ?mode= wins, then the browser's last choice, then privileged.
  const DRIVE_MODES = ["vision", "vision-map", "privileged", "heuristic"];
  // De-mapping stages landed in ?mode=vision (#85). benchmarks/closed_loop.py VISION_STAGE records
  // the same number and checks it against this one on every run.
  window.SEMIF_VISION_STAGE = 1; // 1: box flow (#75)
  const driveOf = (id) => (id === "vision-map" ? "vision" : id);
  const MODE_KEY = "semif.driveMode";
  const modeParam = params.get("mode");
  let modeSaved = null;
  try {
    modeSaved = localStorage.getItem(MODE_KEY);
  } catch (_) {}
  window.SEMIF_MODE_ID = DRIVE_MODES.includes(modeParam)
    ? modeParam
    : DRIVE_MODES.includes(modeSaved)
      ? modeSaved
      : "privileged";
  window.SEMIF_DRIVE_MODE = driveOf(window.SEMIF_MODE_ID);
  // Latency stress (#28, benchmarks/closed_loop.py --lag-ms): every decision request waits this long
  // before it goes out, to see whether a result holds only at one timing. At most 1.2 s: the bundle
  // drops a decision that arrives 1.8 s after it asked, lag included, so more would only park the car.
  const lagParam = Number(params.get("lag_ms"));
  window.SEMIF_LAG_MS = Number.isFinite(lagParam) && lagParam > 0 ? Math.min(lagParam, 1200) : 0;
  const seedParam = params.get("seed");
  if (seedParam && Number.isFinite(Number(seedParam))) {
    window.SEMIF_SEED = Number(seedParam);
  }

  document.documentElement.classList.add("fsd-theme");
  document.body.classList.add("fsd-theme");

  const chrome = document.createElement("div");
  chrome.id = "fsd-chrome";
  chrome.innerHTML = `
    <div id="fsd-halo" aria-hidden="true"></div>
    <div id="fsd-boxes"></div>
    <div id="fsd-pip">
      <div class="fsd-pip-header">
        <span class="fsd-pip-title">CAMERA: onboard</span>
        <span id="fsd-pip-fps" class="fsd-pip-fps">-- FPS</span>
      </div>
      <div class="fsd-pip-body">
        <div class="fsd-pip-frame">
          <canvas id="fsd-camera-canvas" width="320" height="180"></canvas>
          <canvas id="fsd-camera-view" width="320" height="180"></canvas>
          <span id="fsd-camera-label" class="fsd-camera-label">FRONT · 100°</span>
        </div>
        <div class="fsd-pip-tabs" role="tablist" aria-label="Onboard camera" title="Press C to cycle the onboard cameras">
          <button type="button" class="fsd-cam-tab" id="fsd-cam-front" role="tab" aria-selected="true">Front</button>
          <button type="button" class="fsd-cam-tab" id="fsd-cam-left" role="tab" aria-selected="false">Left</button>
          <button type="button" class="fsd-cam-tab" id="fsd-cam-right" role="tab" aria-selected="false">Right</button>
          <button type="button" class="fsd-cam-tab" id="fsd-cam-rear" role="tab" aria-selected="false">Rear</button>
          <button type="button" class="fsd-cam-tab" id="fsd-cam-all" role="tab" aria-selected="false">All</button>
        </div>
      </div>
    </div>
    <div id="fsd-status" aria-live="polite">
      <label id="fsd-seed-box">seed
        <input id="fsd-seed-input" type="number" min="0" max="999999" step="1" />
      </label>
      <button type="button" id="fsd-seed-apply">Apply</button>
      <button type="button" id="fsd-seed-rand">Random</button>
      <span id="fsd-intent" class="fsd-chip">SemArbiter</span>
      <span id="fsd-vision" class="fsd-chip" data-state="off">VISION off</span>
      <button type="button" id="fsd-latency" aria-expanded="false" aria-controls="fsd-stats">
        <canvas class="fsd-spark" aria-hidden="true"></canvas><span class="fsd-latency-text">e2e — · P95 —</span>
      </button>
      <button type="button" id="fsd-fleet" class="fsd-chip" data-state="off" title="Fleet mode: traffic drives on the same decision core">FLEET off</button>
    </div>
  `;
  document.body.appendChild(chrome);

  // ---- Driving mode indicator (#21) -------------------------------------------------------------
  // Always on screen (also in the minimal view): which mode drives, what it reads, and in Vision
  // whether perception is healthy. It says what each mode reads, not which is "better".
  const MODE_INFO = {
    vision: { label: "Vision", reads: `Objects, signals & box flow from cameras · stage ${window.SEMIF_VISION_STAGE} · map privileged` },
    "vision-map": { label: "Vision (map)", reads: "Objects & signals from cameras · map privileged" },
    privileged: { label: "Privileged", reads: "Simulator state · the ablation for a decision model" },
    heuristic: { label: "Heuristic", reads: "Geometric rules · no model" },
  };
  const modeEl = document.createElement("div");
  modeEl.id = "sol-mode";
  modeEl.innerHTML = `
    <div class="sol-mode-switch" role="radiogroup" aria-label="Driving mode" title="Driving mode · M">
      ${DRIVE_MODES.map((m) => `<button type="button" id="sol-mode-${m}" class="sol-mode-option" role="radio" aria-checked="false">${MODE_INFO[m].label}</button>`).join("")}
    </div>
    <p class="sol-mode-line"><span id="sol-mode-reads"></span><span id="sol-mode-health"></span></p>
    <span id="sol-mode-announce" class="sol-visually-hidden"></span>
  `;
  document.body.appendChild(modeEl);
  const modeReads = document.getElementById("sol-mode-reads");
  const modeHealth = document.getElementById("sol-mode-health");
  document.getElementById("sol-mode-announce").setAttribute("aria-live", "polite");
  let lastModelMode = window.SEMIF_DRIVE_MODE === "vision" ? window.SEMIF_MODE_ID : "privileged";
  let modeFrames = 0;

  // Vision's health: the detector's state, the evidence's age (from frame capture) and the encoder
  // backend. Loading, failed, stale (over 1.5 s) or missing perception is what the server holds
  // to a crawl (jevpilot_vision/vision_mode.py), so the indicator says so.
  function encoderName(backend) {
    const b = String(backend || "stub");
    if (b === "stub") return "SigLIP stub";
    return /siglip/i.test(b) ? "SigLIP" : b.split("/").pop();
  }
  function modeHealthOf(vis, ageMs) {
    const p = vis && vis.perception && typeof vis.perception === "object" ? vis.perception : null;
    const crawl = " — holding to a crawl";
    if (!vis || !Number.isFinite(ageMs) || ageMs < 0) return { state: "degraded", text: "Waiting for the cameras" + crawl };
    if (p && p.status === "loading") return { state: "degraded", text: "Detector loading" + crawl };
    const status = p && "status" in p ? p.status : "ready";
    if (!p || p.backend == null || p.backend === "none" || status !== "ready") {
      return { state: "degraded", text: "Detector failed" + crawl };
    }
    const age = (ageMs / 1000).toFixed(1);
    if (ageMs > 1500) return { state: "degraded", text: `Evidence ${age} s old` + crawl };
    return { state: "ok", text: `Detector ready · ${age} s · ${encoderName(vis.backend)}` };
  }

  function renderMode() {
    const mode = window.SEMIF_MODE_ID;
    modeEl.setAttribute("data-mode", mode);
    for (const m of DRIVE_MODES) {
      const btn = document.getElementById(`sol-mode-${m}`);
      if (!btn) continue;
      btn.setAttribute("aria-checked", String(m === mode));
      btn.setAttribute("tabindex", m === mode ? "0" : "-1");
    }
    modeReads.textContent = MODE_INFO[mode].reads;
    // Until a decision names its intent, the status card names who will decide.
    const intent = document.getElementById("fsd-intent");
    if (intent && /^(SemArbiter|Heuristic)$/.test(intent.textContent)) {
      intent.textContent = window.SEMIF_DRIVE_MODE === "heuristic" ? "Heuristic" : "SemArbiter";
    }
    renderModeHealth();
  }
  // Screen readers hear the mode and a change of health (ready / which failure), not every tick
  // of the evidence age.
  let announced = "";
  function announce(text) {
    if (text === announced) return;
    announced = text;
    const live = document.getElementById("sol-mode-announce");
    if (live) live.textContent = text;
  }
  function renderModeHealth() {
    if (window.SEMIF_DRIVE_MODE !== "vision") {
      modeEl.setAttribute("data-health", "");
      modeHealth.textContent = "";
      announce(`${MODE_INFO[window.SEMIF_MODE_ID].label} mode`);
      return;
    }
    const age = Number.isFinite(window.SEMIF_VISION_AT) ? performance.now() - window.SEMIF_VISION_AT : NaN;
    const h = modeHealthOf(window.SEMIF_VISION, age);
    modeEl.setAttribute("data-health", h.state);
    modeHealth.textContent = h.text;
    modeHealth.setAttribute("title", h.text);
    // Fixed phrases: the evidence age is on screen, not read out on every tick.
    const reason = h.state === "ok" ? "" : h.text.startsWith("Evidence") ? "evidence stale" : h.text.split(" — ")[0].toLowerCase();
    const label = MODE_INFO[window.SEMIF_MODE_ID].label;
    announce(h.state === "ok" ? `${label} mode, detector ready` : `${label} mode, ${reason}, holding to a crawl`);
  }

  // The bundle's strategy dropdown is the switch for SemArbiter vs the heuristic; it follows the
  // indicator, and the indicator follows it.
  function syncStrategy(mode) {
    const select = document.getElementById("strategy-select");
    const want = mode === "heuristic" ? "heuristic" : "semif";
    if (!select || select.value === want) return;
    select.value = want;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function setDriveMode(mode, fromStrategy) {
    if (!DRIVE_MODES.includes(mode)) return;
    window.SEMIF_MODE_ID = mode;
    window.SEMIF_DRIVE_MODE = driveOf(mode);
    if (mode !== "heuristic") lastModelMode = mode;
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch (_) {}
    try {
      const q = new URLSearchParams(location.search);
      q.set("mode", mode);
      history.replaceState(history.state, "", `${location.pathname || ""}?${q.toString()}${location.hash || ""}`);
    } catch (_) {}
    if (!fromStrategy) syncStrategy(window.SEMIF_DRIVE_MODE);
    renderMode();
  }
  const stepMode = (by) =>
    DRIVE_MODES[(DRIVE_MODES.indexOf(window.SEMIF_MODE_ID) + by + DRIVE_MODES.length) % DRIVE_MODES.length];
  for (const m of DRIVE_MODES) {
    const btn = document.getElementById(`sol-mode-${m}`);
    btn.addEventListener("click", () => setDriveMode(m));
    // Arrow keys move along the switch, as in any radio group.
    btn.addEventListener("keydown", (ev) => {
      const by = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
      if (!by) return;
      ev.preventDefault();
      ev.stopPropagation(); // the bundle steers, and drops autopilot, on arrows that reach window
      const next = stepMode(by);
      setDriveMode(next);
      const target = document.getElementById(`sol-mode-${next}`);
      if (target && target.focus) target.focus();
    });
  }
  // M cycles the mode (V already hides the camera view). Not while typing or with a dialog open.
  document.addEventListener("keydown", (ev) => {
    if (ev.repeat || ev.code !== "KeyM" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (/input|select|textarea/i.test((ev.target && ev.target.tagName) || "")) return;
    if (document.querySelector("dialog[open]")) return;
    setDriveMode(stepMode(1));
  });
  // The dropdown is the bundle's: it may mount after this script, and the bundle's own 1/2/3 keys
  // and strategy buttons set its value without a change event. So the indicator also compares it
  // every frame (tick) and follows whoever drives.
  let strategyWired = false;
  function followStrategy() {
    const select = document.getElementById("strategy-select");
    if (!select) return;
    if (select.value === "heuristic" && window.SEMIF_DRIVE_MODE !== "heuristic") setDriveMode("heuristic", true);
    else if (select.value && select.value !== "heuristic" && window.SEMIF_DRIVE_MODE === "heuristic") setDriveMode(lastModelMode, true);
  }
  // The steering-candidate fan (#19). The bundle draws only the chosen path unless its candidates
  // button is pressed, and keeps that state inside its own module (a layout rebuild resets the fan
  // from it), so the choice is restored by pressing the button once it works. ?candidates=all or
  // ?candidates=selected wins over the browser's last choice.
  const CANDIDATES_KEY = "semif.candidates";
  const candidatesParam = params.get("candidates");
  let candidatesSaved = null;
  try {
    candidatesSaved = localStorage.getItem(CANDIDATES_KEY);
  } catch (_) {}
  const wantFan = candidatesParam === "all" ? true : candidatesParam === "selected" ? false : candidatesSaved === "1";
  let fanShown = null; // null until restored
  function syncCandidates() {
    const btn = document.getElementById("candidates-toggle");
    if (!btn || typeof btn.onclick !== "function") return;
    if (fanShown === null) {
      // The minimal view hides the button: a fan brought back there could not be turned off.
      const minimal = document.body.classList.contains("semif-minimal");
      if (wantFan && !minimal && btn.getAttribute("aria-pressed") !== "true") btn.click();
      fanShown = btn.getAttribute("aria-pressed") === "true";
      return;
    }
    const on = btn.getAttribute("aria-pressed") === "true";
    if (on === fanShown) return;
    fanShown = on;
    try {
      localStorage.setItem(CANDIDATES_KEY, on ? "1" : "0");
    } catch (_) {}
  }

  function wireStrategy() {
    const select = document.getElementById("strategy-select");
    if (!select) return;
    if (!strategyWired) {
      strategyWired = true;
      select.addEventListener("change", followStrategy);
      syncStrategy(window.SEMIF_DRIVE_MODE);
      return;
    }
    followStrategy();
  }
  wireStrategy();
  renderMode();
  window.SEMIF_MODE = { set: setDriveMode, health: modeHealthOf, refresh: renderModeHealth };

  // Minimal view (H, or the corner button): every panel folds away except speed, limit, the
  // autopilot switch and the next turn, so the drive fills the screen. Remembered per browser.
  const minimalBtn = document.createElement("button");
  minimalBtn.type = "button";
  minimalBtn.id = "fsd-minimal";
  minimalBtn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>`;
  document.body.appendChild(minimalBtn);
  let stats = null; // the latency panel, mounted below
  function setMinimal(on) {
    document.body.classList.toggle("semif-minimal", on);
    if (on && stats) stats.toggle(false);
    minimalBtn.setAttribute("aria-pressed", String(on));
    minimalBtn.setAttribute("aria-label", on ? "Show the full interface" : "Minimal view");
    minimalBtn.title = (on ? "Show the full interface" : "Minimal view") + " · H";
    try {
      localStorage.setItem("semif-minimal", on ? "1" : "0");
    } catch (_) {}
  }
  let minimalSaved = null;
  try {
    minimalSaved = localStorage.getItem("semif-minimal");
  } catch (_) {}
  setMinimal(params.has("minimal") ? params.get("minimal") !== "0" : minimalSaved === "1");
  minimalBtn.addEventListener("click", () => setMinimal(!document.body.classList.contains("semif-minimal")));
  document.addEventListener("keydown", (ev) => {
    if (ev.repeat || ev.code !== "KeyH" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (/input|select|textarea/i.test((ev.target && ev.target.tagName) || "")) return;
    setMinimal(!document.body.classList.contains("semif-minimal"));
  });

  // Dock the status bar under the bundle's map / strategy panel, whatever size that panel has.
  const statusEl = document.getElementById("fsd-status");
  let statusDock = "";
  function dockStatus() {
    const panel = document.querySelector(".topbar");
    if (!panel || !statusEl) return;
    if (window.innerWidth <= 900) {
      // Narrow screens: the stylesheet's full-width layout applies.
      if (statusDock) {
        statusEl.style.left = statusEl.style.top = statusEl.style.width = "";
        statusDock = "";
      }
      return;
    }
    const box = panel.getBoundingClientRect();
    if (!box.width) return;
    const dock = `${Math.round(box.left)}:${Math.round(box.bottom)}:${Math.round(box.width)}`;
    if (dock === statusDock) return;
    statusDock = dock;
    statusEl.style.left = `${Math.round(box.left)}px`;
    statusEl.style.top = `${Math.round(box.bottom + 10)}px`;
    statusEl.style.width = `${Math.round(box.width)}px`;
  }

  const halo = document.getElementById("fsd-halo");
  const boxes = document.getElementById("fsd-boxes");
  const seedInput = document.getElementById("fsd-seed-input");
  const visionEl = document.getElementById("fsd-vision");
  const intentEl = document.getElementById("fsd-intent");
  const latencyEl = document.getElementById("fsd-latency");
  const visionOn = params.get("vision") !== "0";
  const visionPacer = window.SEMIF_VISION_PACE
    ? window.SEMIF_VISION_PACE.createVisionPacer()
    : { tryBegin: () => true, ticket: () => 0, signal: () => undefined, end() {}, stats: () => null };
  window.SEMIF_VISION_PACER = visionPacer;
  const lapOnce = params.get("lap") === "1";
  window.SEMIF_VISION = null;
  window.SEMIF_VISION_GEN = null;

  const telemetryCore = window.SEMIF_TELEMETRY_CORE;
  const telemetry = telemetryCore && telemetryCore.createLatencyTelemetry
    ? telemetryCore.createLatencyTelemetry()
    : null;
  window.SEMIF_TELEMETRY = telemetry;

  function exportLatency() {
    if (!telemetry || typeof telemetry.exportJSON !== "function") return;
    const blob = new Blob([JSON.stringify(telemetry.exportJSON(), null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "semif-web-latency.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // The status strip's latency chip opens the charts (semif-stats.js); L does too.
  stats = window.SEMIF_STATS && telemetry && typeof telemetry.getTimeline === "function"
    ? window.SEMIF_STATS.mountStats({ telemetry, chip: latencyEl, parent: chrome, onExport: exportLatency, onOpen: () => setMinimal(false) })
    : null;

  function refreshLatencyHud() {
    if (stats) stats.refresh();
    else if (latencyEl && telemetry && typeof telemetry.hudText === "function") {
      latencyEl.textContent = telemetry.hudText();
    }
  }

  function reloadWithSeed(seed) {
    const q = new URLSearchParams(location.search);
    q.set("seed", String(Math.max(0, Math.floor(Number(seed) || 0) % 1000000)));
    const world = document.getElementById("world-select");
    if (world && world.value) q.set("world", world.value);
    location.search = q.toString();
  }

  document.getElementById("fsd-seed-apply").addEventListener("click", () => {
    reloadWithSeed(seedInput.value);
  });
  document.getElementById("fsd-seed-rand").addEventListener("click", () => {
    reloadWithSeed(Math.floor(Math.random() * 999999));
  });
  seedInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") reloadWithSeed(seedInput.value);
  });

  const pipRoot = document.getElementById("fsd-pip");
  const pipHeader = document.querySelector(".fsd-pip-header");
  const pipFps = document.getElementById("fsd-pip-fps");
  const pipCanvas = document.getElementById("fsd-camera-canvas");
  const PIP_W = 320;
  const PIP_H = 180;
  // The front camera is also what perception reads (#18): twice the side cameras' resolution, so
  // a person 30 m ahead is more than a few pixels. The PIP shows it scaled down.
  const FRONT_W = 640;
  const FRONT_H = 360;
  // A lit lamp 20 m away is a few pixels; at the old quality JPEG's colour blur greyed it out.
  const FRONT_JPEG = 0.85;
  if (pipCanvas) {
    pipCanvas.width = FRONT_W;
    pipCanvas.height = FRONT_H;
  }
  if (pipHeader && pipRoot) {
    pipHeader.addEventListener("click", () => {
      pipRoot.classList.toggle("fsd-pip-collapsed");
    });
  }
  document.addEventListener("keydown", (ev) => {
    if (!pipRoot) return;
    if (ev.repeat) return;
    if (ev.key !== "v" && ev.key !== "V") return;
    const tag = ev.target && ev.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    pipRoot.classList.toggle("fsd-pip-hidden");
  });

  // Fleet mode (#3): traffic cars ask /v1/fleet, the same decision core as the player.
  // Each car is described by what it senses: its speed and ego-relative boxes (rel_x right,
  // rel_z ahead) within camera range, plus the next stop line. No world position is sent.
  const FLEET_POLICIES = ["off", "semif", "raw_flat", "heuristic"];
  const FLEET_PERIOD_S = 0.2;
  const FLEET_STALE_S = 1.0;
  const FLEET_RANGE_M = 42;
  const FLEET_LINE_M = 60;
  const FLEET_MAX = 64;
  // Car footprint when the bundle does not give one (its cars are 1.9 m by 4.75 m).
  const FLEET_WIDTH_M = 1.9;
  const FLEET_DEPTH_M = 4.75;
  // The decision owns the signal. Junction interlocks the 1D planner cannot see
  // (crossing traffic, stop-sign order, pedestrians) stay with the traffic rules.
  const FLEET_SIGNAL_STOPS = new Set(["Red light", "Amber light"]);
  const FLEET_SIGNAL_NAMES = { red: "red", amber: "yellow", yellow: "yellow", green: "green" };
  const fleetBtn = document.getElementById("fsd-fleet");
  const fleetParam = params.get("fleet");
  const fleet = {
    policy: FLEET_POLICIES.indexOf(fleetParam) > 0 ? fleetParam : "off",
    decisions: new Map(),
    inflight: false,
    nextAt: 0,
    epoch: 0,
    lastTime: null,
    seed: null,
    session: `fleet-${Math.random().toString(36).slice(2, 10)}`,
    posts: 0,
    errors: 0,
    contacts: new Set(),
    reds: 0,
    lines: new Map(),
  };
  window.SEMIF_FLEET = fleet;

  function fleetOn() {
    return fleet.policy !== "off";
  }

  function refreshFleetHud() {
    if (!fleetBtn) return;
    fleetBtn.textContent = fleetOn()
      ? `FLEET ${fleet.policy} · hits ${fleet.contacts.size} · reds ${fleet.reds}${fleet.errors ? " · error" : ""}`
      : "FLEET off";
  }

  // A new policy or a restarted world: nothing from before carries over.
  function resetFleet() {
    fleet.epoch += 1;
    fleet.decisions.clear();
    fleet.contacts.clear();
    fleet.lines.clear();
    fleet.reds = 0;
    fleet.errors = 0;
    fleet.nextAt = 0;
  }

  function setFleetPolicy(policy) {
    fleet.policy = FLEET_POLICIES.indexOf(policy) >= 0 ? policy : "off";
    resetFleet();
    refreshFleetHud();
  }

  if (fleetBtn) {
    fleetBtn.addEventListener("click", () => {
      const at = FLEET_POLICIES.indexOf(fleet.policy);
      setFleetPolicy(FLEET_POLICIES[(at + 1) % FLEET_POLICIES.length]);
    });
  }
  refreshFleetHud();

  function fleetCars(sim) {
    return (sim.traffic || []).filter((car) => car && !car.parked && car.id);
  }

  // Right-positive, forward-positive, heading 0 is -Z (the Web bicycle's frame).
  function egoRelative(car, other) {
    const dx = other.x - car.x;
    const dz = other.z - car.z;
    const h = Number(car.heading) || 0;
    return { rel_x: dx * Math.cos(h) + dz * Math.sin(h), rel_z: dx * Math.sin(h) - dz * Math.cos(h) };
  }

  function fleetBox(kind, rel) {
    return { kind, rel_x: +rel.rel_x.toFixed(2), rel_z: +rel.rel_z.toFixed(2) };
  }

  function fleetAgent(sim, car, rule, index) {
    const obstacles = [];
    for (const other of [sim.player].concat(sim.traffic || [])) {
      if (!other || other === car) continue;
      const rel = egoRelative(car, other);
      if (Math.hypot(rel.rel_x, rel.rel_z) <= FLEET_RANGE_M) obstacles.push(fleetBox("vehicle", rel));
    }
    for (const ped of sim.pedestrians || []) {
      const rel = egoRelative(car, ped);
      if (Math.hypot(rel.rel_x, rel.rel_z) <= FLEET_RANGE_M) obstacles.push(fleetBox("pedestrian", rel));
    }
    const agent = {
      id: car.id,
      steers: false,
      speed_mps: Math.max(0, Number(car.speed) || 0),
      speed_ceiling_mps: Number(sim.world && sim.world.theme && sim.world.theme.limit) || 14,
      obstacles,
      seed: ((sim.world && Number(sim.world.seed)) || 0) + index,
    };
    const dist = rule ? Number(rule.distance) : NaN;
    if (Number.isFinite(dist) && dist >= 0 && dist <= FLEET_LINE_M) {
      const signal = FLEET_SIGNAL_NAMES[rule.color];
      agent.intersection = {
        control: signal ? "traffic_light" : "stop",
        distance_to_line_m: +dist.toFixed(1),
        signal: signal || "none",
        stop_completed: !!rule.stopCompleted,
        already_entered: false,
      };
    }
    return agent;
  }

  function fleetDecision(sim, car) {
    if (!fleetOn() || !car || car === sim.player || car.parked) return null;
    const d = fleet.decisions.get(car.id);
    const age = (Number(sim.time) || 0) - (d ? d.at : 0);
    return d && age >= 0 && age <= FLEET_STALE_S ? d : null;
  }

  function bindFleet(sim) {
    if (sim._fleetBound) return;
    sim._fleetBound = true;
    const baseRule = typeof sim.rule === "function" ? sim.rule.bind(sim) : null;
    const baseEnvelope = typeof sim.speedEnvelope === "function" ? sim.speedEnvelope.bind(sim) : null;
    sim._fleetBaseRule = baseRule;
    if (baseRule) {
      // A fleet car stops for a signal on its decision, not on the script's stop-line clamp.
      sim.rule = function (car, flag) {
        const out = baseRule(car, flag);
        if (!out || !out.mustStop || !FLEET_SIGNAL_STOPS.has(out.reason) || !fleetDecision(sim, car)) return out;
        return Object.assign({}, out, { mustStop: false, reason: `Fleet ${fleet.policy}` });
      };
    }
    if (baseEnvelope) {
      // Same as the player: the decision's speed under the safety envelope; raw_flat drops it, like raw mode.
      sim.speedEnvelope = function (car) {
        const env = baseEnvelope(car);
        const d = fleetDecision(sim, car);
        if (!env || !d) return env;
        const decided = Math.max(0, d.target_speed_mps);
        const max = fleet.policy === "raw_flat" ? decided : Math.min(Number(env.max), decided);
        return Object.assign({}, env, { max, reason: `Fleet ${fleet.policy}` });
      };
    }
  }

  function fleetStats(sim) {
    const everyone = [sim.player].concat(sim.traffic || []).filter(Boolean);
    for (const car of fleetCars(sim)) {
      if (!fleetDecision(sim, car)) continue;
      for (const other of everyone) {
        if (other === car) continue;
        const rel = egoRelative(car, other);
        const halfDepth = ((car.depth || FLEET_DEPTH_M) + (other.depth || FLEET_DEPTH_M)) / 2;
        const halfWidth = ((car.width || FLEET_WIDTH_M) + (other.width || FLEET_WIDTH_M)) / 2;
        if (Math.abs(rel.rel_z) >= halfDepth || Math.abs(rel.rel_x) >= halfWidth) continue;
        fleet.contacts.add([car.id, other.id || "player"].sort().join("|"));
      }
      const rule = sim._fleetBaseRule ? sim._fleetBaseRule(car) : null;
      const dist = rule ? Number(rule.distance) : NaN;
      if (!Number.isFinite(dist)) continue;
      const before = fleet.lines.get(car.id);
      const crossed = before && before.node === rule.nodeId && before.dist > 0 && dist <= 0;
      if (crossed && before.color === "red" && car.speed > 2) fleet.reds += 1;
      fleet.lines.set(car.id, { node: rule.nodeId, dist, color: rule.color });
    }
  }

  function fleetTick(sim) {
    if (!fleetOn() || !sim) return;
    bindFleet(sim);
    const now = Number(sim.time) || 0;
    const seed = sim.world ? sim.world.seed : null;
    if ((fleet.lastTime != null && now < fleet.lastTime) || seed !== fleet.seed) resetFleet();
    fleet.lastTime = now;
    fleet.seed = seed;
    fleetStats(sim);
    if (fleet.inflight || now < fleet.nextAt) return;
    const cars = fleetCars(sim).slice(0, FLEET_MAX);
    if (!cars.length) return;
    fleet.nextAt = now + FLEET_PERIOD_S;
    const base = sim._fleetBaseRule;
    const agents = cars.map((car, i) => fleetAgent(sim, car, base ? base(car) : null, i));
    const policy = fleet.policy;
    const epoch = fleet.epoch;
    fleet.inflight = true;
    fleet.posts += 1;
    origFetch("/v1/fleet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ policy, agents, session: `${fleet.session}-${epoch}`, t: now }),
    })
      .then((res) => res.json())
      .then((body) => {
        if (!body || !body.decisions) {
          fleet.errors += 1;
          return;
        }
        if (fleet.policy !== policy || fleet.epoch !== epoch) return;
        const at = Number(sim.time) || 0;
        for (const [id, d] of Object.entries(body.decisions)) {
          fleet.decisions.set(id, { target_speed_mps: Number(d.target_speed_mps) || 0, choice: d.choice, at });
        }
      })
      .catch(() => {
        fleet.errors += 1;
      })
      .finally(() => {
        fleet.inflight = false;
        refreshFleetHud();
      });
  }

  const STALL_SPEED = 0.2;
  const STALL_PROGRESS_M = 0.5;
  const STALL_HOLD_S = 3.0;
  const STALL_COOLDOWN_S = 8.0;

  function requestEgoReplan(sim, dt) {
    const p = sim && sim.player;
    if (!p) return;
    if (!sim.autopilot) {
      sim._stallHeld = 0;
      sim._stallS0 = p.s;
      return;
    }
    sim._stallCool = Math.max(0, (sim._stallCool || 0) - (dt || 0));
    const speed = Math.abs(Number(p.speed) || 0);
    if (speed >= STALL_SPEED) {
      sim._stallHeld = 0;
      sim._stallS0 = p.s;
      return;
    }
    if (sim._stallS0 == null) sim._stallS0 = p.s;
    sim._stallHeld = (sim._stallHeld || 0) + (dt || 0);
    const progress = Number.isFinite(p.s) && Number.isFinite(sim._stallS0)
      ? Math.abs(p.s - sim._stallS0)
      : 0;
    if (sim._stallHeld < STALL_HOLD_S || progress >= STALL_PROGRESS_M || sim._stallCool > 0) return;
    sim._stallHeld = 0;
    sim._stallS0 = p.s;
    sim._stallCool = STALL_COOLDOWN_S;
    sim.offRouteSince = sim.time;
    sim.nextRouteCheck = sim.time;
    if (typeof sim.rerouteIfNeeded === "function") sim.rerouteIfNeeded();
  }

  const LANE_KEEP_OFFSET_M = 1.4;
  const LOOKAHEAD_MIN_M = 4.0;
  const LOOKAHEAD_MAX_M = 8.0;
  const LOOKAHEAD_S = 0.40;

  window.SEMIF_APPLY_STEER = function (_player, u) {
    return u;
  };

  function laneKeepManeuver(selectedOffset, speed) {
    if (
      selectedOffset != null &&
      Number.isFinite(selectedOffset) &&
      Math.abs(selectedOffset) > LANE_KEEP_OFFSET_M
    ) {
      return { lane_offset_m: selectedOffset, lookahead_m: null };
    }
    const look = Math.max(
      LOOKAHEAD_MIN_M,
      Math.min(LOOKAHEAD_MAX_M, LOOKAHEAD_S * Math.abs(Number(speed) || 0))
    );
    return { lane_offset_m: 0, lookahead_m: look };
  }

  function applyLaneKeepReference(sim) {
    const p = sim && sim.player;
    if (!p || !sim.autopilot || sim.paused || sim.crash) return;
    const src = p.maneuver;
    if (!src) return;
    if (src._pdCaptured !== true) {
      src._pdCaptured = true;
      src._pdSelOff = Number.isFinite(src.lane_offset_m) ? src.lane_offset_m : null;
    }
    const keep = laneKeepManeuver(src._pdSelOff, p.speed);
    if (keep.lookahead_m == null) {
      src.lane_offset_m = keep.lane_offset_m;
      return;
    }
    src.lane_offset_m = 0;
    const speed = Number(p.speed) || 0;
    if (sim._pdLook == null || Math.abs(speed - (sim._pdLookSpeed || 0)) > 3) {
      sim._pdLook = keep.lookahead_m;
      sim._pdLookSpeed = speed;
    }
    src.lookahead_m = sim._pdLook;
  }

  function applyRawMode(on) {
    window.SEMIF_RAW_MODE = !!on;
    const sim = window.SEMIF_SIM;
    if (!sim) return;
    sim.rawMode = !!on;
    sim.safety = !on;
    if (sim.player) {
      sim.player.rawMode = !!on;
      if (on && sim.player.maneuver) {
        sim.player.maneuver = { ...sim.player.maneuver, stop_at_line: null };
      }
    }
  }

  // What every decision request carries besides the bundle's own state.
  function shapeDecisionBody(body) {
    body.raw_mode = !!window.SEMIF_RAW_MODE;
    if (window.SEMIF_SIM && window.SEMIF_SIM.world) {
      body.state = body.state || {};
      body.state.seed = window.SEMIF_SIM.world.seed;
      body.state.raw_mode = !!window.SEMIF_RAW_MODE;
    }
    const sim = window.SEMIF_SIM;
    const laneOffset =
      sim &&
      ((sim.lastDecisionState && sim.lastDecisionState.lane && sim.lastDecisionState.lane.offset_m) ??
        (sim.lastPlan && sim.lastPlan.lane && sim.lastPlan.lane.offset_m));
    if (typeof laneOffset === "number" && Number.isFinite(laneOffset)) {
      body.state = body.state || {};
      body.state.lateral_offset_m = laneOffset;
    }
    if (window.SEMIF_VISION) {
      body.state = body.state || {};
      body.state.vision = window.SEMIF_VISION;
      if (Number.isFinite(window.SEMIF_VISION_AT)) body.state.vision_age_ms = Math.round(performance.now() - window.SEMIF_VISION_AT);
    }
    if (window.SEMIF_DRIVE_MODE === "vision") {
      body.drive_mode = "vision";
      // The new Vision names its stage; Vision (map) sends none and the server keeps its old rules.
      if (window.SEMIF_MODE_ID === "vision") body.vision_stage = window.SEMIF_VISION_STAGE;
      updateSeenSignal();
      body.state = body.state || {};
      body.state.seen_signal = window.SEMIF_SEEN_SENT || null;
      const paths = candidatePaths(body.state.candidates);
      if (paths) body.state.candidate_paths = paths;
    }
    return body;
  }

  // The planner's own projection of each candidate, so the server sweeps the path the car will
  // drive (it re-steers to follow its lane) rather than a constant steer. Candidates arrive under
  // aliases; each is matched to the plan's vector by speed and steer. [t s, ahead m, right m,
  // heading rad] in the car's frame at planning time, every 0.2 s for 3 s.
  function candidatePaths(candidates) {
    const plan = window.SEMIF_SIM && window.SEMIF_SIM.lastPlan;
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
  window.SEMIF_SHAPE_DECISION = shapeDecisionBody;

  // Vision mode's signal colour: what the cameras read, counted from when the frame was taken. A
  // red or amber reading is kept 2.5 s; a green only 0.8 s, so with a decision taking effect up to
  // 1.2 s later a lost reading cannot carry a green past an amber phase (2 s). Evidence more than
  // 1.5 s old, or from the future (another page's clock), says nothing.
  // SEMIF_SEEN_SENT goes to the server: the reading, or null when there is none.
  // SEMIF_SEEN_SIGNAL goes to the planner (BUNDLE_PATCHES.md vision-plan): the same, red when null;
  // the planner applies it only at a signalled line, as the server does (jevpilot_vision/vision_mode.py).
  const SEEN_MEMORY_MS = { red: 2500, amber: 2500, green: 800 };
  let lastSeen = null;
  function updateSeenSignal() {
    const now = performance.now();
    const vis = window.SEMIF_VISION;
    const p = vis && vis.perception;
    const taken = window.SEMIF_VISION_AT;
    const fresh = Number.isFinite(taken) && now >= taken && now - taken <= 1500;
    const ok = fresh && p && p.backend && p.backend !== "none" && (p.status || "ready") === "ready";
    const state = ok && p.signal && p.signal.state;
    if (["red", "amber", "green"].includes(state) && !(lastSeen && lastSeen.at > taken)) lastSeen = { state, at: taken };
    const held = ok && lastSeen && now >= lastSeen.at && now - lastSeen.at <= SEEN_MEMORY_MS[lastSeen.state] ? lastSeen.state : null;
    window.SEMIF_SEEN_SENT = held;
    window.SEMIF_SEEN_SIGNAL = held || "red";
  }
  window.SEMIF_UPDATE_SEEN = updateSeenSignal;

  const origFetch = window.fetch.bind(window);
  // How the decision path's requests went, for the closed-loop evaluation (#28): counted where the
  // requests are made. An outage (the request never reached a working server: a network failure, a
  // 502/503/504) is told apart from the system under test failing (a 500, the bundle's 12 s
  // timeout, a reply that is not JSON).
  window.SEMIF_CLASSIFIER_STATS = { ok: 0, http_errors: 0, network_errors: 0, bad_replies: 0, gateway_errors: 0, timeouts: 0 };
  const isTimeout = (err) => !!err && (err.name === "TimeoutError" || err.name === "AbortError");
  const classifierStats = window.SEMIF_CLASSIFIER_STATS;
  window.fetch = function (url, opts) {
    const href = typeof url === "string" ? url : url && url.url;
    if (href && href.indexOf("/classifier") !== -1 && opts && typeof opts.body === "string") {
      try {
        const body = shapeDecisionBody(JSON.parse(opts.body));
        opts = Object.assign({}, opts, { body: JSON.stringify(body) });
      } catch (_err) {
        /* leave request unchanged */
      }
      let tClass = performance.now();
      // The classifier's latency is timed from when the request really goes out (after any lag).
      const sent = window.SEMIF_LAG_MS > 0
        ? new Promise((resolve) => setTimeout(resolve, window.SEMIF_LAG_MS)).then(() => {
            tClass = performance.now();
            return origFetch(url, opts);
          })
        : origFetch(url, opts);
      return sent.then(async (res) => {
        if ([502, 503, 504].includes(res.status)) classifierStats.gateway_errors += 1;
        else if (!res.ok) classifierStats.http_errors += 1;
        let data;
        let raw = "";
        try {
          raw = await res.text();
          data = JSON.parse(raw);
        } catch (err) {
          if (isTimeout(err)) classifierStats.timeouts += 1;
          else if (res.ok) classifierStats.bad_replies += 1;
          // The body is read: hand the bundle a fresh response with the same text, status and
          // headers (the original's body is used and cannot be read again).
          return new Response(raw, { status: res.status, statusText: res.statusText, headers: res.headers });
        }
        if (res.ok) classifierStats.ok += 1;
        try {
          data = fillJevAnswers(data, JSON.parse(opts.body));
        } catch (_err) {
          /* keep server JSON */
        }
        if (telemetry && data && res.ok) {
          const rtt = performance.now() - tClass;
          const cls = Number(data.classifier_ms != null ? data.classifier_ms : (data.meta && data.meta.classifier_ms));
          if (Number.isFinite(cls)) {
            telemetry.recordClassifier({
              classifier_ms: cls,
              rtt_ms: rtt,
            });
            refreshLatencyHud();
          }
        }
        if (data && data.meta) renderDecision(data);
        return new Response(JSON.stringify(data), {
          status: res.status,
          statusText: res.statusText,
          headers: { "Content-Type": "application/json" },
        });
      }, (err) => {
        if (isTimeout(err)) classifierStats.timeouts += 1;
        else classifierStats.network_errors += 1;
        throw err;
      });
    }
    return origFetch(url, opts);
  };

  function mockChoice(ids, pick) {
    const probs = {};
    const rest = Math.max(ids.length - 1, 1);
    for (const id of ids) probs[id] = id === pick ? 0.85 : 0.15 / rest;
    const total = Object.values(probs).reduce((a, b) => a + b, 0) || 1;
    for (const id of ids) probs[id] = Math.round((probs[id] / total) * 1e4) / 1e4;
    return { choice: pick, probabilities: probs };
  }

  function fillJevAnswers(data, req) {
    if (!data || typeof data !== "object") return data;
    const answers = data.answers || (data.answers = {});
    const qs = (req && req.questions) || {};
    const motionCrit = qs.motion && qs.motion.criteria;
    if (motionCrit && typeof motionCrit === "object" && !answers.motion) {
      const ids = Object.keys(motionCrit);
      if (ids.length) {
        const pick = ids.indexOf("drive") >= 0 ? "drive" : ids[0];
        answers.motion = mockChoice(ids, pick);
      }
    }
    const vectorCrit = qs.vector && qs.vector.criteria;
    if (vectorCrit && typeof vectorCrit === "object" && answers.vector) {
      const ids = Object.keys(vectorCrit);
      if (ids.length) {
        const raw = answers.vector.probabilities || {};
        const pick = ids.indexOf(answers.vector.choice) >= 0 ? answers.vector.choice : ids[0];
        const filled = {};
        for (const id of ids) {
          const p = Number(raw[id]);
          filled[id] = Number.isFinite(p) ? Math.min(1, Math.max(0, p)) : id === pick ? 0.8 : 0;
        }
        const sum = Object.values(filled).reduce((a, b) => a + b, 0) || 1;
        for (const id of ids) filled[id] = filled[id] / sum;
        answers.vector = { choice: pick, probabilities: filled };
      }
    }
    return data;
  }

  function renderDecision(data) {
    const meta = data.meta || {};
    const intent = meta.tier1_maneuver || "SemArbiter";
    const choice = data.answers && data.answers.vector && data.answers.vector.choice;
    intentEl.textContent = choice ? `${intent} · ${choice}` : String(intent).replace(/_/g, " ");
  }

  function project(camera, x, y, z, width, height) {
    if (!camera || !camera.matrixWorldInverse || !camera.projectionMatrix) return null;
    const e = camera.matrixWorldInverse.elements;
    const p = camera.projectionMatrix.elements;
    const cx = e[0] * x + e[4] * y + e[8] * z + e[12];
    const cy = e[1] * x + e[5] * y + e[9] * z + e[13];
    const cz = e[2] * x + e[6] * y + e[10] * z + e[14];
    const cw = e[3] * x + e[7] * y + e[11] * z + e[15];
    const nx = p[0] * cx + p[4] * cy + p[8] * cz + p[12] * cw;
    const ny = p[1] * cx + p[5] * cy + p[9] * cz + p[13] * cw;
    const nz = p[2] * cx + p[6] * cy + p[10] * cz + p[14] * cw;
    const nw = p[3] * cx + p[7] * cy + p[11] * cz + p[15] * cw;
    if (!nw) return null;
    const ndcZ = nz / nw;
    if (ndcZ < -1 || ndcZ > 1) return null;
    return {
      x: (nx / nw * 0.5 + 0.5) * width,
      y: (-ny / nw * 0.5 + 0.5) * height,
    };
  }

  function dist2(a, b) {
    const dx = a.x - b.x;
    const dz = a.z - b.z;
    return Math.hypot(dx, dz);
  }

  // Camera-relative perception (perception.py: ahead_m / right_m from the onboard camera, which sits
  // CAMERA_AHEAD_M ahead of the car's centre) to world x / z.
  const CAMERA_AHEAD_M = 0.15;
  const SEEN_HEIGHT_M = { pedestrian: 1.7, car: 1.5, motorcycle: 1.6 }; // perception.HEIGHT_M
  const SEEN_STALE_MS = 1500; // vision_mode.STALE_MS: older evidence is no evidence

  // Where the car was over the last 2 s: perception is relative to the frame grabbed at
  // SEMIF_VISION_AT, so its objects are placed from the car's pose then, not now.
  const poseLog = [];
  function logPose(player) {
    const t = performance.now();
    poseLog.push({ t, x: player.x, z: player.z, heading: player.heading || 0 });
    while (poseLog.length && poseLog[0].t < t - 2000) poseLog.shift();
  }
  function poseAt(t, player) {
    let best = null;
    for (const p of poseLog) if (p.t <= t && (!best || p.t > best.t)) best = p;
    return best || player;
  }

  function seenToWorld(player, ahead, right) {
    const h = player.heading || 0;
    const fwd = ahead + CAMERA_AHEAD_M;
    return {
      x: player.x + Math.sin(h) * fwd + Math.cos(h) * right,
      z: player.z - Math.cos(h) * fwd + Math.sin(h) * right,
    };
  }

  // What the boxes show (#54). Vision mode: only what the camera reported, never the simulator's
  // objects. Privileged and Heuristic: the simulator's truth, labelled as such.
  function boxTargets(sim) {
    if (window.SEMIF_DRIVE_MODE === "vision") {
      const vis = window.SEMIF_VISION;
      const objects = vis && vis.perception && Array.isArray(vis.perception.objects) ? vis.perception.objects : [];
      const takenAt = Number(window.SEMIF_VISION_AT);
      const age = performance.now() - takenAt;
      if (!(age >= 0 && age <= SEEN_STALE_MS)) return [];
      const then = poseAt(takenAt, sim.player);
      const out = [];
      for (const o of objects) {
        if (!o || !Object.prototype.hasOwnProperty.call(SEEN_HEIGHT_M, o.kind)) continue;
        const ahead = Number(o.ahead_m);
        const right = Number(o.right_m);
        if (!Number.isFinite(ahead) || !Number.isFinite(right)) continue;
        const at = seenToWorld(then, ahead, right);
        out.push({
          x: at.x,
          z: at.z,
          height: SEEN_HEIGHT_M[o.kind],
          d: dist2(at, sim.player), // from the car now, to where the camera saw it
          tag: o.kind === "pedestrian" ? "PED" : "VEH",
          source: "CAM",
          hazard: false,
        });
      }
      return out;
    }
    const player = sim.player;
    return []
      .concat(sim.pedestrians || [])
      .concat((sim.traffic || []).filter((v) => v.hazardLights))
      .map((obj) => ({
        x: obj.x,
        z: obj.z,
        height: obj.height || 1.6,
        d: dist2(obj, player),
        tag: obj.type === "pedestrian" ? "PED" : "VEH",
        source: "TRUTH",
        hazard: !!obj.hazardLights,
      }));
  }

  function drawBoxes(sim, world) {
    boxes.innerHTML = "";
    if (!sim || !world || !world.camera || !world.canvas) return;
    const w = world.canvas.clientWidth;
    const h = world.canvas.clientHeight;
    const camera = world.camera;
    if (sim.player) logPose(sim.player);
    let nearest = Infinity;
    for (const obj of boxTargets(sim)) {
      const d = obj.d;
      if (d < nearest) nearest = d;
      if (d > 55) continue;
      const top = project(camera, obj.x, obj.height, obj.z, w, h);
      const bot = project(camera, obj.x, 0.05, obj.z, w, h);
      if (!top || !bot) continue;
      const height = Math.max(18, Math.abs(bot.y - top.y));
      const width = Math.max(16, height * 0.45);
      const el = document.createElement("div");
      el.className = "fsd-box" + (obj.hazard ? " is-hazard" : "");
      el.style.left = `${top.x - width / 2}px`;
      el.style.top = `${Math.min(top.y, bot.y)}px`;
      el.style.width = `${width}px`;
      el.style.height = `${height}px`;
      el.innerHTML = `<span>${obj.source} ${obj.tag} ${d.toFixed(0)}m</span><i class="fsd-vec"></i>`;
      boxes.appendChild(el);
    }
    // Styled by state in semif-layer.css (#fsd-halo[data-level]).
    halo.dataset.level = nearest < 12 ? "near" : nearest < 24 ? "watch" : "";
  }

  const pipFrameMs = [];
  function pipFpsText(now) {
    pipFrameMs.push(now);
    const cutoff = now - 1000;
    while (pipFrameMs.length && pipFrameMs[0] < cutoff) pipFrameMs.shift();
    if (pipFrameMs.length < 2) return "-- FPS";
    const span = pipFrameMs[pipFrameMs.length - 1] - pipFrameMs[0];
    if (span <= 0) return "-- FPS";
    return Math.round(((pipFrameMs.length - 1) * 1000) / span) + " FPS";
  }

  function onboardMount(player, yaw) {
    const ahead = 0.15;
    const height = 1.45;
    const h = (Number(player.heading) || 0) + (Number(yaw) || 0);
    const x = player.x + Math.sin(h) * ahead;
    const z = player.z - Math.cos(h) * ahead;
    return {
      x: x,
      y: height,
      z: z,
      lookX: x + Math.sin(h) * 25,
      lookY: height,
      lookZ: z - Math.cos(h) * 25,
    };
  }

  function paintOnboardPixels(pixels, canvas, w = PIP_W, h = PIP_H) {
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const image = ctx.createImageData(w, h);
    const row = w * 4;
    for (let y = 0; y < h; y++) {
      const src = (h - 1 - y) * row;
      image.data.set(pixels.subarray(src, src + row), y * row);
    }
    ctx.putImageData(image, 0, 0);
  }

  // ---- camera switcher --------------------------------------------------------------------
  // What the PIP shows. The posted vision frames do not depend on it.
  const CAMERA_VIEWS = ["front", "left", "right", "rear", "all"];
  const CAMERA_LABELS = { front: "FRONT", left: "LEFT", right: "RIGHT", rear: "REAR", all: "SURROUND" };
  const VIEW_PERIOD_MS = 66;
  // The front PIP repaints at the same 15 Hz as the other views (#42 item 3).
  const PIP_PERIOD_MS = VIEW_PERIOD_MS;
  let pipNextAt = 0;
  const cameraView = document.getElementById("fsd-camera-view");
  const cameraLabel = document.getElementById("fsd-camera-label");
  const pipView = { name: "front", nextAt: 0 };
  window.SEMIF_PIP_VIEW = pipView;

  function setCameraView(name) {
    pipView.name = CAMERA_VIEWS.indexOf(name) >= 0 ? name : "front";
    pipView.nextAt = 0;
    for (const view of CAMERA_VIEWS) {
      const tab = document.getElementById(`fsd-cam-${view}`);
      if (tab && tab.setAttribute) tab.setAttribute("aria-selected", view === pipView.name ? "true" : "false");
    }
    if (cameraView && cameraView.style) cameraView.style.visibility = pipView.name === "front" ? "hidden" : "visible";
    if (cameraLabel) {
      cameraLabel.textContent = `${CAMERA_LABELS[pipView.name]} · 100°`;
      if (cameraLabel.style) cameraLabel.style.visibility = pipView.name === "all" ? "hidden" : "visible";
    }
  }

  for (const view of CAMERA_VIEWS) {
    const tab = document.getElementById(`fsd-cam-${view}`);
    if (!tab) continue;
    tab.addEventListener("click", (ev) => {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      setCameraView(view);
    });
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.repeat || (ev.key !== "c" && ev.key !== "C")) return;
    const tag = ev.target && ev.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    setCameraView(CAMERA_VIEWS[(CAMERA_VIEWS.indexOf(pipView.name) + 1) % CAMERA_VIEWS.length]);
  });

  function paintCameraView(world, now) {
    if (pipView.name === "front" || !cameraView || now < pipView.nextAt) return;
    pipView.nextAt = now + VIEW_PERIOD_MS;
    const ctx = cameraView.getContext("2d");
    if (!ctx) return;
    if (pipView.name !== "all") {
      const side = SURROUND_SIDES.find(([name]) => name === pipView.name);
      if (side) renderView(world, side[1], cameraView);
      return;
    }
    const cells = [["front", pipCanvas, 0, 0], ["right", null, 1, 0], ["left", null, 0, 1], ["rear", null, 1, 1]];
    const w = PIP_W / 2;
    const h = PIP_H / 2;
    for (const [name, source, col, row] of cells) {
      let src = source;
      if (!src) {
        const side = SURROUND_SIDES.find(([n]) => n === name);
        src = surroundCanvas(name);
        if (!side || !renderView(world, side[1], src)) continue;
      }
      ctx.drawImage(src, col * w, row * h, w, h);
      ctx.fillStyle = pipToken("--sol-scrim", "rgba(3, 10, 16, 0.58)");
      ctx.fillRect(col * w + 4, row * h + 4, 40, 13);
      ctx.fillStyle = pipToken("--sol-ink", "#f8efe2");
      ctx.font = `700 9px ${pipToken("--sol-font", "system-ui, sans-serif")}`;
      ctx.fillText(CAMERA_LABELS[name], col * w + 8, row * h + 14);
    }
    ctx.fillStyle = pipToken("--sol-line-strong", "rgba(248, 239, 226, 0.3)");
    ctx.fillRect(w - 0.5, 0, 1, PIP_H);
    ctx.fillRect(0, h - 0.5, PIP_W, 1);
  }

  // The surround picture's labels take the overlay's tokens (semif-layer.css), read once.
  const pipTokens = {};
  function pipToken(name, fallback) {
    if (!(name in pipTokens)) {
      let v = "";
      try {
        v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      } catch (_err) {
        /* no style sheet (node tests): the built-in value */
      }
      pipTokens[name] = v || fallback;
    }
    return pipTokens[name];
  }

  // Pills carry their state (on / off / waiting / error) for the stylesheet.
  function pillState(text) {
    const t = String(text || "").toLowerCase();
    if (t.indexOf("error") >= 0) return "error";
    if (t.indexOf(" off") >= 0 || t === "fleet off") return "off";
    if (t.indexOf("waiting") >= 0) return "waiting";
    return "on";
  }

  function watchPill(el) {
    if (!el || typeof MutationObserver === "undefined") return;
    const sync = () => {
      el.dataset.state = pillState(el.textContent);
    };
    new MutationObserver(sync).observe(el, { childList: true, characterData: true, subtree: true });
    sync();
  }

  setCameraView("front");
  watchPill(visionEl);
  watchPill(fleetBtn);

  // Four onboard cameras, about 100° horizontal each. Yaw turns clockwise from forward.
  const ONBOARD_HFOV = 100;
  const ONBOARD_VFOV = 2 * Math.atan(Math.tan((ONBOARD_HFOV * Math.PI) / 360) / (PIP_W / PIP_H)) * (180 / Math.PI);
  // Vision mode adds a narrow forward camera, as production cars carry, for lights the wide one
  // sees as a few pixels (jevpilot_vision/perception.py NARROW_HFOV_DEG).
  const NARROW_HFOV = 40;
  const NARROW_VFOV = 2 * Math.atan(Math.tan((NARROW_HFOV * Math.PI) / 360) / (FRONT_W / FRONT_H)) * (180 / Math.PI);
  const SURROUND_SIDES = [
    ["right", Math.PI / 2],
    ["rear", Math.PI],
    ["left", -Math.PI / 2],
  ];
  const surroundCanvases = {};

  function surroundCanvas(name, w = PIP_W, h = PIP_H) {
    if (!surroundCanvases[name]) {
      const node = document.createElement("canvas");
      node.width = w;
      node.height = h;
      surroundCanvases[name] = node;
    }
    return surroundCanvases[name];
  }

  function renderOnboard(world) {
    return renderView(world, 0, pipCanvas, FRONT_W, FRONT_H);
  }

  // The graphics meter (semif-world/perf.js) runs on the coast only; old maps render as before.
  function onCoastMap(view) {
    return !!(view && view.sim && view.sim.world && view.sim.world.type === "coast");
  }

  function renderView(world, yaw, canvas, w = PIP_W, h = PIP_H, vfov = ONBOARD_VFOV) {
    if (!canvas) return false;
    const shot = renderToTarget(world, yaw, w, h, vfov);
    if (!shot) return false;
    const pixels = new Uint8Array(w * h * 4);
    if (shot.renderer.readRenderTargetPixels) {
      shot.renderer.readRenderTargetPixels(shot.target, 0, 0, w, h, pixels);
    }
    paintOnboardPixels(pixels, canvas, w, h);
    return true;
  }

  // One onboard camera rendered into its size's render target, nothing read back yet. Targets are
  // shared per size, so a caller reading asynchronously queues its read before the next render.
  function renderToTarget(world, yaw, w = PIP_W, h = PIP_H, vfov = ONBOARD_VFOV) {
    const player = world && world.sim && world.sim.player;
    const renderer = world && world.renderer;
    const scene = world && world.scene;
    const sample = world && world.sun && world.sun.shadow && world.sun.shadow.map;
    if (!player || !renderer || !scene || !sample || !world.camera) return null;
    const mount = onboardMount(player, yaw);
    if (!world._onboardCam) world._onboardCam = world.camera.clone();
    const cam = world._onboardCam;
    cam.fov = vfov;
    cam.aspect = w / h;
    cam.position.set(mount.x, mount.y, mount.z);
    cam.lookAt(mount.lookX, mount.lookY, mount.lookZ);
    if (cam.updateProjectionMatrix) cam.updateProjectionMatrix();
    if (cam.updateMatrixWorld) cam.updateMatrixWorld();
    // One render target per size: the front camera and the side cameras differ.
    world._onboardTargets = world._onboardTargets || {};
    const key = `${w}x${h}`;
    if (!world._onboardTargets[key]) {
      world._onboardTargets[key] = new sample.constructor(w, h);
    }
    const target = world._onboardTargets[key];
    target.isXRRenderTarget = true;
    if (target.texture) {
      target.texture.colorSpace = renderer.outputColorSpace || "srgb";
      target.texture.internalFormat = "RGBA8";
    }
    // The cameras sit on the body shell, so the ego car itself is never in view; the steering
    // candidates and the sensor cone are the driver's overlays, not part of the world.
    const hidden = [];
    for (const obj of [world.player, world.vectors && world.vectors.group, world.sensorCone]) {
      if (obj && obj.visible !== false) {
        hidden.push(obj);
        obj.visible = false;
      }
    }
    const prev = renderer.getRenderTarget ? renderer.getRenderTarget() : null;
    try {
      renderer.setRenderTarget(target);
      if (onCoastMap(world) && window.SEMIF_PERF) window.SEMIF_PERF.span("onboard", renderer, () => renderer.render(scene, cam));
      else renderer.render(scene, cam);
    } finally {
      if (renderer.setRenderTarget) renderer.setRenderTarget(prev);
      hidden.forEach((obj) => {
        obj.visible = true;
      });
    }
    return { renderer: renderer, target: target };
  }

  function routeEnd(player) {
    const points = player && player.route && player.route.points;
    if (!points || !points.length) return null;
    return points[points.length - 1];
  }

  function lapSnapshot(sim) {
    if (!lapOnce || sim.complete || sim.freeExplore || sim.crash) return null;
    const player = sim.player;
    const end = routeEnd(player);
    if (!player || !end) return null;
    return {
      route: player.route,
      end,
      s: player.s,
      dist: Math.hypot(player.x - end.x, player.z - end.z),
      speed: player.speed,
    };
  }

  function finishLap(sim, before) {
    if (!before || sim.crash) return;
    const player = sim.player;
    if (!player) return;
    const end = routeEnd(player);
    const changed = player.route !== before.route || end !== before.end;
    const dist = Math.hypot(player.x - before.end.x, player.z - before.end.z);
    if (changed && dist < 3 && player.speed < 1) {
      player.route = before.route;
      player.s = before.s;
      player.target = 0;
      player.speed = 0;
      sim.complete = true;
    }
  }

  function tick() {
    const sim = window.SEMIF_SIM;
    const world = window.SEMIF_WORLD;
    try {
      dockStatus();
    } catch (_err) {
      /* layout must not kill the drive loop */
    }
    if (sim) {
      if (sim._fsdBound !== true) {
        sim._fsdBound = true;
        applyRawMode(window.SEMIF_RAW_MODE);
        const orig = sim.step.bind(sim);
        sim.step = function (dt) {
          sim._pdDt = dt;
          try {
            applyLaneKeepReference(sim);
          } catch (_err) {
            /* PD must not kill the drive loop */
          }
          const lapBefore = lapSnapshot(sim);
          let out;
          try {
            out = orig(dt);
          } catch (err) {
            console.warn("semif: sim.step", err);
            return out;
          }
          try {
            finishLap(sim, lapBefore);
          } catch (_err) {
            /* A finished lap must not kill the drive loop */
          }
          try {
            requestEgoReplan(sim, dt);
          } catch (_err) {
            /* replan must not kill the drive loop */
          }
          try {
            fleetTick(sim);
          } catch (_err) {
            /* fleet mode must not kill the drive loop */
          }
          return out;
        };
      }
      const seed = sim.world && sim.world.seed;
      if (seed != null && document.activeElement !== seedInput) seedInput.value = String(seed);
      drawBoxes(sim, world);
    }
    // The PIP is a 15 Hz preview (#42 item 3): a whole-scene render plus a pixel read every display
    // frame cost the drive more than the preview is worth. Vision does not wait for it: on the frames
    // between repaints, a free vision slot grabs at once and paints the front camera itself.
    let painted = false;
    const pipDue = performance.now() >= pipNextAt;
    try {
      if (pipDue) {
        painted = !!renderOnboard(world);
        if (painted) pipNextAt = performance.now() + PIP_PERIOD_MS;
      }
      if (painted && pipFps) pipFps.textContent = pipFpsText(performance.now());
      if (painted) paintCameraView(world, performance.now());
    } catch (_err) {
      /* The onboard view must not kill the drive loop */
    }
    visionTick(); // the pacer decides whether the server can take frames now
    if (window.SEMIF_DRIVE_MODE === "vision") updateSeenSignal();
    wireStrategy();
    try {
      syncCandidates();
    } catch (_err) {
      /* the candidates preference must not kill the drive loop */
    }
    if (++modeFrames % 15 === 0) renderModeHealth();
    requestAnimationFrame(tick);
  }

  requestAnimationFrame(tick);

  function grabFrame() {
    const world = window.SEMIF_WORLD;
    if (!renderOnboard(world) || !pipCanvas) return null;
    return pipCanvas.toDataURL("image/jpeg", FRONT_JPEG);
  }

  window.SEMIF_GRAB_FRAME = grabFrame;

  // JPEGs are encoded in a worker (semif-encode-worker.js); see semif-capture.js.
  let encoder = null;

  // Front, right, rear and left (and the narrow camera in Vision mode). Every view renders now, in
  // one instant of the world, and queues its pixel read on the GPU at once (semif-capture.js); the
  // waiting and the JPEG encoding happen after, off the main thread. The front view is also painted
  // into the PIP canvas, so the preview shows what Vision was sent.
  async function grabSurround() {
    const world = window.SEMIF_WORLD;
    const capture = window.SEMIF_CAPTURE;
    encoder = encoder || capture.createEncoder("/jevpilot/semif-encode-worker.js?v=20261003s1");
    const views = [["front", 0, FRONT_W, FRONT_H, ONBOARD_VFOV, FRONT_JPEG]].concat(
      SURROUND_SIDES.map(([name, yaw]) => [name, yaw, PIP_W, PIP_H, ONBOARD_VFOV, 0.55])
    );
    if (window.SEMIF_DRIVE_MODE === "vision") views.push(["narrow", 0, FRONT_W, FRONT_H, NARROW_VFOV, FRONT_JPEG]);
    const reads = [];
    for (const [name, yaw, w, h, vfov, quality] of views) {
      const shot = renderToTarget(world, yaw, w, h, vfov);
      if (!shot) return null;
      const pixels = capture.readPixels(shot.renderer, shot.target, w, h);
      pixels.catch(() => {}); // awaited below; after a failure the rest are not, and stay quiet
      reads.push({ name, w, h, quality, pixels });
    }
    const frames = {};
    const encodes = [];
    for (const read of reads) {
      const pixels = await read.pixels;
      if (read.name === "front" && pipCanvas) paintOnboardPixels(pixels, pipCanvas, read.w, read.h);
      // The encoder takes the pixels by transfer: nothing may read them after this line.
      encodes.push(encoder.encode(pixels, read.w, read.h, read.quality).then((url) => (frames[read.name] = url)));
      encodes[encodes.length - 1].catch(() => {}); // awaited below, unless a later read fails first
    }
    await Promise.all(encodes);
    return frames;
  }

  async function visionTick() {
    if (!visionOn) {
      visionEl.textContent = "VISION off";
      return;
    }
    // One request at a time (semif-vision-pace.js): frames grabbed while the server is busy are
    // thrown away there, after costing four renders, reads and encodes here.
    if (!visionPacer.tryBegin()) return;
    const ticket = visionPacer.ticket();
    const signal = visionPacer.signal();
    try {
      // The moment of the renders; grab_ms runs to when the frames are encoded (#42 item 2).
      const tGrab = performance.now();
      let frames = null;
      try {
        frames = await grabSurround();
      } catch (_err) {
        visionEl.textContent = "VISION error";
        return;
      }
      const grabMs = performance.now() - tGrab;
      if (!frames) {
        visionEl.textContent = "VISION waiting";
        return;
      }
      try {
        const tVis = performance.now();
        const res = await origFetch("/v1/vision", {
          method: "POST",
          signal: signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ frames: frames, t_ms: tGrab }),
        });
        const data = await res.json();
        const rttMs = performance.now() - tVis;
        if (!res.ok || data.error) {
          visionEl.textContent = "VISION error";
          return;
        }
        if (!data.vision || typeof data.vision !== "object") {
          visionEl.textContent = "VISION waiting";
          return;
        }
        const vis = data.vision;
        const incoming = Number(data.vision_gen);
        const held = Number(window.SEMIF_VISION_GEN);
        if (Number.isFinite(incoming) && Number.isFinite(held) && incoming <= held) {
          return; // older, or the same evidence handed back while the server was busy
        }
        window.SEMIF_VISION = vis;
        // Age counts from when the frames were grabbed, not from when the answer arrived.
        window.SEMIF_VISION_AT = Number.isFinite(Number(vis.captured_ms)) ? Number(vis.captured_ms) : performance.now();
        updateSeenSignal();
        if (Number.isFinite(incoming)) window.SEMIF_VISION_GEN = incoming;
        const encode = Number(data.vision_encode_ms);
        if (telemetry && Number.isFinite(encode)) {
          telemetry.recordVision({
            encode_ms: encode,
            rtt_ms: rttMs,
            grab_ms: grabMs,
          });
          refreshLatencyHud();
        }
        const sig = vis.signal || "unknown";
        visionEl.textContent = vis.event
          ? ["VISION", vis.event].join(" · ")
          : [
              "VISION",
              vis.backend || "stub",
              "sig " + sig,
              "ped " + (vis.pedestrian != null ? Number(vis.pedestrian).toFixed(2) : "—"),
              "veh " + (vis.vehicle != null ? Number(vis.vehicle).toFixed(2) : "—"),
            ].join(" · ");
      } catch (_err) {
        visionEl.textContent = "VISION error";
      }
    } finally {
      visionPacer.end(ticket);
    }
  }

})();
