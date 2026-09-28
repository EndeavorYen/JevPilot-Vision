"""Ego-centric IPM from a ground-contact pixel. No world (x, z).

Four onboard pinhole cameras share one intrinsic: 224×224, about 100°
horizontal, horizon at v=120. Each camera differs only by yaw.
rel_z is metres ahead of the bumper, rel_x is metres to the right.

Range: at this resolution a car keeps the 12 mask pixels a blob needs out to
about 42 m. That covers the 40 m give-way rule, not the 45 m go-around one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

IMAGE_W = 224
IMAGE_H = 224
CAM_H_M = 1.4
CAM_HFOV_DEG = 100.0
CAM_F_PX = (IMAGE_W / 2.0) / math.tan(math.radians(CAM_HFOV_DEG / 2.0))
CAM_U0 = IMAGE_W / 2.0
CAM_V0 = IMAGE_H / 2.0
HORIZON_V = 120.0
CAM_THETA = -math.atan((HORIZON_V - CAM_V0) / CAM_F_PX)

_KIND = {
    "vehicle": "vehicle",
    "pedestrian": "pedestrian",
    "construction": "roadside",
}


@dataclass(frozen=True)
class Camera:
    """One onboard camera. yaw_deg turns clockwise from forward: right is 90."""

    name: str
    yaw_deg: float
    hfov_deg: float = CAM_HFOV_DEG

    def to_ego(self, lx: float, lz: float) -> Tuple[float, float]:
        yaw = math.radians(self.yaw_deg)
        return (
            lx * math.cos(yaw) + lz * math.sin(yaw),
            lz * math.cos(yaw) - lx * math.sin(yaw),
        )

    def from_ego(self, rel_x: float, rel_z: float) -> Tuple[float, float]:
        yaw = math.radians(self.yaw_deg)
        return (
            rel_x * math.cos(yaw) - rel_z * math.sin(yaw),
            rel_x * math.sin(yaw) + rel_z * math.cos(yaw),
        )


FRONT = Camera("front", 0.0)
CAMERAS = (FRONT, Camera("right", 90.0), Camera("rear", 180.0), Camera("left", 270.0))


def ground_uv_to_ego(u: float, v: float, camera: Camera = FRONT) -> Optional[Dict[str, float]]:
    """Pinhole + flat ground. Pixels on or above the horizon are dropped."""
    if v <= HORIZON_V + 1.5:
        return None
    pitch = CAM_THETA + math.atan((v - CAM_V0) / CAM_F_PX)
    if abs(pitch) < 1e-4:
        return None
    lz = CAM_H_M / math.tan(pitch)
    if lz <= 0.3 or lz > 80.0:
        return None
    lx = lz * (u - CAM_U0) / CAM_F_PX
    rel_x, rel_z = camera.to_ego(lx, lz)
    return {"rel_x": float(rel_x), "rel_z": float(rel_z)}


def camera_obstacles_from_blobs(
    blobs: Dict[str, Dict[str, float]],
    *,
    camera: Camera = FRONT,
    image_w: int = IMAGE_W,
    image_h: int = IMAGE_H,
) -> List[Dict[str, Any]]:
    """Bottom-center of each blob → ego (rel_x, rel_z). Lights are not obstacles."""
    out: List[Dict[str, Any]] = []
    for kind, box in blobs.items():
        mapped = _KIND.get(kind)
        if mapped is None:
            continue
        if float(box.get("w") or 0) > 0.45:
            continue
        u = float(box["cx"]) * image_w
        v = (float(box["cy"]) + float(box["h"]) / 2.0) * image_h
        ego = ground_uv_to_ego(u, v, camera=camera)
        if ego is None:
            continue
        out.append(
            {
                "kind": mapped,
                "rel_x": round(ego["rel_x"], 2),
                "rel_z": round(ego["rel_z"], 2),
            }
        )
    return out
