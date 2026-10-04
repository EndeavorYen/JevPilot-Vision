"""Python copies of the bundle's models, checked against the bundle itself (#61).

`vision_mode` re-implements the car's kinematics and body boxes, and `demo/server.py` the stop
model the coast stop-offer patch uses. Nothing failed when one side changed. These tests read the
numbers (or run the code, in node) from the shipped bundle and compare.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from demo.server import DecisionEngine
from jevpilot_vision import vision_mode

ASSETS = Path(__file__).resolve().parents[1] / "jevpilot_vision" / "web" / "assets"
WEB = ASSETS.parent
MAIN = (ASSETS / "main-CvLEeHjW.js").read_text(encoding="utf-8")
WORKER = (ASSETS / "planner.worker-DFdG3q6n.js").read_text(encoding="utf-8")


def _function_with(src: str, marker: str) -> tuple[str, str]:
    """(name, source) of the one bundle function whose body holds `marker`."""
    at = src.index(marker)
    assert src.count(marker) == 1, marker
    start = src.rindex("function ", 0, at)
    name = re.match(r"function (\w+)\(", src[start:]).group(1)
    depth, end = 0, src.index("{", start)
    for end in range(end, len(src)):
        depth += {"{": 1, "}": -1}.get(src[end], 0)
        if depth == 0:
            break
    return name, src[start : end + 1]


# The worker's own planner projection: speed, steering (rate-limited) and pose, one step at a time.
_CLAMP = "e=(e,t,n)=>Math.max(t,Math.min(n,e))"
_WRAP = "i=e=>Math.atan2(Math.sin(e),Math.cos(e))"


def _bundle_path(target: float, steer: float, speed: float, wheel: float) -> list[list[float]]:
    assert _CLAMP in WORKER and _WRAP in WORKER, "the worker's clamp/wrap helpers moved"
    wheelbase = re.search(r"let C=([\d.]+),w=", WORKER).group(1)
    ease, _ = _function_with(WORKER, "return .58+.37*(1-e((Math.abs(")
    parts = [
        _function_with(WORKER, "return .58+.37*(1-e((Math.abs(")[1],
        _function_with(WORKER, f"return Math.tan(e*{ease}(t))/C")[1],
        _function_with(WORKER, "t.wheelSteering=a+e(n-a,")[1],
        _function_with(WORKER, "e.z-=Math.cos(e.heading)*e.speed*n")[1],
    ]
    step = _function_with(WORKER, "t.wheelSteering=a+e(n-a,")[0]
    n = round(vision_mode.HORIZON_S / vision_mode.STEP_S)
    script = (
        f"const {_CLAMP},{_WRAP};let C={wheelbase};" + "".join(parts) +
        f"const s={{speed:{speed},heading:0,x:0,z:0,wheelSteering:{wheel}}},out=[];"
        f"for(let k=1;k<={n};k++){{{step}(s,{steer},{target},{vision_mode.STEP_S});"
        "out.push([k*" + str(vision_mode.STEP_S) + ",-s.z,s.x,s.heading])}"
        "console.log(JSON.stringify(out))"
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node runs the bundle's own code")
@pytest.mark.parametrize(
    "target,steer,speed,wheel",
    [
        (8.0, 0.0, 8.0, 0.0),  # straight, steady
        (6.0, 0.25, 6.0, 0.25),  # held turn
        (10.0, -0.4, 4.0, -0.4),  # turn while speeding up
        (2.0, 0.3, 9.0, 0.3),  # turn while braking
        (7.0, 0.35, 7.0, 0.0),  # steering winds in at the bundle's rate
        (5.0, -0.2, 5.0, 0.3),  # and winds back the other way
    ],
)
def test_issue61_the_fallback_path_follows_the_bundles_own_kinematics(target, steer, speed, wheel):
    bundle = _bundle_path(target, steer, speed, wheel)
    python = list(vision_mode._model_path(target, steer, speed, wheel=wheel))
    assert len(python) == len(bundle)
    for (t, ahead, right, heading), (bt, b_ahead, b_right, b_heading) in zip(python, bundle):
        assert abs(t - bt) < 1e-9
        assert abs(ahead - b_ahead) < 0.01 and abs(right - b_right) < 0.01, (t, ahead, right, b_ahead, b_right)
        assert abs(heading - b_heading) < 1e-3


def test_issue61_the_kinematic_constants_are_the_bundles():
    assert float(re.search(r"var _=([\d.]+),v=", MAIN).group(1)) == vision_mode.WHEELBASE_M
    assert float(re.search(r"let C=([\d.]+),w=", WORKER).group(1)) == vision_mode.WHEELBASE_M
    for src in (MAIN, WORKER):
        assert "-1.8*" in src and "1.8*" in src
        assert re.search(r"-8\*\w,5\*\w\)", src), "accel/brake limits moved"
    assert vision_mode.STEER_RATE == 1.8
    assert (vision_mode.ACCEL_MPS2, vision_mode.BRAKE_MPS2) == (5.0, 8.0)


def test_issue61_the_collision_boxes_are_the_bundles_and_the_models():
    hero = re.search(r"intersectionMemory:null,width:([\d.]+),depth:([\d.]+)\}", MAIN)
    assert hero, "the hero's box moved"
    assert vision_mode.EGO_HALF == (float(hero.group(2)) / 2, float(hero.group(1)) / 2)
    traffic = re.search(r"width:e%5==0\?([\d.]+):([\d.]+),depth:e%5==0\?([\d.]+):([\d.]+),", MAIN)
    assert traffic, "the traffic box moved"
    moto_w, car_w, moto_d, car_d = (float(traffic.group(k)) for k in range(1, 5))
    assert vision_mode.OBJECT_HALF["car"] == (car_d / 2, car_w / 2)
    assert vision_mode.OBJECT_HALF["motorcycle"] == (moto_d / 2, moto_w / 2)
    walker = re.search(r"walking:!1,speed:0,width:([\d.]+),depth:([\d.]+),", MAIN)
    assert vision_mode.OBJECT_HALF["pedestrian"] == (float(walker.group(2)) / 2, float(walker.group(1)) / 2)
    # the drawn cars use the same lengths
    vehicles = (WEB / "semif-world" / "vehicles.js").read_text(encoding="utf-8")
    assert float(re.search(r"HERO_LENGTH = ([\d.]+);", vehicles).group(1)) == float(hero.group(2))
    assert float(re.search(r"TRAFFIC_LENGTH = ([\d.]+);", vehicles).group(1)) == car_d


def test_issue61_the_stop_offer_patch_and_the_mock_share_one_stop_model():
    """Same reaction time and braking; the margins differ on purpose: the patch starts offering a
    stop 1 m before the last point the car can stop from, the mock calls it unstoppable 0.5 m past it."""
    formula = r"\(V=>V\*([\d.]+)\+V\*V/([\d.]+)\+([\d.]+)\)"
    for src in (MAIN, WORKER):
        found = re.findall(formula, src)
        assert len(found) == 1, "the coast stop-offer patch moved"
        gap, twice_decel, margin = (float(x) for x in found[0])
        assert gap == DecisionEngine.DECISION_GAP_S
        assert twice_decel == 2 * DecisionEngine.STOP_DECEL_MPS2
        assert margin == 1.0
