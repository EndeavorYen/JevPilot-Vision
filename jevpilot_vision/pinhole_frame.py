"""In-process pinhole frames for the ten named driving scenarios.

Camera constants match ``jevpilot_vision.ipm`` so blob bottoms land on the
same ground plane the obstacle mapper reads. This is not the web-city camera.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

from jevpilot_vision.ipm import (
    CAM_F_PX,
    CAM_H_M,
    CAM_THETA,
    CAM_U0,
    CAM_V0,
    HORIZON_V,
    IMAGE_H,
    IMAGE_W,
)

SKY = (135, 180, 230)
ROAD = (80, 80, 80)
LANE = (255, 255, 255)


def _project(rel_x: float, rel_z: float) -> Optional[Tuple[float, float]]:
    if rel_z <= 0.3 or rel_z > 80.0:
        return None
    pitch = math.atan(CAM_H_M / rel_z)
    v = CAM_V0 + CAM_F_PX * math.tan(pitch - CAM_THETA)
    u = CAM_U0 + CAM_F_PX * rel_x / rel_z
    return u, v


def _paint_signal(draw: Any, rel_x: float, rel_z: float, color: Tuple[int, int, int]) -> None:
    """Keep the lamp in the upper band so the red mask is a light, not a vehicle."""
    projected = _project(rel_x, rel_z)
    if projected is None:
        return
    u, v = projected
    height_px = CAM_F_PX * 0.4 / rel_z
    width_px = CAM_F_PX * 0.4 / rel_z
    upper_bottom = int(IMAGE_H * 0.48) - 2
    bottom = min(v - 8.0, float(upper_bottom))
    top = bottom - height_px
    if v > bottom:
        draw.line([(u, bottom), (u, v)], fill=(50, 50, 55), width=2)
    draw.rectangle(
        (u - width_px / 2.0, top, u + width_px / 2.0, bottom),
        fill=color,
    )


def _paint_subject(draw: Any, rel_x: float, rel_z: float, height_m: float, color: Tuple[int, int, int], width_m: float) -> None:
    projected = _project(rel_x, rel_z)
    if projected is None:
        return
    u, v = projected
    height_px = CAM_F_PX * height_m / rel_z
    width_px = CAM_F_PX * width_m / rel_z
    draw.rectangle(
        (u - width_px / 2.0, v - height_px, u + width_px / 2.0, v),
        fill=color,
    )


def _actor(env: Any, name: str) -> Any:
    return getattr(env, name, None)


def _lanes(draw: Any, env: Any) -> None:
    sign = 1.0 if float(getattr(env, "track_curvature", 0.0) or 0.0) >= 0.0 else -1.0
    for side in (-1.6, 1.6):
        points = []
        distance = 4.0
        while distance <= 60.0:
            projected = _project(side + sign * 0.004 * distance * distance, distance)
            if projected is not None:
                points.append(projected)
            distance += 4.0
        if len(points) >= 2:
            draw.line(points, fill=LANE, width=2)


def render_pinhole_frame(scenario: str, env: Any) -> Any:
    """Return a 224×224 RGB view. Skips a subject when rel_z is outside (0.3, 80]."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (int(IMAGE_W), int(IMAGE_H)), SKY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, int(HORIZON_V) + 1, int(IMAGE_W), int(IMAGE_H)), fill=ROAD)
    ego_x = float(getattr(env, "x", 0.0) or 0.0)
    ego_z = float(getattr(env, "z", 0.0) or 0.0)

    if scenario == "traffic_light_red":
        intersection = _actor(env, "intersection") or {}
        rel_z = float(intersection.get("stop_line_ahead_m", 55.0)) - ego_z
        _paint_signal(draw, 0.0, rel_z, (220, 30, 30))
    elif scenario == "speed_zone_city":
        _paint_subject(draw, 2.0, 40.0 - ego_z, 0.6, (240, 240, 240), 0.6)
    elif scenario == "pedestrian_jaywalking":
        actor = _actor(env, "pedestrian") or {}
        _paint_subject(
            draw,
            float(actor.get("x", 0.0)) - ego_x,
            float(actor.get("z", 0.0)) - ego_z,
            1.7,
            (20, 20, 20),
            0.5,
        )
    elif scenario == "roadside_parked_hazard":
        actor = _actor(env, "roadside_obstacle") or {}
        _paint_subject(
            draw,
            float(actor.get("x", 0.0)) - ego_x,
            float(actor.get("z", 0.0)) - ego_z,
            1.5,
            (100, 100, 100),
            1.9,
        )
    elif scenario == "cut_in_vehicle":
        actor = _actor(env, "cut_in_vehicle") or {}
        _paint_subject(
            draw,
            float(actor.get("x", 0.0)) - ego_x,
            float(actor.get("z", 0.0)) - ego_z,
            1.5,
            (100, 100, 100),
            1.8,
        )
    elif scenario == "ambiguous_priority":
        actor = _actor(env, "other_vehicle") or {}
        _paint_subject(
            draw,
            float(actor.get("x", 0.0)) - ego_x,
            float(actor.get("z", 0.0)) - ego_z,
            1.5,
            (100, 100, 100),
            1.8,
        )
    elif scenario == "construction_detour":
        actor = _actor(env, "construction") or {}
        _paint_subject(
            draw,
            float(actor.get("x", 0.0)) - ego_x,
            float(actor.get("z", 0.0)) - ego_z,
            0.7,
            (230, 120, 20),
            0.4,
        )
    elif scenario == "emergency_vehicle":
        actor = _actor(env, "emergency_vehicle") or {}
        _paint_subject(
            draw,
            float(actor.get("x", 0.0)) - ego_x,
            float(actor.get("z", 0.0)) - ego_z,
            1.5,
            (200, 40, 40),
            1.8,
        )
    elif scenario == "sharp_curve":
        _lanes(draw, env)
    return image
