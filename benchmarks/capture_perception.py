"""Capture onboard front frames with simulator ground truth, for benchmarks/eval_perception.py (#75).

Ground truth is read only here, to score perception; nothing that drives reads it. The page is
driven by its own autopilot in Vision (map) on the mock arbiter. Each frame the page sends to
/v1/vision is kept with the truth read the moment the request is built (a few tens of ms after
the render: the frame's encode time).

    python benchmarks/capture_perception.py <out_dir> [--seeds 895794 31337] [--routes festival harbour]
        [--seconds 90] [--base http://127.0.0.1:8768]

Writes <out_dir>/<seed>-<route>/fNNNN.jpg and truth.json:
[{"file", "t", "grab_ms", "ego_speed", "yaw_rps", "near": [{"type", "id", "ahead", "right", "closing", "depth"}]}]
in the ego frame (metres; closing in m/s along our heading, positive when the gap shrinks).
Tuning seeds only (benchmarks/closed_loop_seeds.json): this is for looking into perception.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import closed_loop as cl  # noqa: E402

# The truth of every car and walker within 60 m, in the ego frame, when a vision request is built.
_HOOK = r"""
(() => {
  if (window.__cap) return 1;
  window.__cap = [];
  const stringify = JSON.stringify;
  JSON.stringify = function (value, ...rest) {
    try {
      if (value && value.frames && value.frames.front && "t_ms" in value) {
        const s = window.SEMIF_SIM, p = s.player, f = [Math.sin(p.heading), -Math.cos(p.heading)];
        const r = [Math.cos(p.heading), Math.sin(p.heading)];
        const ve = [f[0] * p.speed, f[1] * p.speed];
        const near = [];
        for (const o of [...s.traffic, ...s.pedestrians]) {
          const dx = o.x - p.x, dz = o.z - p.z;
          if (Math.hypot(dx, dz) > 60) continue;
          const sp = o.speed || 0, h = o.heading || 0;
          const vo = [Math.sin(h) * sp, -Math.cos(h) * sp];
          near.push({ type: o.type === "pedestrian" ? "pedestrian" : o.type === "motorcycle" ? "motorcycle" : "car", id: o.id,
            ahead: dx * f[0] + dz * f[1], right: dx * r[0] + dz * r[1],
            closing: -((vo[0] - ve[0]) * f[0] + (vo[1] - ve[1]) * f[1]), depth: o.depth || 0 });
        }
        window.__cap.push({ t: value.t_ms / 1000, grab_ms: Math.round(performance.now() - value.t_ms), ego_speed: p.speed, yaw_rps: value.yaw_rps ?? 0,
          front: value.frames.front, near });
      }
    } catch (_) {}
    return stringify.call(this, value, ...rest);
  };
  return 1;
})()
"""
_TAKE = "(() => { const out = window.__cap.splice(0, window.__cap.length); return JSON.stringify(out); })()"


def capture(base: str, seed: int, route: str, seconds: int, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    tab = cl.open_tab(base)
    rows, n = [], 0
    try:
        url = f"{base.rstrip('/')}/jevpilot/?minimal=0&candidates=selected&traffic=low&people=low&seed={seed}&world=coast:{route}&mode=vision-map&gfx=medium"
        cl._js(tab["target"], f"(location.href = {json.dumps(url)}, 1)", timeout=30)
        time.sleep(2)
        cl._js(tab["target"], "(async () => { " + cl._READY + "; return 1; })()", timeout=120)
        cl._js(tab["target"], _HOOK, timeout=30)
        cl._js(tab["target"], "(() => { if (!window.SEMIF_SIM.autopilot) document.querySelector('#autopilot').click(); return 1; })()", timeout=30)
        end = time.time() + seconds
        while time.time() < end:
            time.sleep(min(5.0, max(0.0, end - time.time())))
            taken = cl._js(tab["target"], _TAKE, timeout=60)  # _js already parses the JSON
            for item in json.loads(taken) if isinstance(taken, str) else taken:
                name = f"f{n:04d}.jpg"
                (out / name).write_bytes(base64.b64decode(item.pop("front").split(",", 1)[1]))
                rows.append({"file": name, **item})
                n += 1
    finally:
        cl.close_tab(tab, wait=True)
    (out / "truth.json").write_text(json.dumps(rows), encoding="utf-8")
    return n


def main() -> None:
    seeds = json.loads(cl.SEEDS_FILE.read_text(encoding="utf-8"))["tuning"]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--seeds", nargs="+", type=int, default=seeds[:2])
    ap.add_argument("--routes", nargs="+", default=["festival", "harbour"], choices=cl.ROUTES)
    ap.add_argument("--seconds", type=int, default=90)
    ap.add_argument("--base", default="http://127.0.0.1:8768")
    args = ap.parse_args()
    bad = [s for s in args.seeds if s not in seeds]
    if bad:
        raise SystemExit(f"tuning seeds only (benchmarks/closed_loop_seeds.json): {bad}")
    cl.ensure_anchor(args.base)
    for seed in args.seeds:
        for route in args.routes:
            n = capture(args.base, seed, route, args.seconds, Path(args.out).resolve() / f"{seed}-{route}")
            print(f"seed {seed} {route}: {n} frames")


if __name__ == "__main__":
    main()
