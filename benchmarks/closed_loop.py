"""Closed-loop evaluation on the coast map (#28): drive many seeds, report rates, not anecdotes.

Each run opens /jevpilot/ in one background Chrome tab (chrome-cdp-ex, CDP_PORT 9222), engages the
autopilot for N seconds and reads the simulator's counters. Runs go one at a time: the server's
vision slot is shared, so two tabs would mix their camera evidence.

Seeds come from closed_loop_seeds.json: tune on `tuning`, report on `held_out` (see its rule).
Results are JSONL, one run per line, and a rerun with the same file only drives what is missing.

    python benchmarks/closed_loop.py --set held_out --out D:/evals/2026-10-03/runs.jsonl
    python benchmarks/closed_loop.py --report D:/evals/2026-10-03/runs.jsonl
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
SEEDS_FILE = HERE / "closed_loop_seeds.json"
ROUTES = ("festival", "harbour", "pass")
MODES = ("privileged", "vision")
CDP = os.environ.get("CHROME_CDP", str(Path.home() / ".claude/skills/chrome-cdp-ex/bin/chrome-cdp"))

# Where the mock arbiter's stopping constants come from (demo/server.py); every report repeats it,
# so a reader knows they were measured on one machine, not derived.
CONSTANTS_NOTE = (
    "Mock constants (demo/server.py): DECISION_GAP_S = 1.5 s and STOP_DECEL_MPS2 = 2.5 m/s^2 were "
    "measured in one background Chrome on one machine (#18); they are not derived."
)


# ---- Seeds, plans, results ------------------------------------------------------------------------

def load_seeds(path: Path = SEEDS_FILE) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def plan_runs(seeds: Iterable[int], routes: Iterable[str], modes: Iterable[str], seconds: int, lag_ms: int) -> List[Dict[str, Any]]:
    return [
        {"seed": int(seed), "route": route, "mode": mode, "seconds": int(seconds), "lag_ms": int(lag_ms)}
        for seed in seeds
        for route in routes
        for mode in modes
    ]


def _key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return (row.get("seed"), row.get("route"), row.get("mode"), row.get("seconds"), row.get("lag_ms", 0))


def read_rows(path: Path) -> List[Dict[str, Any]]:
    """Every complete JSON line; a line cut off by an interruption is skipped."""
    rows = []
    if not Path(path).exists():
        return rows
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def pending(plan: List[Dict[str, Any]], done: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {_key(r) for r in done if r.get("ok")}
    return [run for run in plan if _key(run) not in seen]


def page_url(base: str, run: Dict[str, Any]) -> str:
    url = f"{base.rstrip('/')}/jevpilot/?minimal=0&seed={run['seed']}&world=coast:{run['route']}&mode={run['mode']}"
    if run.get("lag_ms"):
        url += f"&lag_ms={int(run['lag_ms'])}"
    return url


# ---- Statistics ------------------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """95% Wilson score interval for k events in n trials: honest about small n (0/30 is not 0%)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        mode = row.get("mode", "?")
        s = out.setdefault(mode, {"runs": 0, "failed_runs": 0, "distance_km": 0.0, "runs_with_red_light": 0,
                                  "red_light_events": 0, "runs_with_collision": 0, "collision_events": 0,
                                  "pedestrian_casualties": 0, "crashes": 0, "lag_ms": set(), "seconds": set()})
        if not row.get("ok"):
            s["failed_runs"] += 1
            continue
        s["runs"] += 1
        s["distance_km"] += float(row.get("distance_m") or 0.0) / 1000.0
        red = int(row.get("red_light") or 0)
        hits = int(row.get("collisions") or 0)
        s["red_light_events"] += red
        s["runs_with_red_light"] += 1 if red else 0
        s["collision_events"] += hits
        s["runs_with_collision"] += 1 if hits or row.get("crash") else 0
        s["pedestrian_casualties"] += int(row.get("pedestrian_casualties") or 0)
        s["crashes"] += 1 if row.get("crash") else 0
        s["lag_ms"].add(int(row.get("lag_ms") or 0))
        s["seconds"].add(int(row.get("seconds") or 0))
    for s in out.values():
        km = s["distance_km"]
        s["red_light_per_km"] = s["red_light_events"] / km if km else None
        s["collisions_per_km"] = s["collision_events"] / km if km else None
        s["lag_ms"] = sorted(s["lag_ms"])
        s["seconds"] = sorted(s["seconds"])
    return out


def _share(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} runs (95% {lo * 100:.0f}-{hi * 100:.0f}%)"


def report(summary: Dict[str, Dict[str, Any]]) -> str:
    lines = []
    for mode in sorted(summary):
        s = summary[mode]
        n = s["runs"]
        per_km = lambda v: "n/a" if v is None else f"{v:.2f}/km"
        lines.append(
            f"{mode}: {n} runs, {s['distance_km']:.1f} km driven"
            + (f", {s['failed_runs']} failed to run" if s["failed_runs"] else "")
            + f" (lag {s['lag_ms']} ms, {s['seconds']} s each)"
        )
        lines.append(f"  red light {_share(s['runs_with_red_light'], n)}; {s['red_light_events']} events, {per_km(s['red_light_per_km'])}")
        lines.append(f"  collision {_share(s['runs_with_collision'], n)}; {s['collision_events']} events, {per_km(s['collisions_per_km'])}")
        lines.append(f"  pedestrian casualties {s['pedestrian_casualties']}; crashes that ended the drive {s['crashes']}")
    lines.append(CONSTANTS_NOTE)
    return "\n".join(lines)


# ---- Driving one run in the browser ---------------------------------------------------------------

def _cdp(*args: str, timeout: int = 300) -> str:
    env = {**os.environ, "CDP_PORT": os.environ.get("CDP_PORT", "9222"), "CDP_BACKGROUND": "1"}
    out = subprocess.run(["node", CDP, *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if out.returncode:
        raise RuntimeError((out.stdout[-800:] + out.stderr[-800:]).strip())
    return out.stdout


def _js(target: str, code: str, timeout: int = 120) -> Any:
    raw = _cdp("eval", target, "--raw", "--b64", base64.b64encode(code.encode()).decode(), timeout=timeout).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


_READY = (
    "await new Promise((r, x) => { const t0 = Date.now(); const t = setInterval(() => {"
    " if (window.SEMIF_SIM?.player?.route && document.getElementById('scene-loader')?.hidden) { clearInterval(t); r(1); }"
    " else if (Date.now() - t0 > 90000) { clearInterval(t); x(new Error('the drive did not load in 90 s')); } }, 250); })"
)
_START = (
    "(() => { const s = window.SEMIF_SIM; window.__eval = { minGap: 99 };"
    " window.__evalTimer = setInterval(() => { for (const o of [...s.traffic, ...s.pedestrians]) {"
    " const d = Math.hypot(o.x - s.player.x, o.z - s.player.z); if (d < window.__eval.minGap) window.__eval.minGap = d; } }, 250);"
    " if (!s.autopilot) document.querySelector('#autopilot').click(); return 1; })()"
)
_READ = (
    "JSON.stringify((() => { clearInterval(window.__evalTimer); const s = window.SEMIF_SIM;"
    " return { mode_seen: window.SEMIF_DRIVE_MODE, sim_time_s: Math.round(s.time), distance_m: Math.round(s.distance),"
    " autopilot: !!s.autopilot, crash: !!s.crash, collisions: s.collisions || 0, vehicle_collisions: s.vehicleCollisions || 0,"
    " pedestrian_casualties: s.pedestrianCasualties || 0, red_light: s.redLightViolations || 0, violations: s.violations || 0,"
    " min_gap_m: +window.__eval.minGap.toFixed(1), events: s.events.slice(0, 12).map((e) => e.time.toFixed(0) + ' ' + e.text) }; })())"
)


def find_tab(base: str) -> str:
    tabs = [line.split()[0] for line in _cdp("list").splitlines() if "/jevpilot" in line]
    if tabs:
        for other in tabs[1:]:
            _cdp("nav", other, f"{base.rstrip('/')}/openapi.json")  # one simulation at a time
        return tabs[0]
    _cdp("open", f"{base.rstrip('/')}/jevpilot/")
    return [line.split()[0] for line in _cdp("list").splitlines() if "/jevpilot" in line][0]


def drive(target: str, base: str, run: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(run, started=time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        _cdp("nav", target, page_url(base, run))
        _js(target, _READY, timeout=150)
        time.sleep(3)
        _js(target, _START)
        time.sleep(run["seconds"])
        got = _js(target, _READ)
        if isinstance(got, str):
            got = json.loads(got)
        row.update(got, ok=got.get("mode_seen") == run["mode"])
        if not row["ok"]:
            row["error"] = f"page drove in mode {got.get('mode_seen')!r}"
    except Exception as err:  # a run that could not be driven is recorded, never counted as a good drive
        row.update(ok=False, error=str(err)[:300])
    return row


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", choices=("tuning", "held_out"), default="tuning")
    ap.add_argument("--seeds", type=int, nargs="*", help="a subset of the chosen set")
    ap.add_argument("--routes", nargs="*", default=list(ROUTES))
    ap.add_argument("--modes", nargs="*", default=list(MODES))
    ap.add_argument("--seconds", type=int, default=150)
    ap.add_argument("--lag-ms", type=int, default=0)
    ap.add_argument("--base", default="http://localhost:8768")
    ap.add_argument("--out", type=Path, help="JSONL results (absolute path); reruns resume")
    ap.add_argument("--report", type=Path, help="only summarise an existing results file")
    args = ap.parse_args(argv)

    if args.report:
        print(report(summarize(read_rows(args.report))))
        return 0
    if not args.out or not args.out.is_absolute():
        ap.error("--out must be an absolute path")
    chosen = load_seeds()[args.set]
    seeds = [s for s in chosen if not args.seeds or s in args.seeds]
    if args.seeds and set(args.seeds) - set(chosen):
        ap.error(f"seeds {sorted(set(args.seeds) - set(chosen))} are not in the {args.set} set")
    plan = plan_runs(seeds, args.routes, args.modes, args.seconds, args.lag_ms)
    todo = pending(plan, read_rows(args.out))
    print(f"{len(plan)} runs planned ({args.set}), {len(plan) - len(todo)} already in {args.out}; "
          f"about {len(todo) * (args.seconds + 25) / 60:.0f} min to go", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    target = find_tab(args.base)
    for i, run in enumerate(todo, 1):
        row = drive(target, args.base, run)
        row["set"] = args.set
        with args.out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"[{i}/{len(todo)}] seed {run['seed']} {run['route']}/{run['mode']}: "
              + (f"{row.get('distance_m')} m, red {row.get('red_light')}, collisions {row.get('collisions')}"
                 if row["ok"] else f"FAILED {row.get('error')}"), flush=True)
    print(report(summarize(read_rows(args.out))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
