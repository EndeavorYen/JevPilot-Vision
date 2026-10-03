"""Onboard camera frames read back and encoded off the main thread's critical path (#42 item 2).

The four renders stay synchronous (one instant of the world); the pixel read waits on a GPU fence
(three.js readRenderTargetPixelsAsync) and the JPEG is encoded by canvas.toBlob, which Chrome runs
off the main thread. Both fall back to the synchronous calls where the async ones are missing.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CAPTURE_JS = REPO / "jevpilot_vision" / "web" / "semif-capture.js"
LAYER_JS = REPO / "jevpilot_vision" / "web" / "semif-layer.js"
INDEX = REPO / "jevpilot_vision" / "web" / "index.html"

_FAKES = r"""
const C = require(%s);
const out = (v) => process.stdout.write(JSON.stringify(v));
const calls = [];
const asyncRenderer = { readRenderTargetPixelsAsync: (t, x, y, w, h, buf) => { calls.push('async'); buf.fill(7); return Promise.resolve(buf); },
  readRenderTargetPixels: (t, x, y, w, h, buf) => { calls.push('sync'); buf.fill(3); } };
const syncRenderer = { readRenderTargetPixels: (t, x, y, w, h, buf) => { calls.push('sync'); buf.fill(3); } };
class Reader { readAsDataURL(blob) { setTimeout(() => { this.result = 'data:image/jpeg;base64,' + blob.tag; this.onload(); }, 0); } }
globalThis.FileReader = Reader;
const blobCanvas = { toBlob(cb, type, q) { calls.push('toBlob:' + type + ':' + q); setTimeout(() => cb({ tag: 'BLOB' }), 0); }, toDataURL: () => 'data:sync' };
const plainCanvas = { toDataURL: (type, q) => { calls.push('toDataURL:' + type + ':' + q); return 'data:sync'; } };
const nullBlobCanvas = { toBlob(cb) { setTimeout(() => cb(null), 0); }, toDataURL: () => 'data:fallback' };
"""


def _node(body: str):
    script = _FAKES % json.dumps(str(CAPTURE_JS)) + body
    return json.loads(subprocess.check_output(["node", "-e", script], cwd=str(REPO)))


def test_pixels_are_read_through_the_gpu_fence_when_three_offers_it():
    got = _node("""
(async () => {
  const a = await C.readPixels(asyncRenderer, {}, 2, 1);
  const b = await C.readPixels(syncRenderer, {}, 2, 1);
  out({ a: Array.from(a), b: Array.from(b), calls });
})();""")
    assert got["a"] == [7] * 8 and got["b"] == [3] * 8
    assert got["calls"] == ["async", "sync"]


def test_pixels_go_to_the_encode_worker_by_transfer_and_come_back_as_jpeg():
    """toBlob and a main-thread convertToBlob wait for the main thread's idle time: about 1 s per
    frame in the running simulation (#42 measurement). A worker encodes in 8-50 ms, off the main
    thread; the pixels are transferred, not copied."""
    got = _node("""
(async () => {
  const sent = [];
  class FakeWorker { constructor(url) { this.url = url; } postMessage(msg, transfer) {
      sent.push({ url: this.url, w: msg.w, h: msg.h, q: msg.q, transferred: transfer && transfer[0] === msg.buf });
      setTimeout(() => this.onmessage({ data: { id: msg.id, url: 'data:image/jpeg;base64,W' + msg.id } }), 0); } }
  globalThis.Worker = FakeWorker; globalThis.OffscreenCanvas = function () {};
  const enc = C.createEncoder('/jevpilot/semif-encode-worker.js');
  const [a, b] = await Promise.all([enc.encode(new Uint8Array(8), 2, 1, 0.55), enc.encode(new Uint8Array(8), 2, 1, 0.7)]);
  out({ a, b, sent });
})();""")
    assert got["a"] == "data:image/jpeg;base64,W1" and got["b"] == "data:image/jpeg;base64,W2", "answers matched by id"
    assert got["sent"][0] == {"url": "/jevpilot/semif-encode-worker.js", "w": 2, "h": 1, "q": 0.55, "transferred": True}


def test_without_a_worker_the_pixels_are_encoded_on_a_canvas():
    got = _node("""
(async () => {
  delete globalThis.Worker;
  const painted = [];
  const canvas = { width: 0, height: 0, getContext: () => ({ createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }), putImageData: (img) => painted.push(Array.from(img.data)) }),
    toDataURL: (type, q) => 'data:fallback:' + type + ':' + q };
  const enc = C.createEncoder('/x.js', () => canvas);
  const url = await enc.encode(new Uint8Array([1, 1, 1, 1, 2, 2, 2, 2]), 1, 2, 0.6);
  out({ url, painted, size: [canvas.width, canvas.height] });
})();""")
    assert got["url"] == "data:fallback:image/jpeg:0.6"
    assert got["painted"] == [[2, 2, 2, 2, 1, 1, 1, 1]], "rows flipped: WebGL reads bottom-up"
    assert got["size"] == [1, 2]


def test_the_worker_flips_rows_and_encodes_with_offscreen_canvas():
    worker = (REPO / "jevpilot_vision" / "web" / "semif-encode-worker.js").read_text(encoding="utf-8")
    assert "convertToBlob" in worker and "FileReaderSync" in worker and "OffscreenCanvas" in worker
    got = json.loads(subprocess.check_output(["node", "-e", "const W = require(%s); process.stdout.write(JSON.stringify(Array.from(W.flipRows(new Uint8Array([1,1,1,1,2,2,2,2,3,3,3,3]), 1, 3))))" % json.dumps(str(REPO / "jevpilot_vision" / "web" / "semif-encode-worker.js"))], cwd=str(REPO)))
    assert got == [3, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 1]


def test_the_layer_renders_every_view_before_it_waits_and_queues_each_read_before_the_next_render():
    """The side cameras share one render target: three.js queues each read into a GPU buffer before
    its first await, so the read must be issued right after its own render."""
    js = LAYER_JS.read_text(encoding="utf-8")
    grab = js.split("async function grabSurround(", 1)[1].split("\n  }\n", 1)[0]
    assert "window.SEMIF_CAPTURE" in grab and "capture.readPixels(" in grab and "encoder.encode(" in grab
    first_await = grab.index("await ")
    renders = [i for i in range(len(grab)) if grab.startswith("renderToTarget(", i)]
    assert renders and all(i < first_await for i in renders), "every render before any await: one instant of the world"
    for a, b in zip(renders, renders[1:] + [first_await]):
        assert "readPixels(" in grab[a:b], "each read is issued before the next render reuses the target"


def test_the_page_loads_the_capture_helpers_before_the_layer():
    html = INDEX.read_text(encoding="utf-8")
    assert html.index("semif-capture.js") < html.index("semif-layer.js")


def test_the_pack_buffer_three_leaves_bound_is_unbound_before_the_wait():
    """three.js binds a PIXEL_PACK_BUFFER for the async read and keeps it bound through the fence
    wait; any synchronous readPixels in that window (the PIP) fails and paints black (#42 review)."""
    got = _node("""
(async () => {
  let bound = 'pbo';
  const gl = { PIXEL_PACK_BUFFER: 0x88EB, bindBuffer(target, buf) { if (target === 0x88EB) bound = buf; } };
  let boundDuringWait = null;
  const renderer = { getContext: () => gl,
    readRenderTargetPixelsAsync: (t, x, y, w, h, buf) => { bound = 'pbo'; return new Promise((r) => setTimeout(() => { boundDuringWait = bound; r(buf); }, 0)); } };
  await C.readPixels(renderer, {}, 1, 1);
  out({ boundDuringWait });
})();""")
    assert got["boundDuringWait"] is None


def test_the_front_camera_is_read_and_encoded_like_the_others():
    """#42 review M1: the front frame used to come from grabFrame() (sync read, toDataURL) on most
    captures; now every view goes through the async read and toBlob."""
    js = LAYER_JS.read_text(encoding="utf-8")
    grab = js.split("async function grabSurround(", 1)[1].split("\n  }\n", 1)[0]
    assert '["front", 0, FRONT_W, FRONT_H' in grab
    vision = js.split("async function visionTick(", 1)[1].split("\n  }\n\n", 1)[0]
    assert "grabFrame()" not in vision and "toDataURL" not in vision


def test_a_failed_read_never_leaves_an_unhandled_rejection_and_the_abort_signal_is_taken_first():
    js = LAYER_JS.read_text(encoding="utf-8")
    grab = js.split("async function grabSurround(", 1)[1].split("\n  }\n", 1)[0]
    assert ".catch(() => {})" in grab, "queued reads that are never awaited after a failure are handled"
    vision = js.split("async function visionTick(", 1)[1].split("\n  }\n\n", 1)[0]
    assert vision.index("const signal = visionPacer.signal();") < vision.index("grabSurround("), "the signal belongs to this request"
    assert "signal: signal" in vision


def test_a_job_the_worker_never_answers_fails_after_its_timeout():
    """#42 review M1: a hung encode would keep its grab pending forever, one more every 5 s."""
    got = _node("""
(async () => {
  class SilentWorker { postMessage() {} terminate() {} }
  globalThis.Worker = SilentWorker; globalThis.OffscreenCanvas = function () {};
  const enc = C.createEncoder('/w.js', null, { timeoutMs: 20 });
  let error = null;
  try { await enc.encode(new Uint8Array(4), 1, 1, 0.5); } catch (e) { error = e.message; }
  out({ error, waiting: enc.waiting() });
})();""")
    assert got == {"error": "encode timed out", "waiting": 0}


def test_a_failed_worker_is_terminated_and_later_frames_use_the_canvas():
    """#42 review M3 and L3."""
    got = _node("""
(async () => {
  let terminated = false, prevented = false, w = null;
  class BadWorker { constructor() { w = this; } postMessage() { setTimeout(() => this.onerror({ preventDefault() { prevented = true; } }), 0); } terminate() { terminated = true; } }
  globalThis.Worker = BadWorker; globalThis.OffscreenCanvas = function () {};
  const canvas = { getContext: () => ({ createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }), putImageData() {} }), toDataURL: () => 'data:canvas' };
  const enc = C.createEncoder('/w.js', () => canvas);
  let first = null; try { await enc.encode(new Uint8Array(4), 1, 1, 0.5); } catch (e) { first = e.message; }
  const second = await enc.encode(new Uint8Array(4), 1, 1, 0.5);
  out({ first, second, terminated, prevented, messageerror: typeof w.onmessageerror });
})();""")
    assert got == {"first": "encode worker failed", "second": "data:canvas", "terminated": True, "prevented": True, "messageerror": "function"}


def test_encodes_already_queued_stay_quiet_if_a_later_read_fails():
    js = LAYER_JS.read_text(encoding="utf-8")
    grab = js.split("async function grabSurround(", 1)[1].split("\n  }\n", 1)[0]
    queued = grab.split("encodes.push(", 1)[1].split("\n", 1)[0]
    assert ".catch(" in grab.split("encodes.push(", 1)[1].split("await Promise.all", 1)[0], queued
