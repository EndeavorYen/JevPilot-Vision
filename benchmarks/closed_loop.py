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
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
SEEDS_FILE = HERE / "closed_loop_seeds.json"
ROUTES = ("festival", "harbour", "pass", "coast", "highway")  # the coast map's start points
MODES = ("privileged", "vision", "heuristic")
DEFAULT_ROUTES = ("festival", "harbour", "pass")
DEFAULT_MODES = ("privileged", "vision")
# The bundle drops a decision that arrives more than 1.8 s after it asked, injected lag included;
# beyond this the stress only parks the car (semif-layer.js caps ?lag_ms= the same).
MAX_LAG_MS = 1200
# A run counts only if the simulation really ran most of it (a hidden tab does not step).
MIN_SIM_SHARE = 0.8
# A car that averaged less than this never really drove: a stall is reported, not a clean run.
STALL_MPS = 1.0
MIN_SECONDS = 30
CDP = os.environ.get("CHROME_CDP", str(Path.home() / ".claude/skills/chrome-cdp-ex/bin/chrome-cdp"))

# Where the mock arbiter's stopping constants come from (demo/server.py); every report repeats it,
# so a reader knows they were measured on one machine, not derived.
CONSTANTS_NOTE = (
    "Mock constants (demo/server.py): DECISION_GAP_S = 1.5 s and STOP_DECEL_MPS2 = 2.5 m/s^2 were "
    "measured in one background Chrome on one machine (#18); they are not derived."
)


# ---- Seeds, plans, results ------------------------------------------------------------------------

def load_seeds(path: Path = SEEDS_FILE) -> Dict[str, Any]:
    """The seed sets, refusing a file that breaks its own rule (held_out apart from the rest)."""
    seeds = json.loads(Path(path).read_text(encoding="utf-8"))
    held = set(seeds.get("held_out", []))
    clash = held & (set(seeds.get("tuning", [])) | set(seeds.get("debugged", [])))
    if clash:
        raise ValueError(f"held_out seeds {sorted(clash)} are also tuning or debugged seeds")
    return seeds


def current_rows(rows: List[Dict[str, Any]], seeds: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Rows still valid under today's seed file: a held_out row whose seed has since been looked
    into (moved to debugged, or out of held_out) no longer reports as held out."""
    held = set(seeds.get("held_out", [])) - set(seeds.get("debugged", []))
    kept, dropped = [], []
    for row in rows:
        # Rows from before seed sets and outcomes were recorded do not say enough to be counted.
        unknown = row.get("set") not in ("tuning", "held_out") or (row.get("ok") and "stalled" not in row)
        stale = unknown or (row.get("set") == "held_out" and row.get("seed") not in held)
        (dropped if stale else kept).append(row)
    return kept, dropped


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


def _complete_row(row: Dict[str, Any]) -> bool:
    """An ok row written under the current rules (with its outcomes)."""
    return bool(row.get("ok")) and "stalled" in row


def pending(plan: List[Dict[str, Any]], done: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {_key(r) for r in done if _complete_row(r)}
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


def latest(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per run. A run that was driven keeps its first result: what the car did is never
    replaced by a luckier retry. Only a run that could not be driven (setup failure) is replaced
    by a later attempt."""
    chosen: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for row in rows:
        key = (row.get("set"),) + _key(row)
        held = chosen.get(key)
        if held is None or not held.get("ok"):
            chosen[key] = row
    return list(chosen.values())


Group = Tuple[Any, Any, Any, Any]  # (set, mode, seconds, lag_ms)


def _reason_kind(reason: str) -> str:
    """Failure reasons grouped by kind (numbers dropped), so a pattern reads as one line."""
    return re.sub(r"-?\d+(\.\d+)?", "N", reason)


def summarize(rows: List[Dict[str, Any]]) -> Dict[Group, Dict[str, Any]]:
    """Per (set, mode, seconds, lag): only runs made the same way are pooled. A run that did not
    drive (failed, autopilot off, hidden tab, wrong mode/route/lag) is counted apart with its reason,
    never as a good drive. Collisions end a drive, so collisions per km are crashes per km."""
    out: Dict[Group, Dict[str, Any]] = {}

    def group_of(row: Dict[str, Any]) -> Group:
        return (row.get("set", "?"), row.get("mode", "?"), int(row.get("seconds") or 0), int(row.get("lag_ms") or 0))

    def new() -> Dict[str, Any]:
        return {"runs": 0, "attempts": 0, "retried": 0, "failed_runs": 0, "failures": {}, "never_driven": [],
                "distance_km": 0.0, "runs_with_red_light": 0, "red_light_events": 0, "runs_with_collision": 0,
                "collision_events": 0, "pedestrian_casualties": 0, "crashes": 0, "runs_disengaged": 0,
                "runs_stalled": 0, "runs_broke": 0, "runs_unreadable": 0, "tab_check_failed": 0, "decision_failures": 0,
                "drove": 0, "drove_with_red_light": 0, "drove_with_collision": 0}

    # Every attempt is visible: a run that needed retries says so.
    failed_keys = set()
    for row in rows:
        s = out.setdefault(group_of(row), new())
        s["attempts"] += 1
        if not row.get("ok"):
            failed_keys.add((row.get("set"),) + _key(row))
    for row in latest(rows):
        s = out.setdefault(group_of(row), new())
        if not row.get("ok"):
            s["failed_runs"] += 1
            reason = _reason_kind(str(row.get("error") or "unknown"))
            s["failures"][reason] = s["failures"].get(reason, 0) + 1
            s["never_driven"].append(row.get("seed"))
            continue
        if (row.get("set"),) + _key(row) in failed_keys:
            s["retried"] += 1
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
        s["runs_disengaged"] += 1 if row.get("disengaged") else 0
        s["runs_stalled"] += 1 if row.get("stalled") else 0
        s["runs_broke"] += 1 if row.get("broke") else 0
        s["runs_unreadable"] += 1 if row.get("unreadable") else 0
        s["tab_check_failed"] += 1 if row.get("tab_check") == "failed" else 0
        s["decision_failures"] += 1 if row.get("decision_failures") or row.get("server_ok") is False else 0
        # Violation rates are over runs that moved: a car that never moved commits none. A run that
        # ran a red light and then gave up (or broke) still ran it. A drive whose result could not be
        # read is unknown, not clean: it is left out and counted on its own.
        if not row.get("stalled") and not row.get("unreadable"):
            s["drove"] += 1
            s["drove_with_red_light"] += 1 if red else 0
            s["drove_with_collision"] += 1 if hits or row.get("crash") else 0
    for s in out.values():
        s["never_driven"] = sorted(x for x in s["never_driven"] if x is not None)
        km = s["distance_km"]
        s["red_light_per_km"] = s["red_light_events"] / km if km else None
        s["collisions_per_km"] = s["collision_events"] / km if km else None
    return out


def _share(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} runs (95% {lo * 100:.0f}-{hi * 100:.0f}%)"


def report(summary: Dict[Group, Dict[str, Any]]) -> str:
    lines = []
    for group in sorted(summary, key=lambda g: tuple(str(x) for x in g)):
        seed_set, mode, seconds, lag = group
        s = summary[group]
        n = s["runs"]
        per_km = lambda v: "n/a" if v is None else f"{v:.2f}/km"
        lines.append(f"{seed_set} · {mode} · {seconds} s · lag {lag} ms: {n} runs, {s['distance_km']:.1f} km driven, "
                     f"{s['attempts']} attempts ({s['retried']} retried after a setup failure)")
        if s["failed_runs"]:
            why = "; ".join(f"{k} ×{v}" for k, v in sorted(s["failures"].items()))
            lines.append(f"  could not be driven {s['failed_runs']} (setup, left out of the rates): {why}; "
                         f"never driven: seeds {s['never_driven']}")
        lines.append(f"  autopilot gave up {_share(s['runs_disengaged'], n)}; car did not move {_share(s['runs_stalled'], n)}; "
                     f"drive broke (page stopped) {_share(s['runs_broke'], n)}; result unreadable {_share(s['runs_unreadable'], n)}")
        notes = []
        if s["decision_failures"]:
            notes.append(f"decision service failed during {s['decision_failures']} (kept: the car had moved)")
        if s["tab_check_failed"]:
            notes.append(f"tab check could not be made for {s['tab_check_failed']}")
        if notes:
            lines.append("  " + "; ".join(notes))
        d = s["drove"]
        moved = lambda k: _share(k, d).replace(" runs", " runs that moved", 1)
        lines.append(f"  red light {moved(s['drove_with_red_light'])} · {_share(s['runs_with_red_light'], n).replace(' runs', ' of all runs', 1)}"
                     f"; {s['red_light_events']} events, {per_km(s['red_light_per_km'])}")
        lines.append(f"  collision {moved(s['drove_with_collision'])} · {_share(s['runs_with_collision'], n).replace(' runs', ' of all runs', 1)}"
                     f"; {s['collision_events']} events, {per_km(s['collisions_per_km'])}")
        lines.append(f"  of those, pedestrians {s['pedestrian_casualties']}; a collision ends the drive")
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
    "(() => { const s = window.SEMIF_SIM; window.__eval = { minGap: 99, t0: s.time, failures: 0 };"
    " const toast = document.getElementById('toast'); if (toast) new MutationObserver(() => {"
    " if (/failed requests/i.test(toast.textContent || '')) window.__eval.failures += 1; })"
    ".observe(toast, { childList: true, characterData: true, subtree: true });"
    " window.__evalTimer = setInterval(() => { for (const o of [...s.traffic, ...s.pedestrians]) {"
    " const d = Math.hypot(o.x - s.player.x, o.z - s.player.z); if (d < window.__eval.minGap) window.__eval.minGap = d; } }, 250);"
    " if (!s.autopilot) document.querySelector('#autopilot').click();"
    " return new Promise((r) => setTimeout(() => { window.__eval.engaged = !!s.autopilot; r(window.__eval.engaged); }, 1500)); })()"
)
_READ = (
    "JSON.stringify((() => { clearInterval(window.__evalTimer); const s = window.SEMIF_SIM;"
    " return { engaged: window.__eval.engaged, decision_failures: window.__eval.failures > 0, mode_seen: window.SEMIF_DRIVE_MODE, world_seen: s.world.selectValue || s.world.type, lag_seen: window.SEMIF_LAG_MS || 0,"
    " hidden: document.hidden, sim_time_s: Math.round(s.time - window.__eval.t0), distance_m: Math.round(s.distance),"
    " autopilot: !!s.autopilot, crash: !!s.crash, collisions: s.collisions || 0, vehicle_collisions: s.vehicleCollisions || 0,"
    " pedestrian_casualties: s.pedestrianCasualties || 0, red_light: s.redLightViolations || 0, violations: s.violations || 0,"
    " min_gap_m: +window.__eval.minGap.toFixed(1), events: s.events.map((e) => e.time.toFixed(0) + ' ' + e.text) }; })())"
)


def _jevpilot_tabs() -> List[str]:
    return [line.split()[0] for line in _cdp("list").splitlines() if "/jevpilot" in line]


def open_tab(base: str) -> str:
    """A tab of our own, opened by chrome-cdp-ex (so it is not a hidden background tab). Another
    simulation tab would share the server's vision slot and mix camera evidence, so we refuse to
    start rather than take over someone's tab."""
    others = _jevpilot_tabs()
    if others:
        raise SystemExit(f"close the open simulation tab(s) {others} first: they share the server's vision slot")
    _cdp("open", f"{base.rstrip('/')}/jevpilot/?minimal=0")
    for _ in range(20):
        tabs = _jevpilot_tabs()
        if tabs:
            return tabs[0]
        time.sleep(0.5)
    raise SystemExit("the evaluation tab did not appear")


def validate(run: Dict[str, Any], got: Dict[str, Any]) -> Optional[str]:
    """Why this run was not set up as asked (a setup failure, retried), or None. Only things true
    before the car drove are setup: the tab, the page's mode/route/lag, the autopilot engaging, and
    a decision service that failed outright. What happened once it drove is a result: outcome()."""
    if got.get("hidden"):
        return "tab hidden (the simulation does not step)"
    if got.get("mode_seen") != run["mode"]:
        return f"drove mode {got.get('mode_seen')!r}"
    if got.get("world_seen") != f"coast:{run['route']}":
        return f"drove route {got.get('world_seen')!r}"
    if int(got.get("lag_seen") or 0) != int(run.get("lag_ms") or 0):
        return f"page lag {got.get('lag_seen')} ms"
    if got.get("engaged") is False:
        return "autopilot never engaged"
    moved = got.get("crash") or float(got.get("distance_m") or 0) >= STALL_MPS * run["seconds"]
    if not moved:
        # The car did not get going and the decisions were failing: an outage, not the driving.
        if got.get("server_ok") is False:
            return "decision server unreachable after the run"
        if got.get("decision_failures"):
            return "decision service failed (the bundle paused after three failed requests)"
    return None


def outcome(run: Dict[str, Any], got: Dict[str, Any]) -> Dict[str, bool]:
    """Results that are not violations but are not good drives either: the autopilot gave up
    (three failed or expired decisions), or the car hardly moved. A crash is its own result."""
    none = {"disengaged": False, "stalled": False, "broke": False, "unreadable": False}
    if got.get("crash"):
        return none
    # Free driving chains destinations (the bundle picks the next one and keeps the autopilot on);
    # the evaluation never sets lap=1, the only mode where arriving ends a drive.
    return dict(
        none,
        disengaged=not got.get("autopilot"),
        stalled=float(got.get("distance_m") or 0) < STALL_MPS * run["seconds"],
        # The page stopped stepping while the car drove (a freeze, an error): a result, not setup.
        broke=float(got.get("sim_time_s") or 0) < MIN_SIM_SHARE * run["seconds"],
    )


def server_ok(base: str, tries: int = 3) -> bool:
    """The decision server answers its health check (infrastructure, independent of the drive).
    Asked after the drive stopped, and a few times: a server busy with the detector is not down."""
    import urllib.request

    for attempt in range(tries):
        try:
            with urllib.request.urlopen(f"{base.rstrip('/')}/health", timeout=10) as res:
                if 200 <= res.status < 300:
                    return True
        except Exception:
            pass
        if attempt + 1 < tries:
            time.sleep(5)
    return False


def drive(target: str, base: str, run: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(run, started=time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        _cdp("nav", target, page_url(base, run))
        _js(target, _READY, timeout=150)
        time.sleep(3)
        _js(target, _START)
    except Exception as err:  # the drive never started: setup, retried
        row.update(ok=False, error=f"setup: {str(err)[:300]}")
        return row
    try:
        time.sleep(run["seconds"])
        got = _js(target, _READ)
        if isinstance(got, str):
            got = json.loads(got)
        _cdp("nav", target, f"{base.rstrip('/')}/openapi.json")  # stop the drive before asking the server
        got["server_ok"] = server_ok(base)
        reason = validate(run, got)
        row.update(got, ok=reason is None)
        if reason:
            row["error"] = reason
        else:
            row.update(outcome(run, got))
    except Exception as err:  # the drive started and then the page could not be read: a result, unknown
        row.update(ok=True, disengaged=False, stalled=False, broke=True, unreadable=True, error=f"drive broke: {str(err)[:300]}")
    return row


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", choices=("tuning", "held_out"), default="tuning")
    ap.add_argument("--seeds", type=int, nargs="+", help="a subset of the chosen set")
    ap.add_argument("--routes", nargs="+", choices=ROUTES, default=list(DEFAULT_ROUTES))
    ap.add_argument("--modes", nargs="+", choices=MODES, default=list(DEFAULT_MODES))
    ap.add_argument("--seconds", type=int, default=150)
    ap.add_argument("--lag-ms", type=int, default=0, help=f"0..{MAX_LAG_MS}: the bundle drops decisions older than 1.8 s")
    ap.add_argument("--base", default="http://localhost:8768")
    ap.add_argument("--out", type=Path, help="JSONL results (absolute path); reruns resume")
    ap.add_argument("--report", type=Path, help="only summarise an existing results file")
    args = ap.parse_args(argv)

    if not 0 <= args.lag_ms <= MAX_LAG_MS:
        ap.error(f"--lag-ms must be 0..{MAX_LAG_MS}")
    if args.seconds < MIN_SECONDS:
        ap.error(f"--seconds must be at least {MIN_SECONDS}")
    if args.report:
        kept, dropped = current_rows(read_rows(args.report), load_seeds())
        if dropped:
            print(f"left out {len(dropped)} rows: no seed set, written before outcomes were recorded, "
                  "or a held_out seed that has since been looked into")
        print(report(summarize(kept)))
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
    target = open_tab(args.base)
    try:
        _drive_all(args, todo, target)
    finally:
        _cdp("nav", target, f"{args.base.rstrip('/')}/openapi.json")  # stop the last drive, even on Ctrl-C
    print(report(summarize(current_rows(read_rows(args.out), load_seeds())[0])))
    return 0


def _drive_all(args: argparse.Namespace, todo: List[Dict[str, Any]], target: str) -> None:
    for i, run in enumerate(todo, 1):
        try:
            others = [t for t in _jevpilot_tabs() if t != target]
        except Exception:
            others = []  # could not check; the check after the run records it
        if others:
            raise SystemExit(f"another simulation tab {others} opened during the evaluation: it shares the vision slot")
        row = drive(target, args.base, run)
        try:
            shared = [t for t in _jevpilot_tabs() if t != target]
            row["tab_check"] = "ok"
        except Exception:
            shared = []
            row["tab_check"] = "failed"  # the run is kept; the check could not be made
        if shared:
            # Another tab shared the vision slot during this run: its evidence is not this drive's.
            row.update(ok=False, error="another simulation tab shared the vision slot during the run")
            row["set"] = args.set
            with args.out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            raise SystemExit("another simulation tab opened during the evaluation; stopped")
        row["set"] = args.set
        with args.out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"[{i}/{len(todo)}] seed {run['seed']} {run['route']}/{run['mode']}: "
              + (f"{row.get('distance_m')} m, red {row.get('red_light')}, collisions {row.get('collisions')}"
                 + (", autopilot gave up" if row.get("disengaged") else "") + (", did not move" if row.get("stalled") else "")
                 if row["ok"] else f"COULD NOT DRIVE {row.get('error')}"), flush=True)


if __name__ == "__main__":
    sys.exit(main())
