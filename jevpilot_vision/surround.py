"""Four onboard cameras merged into one ego-relative list. No world (x, z).

Each camera runs the same blob + IPM pass. Adjacent cameras overlap, so a
subject seen twice is kept once. An emergency vehicle is a vehicle blob with a
warning-light blob on it; position comes from the vehicle blob's ground contact.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from jevpilot_vision.ipm import (
    CAMERAS,
    HORIZON_V,
    IMAGE_H,
    IMAGE_W,
    Camera,
    camera_obstacles_from_blobs,
    ground_uv_to_ego,
)

DEDUPE_M = 2.5
# Rows below this one are road (the renderer paints from HORIZON_V + 1).
GROUND_ROW = int(HORIZON_V)

Blobs = Dict[str, Dict[str, float]]


def surround_blobs(frames: Dict[str, Any]) -> Dict[str, Blobs]:
    """Blob pass on each camera frame, keyed by camera name."""
    from jevpilot_vision.vision import blobs_from_frame

    return {name: blobs_from_frame(image, ground_row=GROUND_ROW) for name, image in frames.items()}


def _camera(name: str) -> Optional[Camera]:
    return next((cam for cam in CAMERAS if cam.name == name), None)


def _off_center(item: Dict[str, Any], camera: Camera) -> float:
    """Angle off the camera axis. The camera that sees it most centrally wins."""
    lx, lz = camera.from_ego(item["rel_x"], item["rel_z"])
    return abs(math.atan2(lx, lz))


def surround_obstacles(blobs_by_camera: Dict[str, Blobs]) -> List[Dict[str, Any]]:
    """One ego-relative obstacle list. rel_z < 0 is behind, rel_x < 0 is left."""
    seen: List[tuple[float, Dict[str, Any]]] = []
    for name, blobs in blobs_by_camera.items():
        camera = _camera(name)
        if camera is None:
            continue
        for item in camera_obstacles_from_blobs(blobs, camera=camera):
            seen.append((_off_center(item, camera), item))
    seen.sort(key=lambda pair: pair[0])
    out: List[Dict[str, Any]] = []
    for _angle, item in seen:
        duplicate = any(
            kept["kind"] == item["kind"]
            and math.hypot(kept["rel_x"] - item["rel_x"], kept["rel_z"] - item["rel_z"]) < DEDUPE_M
            for kept in out
        )
        if not duplicate:
            out.append(item)
    return out


def _emergency_in(blobs: Blobs, camera: Camera) -> Optional[Dict[str, float]]:
    light = blobs.get("emergency")
    body = blobs.get("vehicle")
    if light is None or body is None:
        return None
    if abs(float(light["cx"]) - float(body["cx"])) > (float(light["w"]) + float(body["w"])) / 2.0:
        return None
    light_bottom = float(light["cy"]) + float(light["h"]) / 2.0
    body_top = float(body["cy"]) - float(body["h"]) / 2.0
    if abs(light_bottom - body_top) > 0.05:
        return None
    u = float(body["cx"]) * IMAGE_W
    v = (float(body["cy"]) + float(body["h"]) / 2.0) * IMAGE_H
    return ground_uv_to_ego(u, v, camera=camera)


def emergency_from_surround(blobs_by_camera: Dict[str, Blobs]) -> Optional[Dict[str, Any]]:
    """Nearest emergency vehicle any camera sees, or None. Siren is not a pixel."""
    best: Optional[Dict[str, float]] = None
    for name, blobs in blobs_by_camera.items():
        camera = _camera(name)
        if camera is None:
            continue
        ego = _emergency_in(blobs, camera)
        if ego is None:
            continue
        if best is None or math.hypot(ego["rel_x"], ego["rel_z"]) < math.hypot(best["rel_x"], best["rel_z"]):
            best = ego
    if best is None:
        return None
    return {
        "distance_m": round(abs(best["rel_z"]), 1),
        "lateral_offset_m": round(best["rel_x"], 1),
        "behind": best["rel_z"] < 0.0,
    }



TRACK_GATE_M = 3.0
# A speed step between frames is IPM noise more than motion; move part of the way.
TRACK_SMOOTHING = 0.35
# An overtaking car goes through the blind spot beside the ego. Coast it this long.
COAST_S = 1.0
COAST_UNTIL_AHEAD_M = 6.0


def track_obstacles(
    previous: Optional[List[Dict[str, Any]]],
    current: List[Dict[str, Any]],
    dt: float,
) -> List[Dict[str, Any]]:
    """Add rel_vz_mps (d rel_z / dt) by matching each obstacle to the nearest one of its kind last frame.

    Ego-relative only: a parked car ahead reads about -ego_speed, a car catching up from behind reads > 0.
    A car catching up that no camera sees this frame is coasted on its last speed (coasted_s) until it
    is COAST_UNTIL_AHEAD_M ahead or COAST_S has passed.
    """
    if not previous or dt <= 0.0:
        return [dict(item) for item in current]
    out: List[Dict[str, Any]] = []
    used: set[int] = set()
    for item in current:
        tracked = dict(item)
        best_i: Optional[int] = None
        best_d = TRACK_GATE_M
        for i, old in enumerate(previous):
            if i in used or old.get("kind") != item.get("kind"):
                continue
            ox, oz = float(old["rel_x"]), float(old["rel_z"])
            if old.get("rel_vz_mps") is not None:
                oz += float(old["rel_vz_mps"]) * dt
            d = math.hypot(ox - float(item["rel_x"]), oz - float(item["rel_z"]))
            if d < best_d:
                best_i, best_d = i, d
        if best_i is not None:
            used.add(best_i)
            old = previous[best_i]
            measured = (float(item["rel_z"]) - float(old["rel_z"])) / dt
            if old.get("rel_vz_mps") is not None:
                prior = float(old["rel_vz_mps"])
                measured = prior + TRACK_SMOOTHING * (measured - prior)
            tracked["rel_vz_mps"] = round(measured, 2)
        out.append(tracked)
    for i, old in enumerate(previous):
        rel_vz = old.get("rel_vz_mps")
        if i in used or rel_vz is None or float(rel_vz) <= 0.0:
            continue
        coasted = float(old.get("coasted_s", 0.0)) + dt
        rel_z = float(old["rel_z"]) + float(rel_vz) * dt
        if coasted > COAST_S or rel_z > COAST_UNTIL_AHEAD_M:
            continue
        ghost = dict(old)
        ghost["rel_z"] = round(rel_z, 2)
        ghost["coasted_s"] = round(coasted, 3)
        out.append(ghost)
    return out
