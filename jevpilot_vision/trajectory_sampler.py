"""Shared geometric trajectory sampler.

The sampler does not read traffic-light semantics. A stop line is a meter mark.
Web 3D and the Python loop share this option contract; they do not share a world.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

VECTOR_COLUMNS = (
    "speed",
    "steer",
    "route_error",
    "offroad_fraction",
    "collision",
    "stop_at_line",
)
VECTOR_INSTRUCTIONS = "Legal, lane-centered path. Halt if red."

# Keys allowed in the model prompt. Candidates live only as choice options.
PROMPT_STATE_KEYS = (
    "speed_mps",
    "speed_ceiling_mps",
    "on_road",
    "intersection",
    "vision",
    "directive",
)


_SLIM_OBJECT_KEYS = {
    "intersection": ("control", "distance_to_line_m", "signal"),
    "vision": (
        "event",
        "signal",
    ),
}


def format_lane_offset(offset_m: Any) -> str:
    try:
        x = float(offset_m)
    except (TypeError, ValueError):
        return "unknown"
    if abs(x) < 0.15:
        return "centered"
    side = "right" if x > 0 else "left"
    return f"drifted {abs(x):.1f}m {side}"


def compact_jev_state(state: Any) -> Dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    packed: Dict[str, Any] = {}
    for key in PROMPT_STATE_KEYS:
        if key not in state or state[key] is None:
            continue
        value = state[key]
        allowed = _SLIM_OBJECT_KEYS.get(key)
        if allowed and isinstance(value, dict):
            slim = {inner: value[inner] for inner in allowed if inner in value}
            if not slim:
                continue
            if key == "vision" and isinstance(slim.get("event"), str) and len(slim["event"]) > 96:
                slim["event"] = slim["event"][:93] + "..."
            packed[key] = slim
        else:
            packed[key] = value
    if state.get("lateral_offset_m") is not None:
        try:
            lat = float(state.get("lateral_offset_m"))
        except (TypeError, ValueError):
            lat = None
        if lat is not None and abs(lat) <= 8.0:
            packed["lane_offset"] = format_lane_offset(lat)
    return packed


# csv = shortest. words = 512-bucket Pareto default. verbose = richer English, 1024 bucket.
OPTION_TAG_STYLE = os.environ.get("SEMIF_OPTION_TAG", "words")
# Absolute end_x gate for a center tag. Relative later+0.05<now is blind near 0.
CENTER_ABS_M = 0.08


def vector_option_tag(
    vec: Sequence[Any],
    style: Optional[str] = None,
    *,
    ego_x: Optional[float] = None,
    signal: Optional[str] = None,
) -> str:
    speed, steer, route_error, offroad, collision, stop_at_line = vec[:6]
    speed_f = float(speed)
    steer_f = float(steer)
    end_x = float(route_error)
    off_f = float(offroad)
    hit = bool(collision)
    halt = bool(stop_at_line)
    chosen = style or OPTION_TAG_STYLE
    centering = ""
    if ego_x is not None:
        now = abs(float(ego_x))
        later = abs(end_x)
        if later <= CENTER_ABS_M or later + 0.05 < now:
            centering = "centering"
        elif later > now + 0.05:
            centering = "diverging"
        else:
            centering = "holding"
    run_red = str(signal or "").lower() == "red" and (not halt) and abs(speed_f) > 0.8
    if chosen == "csv":
        base = f"{speed_f:.1f},{steer_f:+.2f},{off_f:.2f},{int(hit)},{int(halt)}"
        if signal is not None:
            base += f",{int(run_red)}"
        return base
    if chosen == "verbose":
        bits = [
            f"speed {speed_f:.1f} m/s, steer {steer_f:+.2f}",
            f"collision {hit}, stop_at_line {halt}",
        ]
        if centering:
            bits.append(centering)
        if run_red:
            bits.append("violates_signal=yes")
        return ", ".join(bits)
    short_center = {"centering": "center", "diverging": "diverge", "holding": "hold"}.get(centering, "")
    parts = [f"{speed_f:.1f}m/s", f"{steer_f:+.2f}"]
    if short_center:
        parts.append(short_center)
    parts.append("hit" if hit else "clear")
    parts.append("halt" if halt else "go")
    if run_red:
        parts.append("illegal")
    return " ".join(parts)


# Planner worker (jevpilot_vision/web/assets/planner.worker-*.js) policy, 1D track rewrite.
# Steer is clamped to ±0.85. On-road it draws ~55 samples; we keep 16 for letter-slot.
# Evaluation uses dt=0.05 and ~31 points (offroad_fraction uses p/31).
STEER_LIMIT = 0.85
PLAN_DT = 0.05
PLAN_POINTS = 31
MAX_SAMPLES = 16
LANE_HALF_M = 4.5  # matches JevPilot2Simulator.off_track
REAR_CLEAR_M = 0.55  # matches JevPilot2Simulator's rear catch-up rule
REAR_MARGIN_M = 1.0  # tracked IPM speed lags; keep clear a little past the rule's 6 m
CONTACT_DZ_M = 3.5  # car-sized box, the ahead check's size
CONTACT_DX_M = 1.8
# Pull-over: hold a right offset past the Web A() lane-keep snap (1.4 m), far enough that a car
# passing in the lane centre clears the box (CONTACT_DX_M) by the time it is alongside. Right is positive.
# Sampled every frame, whatever the scene says. Speed fractions of planning-max.
PULL_OVER_OFFSET_M = 2.8
PULL_OVER_SPEED_FRACTIONS = (0.9, 0.45)
# Speed mix is a fraction of planning-max, matching the worker's A*(0.78..1.0) / A*(0.25..0.55).
# Required-stop bias (O&&r<8) is NOT copied: that is signal injection.


@dataclass
class Sample:
    id: str
    speed: float
    steer: float
    route_error: float
    offroad: float
    collision: bool
    stop_at_line: bool
    end_speed: float
    end_x: float
    end_z: float
    description: str
    hold_offset_m: Optional[float] = None

    def as_vec(self) -> List[Any]:
        return [
            round(self.speed, 1),
            round(self.steer, 2),
            round(self.route_error, 2),
            round(self.offroad, 3),
            self.collision,
            self.stop_at_line,
        ]

    def meta(self) -> Dict[str, Any]:
        return {
            "end_speed": round(self.end_speed, 2),
            "end_x": round(self.end_x, 2),
            "end_z": round(self.end_z, 2),
            "steer": round(self.steer, 2),
            "stop_at_line": self.stop_at_line,
            "description": self.description,
            **({"hold_offset_m": self.hold_offset_m} if self.hold_offset_m is not None else {}),
        }


def _hits_obstacle(
    x: float,
    z: float,
    obj: Dict[str, Any],
    speed: float,
    ego_x: float = 0.0,
    ego_z: float = 0.0,
    t: float = 0.0,
    ego_speed: float = 0.0,
) -> bool:
    """Same radii as JevPilot2Simulator.step — prediction must match the loop.

    Prefer ego-frame rel_x/rel_z from IPM. World x/z is only for unit tests.
    A tracked vehicle (rel_vz_mps) moves at ego speed + rel_vz for t seconds.
    """
    if obj.get("rel_z") is not None:
        ox = float(ego_x) + float(obj.get("rel_x") or 0.0)
        oz = float(ego_z) + float(obj["rel_z"])
        rel_vz = obj.get("rel_vz_mps")
        if rel_vz is not None and float(rel_vz) > 0.0 and float(obj["rel_z"]) < 6.0:
            # Catching up or passing. The simulator's rear rule: |dx| < 0.55 while -4 < dz < 6.
            # Wherever the moved car is alongside or ahead, it is also a car-sized box.
            oz += (float(ego_speed) + float(rel_vz)) * t
            dz = oz - z
            if abs(dz) < CONTACT_DZ_M and abs(x - ox) < CONTACT_DX_M:
                return True
            return abs(x - ox) < REAR_CLEAR_M and -4.0 < dz < 6.0 + REAR_MARGIN_M
        if (
            rel_vz is not None
            and str(obj.get("kind") or "vehicle") == "vehicle"
            and float(obj["rel_z"]) > -CONTACT_DZ_M
        ):
            # Closing on or passing a slower car. Far IPM speed is coarse, so keep the
            # static check ahead and add the car as a box that moves at its own speed and
            # stays beside the ego while alongside. A car behind that is not closing is its
            # own driver's to avoid, as in the ahead-only check.
            if 0.0 <= oz - z < 3.5 and abs(x - ox) < 1.8:
                return True
            moved = oz + (float(ego_speed) + float(rel_vz)) * t
            return abs(moved - z) < 3.5 and abs(x - ox) < 1.8
    else:
        oz = obj.get("z")
        ox = float(obj.get("x", 0.0) or 0.0)
        if oz is None:
            return False
        oz = float(oz)
    kind = str(obj.get("kind") or obj.get("type") or "vehicle")
    dz = oz - z
    dx = x - ox
    if kind == "pedestrian":
        return abs(dz) < 3.0 and abs(dx) < 1.6 and speed > 2.0
    if kind == "roadside":
        return abs(dz) < 3.5 and (x + 0.95) > (ox - 0.70)
    if 0.0 <= dz < 3.5 and abs(dx) < 1.8:
        return True
    return False


def planning_max(speed: float, speed_ceiling: Optional[float] = None) -> float:
    cap = min(30.0, max(0.15, speed) + 2.5)
    if speed_ceiling is not None and math.isfinite(float(speed_ceiling)):
        cap = min(cap, float(speed_ceiling))
    return max(0.0, cap)


def rollout(
    ego_x: float,
    ego_z: float,
    speed: float,
    target_speed: float,
    target_steer: float,
    curvature: float,
    stop_line_z: Optional[float],
    obstacles: Sequence[Dict[str, Any]],
    current_steer: float = 0.0,
    hold_offset_m: Optional[float] = None,
) -> Dict[str, Any]:
    """Same lateral rule as JevPilot2Simulator.step, so a small steer comes back to center."""
    from jevpilot_vision.lateral import plant_steer_target

    x, z, v = ego_x, ego_z, speed
    steer = current_steer
    target_steer = max(-STEER_LIMIT, min(STEER_LIMIT, target_steer))
    offroad_steps = 0
    collision = False
    crossed_line = False
    first_steer: Optional[float] = None
    for step in range(PLAN_POINTS):
        accel = max(-12.0, min(6.0, (target_speed - v) * 4.0))
        v = max(-5.0, v + accel * PLAN_DT)
        offset_dot = steer * v * 2.0 - curvature * v * 1.5
        command = plant_steer_target(target_steer, x, offset_dot, curvature, hold_offset_m=hold_offset_m)
        if first_steer is None:
            first_steer = command
        steer += (command - steer) * 6.0 * PLAN_DT
        z += v * PLAN_DT
        x += steer * v * PLAN_DT * 2.0
        x -= curvature * v * PLAN_DT * 1.5
        if abs(x) > LANE_HALF_M:
            offroad_steps += 1
        if stop_line_z is not None and z >= stop_line_z:
            crossed_line = True
        for obj in obstacles:
            if _hits_obstacle(
                x, z, obj, v, ego_x=ego_x, ego_z=ego_z, t=(step + 1) * PLAN_DT, ego_speed=speed
            ):
                collision = True
    stop_at_line = False
    if stop_line_z is not None and (stop_line_z - ego_z) > 0.5:
        stop_at_line = v < 0.8 and z < stop_line_z - 0.3 and not crossed_line
    return {
        "end_speed": v,
        "end_x": x,
        "end_z": z,
        "offroad": offroad_steps / PLAN_POINTS,
        "collision": collision,
        "stop_at_line": stop_at_line,
        "route_error": x,
        "crosses_stop_line": crossed_line,
        "first_steer": first_steer if first_steer is not None else target_steer,
    }


def _speed_fraction(index: int, rng: random.Random, speed: float = 0.0) -> float:
    """Mirror worker mix without required-stop (O) or queue (R) branches.

    Index 1 is reverse when the car is slow (planning-max < 0.15 analogue).
    """
    if index == 0:
        return 0.0
    if index == 1 and speed < 4.0:
        return -(0.35 + rng.random() * 0.35)
    if index <= 4:
        return 0.25 + rng.random() * 0.30
    if index % 5 == 0:
        return 0.78 + rng.random() * 0.12
    return 0.94 + rng.random() * 0.06


def _steer_sample(index: int, rng: random.Random, current_steer: float) -> float:
    """Worker: every 3rd sample is full-range; others hug current steer."""
    if index % 3 == 0:
        return (rng.random() * 2 - 1) * STEER_LIMIT
    spread = max(0.015, STEER_LIMIT * 0.25)
    return max(-STEER_LIMIT, min(STEER_LIMIT, current_steer + (rng.random() * 2 - 1) * spread))


def sample_trajectories(
    *,
    ego_x: float,
    ego_z: float,
    speed: float,
    curvature: float = 0.0,
    stop_line_z: Optional[float] = None,
    obstacles: Optional[Sequence[Dict[str, Any]]] = None,
    seed: int = 0,
    speed_ceiling: Optional[float] = None,
    current_steer: float = 0.0,
) -> Dict[str, Sample]:
    """Planner-like mix on a 1D track. Signal color is not an input."""
    rng = random.Random(int(seed) ^ (int(ego_z * 10) << 3))
    obstacles = list(obstacles or [])
    cap = planning_max(speed, speed_ceiling)
    samples: Dict[str, Sample] = {}
    kept = 0
    attempt = 0
    while kept < MAX_SAMPLES - len(PULL_OVER_SPEED_FRACTIONS) - 1 and attempt < 40:
        steer = _steer_sample(attempt, rng, current_steer)
        frac = _speed_fraction(attempt, rng, speed)
        if frac < 0:
            target_speed = -min(4.0, 1.2 + abs(frac) * 4.0)
        else:
            target_speed = cap * frac
        geom = rollout(
            ego_x,
            ego_z,
            speed,
            target_speed,
            steer,
            curvature,
            stop_line_z,
            obstacles,
            current_steer=current_steer,
        )
        attempt += 1
        if geom["offroad"] > 0.55 and target_speed > 0.5:
            continue
        sid = f"t{kept:02d}"
        desc = (
            f"{'reverse ' if target_speed < 0 else ''}target {target_speed:.1f} m/s, steer {steer:+.2f}, "
            f"end_speed {geom['end_speed']:.1f} m/s, end_x {geom['end_x']:.1f} m, "
            f"collision {geom['collision']}, halt_geom {geom['stop_at_line']}"
        )
        samples[sid] = Sample(
            id=sid,
            speed=target_speed,
            steer=steer,
            route_error=geom["route_error"],
            offroad=geom["offroad"],
            collision=geom["collision"],
            stop_at_line=geom["stop_at_line"],
            end_speed=geom["end_speed"],
            end_x=geom["end_x"],
            end_z=geom["end_z"],
            description=desc,
        )
        kept += 1
    # Brake straight: stop where the car is. A full stop from the random mix can carry a
    # full-range steer, and one that recentres can sweep into a car stopped beside it.
    geom = rollout(
        ego_x, ego_z, speed, 0.0, 0.0, curvature, stop_line_z, obstacles,
        current_steer=current_steer, hold_offset_m=ego_x,
    )
    sid = f"t{kept:02d}"
    samples[sid] = Sample(
        id=sid,
        speed=0.0,
        steer=geom["first_steer"],
        route_error=geom["route_error"],
        offroad=geom["offroad"],
        collision=geom["collision"],
        stop_at_line=geom["stop_at_line"],
        end_speed=geom["end_speed"],
        end_x=geom["end_x"],
        end_z=geom["end_z"],
        description=(
            f"brake straight, end_speed {geom['end_speed']:.1f} m/s, end_x {geom['end_x']:.1f} m, "
            f"collision {geom['collision']}, halt_geom {geom['stop_at_line']}"
        ),
        hold_offset_m=float(ego_x),
    )
    kept += 1
    for frac in PULL_OVER_SPEED_FRACTIONS:
        target_speed = cap * frac
        geom = rollout(
            ego_x,
            ego_z,
            speed,
            target_speed,
            0.0,
            curvature,
            stop_line_z,
            obstacles,
            current_steer=current_steer,
            hold_offset_m=PULL_OVER_OFFSET_M,
        )
        if geom["offroad"] > 0.55 and target_speed > 0.5:
            continue
        sid = f"t{kept:02d}"
        desc = (
            f"pull over to {PULL_OVER_OFFSET_M:+.1f} m, target {target_speed:.1f} m/s, "
            f"end_speed {geom['end_speed']:.1f} m/s, end_x {geom['end_x']:.1f} m, "
            f"collision {geom['collision']}, halt_geom {geom['stop_at_line']}"
        )
        samples[sid] = Sample(
            id=sid,
            speed=target_speed,
            steer=geom["first_steer"],
            route_error=geom["route_error"],
            offroad=geom["offroad"],
            collision=geom["collision"],
            stop_at_line=geom["stop_at_line"],
            end_speed=geom["end_speed"],
            end_x=geom["end_x"],
            end_z=geom["end_z"],
            description=desc,
            hold_offset_m=PULL_OVER_OFFSET_M,
        )
        kept += 1
    if len(samples) < 2:
        samples["t00"] = Sample("t00", speed, 0.0, ego_x, 0.0, False, False, speed, ego_x, ego_z, "hold")
        samples["t01"] = Sample("t01", 0.0, 0.0, ego_x, 0.0, False, True, 0.0, ego_x, ego_z, "stop")
    return samples


def partition_ids(candidates: Dict[str, List[Any]], meta: Optional[Dict[str, Any]] = None) -> Tuple[List[str], List[str], List[str]]:
    halt: List[str] = []
    lateral: List[str] = []
    lane: List[str] = []
    meta = meta or {}
    for cid, vec in candidates.items():
        info = meta.get(cid) if isinstance(meta.get(cid), dict) else {}
        end_speed = float(info.get("end_speed", vec[0] if vec else 0.0) or 0.0)
        steer = float(info.get("steer", vec[1] if vec and len(vec) > 1 else 0.0) or 0.0)
        stop_line = bool(info.get("stop_at_line", vec[5] if vec and len(vec) > 5 else False))
        if end_speed < 1.2 or stop_line:
            halt.append(cid)
        elif abs(steer) >= 0.12:
            lateral.append(cid)
        else:
            lane.append(cid)
    if not lane:
        lane = [cid for cid in candidates if cid not in halt]
    return halt, lateral, lane


def candidates_as_vecs(samples: Dict[str, Sample]) -> Dict[str, List[Any]]:
    return {sid: sample.as_vec() for sid, sample in samples.items()}


def candidates_meta(samples: Dict[str, Sample]) -> Dict[str, Any]:
    return {sid: sample.meta() for sid, sample in samples.items()}
