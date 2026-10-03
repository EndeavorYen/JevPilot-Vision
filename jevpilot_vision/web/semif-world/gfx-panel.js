// The graphics button and its panel (docs/superpowers/specs/2026-10-03-visual-quality-design.md §4.2).
// Switching saves the choice and reloads with ?gfx= rewritten: the two qualities are different
// worlds, and a fresh page is the one rebuild that leaves nothing of the old one behind.
import { QUALITIES, gfx, saveQuality, switchUrl, createSlowWatch } from "./quality.js";
import { chipBar } from "./clock.js";

const TEXT = {
  medium: ["Medium", "Today's world. Integrated laptops."],
  high: ["High", "Refined ground, light, plants and cars. Discrete GPUs."],
};
const NOTE = "Switching reloads the page; autopilot stops. The onboard cameras see the world you pick.";
const SLOW = "High is running slowly here. Medium may be smoother.";
const FPS_KEY = "semif-gfx-fps";

export function describe(quality) {
  return TEXT[quality][1];
}

let button = null;
let panel = null;
let readout = "";
let showFps = false;
let elapsed = 0;
let shownAt = 0;
const slow = createSlowWatch();

function storage() {
  try {
    return globalThis.localStorage ?? null;
  } catch (_) {
    return null;
  }
}

function label() {
  const name = TEXT[gfx.quality || "medium"][0];
  button.textContent = `⚙ ${name}${showFps && readout ? ` · ${readout}` : ""}`;
}

function setOpen(open) {
  panel.hidden = !open;
  button.setAttribute("aria-expanded", String(open));
}

let note = null;
let apply = null;
let radios = [];

function picked() {
  return radios.find((r) => r.checked)?.value || gfx.quality;
}

function refreshApply() {
  const q = picked();
  apply.disabled = q === gfx.quality;
  apply.textContent = q === gfx.quality ? `Using ${TEXT[q][0]}` : `Switch to ${TEXT[q][0]}`;
}

// Only the Apply button switches: browsers fire click on a radio when an arrow key moves the
// selection, so switching on the radio would reload the page while a keyboard user reads options.
function applyPicked() {
  const quality = picked();
  if (quality === gfx.quality) return setOpen(false);
  saveQuality(storage(), quality);
  globalThis.location.assign(switchUrl(globalThis.location.href, quality));
}

// Density (#22): vehicles and people, each low / med / high, in this panel too. Like the quality,
// only its own button applies, and applying saves the choice and reloads with ?traffic=&people=
// rewritten: a fresh page builds the world with the new counts.
const DENSITY_TEXT = { low: "Low", med: "Medium", high: "High" };
const DENSITY_ROWS = [["traffic", "Vehicles"], ["people", "People"]];
let densitySelects = [];
let densityApply = null;

function densityNow() {
  return globalThis.window?.SEMIF_SIM?.world?.density ?? globalThis.SEMIF_WORLDGEN?.density?.() ?? { traffic: "med", people: "med" };
}

export function densityUrl(href, levels) {
  const url = new URL(href);
  for (const [kind] of DENSITY_ROWS) url.searchParams.set(kind, levels[kind]);
  return url.toString();
}

function densityPicked() {
  return Object.fromEntries(densitySelects.map((s) => [s.name, s.value]));
}

function refreshDensity() {
  const now = densityNow();
  const picked = densityPicked();
  const same = DENSITY_ROWS.every(([kind]) => picked[kind] === now[kind]);
  densityApply.disabled = same;
  densityApply.textContent = same ? "Using these" : "Apply (reloads)";
}

function applyDensity() {
  const picked = densityPicked();
  if (DENSITY_ROWS.every(([kind]) => picked[kind] === densityNow()[kind])) return setOpen(false);
  const keys = globalThis.SEMIF_WORLDGEN?.DENSITY_KEY ?? { traffic: "semif.density.traffic", people: "semif.density.people" };
  try {
    for (const [kind] of DENSITY_ROWS) storage()?.setItem(keys[kind], picked[kind]);
  } catch (_) {}
  globalThis.location.assign(densityUrl(globalThis.location.href, picked));
}

function buildDensity() {
  const section = el("div", "semif-density");
  section.appendChild(el("h2", "", "Traffic"));
  const now = densityNow();
  densitySelects = DENSITY_ROWS.map(([kind, name]) => {
    const row = el("label", "semif-density-row");
    row.appendChild(el("span", "", name));
    const select = el("select", "semif-density-select");
    select.name = kind;
    for (const level of ["low", "med", "high"]) {
      const option = el("option", "", DENSITY_TEXT[level]);
      option.value = level;
      select.appendChild(option);
    }
    select.value = now[kind];
    select.addEventListener("change", refreshDensity);
    row.appendChild(select);
    section.appendChild(row);
    return select;
  });
  densityApply = el("button", "semif-density-apply");
  densityApply.type = "button";
  densityApply.addEventListener("click", applyDensity);
  section.appendChild(densityApply);
  refreshDensity();
  return section;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function buildPanel() {
  panel = el("div", "semif-gfx-panel");
  panel.id = "semif-gfx-panel";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Graphics");
  panel.appendChild(el("h2", "", "Graphics"));
  const group = el("div", "semif-gfx-options");
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-label", "Quality");
  radios = QUALITIES.map((q) => {
    const row = el("label", "semif-gfx-option");
    const input = el("input");
    input.type = "radio";
    input.name = "semif-gfx";
    input.value = q;
    input.checked = q === gfx.quality;
    input.addEventListener("change", refreshApply);
    const words = el("span");
    words.appendChild(el("b", "", TEXT[q][0]));
    words.appendChild(el("small", "", TEXT[q][1]));
    row.appendChild(input);
    row.appendChild(words);
    group.appendChild(row);
    return input;
  });
  panel.appendChild(group);
  apply = el("button", "semif-gfx-apply");
  apply.type = "button";
  apply.addEventListener("click", applyPicked);
  panel.appendChild(apply);
  const fpsRow = el("label", "semif-gfx-fps");
  const fps = el("input");
  fps.type = "checkbox";
  fps.checked = showFps;
  fps.addEventListener("change", (e) => {
    showFps = e.target.checked;
    try {
      storage()?.setItem(FPS_KEY, showFps ? "1" : "0");
    } catch (_) {}
    label();
  });
  fpsRow.appendChild(fps);
  fpsRow.appendChild(el("span", "", "Show FPS"));
  panel.appendChild(fpsRow);
  panel.appendChild(buildDensity());
  note = el("p", "semif-gfx-note", NOTE);
  note.setAttribute("role", "status");
  panel.appendChild(note);
  panel.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      setOpen(false);
      button.focus();
    }
  });
  document.addEventListener("pointerdown", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && e.target !== button) setOpen(false);
  });
  refreshApply();
  chipBar().appendChild(panel); // opens under its button, wherever the layout puts the bar
}

export function mountGfx() {
  if (button || !globalThis.document?.body) return;
  try {
    showFps = storage()?.getItem(FPS_KEY) === "1";
  } catch (_) {}
  button = document.createElement("button");
  button.type = "button";
  button.className = "semif-gfx";
  button.title = "Graphics quality";
  button.setAttribute("aria-haspopup", "dialog");
  button.setAttribute("aria-controls", "semif-gfx-panel");
  button.setAttribute("aria-expanded", "false");
  const bar = chipBar();
  bar.insertBefore(button, bar.firstChild);
  buildPanel();
  button.addEventListener("click", () => {
    const open = panel.hidden;
    setOpen(open);
    if (open) (radios.find((r) => r.checked) || radios[0])?.focus();
  });
  label();
}

export function showGfx(visible) {
  if (button) button.style.display = visible ? "" : "none";
  if (!visible && panel) setOpen(false);
}

// Every frame on the coast: the FPS readout twice a second, and one hint when high is too slow.
export function gfxTick(dt) {
  if (!button) return;
  elapsed += dt;
  if (elapsed - shownAt < 0.5) return;
  shownAt = elapsed;
  const s = globalThis.window?.SEMIF_PERF?.snapshot();
  const fps = s?.fps_p50;
  if (!fps) return;
  const gpu = s.gpu_ms_p50?.main;
  readout = `${Math.round(fps)} fps${gpu != null ? ` · ${gpu.toFixed(1)} ms` : ""}`;
  label();
  if (gfx.quality === "high" && slow.push(fps, elapsed)) {
    note.textContent = SLOW;
    setOpen(true);
  }
}
