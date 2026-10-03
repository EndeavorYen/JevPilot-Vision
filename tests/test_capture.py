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


def test_jpeg_is_encoded_by_to_blob_and_falls_back_to_to_data_url():
    got = _node("""
(async () => {
  const a = await C.encodeJpeg(blobCanvas, 0.55);
  const b = await C.encodeJpeg(plainCanvas, 0.7);
  const c = await C.encodeJpeg(nullBlobCanvas, 0.7);
  out({ a, b, c, calls });
})();""")
    assert got["a"] == "data:image/jpeg;base64,BLOB"
    assert got["b"] == "data:sync"
    assert got["c"] == "data:fallback", "a canvas that cannot make a blob still yields a frame"
    assert got["calls"] == ["toBlob:image/jpeg:0.55", "toDataURL:image/jpeg:0.7"]


def test_the_layer_renders_every_view_before_it_waits_and_queues_each_read_before_the_next_render():
    """The side cameras share one render target: three.js queues each read into a GPU buffer before
    its first await, so the read must be issued right after its own render."""
    js = LAYER_JS.read_text(encoding="utf-8")
    grab = js.split("async function grabSurround(", 1)[1].split("\n  }\n", 1)[0]
    assert "window.SEMIF_CAPTURE" in grab and "capture.readPixels(" in grab and "capture.encodeJpeg(" in grab
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
