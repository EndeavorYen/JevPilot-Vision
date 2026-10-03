"""Main-view and onboard-camera cost on the coast, per graphics quality
(docs/superpowers/specs/2026-10-03-visual-quality-design.md §4.4).

Opens /jevpilot/ in one background Chrome tab (chrome-cdp-ex, CDP_PORT 9222), engages the autopilot
from the festival at a fixed hour, waits, then reads window.SEMIF_PERF. The canvas size is written
beside the numbers: GPU time scales with it, so compare runs made at the same size.

    python benchmarks/perf_baseline.py --gfx medium high --out D:/evals/2026-10-03/perf.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from closed_loop import _READY, _cdp, _js, open_tab  # noqa: E402

SEED = 895794  # the seed of docs/visual/new-ui and docs/visual/mode-indicator, so the views match
WARMUP_S = 10  # shaders compile and textures upload in the first seconds


def page_url(base: str, gfx: str) -> str:
    # candidates=selected: a fan remembered in this Chrome profile would add lines and worker load (#19).
    # traffic/people=low: the coast the baseline was first measured on (#22).
    return (f"{base.rstrip('/')}/jevpilot/?minimal=0&candidates=selected&traffic=low&people=low&seed={SEED}&world=coast:festival&mode=privileged"
            f"&gfx={gfx}&time=16:30&daycycle=0")


_ENGAGE = "(() => { if (!window.SEMIF_SIM.autopilot) document.querySelector('#autopilot').click(); return 1; })()"
_READ = (
    "JSON.stringify((() => { const c = document.querySelector('canvas'); const gl = c && (c.getContext('webgl2') || c.getContext('webgl'));"
    " const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');"
    " return { snapshot: window.SEMIF_PERF.snapshot(), canvas: c ? [c.width, c.height] : null, dpr: devicePixelRatio,"
    " gpu: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null, quality: window.SEMIF_GFX && window.SEMIF_GFX.quality,"
    " density: (window.SEMIF_SIM && window.SEMIF_SIM.world && window.SEMIF_SIM.world.density) || null }; })())"
)


def measure(target: str, base: str, gfx: str, seconds: int) -> Dict[str, Any]:
    url = page_url(base, gfx)
    _cdp("nav", target, url)
    _js(target, _READY, timeout=150)
    _js(target, _ENGAGE)
    time.sleep(WARMUP_S)
    _js(target, "(window.SEMIF_PERF.reset(), 1)")
    time.sleep(seconds)
    got = _js(target, _READ)
    if isinstance(got, str):
        got = json.loads(got)
    if got.get("quality") != gfx:
        raise RuntimeError(f"asked for {gfx}, the page drew {got.get('quality')}")
    if got.get("density") is not None and got["density"] != {"traffic": "low", "people": "low"}:  # None: before #22
        raise RuntimeError(f"asked for low density, the page drew {got['density']}")
    return {**got["snapshot"], "canvas": got["canvas"], "dpr": got["dpr"], "gpu": got["gpu"],
            "quality_seen": got["quality"], "density_seen": got.get("density"), "url": url, "seconds": seconds}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gfx", nargs="+", choices=("medium", "high"), default=["medium", "high"])
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--base", default="http://localhost:8768")
    ap.add_argument("--out", type=Path, required=True, help="JSON results (absolute path)")
    args = ap.parse_args(argv)
    if not args.out.is_absolute():
        ap.error("--out must be an absolute path")
    target = open_tab(args.base)
    results: Dict[str, Any] = {}
    try:
        for gfx in args.gfx:
            results[gfx] = measure(target, args.base, gfx, args.seconds)
            print(json.dumps({gfx: results[gfx]}), flush=True)
    finally:
        _cdp("nav", target, f"{args.base.rstrip('/')}/openapi.json")  # stop the drive
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
