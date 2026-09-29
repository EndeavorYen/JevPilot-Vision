"""Fleet mode (#3): any car asks the same decision core as the player.

A fleet car is described only by what it can sense: its speed, its lane offset,
ego-relative boxes (rel_x right, rel_z ahead) and the next stop line. No world
position of any car enters a decision.

Policies:
- heuristic: geometric ranking, no signal veto.
- raw_flat: flat scoring in raw mode (no signal veto).
- semif: flat scoring with the red-light veto.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from jevpilot_vision.trajectory_sampler import (
    VECTOR_INSTRUCTIONS,
    candidates_as_vecs,
    candidates_meta,
    sample_trajectories,
)

POLICIES: Dict[str, Dict[str, Any]] = {
    "heuristic": {"mode": "heuristic", "raw_mode": False},
    "raw_flat": {"mode": "flat", "raw_mode": True},
    "semif": {"mode": "flat", "raw_mode": False},
}
SENSOR_RANGE_M = 42.0  # the onboard camera range (jevpilot_vision.ipm)


def agent_state(
    *,
    speed_mps: float,
    speed_ceiling_mps: float,
    obstacles: List[Dict[str, Any]],
    intersection: Optional[Dict[str, Any]] = None,
    lateral_offset_m: float = 0.0,
    current_steer: float = 0.0,
    curvature: float = 0.0,
    seed: int = 0,
) -> Dict[str, Any]:
    """Driving state for one car, with this frame's sampled trajectories."""
    samples = sample_trajectories(
        ego_x=float(lateral_offset_m),
        ego_z=0.0,
        speed=float(speed_mps),
        curvature=float(curvature),
        stop_line_z=float(intersection["distance_to_line_m"]) if intersection else None,
        obstacles=obstacles,
        seed=int(seed),
        speed_ceiling=float(speed_ceiling_mps),
        current_steer=float(current_steer),
    )
    return {
        "speed_mps": round(float(speed_mps), 2),
        "speed_ceiling_mps": round(float(speed_ceiling_mps), 2),
        "on_road": abs(float(lateral_offset_m)) <= 4.0,
        "lateral_offset_m": round(float(lateral_offset_m), 2),
        "track_curvature": float(curvature),
        "intersection": intersection,
        "candidates": candidates_as_vecs(samples),
        "candidate_meta": candidates_meta(samples),
    }


def decide(engine: Any, policy: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Score one car's options on the live decision path. Returns the chosen trajectory."""
    from jevpilot_vision.drive import score_drive_request

    if policy not in POLICIES:
        raise ValueError(f"unknown fleet policy {policy!r}; use one of {sorted(POLICIES)}")
    cfg = POLICIES[policy]
    request = {
        "model": engine.model_name,
        "mode": cfg["mode"],
        "raw_mode": cfg["raw_mode"],
        "state": state,
        "questions": {
            "vector": {
                "type": "choice",
                "instructions": VECTOR_INSTRUCTIONS,
                "criteria": {k: None for k in state["candidates"]},
            }
        },
    }
    started = time.perf_counter()
    response = score_drive_request(engine, request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    choice = (response.get("answers") or {}).get("vector", {}).get("choice")
    vec = state["candidates"].get(choice)
    if vec is None:
        choice, vec = next(iter(state["candidates"].items()))
    meta = state["candidate_meta"].get(choice) or {}
    return {
        "choice": choice,
        "vector": list(vec),
        "target_speed_mps": float(vec[0]),
        "steer": float(vec[1]),
        "hold_offset_m": meta.get("hold_offset_m"),
        "fail_safe": bool((response.get("meta") or {}).get("fail_safe")),
        "latency_ms": round(elapsed_ms, 3),
    }
