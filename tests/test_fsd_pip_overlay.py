"""FSD picture-in-picture frame view (#115).

The node harness loads jevpilot_vision/web/semif-layer.js and calls the animation
callback that script registers. That is the painter the page runs each frame.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OVERLAY_JS = REPO / "jevpilot_vision" / "web" / "semif-layer.js"
OVERLAY_CSS = REPO / "jevpilot_vision" / "web" / "semif-layer.css"

PIP_W = 320
PIP_H = 180
TITLE = "CAMERA: onboard"


def _perspective(fov_deg: float, aspect: float, near: float, far: float) -> list[float]:
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    m = [0.0] * 16
    m[0] = f / aspect
    m[5] = f
    m[10] = (far + near) / (near - far)
    m[11] = -1.0
    m[14] = (2.0 * far * near) / (near - far)
    return m


def _view_at(x: float, y: float, z: float) -> list[float]:
    """Camera at (x, y, z), looking down -Z. Column-major matrixWorldInverse."""
    m = [0.0] * 16
    m[0] = m[5] = m[10] = m[15] = 1.0
    m[12] = -x
    m[13] = -y
    m[14] = -z
    return m


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeCtx(canvas) {
  const ops = [];
  let fillStyle = "";
  let strokeStyle = "";
  const ctx = {
    ops,
    canvas,
    save() { ops.push({ op: "save" }); },
    restore() { ops.push({ op: "restore" }); },
    beginPath() { ops.push({ op: "beginPath" }); },
    closePath() { ops.push({ op: "closePath" }); },
    moveTo(x, y) { ops.push({ op: "moveTo", x, y }); },
    lineTo(x, y) { ops.push({ op: "lineTo", x, y }); },
    arc(x, y, r) { ops.push({ op: "arc", x, y, r, strokeStyle, fillStyle }); },
    fill() { ops.push({ op: "fill", fillStyle }); },
    stroke() { ops.push({ op: "stroke", strokeStyle }); },
    clearRect() { ops.push({ op: "clearRect" }); },
    setTransform() {},
    strokeRect(x, y, w, h) { ops.push({ op: "strokeRect", x, y, w, h, strokeStyle }); },
    fillRect(x, y, w, h) { ops.push({ op: "fillRect", x, y, w, h, fillStyle }); },
    fillText(text, x, y) { ops.push({ op: "fillText", text: String(text), x, y, fillStyle }); },
    createImageData(w, h) { return { data: new Uint8ClampedArray(w * h * 4), width: w, height: h }; },
    putImageData() { ops.push({ op: "putImageData" }); },
    drawImage(src, dx, dy, dw, dh) { ops.push({ op: "drawImage", dx, dy, dw, dh }); },
    setLineWidth() {},
    measureText(text) { return { width: String(text).length * 6 }; },
  };
  Object.defineProperty(ctx, "fillStyle", {
    get() { return fillStyle; },
    set(v) { fillStyle = String(v); },
  });
  Object.defineProperty(ctx, "strokeStyle", {
    get() { return strokeStyle; },
    set(v) { strokeStyle = String(v); },
  });
  Object.defineProperty(ctx, "font", { get() { return ""; }, set() {} });
  Object.defineProperty(ctx, "textAlign", { get() { return "left"; }, set() {} });
  Object.defineProperty(ctx, "textBaseline", { get() { return "alphabetic"; }, set() {} });
  Object.defineProperty(ctx, "lineWidth", { get() { return 1; }, set() {} });
  canvas.getContext = () => ctx;
  canvas.__ctx = ctx;
  return ctx;
}

function el(tag) {
  const node = {
    tagName: String(tag || "div").toUpperCase(),
    id: "",
    className: "",
    dataset: {},
    children: [],
    parentElement: null,
    style: {},
    listeners: {},
    textContent: "",
    value: "",
    width: 300,
    height: 150,
    clientWidth: 640,
    clientHeight: 480,
    hidden: false,
  };
  const classes = new Set();
  node.classList = {
    add(...names) { names.forEach((n) => classes.add(n)); node.className = [...classes].join(" "); },
    remove(...names) { names.forEach((n) => classes.delete(n)); node.className = [...classes].join(" "); },
    contains(n) { return classes.has(n); },
    toggle(n, force) {
      const on = force === undefined ? !classes.has(n) : !!force;
      on ? classes.add(n) : classes.delete(n);
      node.className = [...classes].join(" ");
      return on;
    },
  };
  const attrs = {};
  node.setAttribute = (name, value) => { attrs[name] = String(value); };
  node.getAttribute = (name) => (name in attrs ? attrs[name] : null);
  node.appendChild = (child) => {
    node.children.push(child);
    child.parentElement = node;
    return child;
  };
  node.addEventListener = (type, fn) => {
    (node.listeners[type] || (node.listeners[type] = [])).push(fn);
  };
  node.dispatchEvent = (ev) => {
    const e = ev || {};
    e.target = e.target || node;
    e.preventDefault = e.preventDefault || function () {};
    e.stopPropagation = e.stopPropagation || function () { e.__stopped = true; };
    (node.listeners[e.type] || []).forEach((fn) => fn(e));
    if (node.parentElement && node.parentElement.dispatchEvent && e.bubbles && !e.__stopped) {
      node.parentElement.dispatchEvent(e);
    }
  };
  node.contains = (other) => {
    if (other === node) return true;
    return node.children.some((child) => child.contains && child.contains(other));
  };
  node.click = () => node.dispatchEvent({ type: "click", target: node, bubbles: true });
  node.toDataURL = () => "data:image/jpeg;base64,AAAA";
  Object.defineProperty(node, "innerHTML", {
    get() { return node._html || ""; },
    set(html) {
      node._html = String(html);
      node.children = [];
      parseInto(node, node._html);
    },
  });
  makeCtx(node);
  return node;
}

function parseInto(parent, html) {
  const tagRe = /<\/?([a-zA-Z0-9]+)([^>]*)>/g;
  const stack = [parent];
  let match;
  while ((match = tagRe.exec(html))) {
    const raw = match[0];
    const closing = raw[1] === "/";
    const tag = match[1].toLowerCase();
    const attrs = match[2] || "";
    const self = /\/$/.test(attrs) || raw.endsWith("/>");
    if (closing) {
      const node = stack[stack.length - 1];
      if (stack.length > 1 && node.tagName === tag.toUpperCase()) {
        if (!node.children.length) {
          node.textContent = html.slice(node._htmlStart, match.index).replace(/<[^>]+>/g, "").trim();
        }
        stack.pop();
      }
      continue;
    }
    const node = el(tag);
    const id = /id="([^"]*)"/.exec(attrs);
    const cls = /class="([^"]*)"/.exec(attrs);
    const w = /width="(\d+)"/.exec(attrs);
    const h = /height="(\d+)"/.exec(attrs);
    if (id) node.id = id[1];
    if (cls) cls[1].split(/\s+/).filter(Boolean).forEach((name) => node.classList.add(name));
    if (w) node.width = Number(w[1]);
    if (h) node.height = Number(h[1]);
    node._htmlStart = tagRe.lastIndex;
    stack[stack.length - 1].appendChild(node);
    if (!self) stack.push(node);
  }
}

function walk(node, visit) {
  visit(node);
  (node.children || []).forEach((child) => walk(child, visit));
}

const document = el("document");
document.documentElement = el("html");
document.body = el("body");
document.appendChild(document.documentElement);
document.documentElement.appendChild(document.body);
document.createElement = (tag) => el(tag);
document.getElementById = (id) => {
  let found = null;
  walk(document, (node) => {
    if (!found && node.id === id) found = node;
  });
  return found;
};
document.querySelector = (sel) => {
  let found = null;
  walk(document, (node) => {
    if (found || !node.tagName) return;
    if (sel === "dialog[open]" && node.tagName === "DIALOG" && node.open) found = node;
    else if (sel[0] === "#" && node.id === sel.slice(1)) found = node;
    else if (sel[0] === "." && node.classList && node.classList.contains(sel.slice(1))) found = node;
  });
  return found;
};

const specEarly = JSON.parse(process.argv[3]);
let search = specEarly.vision === "1" ? "" : "?vision=0";
if (specEarly.lap === "1") search += (search ? "&" : "?") + "lap=1";
if (specEarly.fleet) search += (search ? "&" : "?") + "fleet=" + specEarly.fleet;
if (specEarly.mode) search += (search ? "&" : "?") + "mode=" + specEarly.mode;
if (specEarly.lag) search += (search ? "&" : "?") + "lag_ms=" + specEarly.lag;
if (specEarly.candidates) search += (search ? "&" : "?") + "candidates=" + specEarly.candidates;
if (specEarly.minimal) search += (search ? "&" : "?") + "minimal=" + specEarly.minimal;
// Latency stress (#28): timers the overlay sets, and when the decision request really goes out.
const timers = [];
const sentAt = [];
if (specEarly.cmd === "lag") {
  global.setTimeout = (fn, ms) => { timers.push(ms); fn(); return timers.length; };
}
const location = { search };
let nowMs = 0;
const window = global;
window.window = window;
window.document = document;
window.location = location;
window.performance = { now: () => nowMs };
window.requestAnimationFrame = (fn) => {
  window.__raf = fn;
  return 1;
};
window.cancelAnimationFrame = () => {};
const visionPosts = [];
const visionBodies = [];
const surroundLooks = [];
const visionIntervals = [];
window.fetch = function () {
  return Promise.resolve({ ok: false, json: async () => ({}) });
};
if (specEarly.cmd === "upload" || specEarly.cmd === "vision-ack" || specEarly.cmd === "vision-order") {
  global.setInterval = (fn, ms) => {
    visionIntervals.push(ms);
    return visionIntervals.length;
  };
  global.setTimeout = () => 1;
}
if (specEarly.cmd === "vision-ack") {
  window.SEMIF_TELEMETRY_CORE = {
    createLatencyTelemetry() {
      const api = {
        records: [],
        recordVision(row) { api.records.push(row); },
        hudText() { return "hud"; },
      };
      return api;
    },
  };
  const replies = specEarly.replies || [{}];
  let replyAt = 0;
  window.fetch = function (url) {
    const href = typeof url === "string" ? url : "";
    const body = replies[Math.min(replyAt, replies.length - 1)];
    if (href.indexOf("/v1/vision") !== -1) replyAt += 1;
    return Promise.resolve({ ok: true, json: async () => body });
  };
}
if (specEarly.cmd === "vision-order") {
  const pending = [];
  window.__releaseVision = (index, body) => {
    const resolve = pending[index];
    if (resolve) resolve({ ok: true, json: async () => body });
  };
  window.fetch = function (url) {
    const href = typeof url === "string" ? url : "";
    if (href.indexOf("/v1/vision") === -1) {
      return Promise.resolve({ ok: false, json: async () => ({}) });
    }
    return new Promise((resolve) => { pending.push(resolve); });
  };
}
if (specEarly.cmd === "upload") {
  window.fetch = function (url) {
    const href = typeof url === "string" ? url : "";
    if (href.indexOf("/v1/vision") !== -1) {
      visionPosts.push(nowMs);
      const sent = JSON.parse((arguments[1] && arguments[1].body) || "{}");
      visionBodies.push({
        keys: Object.keys(sent),
        frames: sent.frames ? Object.keys(sent.frames) : [],
        front: sent.frames ? sent.frames.front : null,
      });
    }
    return Promise.resolve({
      ok: true,
      json: async () => ({ vision: { signal: "green" }, vision_encode_ms: 3 }),
    });
  };
}
const fleetBodies = [];
if (specEarly.cmd === "fleet") {
  window.fetch = function (url, opts) {
    const href = typeof url === "string" ? url : "";
    if (href.indexOf("/v1/fleet") === -1) {
      return Promise.resolve({ ok: false, json: async () => ({}) });
    }
    const sent = JSON.parse((opts && opts.body) || "{}");
    fleetBodies.push(sent);
    const decisions = {};
    for (const agent of sent.agents || []) {
      decisions[agent.id] = { target_speed_mps: 3.5, choice: "t01" };
    }
    return Promise.resolve({ ok: true, json: async () => ({ policy: sent.policy, decisions }) });
  };
}
// Classifier replies in order: ok JSON, an HTTP 500 error page, a network failure, ok JSON that
// is not JSON (#28: the evaluation counts request failures from the page, not from event text).
if (specEarly.cmd === "cstats") {
  const replies = [
    () => Promise.resolve({ ok: true, status: 200, statusText: "OK", json: async () => ({ answers: {} }), text: async () => "{}" }),
    () => Promise.resolve({ ok: false, status: 500, statusText: "Internal Server Error",
      json: async () => { throw new SyntaxError("Unexpected token 'I'"); }, text: async () => "Internal Server Error" }),
    () => Promise.reject(new TypeError("Failed to fetch")),
    () => Promise.resolve({ ok: true, status: 200, statusText: "OK",
      json: async () => { throw new SyntaxError("bad"); }, text: async () => "<html>" }),
    () => Promise.resolve({ ok: false, status: 503, statusText: "Service Unavailable",
      json: async () => ({}), text: async () => "{}" }),
    () => Promise.reject(Object.assign(new Error("signal timed out"), { name: "TimeoutError" })),
  ];
  let at = 0;
  window.fetch = () => replies[Math.min(at++, replies.length - 1)]();
  global.Response = class { constructor(body, init) { this.body = body; this.status = init && init.status; this.ok = this.status >= 200 && this.status < 300; } };
}
window.URL = { createObjectURL: () => "blob:pip", revokeObjectURL() {} };
// Per-browser storage and the address bar, for the driving-mode preference (#21).
const stored = Object.assign({}, specEarly.storage || {});
window.localStorage = {
  getItem: (k) => (k in stored ? stored[k] : null),
  setItem: (k, v) => { stored[k] = String(v); },
  removeItem: (k) => { delete stored[k]; },
};
const urls = [];
window.history = { state: null, replaceState: (_s, _t, url) => { urls.push(String(url)); } };
location.pathname = "/jevpilot/";
// The bundle's strategy dropdown (semif / heuristic), as mounted before the overlay runs.
const strategyChanges = [];
if (specEarly.cmd === "mode") {
  const select = el("select");
  select.id = "strategy-select";
  select.value = specEarly.strategy || "semif";
  select.addEventListener("change", () => strategyChanges.push(select.value));
  document.body.appendChild(select);
}
global.document = document;
global.location = location;
global.performance = window.performance;
global.requestAnimationFrame = window.requestAnimationFrame;
global.cancelAnimationFrame = window.cancelAnimationFrame;

// The page loads semif-capture.js before the layer (index.html); so does the harness.
window.SEMIF_CAPTURE = require(require("path").join(require("path").dirname(process.argv[1]), "semif-capture.js"));
const code = fs.readFileSync(process.argv[1], "utf8");
vm.runInThisContext(code, { filename: process.argv[1] });

const pip = document.getElementById("fsd-pip");
const canvas = document.getElementById("fsd-camera-canvas");
const title = document.querySelector(".fsd-pip-title");
const header = document.querySelector(".fsd-pip-header");
const fps = document.getElementById("fsd-pip-fps");
const api = window.SEMIF_PIP || {};

function camera(w, h) {
  return {
    matrixWorldInverse: { elements: JSON.parse(process.argv[2]) },
    projectionMatrix: { elements: _perspectiveElements(w, h) },
  };
}

function plainOps(ops) {
  return ops.map((op) => {
    const copy = {};
    for (const key of Object.keys(op)) copy[key] = key === "src" ? true : op[key];
    return copy;
  });
}

function boot(sim, world) {
  window.SEMIF_SIM = sim;
  window.SEMIF_WORLD = world;
  canvas.__ctx.ops.length = 0;
  window.__raf();
  return plainOps(canvas.__ctx.ops);
}

const spec = specEarly;
const view = JSON.parse(process.argv[2]);
const out = { title: title && title.textContent, fps0: fps && fps.textContent, canvas: canvas && { w: canvas.width, h: canvas.height }, hasPip: !!pip };

if (spec.cmd === "cstats") {
  (async () => {
    const outcomes = [];
    for (let i = 0; i < 6; i++) {
      try {
        const res = await window.fetch("/v1/classifier", { method: "POST", body: JSON.stringify({ mode: "flat", state: {} }) });
        outcomes.push(res.status);
      } catch (err) {
        outcomes.push("threw");
      }
    }
    process.stdout.write(JSON.stringify({ outcomes, stats: window.SEMIF_CLASSIFIER_STATS }));
  })();
} else if (spec.cmd === "lag") {
  (async () => {
    await window.fetch("/v1/classifier", { method: "POST", body: JSON.stringify({ mode: "flat", state: {} }) });
    process.stdout.write(JSON.stringify({ timers, lag: window.SEMIF_LAG_MS }));
  })();
} else if (spec.cmd === "mode") {
  const DRIVE_MODES_T = ["vision", "vision-map", "privileged", "heuristic"];
  const shape = () => {
    const body = window.SEMIF_SHAPE_DECISION({ mode: "flat", state: { candidates: {} } });
    return { drive_mode: body.drive_mode || null, mode: body.mode, vision_stage: body.vision_stage ?? null };
  };
  const pick = (m) => document.getElementById("sol-mode-" + m).click();
  const strategy = document.getElementById("strategy-select");
  const reads = () => document.getElementById("sol-mode-reads").textContent;
  const steps = [{ at: "load", mode: window.SEMIF_DRIVE_MODE, id: window.SEMIF_MODE_ID, shaped: shape(), reads: reads(), select: strategy.value }];
  for (const m of ["vision-map", "vision", "heuristic", "privileged"]) {
    pick(m);
    steps.push({ at: "click " + m, mode: window.SEMIF_DRIVE_MODE, id: window.SEMIF_MODE_ID, shaped: shape(), reads: reads(), select: strategy.value,
      checked: document.getElementById("sol-mode-" + m).getAttribute("aria-checked"),
      intent: document.getElementById("fsd-intent").textContent });
  }
  strategy.value = "heuristic";
  strategy.dispatchEvent({ type: "change", bubbles: true });
  steps.push({ at: "select heuristic", mode: window.SEMIF_DRIVE_MODE, shaped: shape() });
  strategy.value = "semif";
  strategy.dispatchEvent({ type: "change", bubbles: true });
  steps.push({ at: "select semif", mode: window.SEMIF_DRIVE_MODE, shaped: shape() });
  // The bundle's own shortcuts (1, 2, 3) and buttons set the dropdown without a change event.
  strategy.value = "heuristic";
  window.__raf();
  steps.push({ at: "bundle sets heuristic", mode: window.SEMIF_DRIVE_MODE });
  strategy.value = "semif";
  window.__raf();
  steps.push({ at: "bundle sets semif", mode: window.SEMIF_DRIVE_MODE });
  const pipHidden = () => document.getElementById("fsd-pip").classList.contains("fsd-pip-hidden");
  const pipBefore = pipHidden();
  document.body.dispatchEvent({ type: "keydown", code: "KeyM", key: "m", bubbles: true });
  steps.push({ at: "key M", mode: window.SEMIF_DRIVE_MODE, pipToggled: pipHidden() !== pipBefore });
  const dialog = el("dialog");
  dialog.open = true;
  document.body.appendChild(dialog);
  document.body.dispatchEvent({ type: "keydown", code: "KeyM", key: "m", bubbles: true });
  steps.push({ at: "key M with a dialog open", mode: window.SEMIF_DRIVE_MODE });
  // Arrow keys on the switch: they move the mode and stop there (the bundle steers on arrows).
  const bundleKeys = [];
  document.addEventListener("keydown", (ev) => bundleKeys.push(ev.key));
  dialog.open = false;
  const radio = document.getElementById("sol-mode-" + window.SEMIF_MODE_ID);
  const before = window.SEMIF_MODE_ID;
  radio.dispatchEvent({ type: "keydown", key: "ArrowRight", code: "ArrowRight", bubbles: true });
  steps.push({ at: "arrow right on the switch", from: before, mode: window.SEMIF_MODE_ID, reachedBundle: bundleKeys.slice(),
    tabindex: DRIVE_MODES_T.map((m) => document.getElementById("sol-mode-" + m).getAttribute("tabindex")) });
  const live = document.getElementById("sol-mode-announce");
  const healthEl = document.getElementById("sol-mode-health");
  steps.push({ at: "live regions", announce: live && live.getAttribute("aria-live"), health: healthEl.getAttribute("aria-live") });
  // What the live region says as stale evidence ages, then when the detector fails.
  window.SEMIF_MODE.set("vision");
  window.SEMIF_VISION = { backend: "stub", perception: { backend: "PekingU/rtdetr_r50vd", status: "ready" } };
  window.SEMIF_VISION_AT = nowMs - 2100;
  window.SEMIF_MODE.refresh();
  const said = [document.getElementById("sol-mode-announce").textContent];
  nowMs += 300;
  window.SEMIF_MODE.refresh();
  said.push(document.getElementById("sol-mode-announce").textContent);
  window.SEMIF_VISION = { backend: "stub", perception: { backend: "none", status: "failed" } };
  window.SEMIF_MODE.refresh();
  said.push(document.getElementById("sol-mode-announce").textContent);
  steps.push({ at: "announcements", said });
  // #78 review: Vision (map) speaks its own name, and comes back after a trip through Heuristic.
  window.SEMIF_MODE.set("vision-map");
  window.SEMIF_MODE.refresh();
  const mapSaid = document.getElementById("sol-mode-announce").textContent;
  strategy.value = "heuristic";
  strategy.dispatchEvent({ type: "change", bubbles: true });
  const viaHeuristic = window.SEMIF_MODE_ID;
  strategy.value = "semif";
  strategy.dispatchEvent({ type: "change", bubbles: true });
  steps.push({ at: "vision-map round trip", mapSaid, viaHeuristic, mode: window.SEMIF_MODE_ID, drive: window.SEMIF_DRIVE_MODE,
    stage: window.SEMIF_VISION_STAGE });
  const h = window.SEMIF_MODE.health;
  const ready = { backend: "PekingU/rtdetr_r50vd", status: "ready" };
  const health = {
    ok: h({ backend: "google/siglip-base-patch16-224", perception: ready }, 400),
    stub: h({ backend: "stub", perception: ready }, 400),
    loading: h({ backend: "stub", perception: { backend: "none", status: "loading" } }, 400),
    failed: h({ backend: "stub", perception: { backend: "none", status: "failed" } }, 400),
    stale: h({ backend: "stub", perception: ready }, 2100),
    nullStatus: h({ backend: "stub", perception: { backend: "PekingU/rtdetr_r50vd", status: null } }, 400),
    noStatus: h({ backend: "stub", perception: { backend: "PekingU/rtdetr_r50vd" } }, 400),
    none: h(null, null),
    future: h({ backend: "stub", perception: ready }, -300),
    notObject: h({ backend: "stub", perception: "failed" }, 400),
  };
  process.stdout.write(JSON.stringify({ steps, stored, urls, strategyChanges, health }));
} else if (spec.cmd === "shape") {
  // The planner's batch: two candidates and their projections (points every 0.05 s).
  const pts = (v, steer) => Array.from({ length: 61 }, (_, k) => ({ x: 100 + v * 0.05 * k, z: 50 + steer * k, heading: Math.PI / 2, speed: v }));
  window.SEMIF_SIM = { world: { seed: 7 }, lastPlan: { origin: { x: 100, z: 50, heading: Math.PI / 2 },
    vectors: { b9_v0: { velocity_mps: 10, steering: 0 }, b9_v1: { velocity_mps: 4, steering: 0.2 } },
    projections: { b9_v0: { points: pts(10, 0) }, b9_v1: { points: pts(4, 0.1) } } } };
  window.SEMIF_VISION = { signal: "red", perception: { backend: "rtdetr", objects: [] } };
  window.SEMIF_VISION_AT = nowMs;
  nowMs += 300;
  const shaped = window.SEMIF_SHAPE_DECISION({ state: { candidates: { v0: [4, 0.2, 0, 0, false, false], v1: [10, 0, 0, 0, false, false] } } });
  const seen = [];
  const sent = [];
  const at = (state, age) => { window.SEMIF_VISION = { perception: { backend: "rtdetr", status: "ready", signal: { state } } }; window.SEMIF_VISION_AT = nowMs - age; window.SEMIF_UPDATE_SEEN(); seen.push(window.SEMIF_SEEN_SIGNAL); sent.push(window.SEMIF_SEEN_SENT); };
  at("unknown", 100);   // never seen yet: red
  at("green", 100);     // seen green
  nowMs += 500; at("unknown", 100);    // lost it half a second later: still green
  nowMs += 600; at("unknown", 100);    // over 0.8 s: green is not trusted longer than an amber could last
  at("red", 100);
  nowMs += 2000; at("unknown", 100);   // a red is kept 2.5 s
  nowMs += 1000; at("unknown", 100);   // then forgotten: red anyway
  at("green", 4000);    // a stale frame says nothing: red
  at("green", 700);     // a green taken 0.7 s ago
  nowMs += 200; at("unknown", 100);    // 0.9 s after it was taken: no longer trusted
  at("green", -500);    // evidence from the future (another page's clock) is not fresh
  process.stdout.write(JSON.stringify({ mode: window.SEMIF_DRIVE_MODE, body: shaped, seen, sent }));
} else if (spec.cmd === "dom") {
  process.stdout.write(JSON.stringify(out));
} else if (spec.cmd === "project") {
  const pt = api.project(camera(spec.w, spec.h), spec.x, spec.y, spec.z, spec.w, spec.h);
  const back = api.unprojectGround(camera(spec.w, spec.h), pt.x, pt.y, spec.w, spec.h);
  process.stdout.write(JSON.stringify({ pt, back }));
} else if (spec.cmd === "paint") {
  const srcW = spec.srcW;
  const srcH = spec.srcH;
  const worldCanvas = el("canvas");
  worldCanvas.width = srcW;
  worldCanvas.height = srcH;
  worldCanvas.clientWidth = srcW;
  worldCanvas.clientHeight = srcH;
  const world = { canvas: worldCanvas, camera: camera(srcW, srcH) };
  const player = { x: 0, z: 0, heading: 0, speed: spec.speed };
  const sim = {
    player,
    pedestrians: spec.ped ? [spec.ped] : [],
    traffic: [],
    step() {},
    lastDecisionState: spec.decision || null,
    decisionState() {
      throw new Error("pip must not call decisionState");
    },
  };
  sim.player.maneuver = spec.maneuver;
  nowMs = 0;
  const first = boot(sim, world);
  sim.player.maneuver = spec.maneuver2 || spec.maneuver;
  nowMs = 500;
  canvas.__ctx.ops.length = 0;
  window.__raf();
  const second = plainOps(canvas.__ctx.ops);
  nowMs = 1000;
  canvas.__ctx.ops.length = 0;
  window.__raf();
  process.stdout.write(JSON.stringify({
    first, second,
    fps: fps.textContent,
  }));
} else if (spec.cmd === "ribbon") {
  const pts = api.ribbonPoints(spec.player, spec.maneuver);
  process.stdout.write(JSON.stringify(pts));
} else if (spec.cmd === "grab") {
  const worldCanvas = el("canvas");
  worldCanvas.toDataURL = () => "data:image/jpeg;base64,PLAYER";
  canvas.toDataURL = () => "data:image/jpeg;base64,ONBOARD";
  const shots = [];
  function makeCam() {
    const cam = {
      fov: 52,
      aspect: 1,
      position: { x: 0, y: 0, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z; } },
      lookAt(x, y, z) { this.look = { x, y, z }; },
      updateProjectionMatrix() {},
      updateMatrixWorld() {},
    };
    cam.clone = () => makeCam();
    return cam;
  }
  function RT(w, h) {
    this.w = w;
    this.h = h;
    this.isWebGLRenderTarget = true;
    this.texture = { colorSpace: "srgb-linear" };
  }
  const world = {
    mode: "map",
    canvas: worldCanvas,
    scene: {},
    player: { traverse() {} },
    vectors: { group: { visible: true } },
    sensorCone: { visible: true },
    sim: { player: { x: 10, z: -4, heading: Math.PI / 2 } },
    camera: makeCam(),
    sun: { shadow: { map: { constructor: RT } } },
    renderer: {
      getRenderTarget() { return null; },
      outputColorSpace: "srgb",
      setRenderTarget(target) {
        shots.push({
          op: "target",
          w: target && target.w,
          h: target && target.h,
          xr: target ? target.isXRRenderTarget === true : false,
          colorSpace: target && target.texture && target.texture.colorSpace,
          internalFormat: target && target.texture ? target.texture.internalFormat || null : null,
        });
      },
      render(_scene, cam) {
        shots.push({ op: "render", x: cam.position.x, y: cam.position.y, z: cam.position.z, fov: cam.fov, look: cam.look, egoVisible: window.SEMIF_WORLD.player.visible,
          vectorsVisible: window.SEMIF_WORLD.vectors?.group.visible, coneVisible: window.SEMIF_WORLD.sensorCone?.visible });
      },
      readRenderTargetPixels(_t, _x, _y, w, h, buf) { buf.fill(8); },
    },
  };
  window.SEMIF_WORLD = world;
  canvas.__ctx.ops.length = 0;
  nowMs = 0;
  const url = window.SEMIF_GRAB_FRAME();
  const first = shots.filter((s) => s.op === "render").pop();
  world.mode = "chase";
  window.SEMIF_GRAB_FRAME();
  const second = shots.filter((s) => s.op === "render").pop();
  const beforeView = shots.filter((s) => s.op === "render").length;
  nowMs = 0;
  window.__raf();
  nowMs = 500;
  window.__raf();
  nowMs = 1000;
  window.__raf();
  const viewShots = shots.filter((s) => s.op === "render").length - beforeView;
  const target = shots.filter((s) => s.op === "target" && s.w)[0];
  process.stdout.write(JSON.stringify({
    url,
    mode: world.mode,
    egoAfter: world.player.visible,
    overlaysAfter: [world.vectors.group.visible, world.sensorCone.visible],
    first,
    second,
    target,
    viewShots,
    ops: plainOps(canvas.__ctx.ops),
    fps: fps.textContent,
  }));
} else if (spec.cmd === "upload") {
  canvas.toDataURL = () => "data:image/jpeg;base64,ONBOARD";
  function makeCam() {
    const cam = {
      fov: 52,
      aspect: 1,
      position: { x: 0, y: 0, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z; } },
      lookAt(x, y, z) { this.look = { x, y, z }; },
      updateProjectionMatrix() {},
      updateMatrixWorld() {},
    };
    cam.clone = () => makeCam();
    return cam;
  }
  function RT(w, h) {
    this.w = w;
    this.h = h;
    this.isWebGLRenderTarget = true;
    this.texture = {};
  }
  window.SEMIF_WORLD = {
    mode: "chase",
    scene: {},
    player: { traverse() {} },
    sim: { player: { x: 10, z: -4, heading: Math.PI / 2 } },
    camera: makeCam(),
    sun: { shadow: { map: { constructor: RT } } },
    renderer: {
      getRenderTarget() { return null; },
      outputColorSpace: "srgb",
      setRenderTarget() {},
      render() {},
      readRenderTargetPixels(_t, _x, _y, w, h, buf) { if (readSizes.length < 6) readSizes.push([w, h]); buf.fill(8); },
    },
  };
  const readSizes = [];
  const frames = spec.frames || 120;
  const dt = 1000 / 60;
  const ticks = [];
  let renders = 0;
  const renderer = window.SEMIF_WORLD.renderer;
  const paint = renderer.render;
  renderer.render = function (_scene, cam) {
    renders += 1;
    if (surroundLooks.length < 6 && cam && cam.look) {
      surroundLooks.push({
        dx: cam.look.x - cam.position.x,
        dz: cam.look.z - cam.position.z,
        fov: cam.fov,
      });
    }
    return paint.apply(this, arguments);
  };
  nowMs = 0;
  // A browser runs promise callbacks between frames; the vision post waits on a few (#42 item 2).
  (async () => {
  for (let i = 0; i < frames; i++) {
    nowMs += dt;
    ticks.push(nowMs);
    window.__raf();
    await new Promise((r) => setImmediate(r));
  }
  process.stdout.write(JSON.stringify({
    posts: visionPosts.length,
    bodies: visionBodies.slice(0, 2),
    yaws: surroundLooks,
    postTimes: visionPosts,
    tickTimes: ticks,
    intervals: visionIntervals,
    fps: fps.textContent,
    renders,
    readSizes,
  }));
  })();
} else if (spec.cmd === "vision-order") {
  canvas.toDataURL = () => "data:image/jpeg;base64,ONBOARD";
  function makeCam() {
    const cam = {
      fov: 52,
      aspect: 1,
      position: { x: 0, y: 0, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z; } },
      lookAt(x, y, z) { this.look = { x, y, z }; },
      updateProjectionMatrix() {},
      updateMatrixWorld() {},
    };
    cam.clone = () => makeCam();
    return cam;
  }
  function RT(w, h) {
    this.w = w;
    this.h = h;
    this.isWebGLRenderTarget = true;
    this.texture = {};
  }
  window.SEMIF_WORLD = {
    scene: {},
    player: { traverse() {} },
    sim: { player: { x: 10, z: -4, heading: 0 } },
    camera: makeCam(),
    sun: { shadow: { map: { constructor: RT } } },
    renderer: {
      getRenderTarget() { return null; },
      outputColorSpace: "srgb",
      setRenderTarget() {},
      render() {},
      readRenderTargetPixels(_t, _x, _y, w, h, buf) { buf.fill(8); },
    },
  };
  (async () => {
  nowMs = 16;
  window.__raf();
  await new Promise((r) => setImmediate(r));
  nowMs = 32;
  window.__raf();
  await new Promise((r) => setImmediate(r));
  window.__releaseVision(1, {
    vision: { signal: "red", event: "newer frame" },
    vision_gen: 2,
    vision_encode_ms: 5,
  });
  setImmediate(() => {
    window.__releaseVision(0, {
      vision: { signal: "green", event: "older frame" },
      vision_gen: 1,
      vision_encode_ms: 9,
    });
    setImmediate(() => {
      process.stdout.write(JSON.stringify({
        signal: window.SEMIF_VISION && window.SEMIF_VISION.signal,
        gen: window.SEMIF_VISION_GEN,
      }));
    });
  });
  })();
} else if (spec.cmd === "vision-ack") {
  canvas.toDataURL = () => "data:image/jpeg;base64,ONBOARD";
  function makeCam() {
    const cam = {
      fov: 52,
      aspect: 1,
      position: { x: 0, y: 0, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z; } },
      lookAt(x, y, z) { this.look = { x, y, z }; },
      updateProjectionMatrix() {},
      updateMatrixWorld() {},
    };
    cam.clone = () => makeCam();
    return cam;
  }
  function RT(w, h) {
    this.w = w;
    this.h = h;
    this.isWebGLRenderTarget = true;
    this.texture = {};
  }
  window.SEMIF_WORLD = {
    scene: {},
    player: { traverse() {} },
    sim: { player: { x: 10, z: -4, heading: 0 } },
    camera: makeCam(),
    sun: { shadow: { map: { constructor: RT } } },
    renderer: {
      getRenderTarget() { return null; },
      outputColorSpace: "srgb",
      setRenderTarget() {},
      render() {},
      readRenderTargetPixels(_t, _x, _y, w, h, buf) { buf.fill(8); },
    },
  };
  const replies = spec.replies || [{}];
  nowMs = 0;
  (async () => {
  for (let i = 0; i < replies.length; i++) {
    nowMs += 16;
    window.__raf();
    await new Promise((r) => setImmediate(r));
  }
  setImmediate(() => {
    process.stdout.write(JSON.stringify({
      vision: window.SEMIF_VISION,
      text: document.getElementById("fsd-vision").textContent,
      records: (window.SEMIF_TELEMETRY && window.SEMIF_TELEMETRY.records) || [],
    }));
  });
  })();
} else if (spec.cmd === "keys") {
  const beforeHidden = pip.classList.contains("fsd-pip-hidden");
  const beforeFold = pip.classList.contains("fsd-pip-collapsed");
  document.dispatchEvent({ type: "keydown", key: "v", target: document.body, bubbles: true });
  const afterVHidden = pip.classList.contains("fsd-pip-hidden");
  document.dispatchEvent({ type: "keydown", key: "v", target: document.body, repeat: true, bubbles: true });
  const afterRepeat = pip.classList.contains("fsd-pip-hidden");
  header.dispatchEvent({ type: "click", target: header, bubbles: true });
  const afterClickFold = pip.classList.contains("fsd-pip-collapsed");
  const seed = document.getElementById("fsd-seed-input");
  const hiddenBeforeType = pip.classList.contains("fsd-pip-hidden");
  seed.dispatchEvent({ type: "keydown", key: "v", target: seed, bubbles: true });
  const hiddenAfterType = pip.classList.contains("fsd-pip-hidden");
  process.stdout.write(JSON.stringify({
    beforeHidden, beforeFold, afterVHidden, afterRepeat, afterClickFold, hiddenBeforeType, hiddenAfterType,
  }));
} else if (spec.cmd === "lap") {
  const player = {
    x: 6,
    z: 0,
    speed: 2,
    target: 4,
    s: 100,
    route: { points: [{ x: 0, z: 0 }, { x: 10, z: 0 }] },
  };
  const sim = {
    complete: false,
    freeExplore: false,
    autopilot: true,
    chained: false,
    player,
    world: { seed: 42 },
    step() {
      player.x = 9.8;
      player.speed = 0.2;
      const last = player.route.points[player.route.points.length - 1];
      const dist = Math.hypot(player.x - last.x, player.z - last.z);
      if (!sim.complete && dist < 3 && player.speed < 1) {
        player.route = { points: [{ x: 0, z: 80 }] };
        player.s = 2;
        sim.complete = false;
        sim.chained = true;
      }
    },
  };
  window.SEMIF_SIM = sim;
  window.SEMIF_WORLD = {};
  window.__raf();
  sim.step(0.016);
  const end = player.route.points[player.route.points.length - 1];
  process.stdout.write(JSON.stringify({
    complete: sim.complete,
    chained: sim.chained,
    target: player.target,
    endZ: end.z,
    s: player.s,
  }));
} else if (spec.cmd === "boxes") {
  // #54: where the on-screen boxes and the halo come from. Truth reads are trapped.
  const reads = [];
  const player = { x: 0, z: 0, heading: 0, speed: 8 };
  const sim = { player, world: { seed: 42 }, step() {} };
  Object.defineProperty(sim, "pedestrians", { get() { reads.push("pedestrians"); return [{ type: "pedestrian", x: 1, z: -12, height: 1.7 }]; } });
  Object.defineProperty(sim, "traffic", { get() { reads.push("traffic"); return []; } });
  const worldCanvas = el("canvas");
  worldCanvas.clientWidth = 640;
  worldCanvas.clientHeight = 360;
  nowMs = 10000;
  window.SEMIF_VISION = { perception: { backend: "rtdetr", status: "ready", objects: spec.objects || [] } };
  window.SEMIF_VISION_AT = nowMs - (spec.age == null ? 200 : spec.age);
  window.SEMIF_SIM = sim;
  window.SEMIF_WORLD = { canvas: worldCanvas, camera: camera(640, 360) };
  if (spec.moved) {
    // The frame was grabbed 200 ms ago with the car here; since then it drove spec.moved m ahead.
    nowMs -= 200;
    window.__raf();
    nowMs += 200;
    player.z -= spec.moved;
  }
  window.__raf();
  const boxEls = document.getElementById("fsd-boxes").children;
  process.stdout.write(JSON.stringify({
    mode: window.SEMIF_DRIVE_MODE,
    reads,
    labels: boxEls.map((b) => (b.innerHTML.match(/<span>([^<]*)<\/span>/) || [])[1] || b.innerHTML),
    centres: boxEls.map((b) => parseFloat(b.style.left) + parseFloat(b.style.width) / 2),
    halo: document.getElementById("fsd-halo").dataset.level || "",
  }));
} else if (spec.cmd === "rng") {
  // #55: the page must not draw from the planner's seeded random; the bundle owns that sequence.
  let draws = 0;
  const sim = {
    time: 0,
    player: { x: 0, z: 0, heading: 0, speed: 10 },
    pedestrians: [],
    traffic: [],
    planRandom() { draws += 1; return 0.5; },
    step(dt) { sim.time += dt; },
  };
  window.SEMIF_SIM = sim;
  window.SEMIF_WORLD = {};
  window.__raf();
  for (let i = 0; i < 1500; i++) sim.step(0.02);
  process.stdout.write(JSON.stringify({ time: sim.time, draws, agents: "_fsdAgents" in sim, wrapped: sim._pdDt === 0.02 }));
} else if (spec.cmd === "candidates") {
  // #19: the bundle's candidates button appears once its module has run, and only then gets its
  // handler; pressing it flips aria-pressed, as main-*.js does.
  window.__raf();
  const btn = el("button");
  btn.id = "candidates-toggle";
  btn.setAttribute("aria-pressed", "false");
  document.body.appendChild(btn);
  window.__raf();
  const pressedBeforeBound = btn.getAttribute("aria-pressed");
  let clicks = 0;
  const handler = () => { clicks += 1; btn.setAttribute("aria-pressed", String(btn.getAttribute("aria-pressed") !== "true")); };
  btn.addEventListener("click", handler);
  btn.onclick = handler;
  window.__raf();
  window.__raf();
  const restored = btn.getAttribute("aria-pressed");
  const restoreClicks = clicks;
  const storedAfterRestore = window.localStorage.getItem("semif.candidates");
  btn.click(); // the driver flips it
  window.__raf();
  process.stdout.write(JSON.stringify({ pressedBeforeBound, restored, restoreClicks, storedAfterRestore,
    stored: window.localStorage.getItem("semif.candidates") }));
} else if (spec.cmd === "fleet") {
  const player = { id: undefined, x: 0, z: 0, heading: 0, speed: 5 };
  const near = { id: "vehicle-0", x: 1.0, z: -12, heading: 0, speed: 8 };
  const far = { id: "vehicle-1", x: 0, z: -200, heading: 0, speed: 8 };
  const parked = { id: "vehicle-2", x: 2, z: -20, heading: 0, speed: 0, parked: true };
  const yielding = { id: "vehicle-3", x: -60, z: 0, heading: Math.PI / 2, speed: 6 };
  const sim = {
    time: 0,
    player,
    traffic: [near, far, parked, yielding],
    pedestrians: [{ x: -1, z: -30 }],
    world: { seed: 42, theme: { limit: 14 } },
    rule(car) {
      if (car === yielding) {
        return { mustStop: true, distance: 6, color: "amber", reason: "Yield to crossing traffic", nodeId: "n2" };
      }
      return { mustStop: true, distance: 18, color: "red", reason: "Red light", nodeId: "n1" };
    },
    speedEnvelope(car) {
      return { max: car === far ? 2 : 9, reason: "script" };
    },
    step(dt) {
      sim.time += dt;
    },
  };
  window.SEMIF_SIM = sim;
  window.SEMIF_WORLD = {};
  (async () => {
    window.__raf();
    const before = { env: sim.speedEnvelope(near).max, stop: sim.rule(near).mustStop };
    sim.step(0.05);
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    sim.step(0.05);
    const after = {
      env: sim.speedEnvelope(near).max,
      stop: sim.rule(near).mustStop,
      reason: sim.speedEnvelope(near).reason,
      playerEnv: sim.speedEnvelope(player).max,
      playerStop: sim.rule(player).mustStop,
      parkedEnv: sim.speedEnvelope(parked).max,
      farEnv: sim.speedEnvelope(far).max,
      yieldStop: sim.rule(yielding).mustStop,
    };
    sim.time += 5;
    const stale = { env: sim.speedEnvelope(near).max, stop: sim.rule(near).mustStop };
    // The world restarts: its clock goes back to zero with the same car ids.
    sim.time = 300;
    sim.step(0.05);
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    const postsBefore = fleetBodies.length;
    sim.time = 0;
    const restartEnv = sim.speedEnvelope(near).max;
    sim.step(0.05);
    const restart = {
      env: restartEnv,
      posted: fleetBodies.length > postsBefore,
      sessions: [...new Set(fleetBodies.map((b) => b.session))].length,
    };
    const button = document.getElementById("fsd-fleet");
    process.stdout.write(JSON.stringify({
      before, after, stale, restart, bodies: fleetBodies, hud: button && button.textContent,
    }));
  })().catch((err) => {
    process.stderr.write(String(err && err.stack || err));
    process.exit(1);
  });
} else {
  throw new Error("unknown cmd");
}

function _perspectiveElements(w, h) {
  const fov = 60 * Math.PI / 180;
  const aspect = w / h;
  const near = 0.1;
  const far = 400;
  const f = 1 / Math.tan(fov / 2);
  const m = Array(16).fill(0);
  m[0] = f / aspect;
  m[5] = f;
  m[10] = (far + near) / (near - far);
  m[11] = -1;
  m[14] = (2 * far * near) / (near - far);
  return m;
}
"""


def _harness_file() -> str:
    """The harness outgrew Windows' command-line limit for `node -e`; node requires it from a file
    (process.argv is the same either way)."""
    import hashlib
    import tempfile

    import os

    path = Path(tempfile.gettempdir()) / f"semif-overlay-harness-{hashlib.sha1(_HARNESS.encode()).hexdigest()[:12]}.js"
    if not path.exists():
        # Written whole, then renamed into place: an interrupted or parallel write never leaves a
        # half file under the final name.
        tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
        tmp.write_text(_HARNESS, encoding="utf-8")
        os.replace(tmp, path)
    return path.as_posix()


def _run(cmd: dict, view: list[float] | None = None) -> dict:
    view = view if view is not None else _view_at(0.0, 1.4, 8.0)
    proc = subprocess.run(
        ["node", "-e", f"require({json.dumps(_harness_file())})", str(OVERLAY_JS), json.dumps(view), json.dumps(cmd)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or proc.stdout[-2000:] or "node failed")
    return json.loads(proc.stdout)


def test_lap_query_stops_at_the_route_end():
    """?lap=1 keeps the finished route and sets complete after the sim chains."""
    lap = _run({"cmd": "lap", "vision": "1", "lap": "1"})
    assert lap["complete"] is True
    assert lap["chained"] is True
    assert lap["endZ"] == 0
    assert lap["target"] == 0
    assert lap["s"] == 100


def test_pip_shell_is_in_the_loaded_overlay():
    dom = _run({"cmd": "dom"})
    assert dom["hasPip"] is True
    assert dom["title"] == TITLE
    assert dom["canvas"] == {"w": 640, "h": 360}, "the front camera renders at 640x360 for perception (#18)"
    assert dom["fps0"] == "-- FPS"
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    html = (REPO / "jevpilot_vision" / "web" / "index.html").read_text(encoding="utf-8")
    assert "preserveDrawingBuffer" in html.split('type="module"')[0]
    assert "#fsd-pip" in css
    assert "pointer-events: auto" in css
    assert "fsd-pip-collapsed" in css
    assert "fsd-pip-hidden" in css


def test_each_display_frame_posts_four_surround_jpegs():
    """Live tick posts one /v1/vision with four camera JPEGs per painted onboard frame."""
    pumped = _run({"cmd": "upload", "vision": "1", "frames": 120})
    assert pumped["posts"] == 120
    # four cameras per capture, plus the 15 Hz PIP repaint (31 in 2 s at most; #42 item 3)
    assert 120 * 4 + 25 <= pumped["renders"] <= 120 * 4 + 31
    body = pumped["bodies"][0]
    assert body["keys"] == ["frames", "t_ms"], "frames carry the moment they were grabbed (#18)"
    assert body["frames"] == ["front", "right", "rear", "left"]
    # the front is encoded from the captured pixels (a worker in Chrome; a canvas here), not the PIP (#42)
    assert body["front"] == "data:image/jpeg;base64,AAAA"
    # heading pi/2 faces +x; right, rear and left turn clockwise from there
    looks = pumped["yaws"][1:5]  # render 0 is the PIP repaint
    directions = [(round(look["dx"]), round(look["dz"])) for look in looks]
    assert directions == [(25, 0), (0, 25), (-25, 0), (0, -25)]
    hfov = [2 * math.degrees(math.atan(math.tan(math.radians(look["fov"] / 2)) * PIP_W / PIP_H)) for look in looks]
    assert all(abs(value - 100.0) < 0.5 for value in hfov)
    assert pumped["postTimes"] == pumped["tickTimes"]
    assert 700 not in pumped["intervals"]
    assert pumped["fps"] == "15 FPS", "the PIP is a 15 Hz preview (#42 item 3)"
    # #18: the front camera, which perception reads, renders at 640x360; the other three at 320x180.
    # read 0 is the PIP repaint; the capture reads front 640x360 then three 320x180 sides
    assert pumped["readSizes"][:5] == [[640, 360], [640, 360], [320, 180], [320, 180], [320, 180]]


def test_late_older_vision_does_not_replace_newer_evidence():
    """An older inference that arrives last leaves the newer evidence in place."""
    ordered = _run({"cmd": "vision-order", "vision": "1"})
    assert ordered["signal"] == "red"
    assert ordered["gen"] == 2


def test_empty_vision_ack_keeps_prior_evidence():
    """A reply without vision does not replace evidence or record encode time."""
    ack = _run({
        "cmd": "vision-ack",
        "vision": "1",
        "replies": [
            {
                "vision": {"signal": "green", "event": "road clear ahead"},
                "vision_encode_ms": 4,
            },
            {},
        ],
    })
    assert ack["vision"]["signal"] == "green"
    assert ack["text"] == "VISION waiting"
    assert ack["records"] == [{"encode_ms": 4, "rtt_ms": ack["records"][0]["rtt_ms"], "grab_ms": ack["records"][0]["grab_ms"]}]
    assert len(ack["records"]) == 1


def test_pip_shows_the_fixed_onboard_camera_not_the_player_view():
    """Change camera is the player view. The posted frame stays on the car."""
    grabbed = _run({"cmd": "grab"})
    assert grabbed["url"] == "data:image/jpeg;base64,ONBOARD"
    assert grabbed["mode"] == "chase"
    shot = grabbed["first"]
    assert shot["fov"] == pytest.approx(67.67, abs=0.01)  # 100° horizontal at 16:9
    assert shot["x"] == pytest.approx(10.15)
    assert shot["y"] == pytest.approx(1.45)
    assert shot["z"] == pytest.approx(-4)
    assert shot["look"]["x"] == pytest.approx(10.15 + 25)
    assert shot["look"]["z"] == pytest.approx(-4)
    assert shot["egoVisible"] is False, "the cameras sit on the body shell; the ego car is not in view"
    assert grabbed["egoAfter"] is not False, "the ego car is back for the main view"
    assert shot["vectorsVisible"] is False, "steering candidates are a driver's overlay, not something the camera sees"
    assert shot["coneVisible"] is False
    assert grabbed["overlaysAfter"] == [True, True], "the overlays are back for the main view"
    again = grabbed["second"]
    assert again["x"] == pytest.approx(shot["x"])
    assert again["z"] == pytest.approx(shot["z"])
    assert any(op["op"] == "putImageData" for op in grabbed["ops"])
    target = grabbed["target"]
    assert target["xr"] is True
    assert target["colorSpace"] == "srgb"
    assert target["internalFormat"] == "RGBA8"
    assert grabbed["viewShots"] == 3
    assert grabbed["fps"] == "2 FPS"
    assert any(op["op"] == "putImageData" for op in grabbed["ops"])
    assert not any(op["op"] == "drawImage" for op in grabbed["ops"])
    js = OVERLAY_JS.read_text(encoding="utf-8")
    # The front frame comes through the async capture now, not grabFrame() (#42 review M1):
    # tests/test_capture.py pins that.


def test_v_and_header_toggle_without_stealing_seed_input():
    keys = _run({"cmd": "keys"})
    assert keys["beforeHidden"] is False
    assert keys["afterVHidden"] is True
    assert keys["afterRepeat"] is keys["afterVHidden"]
    assert keys["afterClickFold"] is not keys["beforeFold"]
    assert keys["hiddenAfterType"] is keys["hiddenBeforeType"]


def test_fleet_mode_drives_traffic_from_v1_fleet():
    """#3: ?fleet=semif posts ego-relative boxes for moving traffic and applies the decisions."""
    out = _run({"cmd": "fleet", "fleet": "semif"})
    assert out["before"] == {"env": 9, "stop": True}
    assert out["bodies"], "fleet mode must post to /v1/fleet"
    body = out["bodies"][0]
    assert body["policy"] == "semif"
    ids = [agent["id"] for agent in body["agents"]]
    assert ids == ["vehicle-0", "vehicle-1", "vehicle-3"], "parked cars are not fleet cars"
    near = body["agents"][0]
    assert "x" not in near and "z" not in near
    for box in near["obstacles"]:
        assert set(box) == {"kind", "rel_x", "rel_z"}
        assert (box["rel_x"] ** 2 + box["rel_z"] ** 2) ** 0.5 <= 42
    player_box = [b for b in near["obstacles"] if b["kind"] == "vehicle"][0]
    assert player_box["rel_z"] == pytest.approx(-12.0)
    assert player_box["rel_x"] == pytest.approx(-1.0)
    assert [b["kind"] for b in body["agents"][1]["obstacles"]] == [], "200 m away is out of range"
    assert near["intersection"]["signal"] == "red"
    assert near["intersection"]["distance_to_line_m"] == 18
    assert out["after"]["env"] == 3.5
    assert out["after"]["stop"] is False
    assert out["after"]["reason"] == "Fleet semif"
    assert out["after"]["playerEnv"] == 9 and out["after"]["playerStop"] is True
    assert out["after"]["parkedEnv"] == 9
    assert out["after"]["farEnv"] == 2, "the decision runs under the safety envelope, as the player's does"
    assert out["after"]["yieldStop"] is True, "junction interlocks stay with the traffic rules"
    assert body["agents"][2]["intersection"]["signal"] == "yellow", "the city's amber is the contract's yellow"
    assert out["stale"] == {"env": 9, "stop": True}, "a stale decision hands the car back to the script"
    assert out["hud"].startswith("FLEET semif")
    assert near["steers"] is False, "web traffic keeps its route geometry; only speed is decided"
    assert body["t"] == pytest.approx(0.05) and body["session"]
    assert out["restart"]["env"] == 9, "a restarted world does not inherit the old world's decisions"
    assert out["restart"]["posted"] is True, "a restarted world posts again at once"
    assert out["restart"]["sessions"] >= 2, "a restarted world starts fresh tracks"


def test_issue19_the_candidate_fan_choice_is_remembered_per_browser():
    """#19: the bundle draws only the chosen path unless its candidates button is pressed; the choice
    now survives a reload."""
    fresh = _run({"cmd": "candidates"})
    assert fresh["restored"] == "false" and fresh["restoreClicks"] == 0, "default: the chosen path only"
    assert fresh["stored"] == "1", "pressing the button is remembered"
    again = _run({"cmd": "candidates", "storage": {"semif.candidates": "1"}})
    assert again["pressedBeforeBound"] == "false", "nothing is pressed before the bundle handles it"
    assert again["restored"] == "true" and again["restoreClicks"] == 1
    assert again["stored"] == "0", "turning it off is remembered too"


def test_issue19_the_address_bar_wins_over_the_remembered_choice():
    shown = _run({"cmd": "candidates", "candidates": "all", "storage": {"semif.candidates": "0"}})
    assert shown["restored"] == "true"
    assert shown["storedAfterRestore"] == "0", "the address bar does not overwrite the browser's choice"
    hidden = _run({"cmd": "candidates", "candidates": "selected", "storage": {"semif.candidates": "1"}})
    assert hidden["restored"] == "false" and hidden["restoreClicks"] == 0


def test_fleet_mode_is_off_by_default():
    out = _run({"cmd": "fleet"})
    assert out["bodies"] == []
    assert out["after"]["env"] == 9 and out["after"]["stop"] is True
    assert out["hud"] == "FLEET off"


def test_vision_mode_marks_each_decision_and_says_how_old_its_evidence_is():
    """#18: ?mode=vision sends drive_mode and the age of the camera evidence with every decision."""
    vision = _run({"cmd": "shape", "vision": "1", "mode": "vision"})
    assert vision["mode"] == "vision"
    assert vision["body"]["drive_mode"] == "vision"
    assert vision["body"]["state"]["vision"]["perception"]["backend"] == "rtdetr"
    assert vision["body"]["state"]["vision_age_ms"] == 300
    assert vision["body"]["state"]["seen_signal"] is None, "nothing seen yet: the server assumes red only at a signalled line"
    # Each candidate carries the planner's own path, matched by speed and steer: [t, ahead, right, heading].
    paths = vision["body"]["state"]["candidate_paths"]
    assert sorted(paths) == ["v0", "v1"]
    assert paths["v1"][-1][0] == pytest.approx(3.0) and paths["v1"][-1][1] == pytest.approx(30.0)
    assert paths["v0"][-1][1] == pytest.approx(12.0) and paths["v0"][-1][2] == pytest.approx(6.0)
    # The planner's signal colour is the camera's: red until green is seen, kept 2.5 s, stale is red.
    # Memory counts from when the frame was taken, not from when it was last looked at.
    assert vision["seen"] == ["red", "green", "green", "red", "red", "red", "red", "red", "green", "red", "red"]
    # What the server is told: a reading the cameras made, or nothing. The planner's red default is
    # not a sighting; on an open road it would order a stop (review #18).
    assert vision["sent"] == [None, "green", "green", None, "red", "red", None, None, "green", None, None]
    plain = _run({"cmd": "shape", "vision": "1"})
    assert plain["mode"] == "privileged" and "drive_mode" not in plain["body"]


def test_vision_mode_adds_a_narrow_forward_camera_for_far_lights():
    """#18: in Vision mode a fifth, narrow (40 degree) forward camera goes with the four, at 640x360."""
    pumped = _run({"cmd": "upload", "vision": "1", "mode": "vision", "frames": 3})
    assert pumped["bodies"][0]["frames"] == ["front", "right", "rear", "left", "narrow"]
    # render 0 is the 15 Hz PIP repaint (#42 item 3); the capture is front, right, rear, left, narrow
    assert pumped["readSizes"][5] == [640, 360]
    narrow = pumped["yaws"][5]
    hfov = 2 * math.degrees(math.atan(math.tan(math.radians(narrow["fov"] / 2)) * PIP_W / PIP_H))
    assert abs(hfov - 40.0) < 0.5
    assert (round(narrow["dx"]), round(narrow["dz"])) == (25, 0), "it looks straight ahead"
    plain = _run({"cmd": "upload", "vision": "1", "frames": 3})
    assert plain["bodies"][0]["frames"] == ["front", "right", "rear", "left"], "other modes keep four cameras"


def test_the_mode_comes_from_the_address_then_the_browser_then_privileged():
    """#21: ?mode= overrides; otherwise the browser's last choice; otherwise privileged."""
    assert _run({"cmd": "mode"})["steps"][0]["mode"] == "privileged"
    assert _run({"cmd": "mode", "storage": {"semif.driveMode": "vision"}})["steps"][0]["mode"] == "vision"
    assert _run({"cmd": "mode", "mode": "heuristic", "storage": {"semif.driveMode": "vision"}})["steps"][0]["mode"] == "heuristic"
    assert _run({"cmd": "mode", "storage": {"semif.driveMode": "nonsense"}})["steps"][0]["mode"] == "privileged"


def test_issue78_review_vision_map_names_itself_and_survives_a_trip_through_heuristic():
    trip = {s["at"]: s for s in _run({"cmd": "mode"})["steps"]}["vision-map round trip"]
    assert trip["mapSaid"] == "Vision (map) mode, detector failed, holding to a crawl"
    assert trip["viaHeuristic"] == "heuristic"
    assert (trip["mode"], trip["drive"], trip["stage"]) == ("vision-map", "vision", 1)


def test_issue78_vision_map_is_its_own_mode_that_drives_as_vision():
    """#78: the old Vision is kept as Vision (map), the baseline the de-mapped Vision is compared to.
    The address and the switch name it; it drives "vision", so every planner patch treats it alike."""
    load = _run({"cmd": "mode", "mode": "vision-map"})["steps"][0]
    assert (load["id"], load["mode"]) == ("vision-map", "vision")
    assert load["shaped"] == {"drive_mode": "vision", "mode": "flat", "vision_stage": None}, "Vision (map) names no stage"
    stored = _run({"cmd": "mode", "storage": {"semif.driveMode": "vision-map"}})["steps"][0]
    assert (stored["id"], stored["mode"]) == ("vision-map", "vision")
    steps = {s["at"]: s for s in _run({"cmd": "mode", "mode": "privileged"})["steps"]}
    click = steps["click vision-map"]
    assert (click["id"], click["mode"], click["checked"]) == ("vision-map", "vision", "true")
    assert click["shaped"] == {"drive_mode": "vision", "mode": "flat", "vision_stage": None}
    assert steps["click vision"]["id"] == "vision"
    # #75: the new Vision names its stage, so the server applies that stage's rules
    assert steps["click vision"]["shaped"] == {"drive_mode": "vision", "mode": "flat", "vision_stage": 1}


def test_switching_mode_from_the_indicator_changes_the_decision_request():
    """#21: each mode is a different decision path: Vision adds drive_mode, Heuristic asks the
    heuristic scorer, Privileged is the SemArbiter on the simulator table. The bundle's strategy
    dropdown follows, the choice is remembered and written into the address."""
    out = _run({"cmd": "mode", "mode": "privileged"})
    steps = {s["at"]: s for s in out["steps"]}
    assert steps["load"]["shaped"] == {"drive_mode": None, "mode": "flat", "vision_stage": None}
    assert steps["click vision"]["shaped"] == {"drive_mode": "vision", "mode": "flat", "vision_stage": 1}
    assert steps["click vision-map"]["shaped"] == {"drive_mode": "vision", "mode": "flat", "vision_stage": None}
    assert steps["click vision"]["checked"] == "true"
    # Heuristic is the bundle's own geometric planner: the strategy dropdown switches to it (the
    # bundle then decides locally and asks no server); nothing in the request is rewritten.
    assert steps["click heuristic"]["select"] == "heuristic"
    assert steps["click heuristic"]["shaped"] == {"drive_mode": None, "mode": "flat", "vision_stage": None}
    assert steps["click privileged"]["shaped"] == {"drive_mode": None, "mode": "flat", "vision_stage": None}
    assert steps["click privileged"]["select"] == "semif"
    assert out["strategyChanges"][:2] == ["heuristic", "semif"], "the bundle hears the change"
    last = [s["mode"] for s in out["steps"] if "mode" in s][-1]
    assert out["stored"]["semif.driveMode"] == last, "the last choice is remembered"
    # The address follows (other parameters kept), one per click.
    assert out["urls"][:4] == ["/jevpilot/?vision=0&mode=vision-map", "/jevpilot/?vision=0&mode=vision",
                               "/jevpilot/?vision=0&mode=heuristic", "/jevpilot/?vision=0&mode=privileged"]


def test_the_indicator_says_what_each_mode_reads_not_which_is_better():
    steps = {s["at"]: s for s in _run({"cmd": "mode"})["steps"]}
    assert steps["click vision-map"]["reads"] == "Objects & signals from cameras · map privileged"
    # #78/#75: the new Vision says which stage it is at and what is still privileged
    assert steps["click vision"]["reads"] == "Objects, signals & box flow from cameras · stage 1 · map privileged"
    assert steps["click privileged"]["reads"] == "Simulator state · the ablation for a decision model"
    assert steps["click heuristic"]["reads"] == "Geometric rules · no model"


def test_the_strategy_dropdown_the_bundles_shortcuts_and_the_m_key_drive_the_indicator_too():
    steps = {s["at"]: s for s in _run({"cmd": "mode", "mode": "vision"})["steps"]}
    assert steps["select heuristic"]["mode"] == "heuristic"
    # Back to SemArbiter in the dropdown: the last SemArbiter mode (privileged, clicked last).
    assert steps["select semif"]["mode"] == "privileged"
    # Review #21 H2: the bundle's 1/2/3 keys change the dropdown with no event; the next frame notices.
    assert steps["bundle sets heuristic"]["mode"] == "heuristic"
    assert steps["bundle sets semif"]["mode"] == "privileged"
    assert steps["key M"]["mode"] == "heuristic", "M cycles vision -> privileged -> heuristic -> vision"
    # Review #21 H1: V hides the camera view; the mode key must not touch it.
    assert steps["key M"]["pipToggled"] is False
    assert steps["key M with a dialog open"]["mode"] == "heuristic", "keys wait while a dialog is open"


def test_vision_health_says_when_the_car_is_held_to_a_crawl():
    """#21: the detector's state, the evidence's age and the encoder backend; loading, failed,
    stale or missing perception is the degraded state the server holds to a crawl (vision_mode.py)."""
    h = _run({"cmd": "mode"})["health"]
    assert h["ok"] == {"state": "ok", "text": "Detector ready · 0.4 s · SigLIP"}
    assert h["stub"]["state"] == "ok" and h["stub"]["text"].endswith("SigLIP stub")
    # Review #21 L1: the same rule as vision_mode._perception_ok: a missing status is ready, a null one is not.
    assert h["noStatus"]["state"] == "ok"
    for key, words in [("loading", "Detector loading"), ("failed", "Detector failed"), ("nullStatus", "Detector failed"),
                       ("stale", "Evidence 2.1 s old"),
                       ("none", "Waiting for the cameras"), ("future", "Waiting for the cameras"),
                       ("notObject", "Detector failed")]:
        assert h[key]["state"] == "degraded", key
        assert h[key]["text"].startswith(words) and h[key]["text"].endswith("holding to a crawl"), h[key]


def test_before_any_decision_the_status_names_the_mode_that_will_decide():
    """#21: in Heuristic the status card does not claim SemArbiter."""
    steps = {s["at"]: s for s in _run({"cmd": "mode"})["steps"]}
    assert steps["click heuristic"]["intent"] == "Heuristic"
    assert steps["click privileged"]["intent"] == "SemArbiter"


def test_review2_arrow_keys_on_the_switch_change_the_mode_and_never_reach_the_driving_keys():
    """The bundle steers (and drops autopilot) on arrow keys it hears on window; a keyboard user
    moving along the switch must not steer the car. One tab stop: the selected mode."""
    steps = {s["at"]: s for s in _run({"cmd": "mode", "mode": "vision"})["steps"]}
    arrow = steps["arrow right on the switch"]
    order = ["vision", "vision-map", "privileged", "heuristic"]
    assert arrow["mode"] == order[(order.index(arrow["from"]) + 1) % 4]
    assert arrow["reachedBundle"] == []
    assert arrow["tabindex"] == ["0" if m == arrow["mode"] else "-1" for m in order]


def test_review2_only_health_changes_are_announced_not_every_age_tick():
    steps = {s["at"]: s for s in _run({"cmd": "mode"})["steps"]}
    live = steps["live regions"]
    assert live["announce"] == "polite" and live["health"] is None
    # Stale at 2.1 s and at 2.4 s is one announcement; a failure is a new one.
    said = steps["announcements"]["said"]
    assert said[0] == said[1] == "Vision mode, evidence stale, holding to a crawl", said
    assert said[2] == "Vision mode, detector failed, holding to a crawl", said


def test_lag_ms_holds_every_decision_request_back_by_that_long():
    """#28: ?lag_ms= stresses the loop with a slower decision path, to see whether a result holds
    only at one timing. Without it nothing waits."""
    lagged = _run({"cmd": "lag", "lag": "300"})
    assert lagged["lag"] == 300 and 300 in lagged["timers"]
    plain = _run({"cmd": "lag"})
    assert plain["lag"] == 0 and 300 not in plain["timers"]
    assert _run({"cmd": "lag", "lag": "-5"})["lag"] == 0, "nonsense is no lag"
    # Review #28: the bundle drops a decision older than 1.8 s from when it asked, lag included, so
    # a stress above 1.2 s would only park the car.
    assert _run({"cmd": "lag", "lag": "5000"})["lag"] == 1200


def test_the_page_counts_classifier_successes_and_failures_for_the_evaluation():
    """#28: whether the decision path failed (HTTP error, network failure, a reply that is not
    JSON) is counted where the requests are made, not guessed from the bundle's event text."""
    out = _run({"cmd": "cstats"})
    assert out["outcomes"] == [200, 500, "threw", 200, 503, "threw"]
    # Review #28 (8): an outage (network failure, 502/503/504) is told apart from a failure of the
    # system under test (a 500, a 12 s timeout, a reply that is not JSON).
    assert out["stats"] == {"ok": 1, "http_errors": 1, "network_errors": 1, "bad_replies": 1, "gateway_errors": 1, "timeouts": 1}


def test_issue19_review_the_minimal_view_does_not_bring_back_a_fan_it_has_no_button_for():
    out = _run({"cmd": "candidates", "minimal": "1", "storage": {"semif.candidates": "1"}})
    assert out["restored"] == "false" and out["restoreClicks"] == 0


def test_issue42_the_onboard_pip_repaints_at_15_hz_not_every_frame():
    """#42 item 3: the PIP is a 15 Hz preview; Vision does not wait for it (see the next test)."""
    pumped = _run({"cmd": "upload", "vision": "0", "frames": 120})
    # 120 frames at 60 Hz are 2 s; one repaint every 66 ms is 31 at most.
    assert 25 <= pumped["renders"] <= 31, pumped["renders"]
    assert pumped["posts"] == 0


def test_issue42_vision_grabs_on_any_frame_the_server_can_take_not_only_on_pip_frames():
    """Between PIP repaints, a free vision slot still grabs at once: the front frame then comes
    from the async capture, so the 15 Hz preview never delays the evidence."""
    pumped = _run({"cmd": "upload", "vision": "1", "frames": 120})
    assert pumped["posts"] == 120, "the harness's server answers at once, so every frame can grab"


def test_issue54_vision_boxes_come_from_the_camera_and_never_read_the_simulator():
    """#54: in Vision mode the boxes and halo are what perception reported, labelled CAM."""
    person = {"kind": "pedestrian", "ahead_m": 9.85, "right_m": 1.0, "width_m": 0.5, "conf": 0.9}
    car = {"kind": "car", "ahead_m": 20.0, "right_m": -2.0, "width_m": 1.8, "conf": 0.8}
    out = _run({"cmd": "boxes", "mode": "vision", "objects": [person, car]})
    assert out["mode"] == "vision"
    assert out["reads"] == [], "Vision mode drew from sim.pedestrians / sim.traffic"
    assert sorted(out["labels"]) == ["CAM PED 10m", "CAM VEH 20m"], out["labels"]
    assert out["halo"] == "near", "the halo follows the nearest perceived object (10 m)"


def test_issue54_stale_camera_evidence_draws_nothing():
    person = {"kind": "pedestrian", "ahead_m": 9.85, "right_m": 1.0, "width_m": 0.5, "conf": 0.9}
    out = _run({"cmd": "boxes", "mode": "vision", "objects": [person], "age": 2000})
    assert out["labels"] == [] and out["halo"] == "" and out["reads"] == []


def test_issue54_privileged_boxes_say_they_are_the_truth():
    out = _run({"cmd": "boxes", "mode": "privileged", "objects": []})
    assert out["labels"] == ["TRUTH PED 12m"], out["labels"]
    assert out["halo"] == "watch"


def test_issue54_review_camera_boxes_are_placed_from_where_the_car_was_when_the_frame_was_taken():
    person = {"kind": "pedestrian", "ahead_m": 9.85, "right_m": 1.0, "width_m": 0.5, "conf": 0.9}
    out = _run({"cmd": "boxes", "mode": "vision", "objects": [person], "moved": 3.0})
    assert out["labels"] == ["CAM PED 7m"], "10 m when the frame was taken, 3 m driven since"


def test_issue54_review_a_person_seen_to_the_right_is_drawn_right_of_centre_and_junk_is_skipped():
    person = {"kind": "pedestrian", "ahead_m": 9.85, "right_m": 1.0, "width_m": 0.5, "conf": 0.9}
    junk = [None, {"kind": "constructor", "ahead_m": 5.0, "right_m": 0.0}, {"kind": "car", "ahead_m": "near", "right_m": 0.0}]
    out = _run({"cmd": "boxes", "mode": "vision", "objects": junk + [person]})
    assert out["labels"] == ["CAM PED 10m"]
    assert out["centres"][0] > 320, out["centres"]


def test_issue55_the_page_never_draws_from_the_planners_seeded_random():
    """Same seed, same drive: only the bundle consumes planRandom (30 s of steps, 0 draws)."""
    out = _run({"cmd": "rng"})
    assert out["wrapped"] is True, "the page's step wrapper ran (else 0 draws proves nothing)"
    assert out["time"] > 29.9
    assert out["draws"] == 0
    assert out["agents"] is False, "no ghost agents that nothing reads"
