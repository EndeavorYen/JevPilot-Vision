"""The decision request's page-side shaping, driven in node (#63: semif-decision.js).

These replace source-text checks on semif-layer.js (`"lateral_offset_m" in js`, `"lane.offset_m" in
js`, `"lateral_offset_m = player.x" not in js`): the module is called with a fake window and what
goes out is checked.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "jevpilot_vision" / "web"

_PRELUDE = r"""
const D = require(process.argv[1]);
const spec = JSON.parse(process.argv[2]);
let clock = 1000;
const win = Object.assign({}, spec.win || {});
const params = new URLSearchParams(spec.query || "");
const dec = D.create({ win, params, now: () => clock });
const out = (v) => process.stdout.write(JSON.stringify(v));
"""


def _run(body: str, spec: dict | None = None):
    done = subprocess.run(["node", "-e", _PRELUDE + body, str(WEB / "semif-decision.js"), json.dumps(spec or {})],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node drives the page module")


def test_issue63_the_lane_offset_is_the_planners_own_never_the_cars_x():
    """#58-62: the request's lateral_offset_m is the planner's lane.offset_m (decision state first,
    then the plan), not a lateral offset recomputed from the car's world x."""
    got = _run(
        "win.SEMIF_SIM = { world: { seed: 9 }, player: { x: 123.4 }, lastDecisionState: { lane: { offset_m: 0.35 } }, lastPlan: { lane: { offset_m: -1 } } };"
        "const a = dec.shape({ state: {} }).state;"
        "win.SEMIF_SIM.lastDecisionState = {}; const b = dec.shape({ state: {} }).state;"
        "win.SEMIF_SIM.lastPlan = {}; const c = dec.shape({ state: {} }).state;"
        "out({ a, b, c });"
    )
    assert got["a"]["lateral_offset_m"] == 0.35 and got["a"]["seed"] == 9
    assert got["b"]["lateral_offset_m"] == -1, "the plan's lane when the decision state has none"
    assert "lateral_offset_m" not in got["c"], "no lane known: none sent, not the car's x"


def test_issue63_privileged_requests_carry_no_vision_fields_and_vision_ones_do():
    got = _run(
        "win.SEMIF_SIM = { world: { seed: 1 } }; win.SEMIF_VISION = { signal: 'red', perception: { backend: 'rtdetr', status: 'ready', signal: { state: 'red' } } };"
        "win.SEMIF_VISION_AT = 900;"
        "win.SEMIF_DRIVE_MODE = 'privileged'; const priv = dec.shape({ state: {} });"
        "win.SEMIF_DRIVE_MODE = 'vision'; win.SEMIF_MODE_ID = 'vision-map'; const map = dec.shape({ state: {} });"
        "win.SEMIF_MODE_ID = 'vision'; win.SEMIF_VISION_STAGE = 3; const nv = dec.shape({ state: {} });"
        "out({ priv, map, nv, seen: win.SEMIF_SEEN_SIGNAL });"
    )
    assert "drive_mode" not in got["priv"] and got["priv"]["state"]["vision_age_ms"] == 100
    assert got["map"]["drive_mode"] == "vision" and "vision_stage" not in got["map"]
    assert got["map"]["state"]["seen_signal"] == "red", "a fresh red reading is remembered"
    assert got["nv"]["vision_stage"] == 3 and got["seen"] == "red"


def test_issue63_a_green_is_trusted_shorter_than_a_red_and_stale_evidence_says_nothing():
    got = _run(
        "win.SEMIF_DRIVE_MODE = 'vision'; const at = (state, age) => { win.SEMIF_VISION = { perception: { backend: 'rtdetr', status: 'ready', signal: { state } } };"
        "  win.SEMIF_VISION_AT = clock - age; dec.updateSeen(); return win.SEMIF_SEEN_SENT; };"
        "const seq = [at('green', 100)]; clock += 1000; seq.push(at('unknown', 100));"
        "seq.push(at('red', 100)); clock += 2000; seq.push(at('unknown', 100)); clock += 1000; seq.push(at('unknown', 100));"
        "seq.push(at('green', 4000));"
        "out(seq);"
    )
    assert got == ["green", None, "red", "red", None, None]


def test_issue63_candidate_paths_follow_the_plans_projection_in_the_cars_frame():
    got = _run(
        "const pts = Array.from({ length: 61 }, (_, k) => ({ x: 100 + 0.5 * k, z: 50, heading: Math.PI / 2 }));"
        "win.SEMIF_SIM = { lastPlan: { origin: { x: 100, z: 50, heading: Math.PI / 2 }, vectors: { a: { velocity_mps: 10, steering: 0 } }, projections: { a: { points: pts } } } };"
        "out({ hit: dec.candidatePaths({ v: [10, 0.02, 0, 0, false, false] }), miss: dec.candidatePaths({ v: [3, 0.4, 0, 0, false, false] }) });"
    )
    path = got["hit"]["v"]
    assert path[0] == [0.2, 2, 0, 0] and path[-1] == [3, 30, 0, 0], "every 0.2 s for 3 s, ahead in metres"
    assert got["miss"] is None, "no plan vector within 0.06 of the candidate"


def test_issue63_localization_error_moves_only_the_new_visions_request_and_never_the_bundles_objects():
    got = _run(
        "win.SEMIF_SIM = { world: { seed: 42 }, time: 5, lastDecisionState: { lane: { offset_m: 0.4 } } };"
        "const inter = { control: 'signal', distance_to_line_m: 20 };"
        "win.SEMIF_DRIVE_MODE = 'vision'; win.SEMIF_MODE_ID = 'vision'; win.SEMIF_VISION_STAGE = 2;"
        "const nv = dec.shape({ state: { intersection: inter, candidates: { k: [8, 0, 0.6, 0, false, false] } } }).state;"
        "win.SEMIF_MODE_ID = 'vision-map'; const map = dec.shape({ state: { intersection: inter } }).state;"
        "out({ nv, map, inter, params: dec.locNoise.params });",
        {"query": "loc_sigma=0.5"},
    )
    assert got["params"]["sigma"] == 0.5
    assert got["nv"]["lateral_offset_m"] != 0.4 and got["nv"]["intersection"]["distance_to_line_m"] != 20
    assert abs((got["nv"]["candidates"]["k"][2] - 0.6) - (got["nv"]["lateral_offset_m"] - 0.4)) < 0.011
    assert got["map"]["lateral_offset_m"] == 0.4 and got["map"]["intersection"]["distance_to_line_m"] == 20
    assert got["inter"]["distance_to_line_m"] == 20, "the bundle's object is copied, not moved"
