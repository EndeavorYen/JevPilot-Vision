"""Vision mode (#18): a decision request that reads the cameras and the map, not the simulator.

In Vision mode the web client already keeps the simulator's objects and signal colour out of its
own planner (BUNDLE_PATCHES.md `vision-*`). Here, before anything scores the request:

- every field built from true objects is dropped (defence in depth);
- the map's stop line stays, but its colour is what perception saw. A light that was not seen
  counts as red: the car stops unless it saw green;
- each candidate's collision column is swept again against the objects perception reported,
  with the bundle's own kinematics (jevpilot_vision/web/assets: `S`, `w`), instead of the
  bundle's column, which used every object's true footprint;
- stale or missing perception is reported (`perception_ok: False`), so the scorer fails closed.

Privileged and Heuristic requests pass through untouched.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, Iterable, List, Optional

# Fields the bundle builds from the simulator's objects.
PRIVILEGED = (
    "pedestrian",
    "roadside_obstacle",
    "scene",
    "traffic",
    "hazard",
    "following",
    "nearby",
    "other_vehicle",
    "emergency_vehicle",
    "construction",
    "blocking_object",
    "_semif_prompt_state",
)

STALE_MS = 1500.0  # perception older than this is no perception
WHEELBASE_M = 2.7
CAMERA_AHEAD_M = 0.15  # the onboard camera sits this far ahead of the car's centre
EGO_HALF = (2.375, 0.95)  # half length, half width
OBJECT_HALF = {"car": (2.1, 0.95), "motorcycle": (1.15, 0.4), "pedestrian": (0.3, 0.3)}
MARGIN = (0.4, 0.25)
HORIZON_S = 3.0
STEP_S = 0.1


def is_vision(payload: Dict[str, Any]) -> bool:
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    return payload.get("drive_mode") == "vision" or state.get("drive_mode") == "vision"


def _perception_ok(state: Dict[str, Any]) -> tuple[bool, Dict[str, Any]]:
    vision = state.get("vision") if isinstance(state.get("vision"), dict) else {}
    perception = vision.get("perception") if isinstance(vision.get("perception"), dict) else {}
    try:
        age = float(state.get("vision_age_ms"))
    except (TypeError, ValueError):
        age = math.inf
    ok = bool(perception) and perception.get("backend") not in (None, "none") and perception.get("status", "ready") == "ready" and age <= STALE_MS
    return ok, perception


def _curvature(steer: float, speed: float) -> float:
    # The bundle's S(): tan(steer * x(speed)) / wheelbase, x easing from 0.95 to 0.58 between 3 and 8 m/s.
    x = 0.58 + 0.37 * (1.0 - min(1.0, max(0.0, (abs(speed) - 3.0) / 5.0)))
    return math.tan(steer * x) / WHEELBASE_M


def _path(target: float, steer: float, speed: float) -> Iterable[tuple[float, float, float, float]]:
    """(t, ahead, right, heading) of the car's centre following one candidate, from the bundle's w()."""
    ahead = right = heading = 0.0
    v = speed
    t = 0.0
    while t < HORIZON_S - 1e-9:
        v += max(-8.0 * STEP_S, min(5.0 * STEP_S, target - v))
        heading += v * _curvature(steer, v) * STEP_S
        ahead += math.cos(heading) * v * STEP_S
        right += math.sin(heading) * v * STEP_S
        t += STEP_S
        yield t, ahead, right, heading


def sweep_collision(vec: List[Any], objects: List[Dict[str, Any]], speed: float) -> bool:
    """Whether following this candidate for 3 s runs into a perceived object.

    Objects move straight ahead at our speed minus their closing speed (a parked car closes at
    our own speed). People, and anything whose speed is not known yet, are taken where they stand.
    """
    try:
        target, steer = float(vec[0]), float(vec[1])
    except (TypeError, ValueError, IndexError):
        return False
    for t, ahead, right, heading in _path(target, steer, speed):
        c, s = math.cos(heading), math.sin(heading)
        for obj in objects:
            half = OBJECT_HALF.get(obj.get("kind"), OBJECT_HALF["car"])
            closing = obj.get("closing_mps")
            moving = 0.0 if obj.get("kind") == "pedestrian" or closing is None else speed - float(closing)
            oa = float(obj["ahead_m"]) + CAMERA_AHEAD_M + moving * t
            dx, dy = oa - ahead, float(obj["right_m"]) - right
            along, across = dx * c + dy * s, -dx * s + dy * c
            if abs(along) <= EGO_HALF[0] + half[0] + MARGIN[0] and abs(across) <= EGO_HALF[1] + half[1] + MARGIN[1]:
                return True
    return False


def prepare(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The request as Vision mode may see it. Non-Vision requests come back unchanged (same object)."""
    if not is_vision(payload) or not isinstance(payload.get("state"), dict):
        return payload
    out = copy.deepcopy(payload)
    state = out["state"]
    for key in PRIVILEGED:
        state.pop(key, None)
    ok, perception = _perception_ok(state)
    objects = [o for o in perception.get("objects", []) if isinstance(o, dict) and "ahead_m" in o and "right_m" in o] if ok else []
    # The page remembers a light it read for 2.5 s (semif-layer.js updateSeenSignal); its memory
    # counts only while the evidence is fresh.
    remembered = state.get("seen_signal") if ok else None
    seen = remembered if remembered in ("red", "amber", "green") else ((perception.get("signal") or {}).get("state") if ok else None)
    signal, source = (seen, "perception") if seen in ("red", "amber", "green") else ("red", "assumed")

    inter = state.get("intersection")
    if isinstance(inter, dict) and str(inter.get("control") or "").lower() in ("signal", "traffic_light"):
        inter["signal"] = signal
        inter["signal_source"] = source
    vision = state.get("vision") if isinstance(state.get("vision"), dict) else None
    if vision is not None:
        vision["signal"] = signal  # what the directive and the arbiter read
    state["perception_ok"] = ok
    state["perceived_objects"] = objects

    try:
        speed = float(state.get("speed_mps") or 0.0)
    except (TypeError, ValueError):
        speed = 0.0
    candidates = state.get("candidates")
    if isinstance(candidates, dict):
        for cid, vec in candidates.items():
            if isinstance(vec, list) and len(vec) >= 6:
                vec[4] = sweep_collision(vec, objects, speed)
    state["drive_mode"] = "vision"
    return out
