"""The nearest point on a route from a grid, the same as the bundle's full scan (#42 item 4).

The bundle's own scan (the planner worker's `l`, the page's `p`) is taken from the shipped asset,
minus the coast patch that hands full-route searches to SEMIF_NEAREST, and run against it in node
on routes like the coast's (1 m apart, thousands of points), on routes that cross themselves, on
zero-length segments and on query points exactly on vertices (ties): every field must be equal.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import test_coast_patches as tcp

WEB = Path(__file__).resolve().parents[1] / "jevpilot_vision" / "web"

_SCRIPT = r"""
require(process.argv[1]);
const nearest = globalThis.SEMIF_NEAREST;
const e = (e, t, n) => Math.max(t, Math.min(n, e));             // the worker's clamp
const a = (e, t) => Math.atan2(t.x - e.x, e.z - t.z);            // the worker's heading
const full = eval("(" + process.argv[2] + ")");                  // the worker's own scan, unpatched
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const withS = (pts) => { let s = 0; return pts.map((p, i) => { if (i) s += Math.hypot(p.x - pts[i - 1].x, p.z - pts[i - 1].z); return { ...p, s }; }); };
const walk = []; { let x = 0, z = 0, h = 0; for (let i = 0; i < 3000; i++) { h += (rnd() - 0.5) * 0.08; x += Math.sin(h); z -= Math.cos(h); walk.push({ x, z }); } }
const eight = []; for (let i = 0; i <= 2000; i++) { const t = (i / 2000) * Math.PI * 2; eight.push({ x: 300 * Math.sin(t), z: 150 * Math.sin(2 * t) }); }
const dupes = []; for (let i = 0; i < 400; i++) { const p = { x: (i >> 1) * 1.0, z: 0 }; dupes.push(p, { ...p }); }
const grid = []; for (let i = 0; i < 60; i++) grid.push({ x: (i % 2) * 40, z: Math.floor(i / 2) * 8 });  // back and forth: parallel legs
const routes = { walk: withS(walk), eight: withS(eight), dupes: withS(dupes), grid: withS(grid) };
const out = {};
for (const [name, pts] of Object.entries(routes)) {
  let same = 0, differ = [];
  const queries = [];
  for (let k = 0; k < 600; k++) { const p = pts[Math.floor(rnd() * pts.length)]; queries.push({ x: p.x + (rnd() - 0.5) * 40, z: p.z + (rnd() - 0.5) * 40 }); }
  for (let k = 0; k < 60; k++) queries.push({ x: (rnd() - 0.5) * 1000, z: (rnd() - 0.5) * 1000 });  // far from the route
  for (let k = 0; k < 60; k++) { const p = pts[Math.floor(rnd() * pts.length)]; queries.push({ x: p.x, z: p.z }); }  // on a vertex: ties
  queries.push({ x: 20, z: 4 }, { x: 0.5, z: 0 });  // equidistant from parallel legs / duplicated points
  for (const q of queries) {
    const want = JSON.stringify(full(q, pts)), got = JSON.stringify(nearest(q, pts, e, a));
    if (want === got) same++; else if (differ.length < 3) differ.push({ q, want, got });
  }
  out[name] = { same, total: queries.length, differ };
}
// as the planner asks: the car (and its forward simulation) is on or beside its route
const near = Array.from({ length: 2000 }, (_, k) => { const p = routes.walk[(k * 37) % routes.walk.length]; return { x: p.x + 1.5, z: p.z - 0.7 }; });
const t0 = process.hrtime.bigint(); for (const q of near) full(q, routes.walk);
const t1 = process.hrtime.bigint(); for (const q of near) nearest(q, routes.walk, e, a);
const t2 = process.hrtime.bigint();
out.speed = { fullUs: Number(t1 - t0) / 2000 / 1000, gridUs: Number(t2 - t1) / 2000 / 1000 };
process.stdout.write(JSON.stringify(out));
"""


def _worker_scan() -> str:
    """The worker's nearest-point function as the bundle shipped it (the patch's prefix removed)."""
    entry = next(p for p in tcp.COAST_PATCHES if p[0] == "coast-nearest-worker")
    text = (tcp.ASSETS / tcp.WORKER).read_text(encoding="utf-8")
    start = text.index(entry[3])
    end = text.index("return i}", start) + len("return i}")
    return text[start:end].replace(entry[3], entry[2])


@pytest.mark.skipif(shutil.which("node") is None, reason="node runs the bundle's own scan")
def test_issue42_the_grid_finds_the_same_nearest_point_as_the_bundles_full_scan():
    done = subprocess.run(["node", "-e", _SCRIPT, str(WEB / "semif-route-index.js"), _worker_scan()],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    for name in ("walk", "eight", "dupes", "grid"):
        assert out[name]["same"] == out[name]["total"], (name, out[name]["differ"])
    assert out["speed"]["gridUs"] * 5 < out["speed"]["fullUs"], out["speed"]


def test_issue42_only_the_coasts_full_route_searches_take_the_grid():
    main = (tcp.ASSETS / tcp.MAIN).read_text(encoding="utf-8")
    worker = (tcp.ASSETS / tcp.WORKER).read_text(encoding="utf-8")
    assert "if(!n&&globalThis.SEMIF_NEAREST&&String(globalThis.SEMIF_SIM?.world?.type??``).startsWith(`coast`))" in main
    assert "if(!r&&globalThis.SEMIF_NEAREST&&String(globalThis.SEMIF_WORLD_TYPE??``).startsWith(`coast`))" in worker
    assert re.search(r'semif-route-index\.js\?v=HASH', (WEB / "index.html").read_text(encoding="utf-8"))
    assert 'import"/jevpilot/semif-route-index.js?v=HASH";' in tcp.WORKER_IMPORT
