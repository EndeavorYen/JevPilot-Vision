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
GREEN_TRUST_MS = 800.0  # a green reading, from when its frame was taken
WHEELBASE_M = 2.7
CAMERA_AHEAD_M = 0.15  # the onboard camera sits this far ahead of the car's centre
EGO_HALF = (2.375, 0.95)  # half length, half width
OBJECT_HALF = {"car": (2.1, 0.95), "motorcycle": (1.15, 0.4), "pedestrian": (0.3, 0.3)}
MARGIN = (0.4, 0.25)
LANE_HALF_M = 1.75  # traffic this close to our line is in our lane: it moves away or stands
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
    # Negative: the frames carry another page's clock (a reload while the server was busy).
    ok = bool(perception) and perception.get("backend") not in (None, "none") and perception.get("status", "ready") == "ready" and 0 <= age <= STALE_MS
    return ok, perception


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _curvature(steer: float, speed: float) -> float:
    # The bundle's S(): tan(steer * x(speed)) / wheelbase, x easing from 0.95 to 0.58 between 3 and 8 m/s.
    x = 0.58 + 0.37 * (1.0 - min(1.0, max(0.0, (abs(speed) - 3.0) / 5.0)))
    return math.tan(steer * x) / WHEELBASE_M


def _model_path(target: float, steer: float, speed: float) -> Iterable[tuple[float, float, float, float]]:
    """(t, ahead, right, heading) of the car's centre at a constant steer, from the bundle's w().
    Only a fallback: the planner re-steers to follow its lane (see `candidate_paths`)."""
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


def sweep_collision(
    vec: List[Any],
    objects: List[Dict[str, Any]],
    speed: float,
    path: Optional[List[List[float]]] = None,
    age_s: float = 0.0,
) -> bool:
    """Whether following this candidate for 3 s runs into a perceived object.

    `path` is the planner's own projection of the candidate ([t, ahead, right, heading] in the
    car's frame); without it a constant-steer model stands in. Objects were seen `age_s` ago: they
    are first moved by what changed since (a parked car is now `speed * age_s` nearer). They move
    straight ahead at our speed minus their closing speed; people, and anything whose speed is not
    known, stand still.
    """
    target, steer = _num(vec[0] if len(vec) > 0 else None), _num(vec[1] if len(vec) > 1 else None)
    if target is None or steer is None:
        return False
    points = [p for p in (path or []) if isinstance(p, (list, tuple)) and len(p) >= 4 and all(_num(v) is not None for v in p[:4])]
    track = [(float(p[0]), float(p[1]), float(p[2]), float(p[3])) for p in points] or list(_model_path(target, steer, speed))
    for t, ahead, right, heading in track:
        c, s = math.cos(heading), math.sin(heading)
        for obj in objects:
            half = OBJECT_HALF.get(obj.get("kind"), OBJECT_HALF["car"])
            closing = obj.get("closing_mps")
            if obj.get("kind") == "pedestrian" or closing is None:
                closing = speed  # standing still
            elif abs(obj["right_m"]) <= LANE_HALF_M:
                closing = min(closing, speed)  # ranging noise, not a car reversing at us
            moving = speed - closing
            oa = obj["ahead_m"] + CAMERA_AHEAD_M - closing * age_s + moving * t
            dx, dy = oa - ahead, obj["right_m"] - right
            along, across = dx * c + dy * s, -dx * s + dy * c
            if abs(along) <= EGO_HALF[0] + half[0] + MARGIN[0] and abs(across) <= EGO_HALF[1] + half[1] + MARGIN[1]:
                return True
    return False


CRAWL_MPS = 1.0  # without perception, only this slow is safe


def _objects(perception: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for o in perception.get("objects", []) or []:
        if not isinstance(o, dict):
            continue
        ahead, right = _num(o.get("ahead_m")), _num(o.get("right_m"))
        if ahead is None or right is None:
            continue
        out.append({**o, "ahead_m": ahead, "right_m": right, "closing_mps": _num(o.get("closing_mps"))})
    return out


def prepare(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The request as Vision mode may see it. Non-Vision requests come back unchanged (same object)."""
    if not is_vision(payload) or not isinstance(payload.get("state"), dict):
        return payload
    out = copy.deepcopy(payload)
    state = out["state"]
    for key in PRIVILEGED:
        state.pop(key, None)
    ok, perception = _perception_ok(state)
    objects = _objects(perception) if ok else []
    # The page remembers a light it read (semif-layer.js updateSeenSignal); its memory counts only
    # while the evidence is fresh.
    remembered = state.get("seen_signal") if ok else None
    reading = (perception.get("signal") or {}).get("state") if ok else None
    if reading == "green" and (_num(state.get("vision_age_ms")) or 0.0) > GREEN_TRUST_MS:
        reading = None  # an amber could have come and gone since (semif-layer.js SEEN_MEMORY_MS)
    seen = remembered if remembered in ("red", "amber", "green") else reading if reading in ("red", "amber", "green") else None
    signal, source = (seen, "perception") if seen else ("red", "assumed")

    inter = state.get("intersection")
    signalled = isinstance(inter, dict) and str(inter.get("control") or "").lower() in ("signal", "traffic_light")
    if signalled:
        inter["signal"] = signal
        inter["signal_source"] = source
    vision = state.get("vision") if isinstance(state.get("vision"), dict) else None
    if vision is not None:
        # What the directive and the arbiter read: the assumed red only at a signalled line.
        vision["signal"] = signal if signalled else (seen or "unknown")
    state["perception_ok"] = ok
    state["perceived_objects"] = objects

    speed = _num(state.get("speed_mps")) or 0.0
    age_s = max(0.0, (_num(state.get("vision_age_ms")) or 0.0) / 1000.0)
    paths = state.get("candidate_paths") if isinstance(state.get("candidate_paths"), dict) else {}
    candidates = state.get("candidates")
    if isinstance(candidates, dict):
        for cid, vec in candidates.items():
            if not (isinstance(vec, list) and len(vec) >= 6):
                continue
            target = _num(vec[0])
            if target is not None and target < 0:
                hit = True  # nothing watches behind the car
            elif not ok:
                hit = target is None or target > CRAWL_MPS  # blind: crawl or stop
            else:
                hit = sweep_collision(vec, objects, speed, paths.get(cid), age_s)
            # The bundle's own flag is computed against the map's buildings in Vision mode.
            vec[4] = bool(vec[4]) or hit
    state["drive_mode"] = "vision"
    return out
