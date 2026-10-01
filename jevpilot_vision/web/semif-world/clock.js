// The coast's clock and its HUD chip. ?time=HH:MM fixes the hour; ?daycycle=0 stops the clock at
// late afternoon; T (or a click on the chip) jumps to the next part of the day.
import { DAY, PRESETS, advance, format, parseTime } from "./daylight.js";

const params = new URLSearchParams(globalThis.location?.search || "");
const fixed = parseTime(params.get("time"));

export const clock = {
  hours: fixed ?? DAY.default,
  running: fixed === null && params.get("daycycle") !== "0",
};

let chip = null;

function period(hours) {
  if (hours < 8) return "Dawn";
  if (hours < 11) return "Morning";
  if (hours < 15) return "Midday";
  if (hours < 18.75) return "Golden hour";
  return "Dusk";
}

function nextPreset() {
  const next = PRESETS.find(([, h]) => h > clock.hours + 0.05) || PRESETS[0];
  clock.hours = next[1];
  render();
}

function render() {
  if (chip) chip.textContent = `☀ ${format(clock.hours)} · ${period(clock.hours)}`;
}

export function mountClock() {
  if (chip || !globalThis.document?.body) return;
  chip = document.createElement("button");
  chip.className = "semif-clock";
  chip.title = "Time of day · T";
  Object.assign(chip.style, {
    position: "fixed", top: "14px", left: "50%", transform: "translateX(-50%)", zIndex: "20",
    padding: "6px 14px", borderRadius: "999px", border: "1px solid rgba(255,255,255,0.14)",
    background: "rgba(16,20,28,0.72)", color: "rgba(241,245,249,0.95)", font: "600 13px system-ui, sans-serif",
    letterSpacing: "0.02em", cursor: "pointer", backdropFilter: "blur(6px)",
  });
  chip.addEventListener("click", nextPreset);
  document.body.appendChild(chip);
  document.addEventListener("keydown", (e) => {
    if ((e.key === "t" || e.key === "T") && !e.ctrlKey && !e.metaKey && !/input|select|textarea/i.test(e.target?.tagName || "")) nextPreset();
  });
  render();
}

export function showClock(visible) {
  if (chip) chip.style.display = visible ? "" : "none";
}

// Advance by real seconds; the HUD only changes when the minute does.
export function tick(seconds) {
  if (!clock.running) return;
  const before = format(clock.hours);
  clock.hours = advance(clock.hours, Math.min(seconds, 0.25));
  if (format(clock.hours) !== before) render();
}
