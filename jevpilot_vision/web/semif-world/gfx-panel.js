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

function choose(quality) {
  if (quality === gfx.quality) return setOpen(false);
  saveQuality(storage(), quality);
  globalThis.location.assign(switchUrl(globalThis.location.href, quality));
}

function buildPanel() {
  panel = document.createElement("div");
  panel.className = "semif-gfx-panel";
  panel.id = "semif-gfx-panel";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Graphics");
  const options = QUALITIES.map(
    (q) => `<label class="semif-gfx-option"><input type="radio" name="semif-gfx" value="${q}"${q === gfx.quality ? " checked" : ""}>` +
      `<span><b>${TEXT[q][0]}</b><small>${TEXT[q][1]}</small></span></label>`,
  ).join("");
  panel.innerHTML =
    `<h2>Graphics</h2><div role="radiogroup" aria-label="Quality">${options}</div>` +
    `<label class="semif-gfx-fps"><input type="checkbox"${showFps ? " checked" : ""}> Show FPS</label>` +
    `<p class="semif-gfx-note" role="status">${NOTE}</p>`;
  // Arrow keys move between the options without switching (no change event fires for a
  // checked radio); a click, Space or Enter on an option switches.
  panel.querySelectorAll('input[type="radio"]').forEach((input) => {
    input.addEventListener("click", () => choose(input.value));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") choose(input.value);
    });
  });
  panel.querySelector(".semif-gfx-fps input").addEventListener("change", (e) => {
    showFps = e.target.checked;
    try {
      storage()?.setItem(FPS_KEY, showFps ? "1" : "0");
    } catch (_) {}
    label();
  });
  panel.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      setOpen(false);
      button.focus();
    }
  });
  document.addEventListener("pointerdown", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && e.target !== button) setOpen(false);
  });
  document.body.appendChild(panel);
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
    if (open) panel.querySelector("input:checked")?.focus();
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
    panel.querySelector(".semif-gfx-note").textContent = SLOW;
    setOpen(true);
  }
}
