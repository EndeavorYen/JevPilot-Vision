// The coast's day: a clock from dawn to dusk, where the sun stands, and the light it gives.
//
// Plain functions of the hour (tests/test_daylight.py runs them in node). The onboard camera reads
// signals, construction, warning lights and people by colour, and its masks were tuned in
// daylight, so `tint` (what the light does to a surface's colour, after exposure) stays within
// a few percent of noon's brightness and never turns a palette colour into a mask colour.

export const DAY = {
  start: 6.25, // 06:15, the sun just up in the east
  end: 19.75, // 19:45, the sun low in the west; no night
  default: 16.5, // the coast opens in late-afternoon light
  cycleSeconds: 900, // dawn to dusk in fifteen minutes
};

export const PRESETS = [
  ["Dawn", 6.75],
  ["Morning", 9.5],
  ["Noon", 13],
  ["Golden hour", 17.75],
  ["Dusk", 19.25],
];

const MAX_ELEVATION = 62; // degrees, at 13:00
const DAYLIGHT_HOURS = 14; // the sun's arc runs 06:00 to 20:00

const rad = (d) => (d * Math.PI) / 180;

// Hours as a number from "HH:MM", or null.
export function parseTime(text) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(text ?? ""));
  if (!m) return null;
  const h = Number(m[1]) + Number(m[2]) / 60;
  return Number(m[1]) < 24 && Number(m[2]) < 60 ? h : null;
}

// The clock `seconds` later, looping from dusk back to dawn.
export function advance(hours, seconds) {
  const span = DAY.end - DAY.start;
  const t = hours - DAY.start + (seconds * span) / DAY.cycleSeconds;
  return DAY.start + (((t % span) + span) % span);
}

export function format(hours) {
  const m = Math.round(hours * 60);
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

function elevation(hours) {
  return MAX_ELEVATION * Math.sin((Math.PI * (hours - 6)) / DAYLIGHT_HOURS);
}

// Unit vector towards the sun, y up. Heading as the bundle: 90 degrees is east (+x), 180 is south
// (+z, over the sea).
export function sunDirection(hours) {
  const az = rad(90 + (180 * (hours - 6)) / DAYLIGHT_HOURS);
  const el = rad(elevation(hours));
  return { x: Math.sin(az) * Math.cos(el), y: Math.sin(el), z: -Math.cos(az) * Math.cos(el) };
}

// Light keyed by the sun's elevation in degrees, interpolated in between.
const KEYS = [2, 8, 20, 45];
const LIGHT = {
  sun: ["#ffb48c", "#ffbf8f", "#ffd9ad", "#fff6ea"],
  sunIntensity: [3.4, 3.4, 3.4, 3.4],
  zenith: ["#5f78ab", "#5c88bf", "#4f87c7", "#4380c8"],
  horizon: ["#f2c6b0", "#f1d6bf", "#dfe5e8", "#d3e1ea"],
  glow: ["#ffd0b4", "#ffdfbf", "#fff0dc", "#fff8ee"],
  fog: ["#d8c4b8", "#dbcfc4", "#cfdae0", "#c6d5df"],
  hemiSky: ["#d2b8b6", "#d0c0bc", "#c6cfdc", "#c9daef"],
  hemiGround: ["#5f544c", "#615a50", "#5c5b4f", "#585c4e"],
  hemiIntensity: [1.25, 1.0, 0.7, 0.55],
  envIntensity: [0.35, 0.45, 0.55, 0.6],
};

const rgb = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const hex = (c) => `#${c.map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0")).join("")}`;

function keyed(values, el) {
  const e = Math.min(Math.max(el, KEYS[0]), KEYS.at(-1));
  let i = 0;
  while (i < KEYS.length - 2 && e > KEYS[i + 1]) i++;
  const t = (e - KEYS[i]) / (KEYS[i + 1] - KEYS[i]);
  const a = values[i], b = values[i + 1];
  if (typeof a === "number") return a + (b - a) * t;
  return hex(rgb(a).map((v, k) => v + (rgb(b)[k] - v) * t));
}

// Direct sun on the ground and on walls, plus sky light, per channel (0..255 scale).
function rawLight(hours) {
  const el = elevation(hours);
  const sun = rgb(keyed(LIGHT.sun, el)).map((v) => v * keyed(LIGHT.sunIntensity, el) * Math.max(Math.sin(rad(el)), 0.3));
  const sky = rgb(keyed(LIGHT.hemiSky, el)).map((v) => v * keyed(LIGHT.hemiIntensity, el) * 1.6);
  return sun.map((v, k) => v + sky[k]);
}

const luma = (c) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
const NOON = rawLight(13);
const NOON_EXPOSURE = 0.95;

export function lightAt(hours) {
  const el = elevation(hours);
  const raw = rawLight(hours);
  // Exposure brings dawn and dusk back to noon's brightness, as an eye (or a game camera) would.
  const exposure = NOON_EXPOSURE * Math.min(1.8, luma(NOON) / luma(raw));
  const out = { elevation: el, exposure };
  for (const [key, values] of Object.entries(LIGHT)) out[key] = keyed(values, el);
  return out;
}

// What the light does to a surface colour relative to noon, per channel, after exposure.
export function tint(hours) {
  const raw = rawLight(hours);
  const k = lightAt(hours).exposure / NOON_EXPOSURE;
  return raw.map((v, i) => (v / NOON[i]) * k);
}
