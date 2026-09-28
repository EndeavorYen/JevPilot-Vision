"""In-process pinhole frames for the ten named driving scenarios.

Camera constants match ``jevpilot_vision.ipm`` so blob bottoms land on the
same ground plane the obstacle mapper reads. This is not the web-city camera.
Each of the four onboard cameras renders the same subjects from its own yaw.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from jevpilot_vision.ipm import (
    CAMERAS,
    CAM_F_PX,
    CAM_H_M,
    CAM_THETA,
    CAM_U0,
    CAM_V0,
    FRONT,
    HORIZON_V,
    IMAGE_H,
    IMAGE_W,
    Camera,
)

SKY = (135, 180, 230)
ROAD = (80, 80, 80)
LANE = (255, 255, 255)
VEHICLE = (100, 100, 100)
EMERGENCY_BODY = (200, 40, 40)
EMERGENCY_LIGHT = (30, 60, 230)


def _project(rel_x: float, rel_z: float, camera: Camera = FRONT) -> Optional[Tuple[float, float, float]]:
    """Ego (rel_x, rel_z) → (u, v, depth) in ``camera``. None when behind it or too far."""
    lx, lz = camera.from_ego(rel_x, rel_z)
    if lz <= 0.3 or lz > 80.0:
        return None
    pitch = math.atan(CAM_H_M / lz)
    v = CAM_V0 + CAM_F_PX * math.tan(pitch - CAM_THETA)
    u = CAM_U0 + CAM_F_PX * lx / lz
    return u, v, lz


def _paint_signal(draw: Any, rel_x: float, rel_z: float, color: Tuple[int, int, int], camera: Camera) -> None:
    """Keep the lamp in the upper band so the red mask is a light, not a vehicle."""
    projected = _project(rel_x, rel_z, camera)
    if projected is None:
        return
    u, v, depth = projected
    height_px = max(2.0, CAM_F_PX * 0.4 / depth)
    width_px = max(2.0, CAM_F_PX * 0.4 / depth)
    upper_bottom = int(IMAGE_H * 0.48) - 2
    bottom = min(v - 8.0, float(upper_bottom))
    top = bottom - height_px
    if v > bottom:
        draw.line([(u, bottom), (u, v)], fill=(50, 50, 55), width=2)
    draw.rectangle(
        (u - width_px / 2.0, top, u + width_px / 2.0, bottom),
        fill=color,
    )


def _paint_subject(
    draw: Any,
    rel_x: float,
    rel_z: float,
    height_m: float,
    color: Tuple[int, int, int],
    width_m: float,
    camera: Camera,
    light: Optional[Tuple[int, int, int]] = None,
) -> None:
    projected = _project(rel_x, rel_z, camera)
    if projected is None:
        return
    u, v, depth = projected
    height_px = CAM_F_PX * height_m / depth
    width_px = CAM_F_PX * width_m / depth
    top = v - height_px
    draw.rectangle(
        (u - width_px / 2.0, top, u + width_px / 2.0, v),
        fill=color,
    )
    if light is not None:
        bar_px = max(2.0, CAM_F_PX * 0.25 / depth)
        draw.rectangle(
            (u - width_px / 3.0, top - bar_px, u + width_px / 3.0, top),
            fill=light,
        )


def _actor(env: Any, name: str) -> Any:
    return getattr(env, name, None)


def _lanes(draw: Any, env: Any, camera: Camera) -> None:
    sign = 1.0 if float(getattr(env, "track_curvature", 0.0) or 0.0) >= 0.0 else -1.0
    for side in (-1.6, 1.6):
        points = []
        distance = -60.0
        while distance <= 60.0:
            bend = sign * 0.004 * distance * distance if distance > 0 else 0.0
            projected = _project(side + bend, distance, camera)
            if projected is not None:
                points.append(projected[:2])
            distance += 4.0
        if len(points) >= 2:
            draw.line(points, fill=LANE, width=2)


def _rel(env: Any, actor: Dict[str, Any], ego_x: float, ego_z: float) -> Tuple[float, float]:
    return float(actor.get("x", 0.0)) - ego_x, float(actor.get("z", 0.0)) - ego_z


def render_pinhole_frame(scenario: str, env: Any, camera: Camera = FRONT) -> Any:
    """Return a 224×224 RGB view from ``camera``. Skips a subject outside its (0.3, 80] m depth."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (int(IMAGE_W), int(IMAGE_H)), SKY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, int(HORIZON_V) + 1, int(IMAGE_W), int(IMAGE_H)), fill=ROAD)
    ego_x = float(getattr(env, "x", 0.0) or 0.0)
    ego_z = float(getattr(env, "z", 0.0) or 0.0)

    if scenario == "traffic_light_red":
        intersection = _actor(env, "intersection") or {}
        rel_z = float(intersection.get("stop_line_ahead_m", 55.0)) - ego_z
        _paint_signal(draw, 0.0, rel_z, (220, 30, 30), camera)
    elif scenario == "speed_zone_city":
        _paint_subject(draw, 2.0, 40.0 - ego_z, 0.6, (240, 240, 240), 0.6, camera)
    elif scenario == "pedestrian_jaywalking":
        rel_x, rel_z = _rel(env, _actor(env, "pedestrian") or {}, ego_x, ego_z)
        _paint_subject(draw, rel_x, rel_z, 1.7, (20, 20, 20), 0.5, camera)
    elif scenario == "roadside_parked_hazard":
        rel_x, rel_z = _rel(env, _actor(env, "roadside_obstacle") or {}, ego_x, ego_z)
        _paint_subject(draw, rel_x, rel_z, 1.5, VEHICLE, 1.9, camera)
    elif scenario == "cut_in_vehicle":
        rel_x, rel_z = _rel(env, _actor(env, "cut_in_vehicle") or {}, ego_x, ego_z)
        _paint_subject(draw, rel_x, rel_z, 1.5, VEHICLE, 1.8, camera)
    elif scenario == "ambiguous_priority":
        rel_x, rel_z = _rel(env, _actor(env, "other_vehicle") or {}, ego_x, ego_z)
        _paint_subject(draw, rel_x, rel_z, 1.5, VEHICLE, 1.8, camera)
    elif scenario == "construction_detour":
        rel_x, rel_z = _rel(env, _actor(env, "construction") or {}, ego_x, ego_z)
        _paint_subject(draw, rel_x, rel_z, 0.7, (230, 120, 20), 0.4, camera)
    elif scenario == "emergency_vehicle":
        rel_x, rel_z = _rel(env, _actor(env, "emergency_vehicle") or {}, ego_x, ego_z)
        _paint_subject(
            draw, rel_x, rel_z, 1.5, EMERGENCY_BODY, 1.8, camera, light=EMERGENCY_LIGHT
        )
    elif scenario == "sharp_curve":
        _lanes(draw, env, camera)
    return image


def render_surround_frames(scenario: str, env: Any) -> Dict[str, Any]:
    """One frame per onboard camera, keyed by camera name."""
    return {camera.name: render_pinhole_frame(scenario, env, camera) for camera in CAMERAS}
