"""Onboard perception for Vision mode (#18): objects and the signal from the front camera's pixels.

A COCO object detector (RT-DETR) finds pedestrians, vehicles and traffic lights. The world is
flat and the camera sits at a known height looking level, so the bottom of a box on the ground
gives its range. A box whose height does not fit a person or a car at that range (a lamp post, a
wall) is dropped. A traffic light's state is read from the pixels inside its box: whichever lamp is
lit. A short tracker turns successive ranges into a closing speed.

Nothing here reads the simulator. SigLIP (jevpilot_vision.vision) stays the scene encoder; this
adds instances and range on top of it.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# COCO labels we drive around, and what they are to the planner.
KIND_OF = {
    "person": "pedestrian",
    "car": "car",
    "truck": "car",
    "bus": "car",
    "motorcycle": "motorcycle",
    "bicycle": "motorcycle",
    "traffic light": "traffic_light",
}
GROUND_KINDS = ("pedestrian", "car", "motorcycle")
# Real heights, to tell a person from a lamp post at the same range.
HEIGHT_M = {"pedestrian": 1.7, "car": 1.5, "motorcycle": 1.6}
MAX_RANGE_M = 80.0

# The onboard camera (jevpilot_vision/web/semif-layer.js: ONBOARD_HFOV, onboardMount).
ONBOARD_HFOV_DEG = 100.0
ONBOARD_HEIGHT_M = 1.45
# The narrow forward camera (semif-layer.js NARROW_HFOV), for lights too far for the wide one.
NARROW_HFOV_DEG = 40.0

# r50: on Solmare Coast frames (640x360) it finds 94% of cars within 40 m against r18's 45%, ~45 ms
# on an RTX 5080; set SEMIF_DETECTOR to change it.
DEFAULT_DETECTOR = "PekingU/rtdetr_r50vd"


@dataclass(frozen=True)
class CameraModel:
    """A level pinhole camera at `height_m` above flat ground."""

    width: int
    height: int
    hfov_deg: float = ONBOARD_HFOV_DEG
    height_m: float = ONBOARD_HEIGHT_M

    @property
    def fx(self) -> float:
        return (self.width / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)

    @property
    def cx(self) -> float:
        return self.width / 2.0

    @property
    def cy(self) -> float:
        return self.height / 2.0

    def ground_point(self, u: float, v: float) -> Optional[tuple[float, float]]:
        """(ahead, right) in metres of the ground point seen at pixel (u, v); None above the horizon."""
        below = v - self.cy
        if below <= 0.5:
            return None
        ahead = self.height_m * self.fx / below
        return ahead, (u - self.cx) * ahead / self.fx


def classify_light(crop: np.ndarray) -> str:
    """red / amber / green / unknown, from the lit lamp inside a traffic light's box.

    A lit lamp is a light source: bright, clearly coloured, and much brighter than the rest of its
    box (the dark housing). Its hue says which lamp. Sky and foliage are too grey or too dim, and
    sunlit ground caught in the box does not outshine it. 15-20 m away the lamp is a few soft
    pixels, so the colour test is mild and the brightness test does the work.
    """
    if crop is None or crop.size == 0:
        return "unknown"
    rgb = crop[..., :3].reshape(-1, 3).astype(np.float64) / 255.0
    mx, mn = rgb.max(axis=1), rgb.min(axis=1)
    bright = max(0.7, float(np.median(mx)) + 0.25)
    lit = (mx > bright) & ((mx - mn) / np.maximum(mx, 1e-6) > 0.2)
    if not lit.any():
        return "unknown"
    r, g, b = rgb[lit, 0], rgb[lit, 1], rgb[lit, 2]
    span = np.maximum(mx[lit] - mn[lit], 1e-6)
    hue = np.where(
        mx[lit] == r,
        ((g - b) / span) % 6.0,
        np.where(mx[lit] == g, (b - r) / span + 2.0, (r - g) / span + 4.0),
    ) * 60.0
    counts = {
        "red": int(np.count_nonzero((hue < 18) | (hue > 340))),
        "amber": int(np.count_nonzero((hue >= 25) & (hue <= 62))),  # a clipped amber core is pure yellow
        "green": int(np.count_nonzero((hue >= 85) & (hue <= 165))),
    }
    state, n = max(counts.items(), key=lambda kv: kv[1])
    return state if n >= 2 else "unknown"


def _hue_state(rgb: np.ndarray) -> np.ndarray:
    """Per pixel: 0 none, 1 red, 2 amber, 3 green, for bright, coloured pixels (lamp candidates)."""
    mx, mn = rgb.max(axis=-1), rgb.min(axis=-1)
    span = np.maximum(mx - mn, 1e-6)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    hue = np.where(mx == r, ((g - b) / span) % 6.0, np.where(mx == g, (b - r) / span + 2.0, (r - g) / span + 4.0)) * 60.0
    lit = (mx > 0.75) & ((mx - mn) / np.maximum(mx, 1e-6) > 0.18)
    out = np.zeros(mx.shape, dtype=np.int8)
    out[lit & ((hue < 18) | (hue > 340))] = 1
    out[lit & (hue >= 25) & (hue <= 62)] = 2
    out[lit & (hue >= 85) & (hue <= 165)] = 3
    return out


MAX_LIT_PIXELS = 4000  # a frame this full of bright colour has no lamp worth finding


def find_lamps(image: np.ndarray, camera: "CameraModel", max_area: int = 400) -> List[Dict[str, Any]]:
    """Lit signal lamps found from pixels alone, for heads the detector did not box: a small bright
    coloured blob (red, amber, green) above the horizon whose surroundings are dark (the housing).
    Sky is blue and fails the colour test; a sunlit warm slope has nothing dark around it."""
    h = int(camera.cy)
    rgb = image[:h, :, :3].astype(np.float64) / 255.0
    state = _hue_state(rgb)
    if np.count_nonzero(state) > MAX_LIT_PIXELS:
        return []
    value = rgb.max(axis=-1)
    seen = np.zeros(state.shape, dtype=bool)
    lamps = []
    for y0, x0 in zip(*np.nonzero(state)):
        if seen[y0, x0]:
            continue
        kind = state[y0, x0]
        stack, pixels = [(y0, x0)], []
        seen[y0, x0] = True
        while stack and len(pixels) <= max_area:
            y, x = stack.pop()
            pixels.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < state.shape[0] and 0 <= nx < state.shape[1] and not seen[ny, nx] and state[ny, nx] == kind:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if not (2 <= len(pixels) <= max_area):
            continue
        ys, xs = [p[0] for p in pixels], [p[1] for p in pixels]
        bx0, bx1, by0, by1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
        bw, bh = bx1 - bx0, by1 - by0
        ring = value[max(0, by0 - 2 * bh) : min(h, by1 + 2 * bh), max(0, bx0 - bw) : min(state.shape[1], bx1 + bw)]
        if ring.size and float(np.median(ring)) < 0.45:
            lamps.append({"state": {1: "red", 2: "amber", 3: "green"}[int(kind)], "box": [float(bx0), float(by0), float(bx1), float(by1)], "area": len(pixels)})
    return lamps


def decode_detections(
    logits: np.ndarray,
    boxes: np.ndarray,
    id2label: Dict[int, str],
    size: tuple[int, int],
    threshold: float = 0.35,
) -> List[Dict[str, Any]]:
    """RT-DETR outputs (per-query class logits, normalised cx,cy,w,h boxes) to pixel boxes."""
    width, height = size
    prob = 1.0 / (1.0 + np.exp(-np.asarray(logits, dtype=np.float64)))
    out = []
    for query, row in enumerate(prob):
        label_id = int(np.argmax(row))
        conf = float(row[label_id])
        kind = KIND_OF.get(id2label.get(label_id, ""))
        if kind is None or conf < threshold:
            continue
        cx, cy, w, h = (float(v) for v in boxes[query])
        out.append({
            "kind": kind,
            "conf": conf,
            "box": [(cx - w / 2) * width, (cy - h / 2) * height, (cx + w / 2) * width, (cy + h / 2) * height],
        })
    return out


def perceive(
    detections: Optional[Sequence[Dict[str, Any]]],
    image: np.ndarray,
    camera: CameraModel,
    *,
    backend: str = "detector",
    tracker: Optional["Tracker"] = None,
    t: Optional[float] = None,
    yaw_rps: float = 0.0,
    speed_mps: float = 0.0,
) -> Dict[str, Any]:
    """Objects on the road with range, and the state of the light ahead.

    `signal` is the hue threshold's reading, as before (Vision (map) reads it). `signal_read` (#76)
    reads the governing head by which of its three lamp cells is lit, next to the hue threshold:
    where both read a colour and they differ it is unknown (logged); else whichever read one."""
    if detections is None:
        return {"backend": "none", "objects": [], "signal": {"state": "unknown", "conf": 0.0}}
    objects = []
    lights = []
    for det in detections:
        x0, y0, x1, y1 = det["box"]
        kind = det["kind"]
        if kind == "traffic_light":
            lights.append(det)
            continue
        if kind not in GROUND_KINDS:
            continue
        point = camera.ground_point((x0 + x1) / 2.0, y1)
        if point is None:
            continue
        ahead, right = point
        if not (0.5 < ahead < MAX_RANGE_M) or abs(right) > 25.0:
            continue
        expected_px = camera.fx * HEIGHT_M[kind] / ahead
        if not (0.45 <= (y1 - y0) / expected_px <= 2.2):
            continue  # too tall or too short for what it claims to be at this range
        objects.append({
            "kind": kind,
            "ahead_m": round(ahead, 2),
            "right_m": round(right, 2),
            "width_m": round((x1 - x0) * ahead / camera.fx, 2),
            "conf": round(float(det["conf"]), 3),
            **box_flow_fields(det["box"], camera, kind),
        })
    objects.sort(key=lambda o: o["ahead_m"])
    if tracker is not None:
        objects = tracker.update(objects, time.monotonic() if t is None else t, yaw_rps, speed_mps)

    # The light that governs us is ahead, above the horizon, near the middle of the view; the
    # biggest such box is the nearest. Readable lights that disagree give no answer at all.
    signal = {"state": "unknown", "conf": 0.0}
    h, w = image.shape[0], image.shape[1]
    readable = []
    for det in lights:
        x0, y0, x1, y1 = det["box"]
        off = abs((x0 + x1) / 2.0 - camera.cx) / (0.35 * camera.width)
        if off > 1.0 or (y0 + y1) / 2.0 > camera.cy:
            continue
        crop = image[max(0, int(y0)) : min(h, int(math.ceil(y1))), max(0, int(x0)) : min(w, int(math.ceil(x1)))]
        state = classify_light(crop)
        if state != "unknown":
            readable.append(((x1 - x0) * (y1 - y0) * (1.0 - 0.5 * off), state, det))
    if not readable:
        # No boxed head was readable: look for lit lamps in dark housings directly.
        for lamp in find_lamps(image, camera):
            x0, y0, x1, y1 = lamp["box"]
            off = abs((x0 + x1) / 2.0 - camera.cx) / (0.35 * camera.width)
            if off <= 1.0:
                readable.append((lamp["area"] * (1.0 - 0.5 * off), lamp["state"], {"conf": 0.5, "box": lamp["box"], "source": "lamp"}))
    if readable:
        readable.sort(key=lambda r: -r[0])
        states = {state for _, state, _ in readable}
        if len(states) == 1:
            _, state, det = readable[0]
            signal = {"state": state, "conf": round(float(det["conf"]), 3), "box": [round(v, 1) for v in det["box"]], "source": det.get("source", "detector")}
        else:
            signal = {"state": "unknown", "conf": 0.0, "conflict": sorted(states)}
    out = {"backend": backend, "objects": objects, "signal": signal}
    out["signal_read"] = read_governing_light(lights, image, camera, signal)
    return out


# Reading which lamp is lit (#76, the owner's choice of 2026-10-04): a head's lamps stand red, amber,
# green from the top (semif-scenery.js, the bundle's signal heads), so the lit one is the brightest
# of three cells, whatever colour the renderer gives it. Thresholds picked on tuning-seed captures
# (benchmarks/eval_lights.py --sweep), in both the current world and a #30 retraction preview.
CELL_STATES = ("red", "amber", "green")
CELL_COLUMNS = 0.6  # the middle of the box's width: the lamps, not the backplate's edges
CELL_PERCENTILE = 90.0  # a lit lamp is a few bright pixels, not the cell's mean
CELL_MIN_CONTRAST = 1.3  # the lit cell is at least this much brighter than the next
CELL_MIN_LUMA = 0.25  # and bright at all (0..1); 0.15-0.4 read the same on the captures
# Any one source may only make the car more careful (#85): a green the hue threshold does not also
# read must stand out further. At 2.0 the lamp cells misread 1-3 of 210-286 tuning frames.
CELL_GREEN_ALONE_CONTRAST = 2.0


def read_lamp_cells(crop: np.ndarray, min_contrast: float = CELL_MIN_CONTRAST, min_luma: float = CELL_MIN_LUMA) -> tuple[str, float]:
    """(state, contrast) from a head's crop: which third, top to bottom, is lit. Unknown when no
    cell stands out (a head seen side-on, too small to split, or between phases)."""
    h, w = crop.shape[0], crop.shape[1]
    if h < 6 or w < 2:
        return "unknown", 0.0
    rgb = crop[..., :3].astype(np.float32) / 255.0
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    c0 = int(round(w * (1.0 - CELL_COLUMNS) / 2.0))
    middle = luma[:, c0 : max(c0 + 1, w - c0)]
    cells = [float(np.percentile(band, CELL_PERCENTILE)) for band in np.array_split(middle, 3, axis=0)]
    order = sorted(range(3), key=lambda k: -cells[k])
    best, second = cells[order[0]], cells[order[1]]
    if best < min_luma:
        return "unknown", 0.0  # nothing lit
    contrast = best / max(second, 1e-3)
    if contrast < min_contrast:
        return "unknown", round(contrast, 2)
    return CELL_STATES[order[0]], round(contrast, 2)


def read_governing_light(lights: List[Dict[str, Any]], image: np.ndarray, camera: "CameraModel",
                         hue_signal: Dict[str, Any]) -> Dict[str, Any]:
    """The light that governs us (ahead, above the horizon, near the middle; the biggest) read by
    its lamp cells and by the hue threshold (#76), then held against the hue path's own reading of
    every head (`hue_signal`): its conflicts stand (two heads that disagree are an assumed red), a
    colour it read that differs is unknown, and with nothing read here its red or amber (a lamp found
    in the pixels) stands; a green from elsewhere alone does not. No boxed head: the hue path's reading stands."""
    out = _read_head(lights, image, camera, hue_signal)
    if out.get("source") == "hue":
        return out
    if hue_signal.get("conflict"):
        return {**out, "state": "unknown", "conf": 0.0, "conflict": hue_signal["conflict"]}
    path = hue_signal.get("state")
    if path in CELL_STATES and out["state"] in CELL_STATES and path != out["state"]:
        logger.info("traffic light: heads read %s, governing head reads %s: unknown", path, out["state"])
        return {**out, "state": "unknown", "conf": 0.0, "conflict": sorted({path, out["state"]})}
    if out["state"] == "unknown" and path in ("red", "amber") and not out.get("conflict"):  # only toward caution (#85)
        return {**out, "state": path, "conf": hue_signal.get("conf", 0.0)}
    return out


def _read_head(lights: List[Dict[str, Any]], image: np.ndarray, camera: "CameraModel",
               hue_signal: Dict[str, Any]) -> Dict[str, Any]:
    h, w = image.shape[0], image.shape[1]
    heads = []
    for det in lights:
        x0, y0, x1, y1 = det["box"]
        off = abs((x0 + x1) / 2.0 - camera.cx) / (0.35 * camera.width)
        if off > 1.0 or (y0 + y1) / 2.0 > camera.cy:
            continue
        heads.append(((x1 - x0) * (y1 - y0) * (1.0 - 0.5 * off), det))
    if not heads:
        return {**hue_signal, "hue": hue_signal.get("state", "unknown"), "cells": None, "source": "hue"}
    _, det = max(heads, key=lambda r: r[0])
    x0, y0, x1, y1 = det["box"]
    crop = image[max(0, int(y0)) : min(h, int(math.ceil(y1))), max(0, int(x0)) : min(w, int(math.ceil(x1)))]
    hue = classify_light(crop) if crop.size else "unknown"
    cells, contrast = read_lamp_cells(crop) if crop.size else ("unknown", 0.0)
    out = {"box": [round(v, 1) for v in det["box"]], "hue": hue, "cells": cells, "contrast": contrast}
    if cells == "green" and hue != "green" and contrast < CELL_GREEN_ALONE_CONTRAST:
        cells = "unknown"  # a lone, faint green: not enough to drive on
        out["cells"] = cells
    readable = {s for s in (hue, cells) if s in CELL_STATES}
    if len(readable) > 1:
        logger.info("traffic light: hue reads %s, lamp cells read %s: unknown", hue, cells)
        return {**out, "state": "unknown", "conf": 0.0, "conflict": sorted(readable)}
    if readable:
        return {**out, "state": readable.pop(), "conf": round(float(det["conf"]), 3)}
    return {**out, "state": "unknown", "conf": 0.0}


# Lane lines from the front camera (#80, the new Vision's de-mapping): the painted lines read in a
# bird's-eye resampling of the road, the flat-ground camera model inverted (the same known camera
# height the ranging uses, so renderer-bound like it). Chosen, then checked against the map's lane
# on tuning-seed captures (benchmarks/eval_lanes.py).
LANE_NEAR_M, LANE_FAR_M, LANE_STEP_M = 4.0, 24.0, 0.5  # rows of the bird's-eye view
LANE_SIDE_M, LANE_CELL_M = 8.0, 0.1  # half its width and its column pitch
LANE_MARK_MIN = 0.18  # a marking is this much brighter (luma 0..1) than the road 0.5 m either side
LANE_MARK_MAX_M = 0.5  # and no wider than this (coast lines are 0.1-0.2 m)
LANE_MIN_POINTS = 8  # rows a line needs to count
LANE_WIDTH_M = (2.5, 8.0)  # a lane narrower or wider than this is two lines that are not one lane
LANE_MAX_SLOPE = 0.3  # a lane line runs within about 17 degrees of the car (crosswalk stripes do not)
LANE_KERB_M = 0.8  # a kerb: the road turns bright (pavement) and stays bright at least this far


def _birdseye(image: np.ndarray, camera: "CameraModel") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(luma[rows, cols], ahead_m[rows], right_m[cols]) of the ground in front, nearest pixel."""
    h, w = image.shape[0], image.shape[1]
    ahead = np.arange(LANE_NEAR_M, LANE_FAR_M + 1e-6, LANE_STEP_M)
    right = np.arange(-LANE_SIDE_M, LANE_SIDE_M + 1e-6, LANE_CELL_M)
    v = camera.cy + camera.height_m * camera.fx / ahead
    u = camera.cx + right[None, :] * camera.fx / ahead[:, None]
    vi = np.clip(np.round(v).astype(int), 0, h - 1)[:, None].repeat(len(right), axis=1)
    ui = np.round(u).astype(int)
    inside = (ui >= 0) & (ui < w) & (v[:, None] < h)
    rgb = image[vi, np.clip(ui, 0, w - 1), :3].astype(np.float32) / 255.0
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    luma[~inside] = np.nan
    return luma, ahead, right


def _mark_points(luma: np.ndarray, ahead: np.ndarray, right: np.ndarray) -> List[tuple[float, float]]:
    """(ahead, right) of each marking crossing: brighter than the road 0.5 m to both sides, narrow."""
    k = int(round(0.5 / LANE_CELL_M))
    pts = []
    for r, row in enumerate(luma):
        side = np.full_like(row, np.nan)
        side[k:-k] = np.fmin(row[: -2 * k], row[2 * k:])  # the darker of the two sides
        bright = (row - side) > LANE_MARK_MIN
        c = 0
        n = len(row)
        while c < n:
            if not bright[c]:
                c += 1
                continue
            start = c
            while c < n and bright[c]:
                c += 1
            if (c - start) * LANE_CELL_M <= LANE_MARK_MAX_M:
                pts.append((float(ahead[r]), float(right[start] + (c - 1 - start) * LANE_CELL_M / 2.0)))
    return pts


def _kerb_points(luma: np.ndarray, ahead: np.ndarray, right: np.ndarray) -> List[tuple[float, float]]:
    """(ahead, right) where the road meets a bright kerb or pavement: the first column, going out
    from the car on each side, that is LANE_MARK_MIN brighter than the road at the car and stays so
    for LANE_KERB_M (a painted line is narrower, and _mark_points reads it)."""
    run = int(round(LANE_KERB_M / LANE_CELL_M))
    centre = int(np.argmin(np.abs(right)))
    pts = []
    for r, row in enumerate(luma):
        road = np.nanmedian(row[max(0, centre - 10) : centre + 11])
        if not np.isfinite(road):
            continue
        bright = (row - road) > LANE_MARK_MIN
        for step in (1, -1):
            c = centre
            while 0 <= c < len(row) and 0 <= c + step * run < len(row):
                if bright[c] and all(bright[c + step * k] for k in range(run)):
                    pts.append((float(ahead[r]), float(right[c]) - step * LANE_CELL_M / 2.0))
                    break
                c += step
    return pts


def _fit_lines(pts: List[tuple[float, float]]) -> List[Dict[str, float]]:
    """Marking points grouped into lines (by where they would cross the car's axis) and each
    fitted right = a + b * ahead + c * ahead^2, least squares, one outlier pass."""
    lines = []
    remaining = sorted(pts, key=lambda p: p[1])
    while remaining:
        # seed with the nearest-ahead points and grow along a straight guess
        seed = remaining[0][1]
        group = [p for p in remaining if abs(p[1] - seed) <= 0.6 + 0.04 * p[0]]
        first = set(group) | {remaining[0]}  # always taken out: every pass leaves fewer points
        if len(group) < LANE_MIN_POINTS:
            remaining = [p for p in remaining if p not in first]
            continue
        for _ in range(2):
            A = np.array([[1.0, a, a * a] for a, _ in group])
            y = np.array([r for _, r in group])
            coef, *_ = np.linalg.lstsq(A, y, rcond=None)
            fit = lambda a: coef[0] + coef[1] * a + coef[2] * a * a  # noqa: E731
            group = [p for p in remaining if abs(p[1] - fit(p[0])) <= 0.35]
            if len(group) < LANE_MIN_POINTS:
                break
        if len(group) >= LANE_MIN_POINTS and abs(coef[1] + 2 * coef[2] * LANE_NEAR_M) <= LANE_MAX_SLOPE:
            resid = float(np.sqrt(np.mean([(r - fit(a)) ** 2 for a, r in group])))
            lines.append({"a": float(coef[0]), "b": float(coef[1]), "c": float(coef[2]), "points": len(group), "resid": resid})
        taken = first | set(group)
        remaining = [p for p in remaining if p not in taken]
    return lines


def lane_from_frame(image: np.ndarray, camera: "CameraModel", prior_width: Optional[float] = None) -> Dict[str, Any]:
    """Our lane as the front camera sees it (#80): `offset_m` of the car right of the lane's centre
    (the planner's sign), `width_m`, `heading_rad` of the lane relative to the car, `curvature` (1/m),
    `conf` 0..1, and the two lines used (`left`, `right`: a, b, c). The pair is the lines either side
    of the car, a lane's width apart, best supported, and, with `prior_width` (the lane's width a
    moment ago, LaneTracker), nearest that width. No such pair: conf 0."""
    luma, ahead, right = _birdseye(image, camera)
    lines = _fit_lines(_mark_points(luma, ahead, right)) + _fit_lines(_kerb_points(luma, ahead, right))
    out: Dict[str, Any] = {"conf": 0.0, "lines": len(lines)}
    best = None
    for left in (ln for ln in lines if ln["a"] < -0.5):
        for right_line in (ln for ln in lines if ln["a"] > 0.5):
            width = right_line["a"] - left["a"]
            if not (LANE_WIDTH_M[0] <= width <= LANE_WIDTH_M[1]):
                continue
            score = min(left["points"], right_line["points"]) - (4.0 * abs(width - prior_width) if prior_width else 0.0)
            if best is None or score > best[0]:
                best = (score, left, right_line, width)
    if best is None:
        return out
    _, left, right_line, width = best
    support = min(left["points"], right_line["points"]) / len(ahead)
    spread = max(left["resid"], right_line["resid"])
    conf = max(0.0, min(1.0, support * 1.5)) * max(0.0, 1.0 - spread / 0.35)
    return {
        **out,
        "offset_m": round(-(left["a"] + right_line["a"]) / 2.0, 3),
        "width_m": round(width, 3),
        "heading_rad": round(float(np.arctan((left["b"] + right_line["b"]) / 2.0)), 4),
        "curvature": round(float(left["c"] + right_line["c"]), 5),
        "conf": round(conf, 3),
        "lines": len(lines),
        "left": [round(left[k], 4) for k in ("a", "b", "c")],
        "right": [round(right_line[k], 4) for k in ("a", "b", "c")],
    }


class LaneTracker:
    """The lane between frames (#80): the width read a moment ago steers which pair of lines is the
    lane, and a frame with no lane keeps the last one, its confidence halving each frame, for up to
    LANE_HOLD_S; after that, no lane."""

    HOLD_S = 1.5

    def __init__(self) -> None:
        self.last: Optional[Dict[str, Any]] = None
        self.at: Optional[float] = None
        self.width: Optional[float] = None

    def update(self, image: np.ndarray, camera: "CameraModel", t: float) -> Dict[str, Any]:
        lane = lane_from_frame(image, camera, self.width)
        if lane["conf"] > 0:
            self.width = lane["width_m"] if self.width is None else 0.7 * self.width + 0.3 * lane["width_m"]
            self.last, self.at = lane, t
            return {**lane, "held_s": 0.0}
        if self.last is not None and self.at is not None and 0 <= t - self.at <= self.HOLD_S:
            self.last = {**self.last, "conf": round(self.last["conf"] / 2.0, 3)}
            return {**self.last, "held_s": round(t - self.at, 2)}
        self.last = self.at = self.width = None
        return lane


# Optical flow B (#75): how a tracked box moves. Chosen, not measured; the TTC error they give is
# measured by benchmarks/eval_perception.py on tuning-seed captures (see #75).
FLOW_WINDOW_S = 1.5  # = Tracker.MAX_GAP_S: a track's samples older than one allowed gap are dropped
FLOW_MIN_SAMPLES = 3  # a line through two points fits their noise exactly
FLOW_MIN_SPAN_S = 0.25  # captures run at 3-20 frames/s (one request at a time); tracks often last < 0.5 s
FLOW_MAX_TTC_S = 20.0  # slower expansion is under the jitter of a +-1 px box at 15 m (tests/test_perception.py)
FLOW_EDGE_PX = 2.0  # a box this close to the frame's edge is cut off: its size is not the object's


def box_flow_fields(box: Sequence[float], camera: "CameraModel", kind: str = "car") -> Dict[str, Any]:
    """The pixel box, the size its expansion is read from and its bearing from the optical axis:
    what the tracker's flow reads. A walker's width swings with its stride, so its height. A box
    cut by the frame's edge has no size (None): entering the view, it would read as closing."""
    x0, y0, x1, y1 = (float(v) for v in box)
    if kind == "pedestrian":  # sized by height: only the top and bottom edges cut it
        cut = y0 <= FLOW_EDGE_PX or y1 >= camera.height - FLOW_EDGE_PX
    else:  # sized by width
        cut = x0 <= FLOW_EDGE_PX or x1 >= camera.width - FLOW_EDGE_PX
    return {
        "box_px": [round(float(v), 1) for v in box],
        "scale_px": None if cut else round(y1 - y0 if kind == "pedestrian" else x1 - x0, 2),
        "bearing_rad": round(math.atan2((x0 + x1) / 2.0 - camera.cx, camera.fx), 5),
    }


def _slope(samples: List[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares (slope, value at the last sample's time)."""
    n = len(samples)
    mt = sum(t for t, _ in samples) / n
    mv = sum(v for _, v in samples) / n
    var = sum((t - mt) ** 2 for t, _ in samples)
    slope = sum((t - mt) * (v - mv) for t, v in samples) / var if var > 0 else 0.0
    return slope, mv + slope * (samples[-1][0] - mt)


def _enough(samples: List[tuple[float, float]]) -> bool:
    return len(samples) >= FLOW_MIN_SAMPLES and samples[-1][0] - samples[0][0] >= FLOW_MIN_SPAN_S


def box_flow(history: List[tuple[float, Optional[float], float, float, float, float]], ahead_m: float, right_m: float) -> Dict[str, Optional[float]]:
    """TTC from the box's expansion and the speed toward our lane's line, over (t, scale_px or
    None, right_m, ahead_m, ego yaw rate, ego speed) samples.

    Expansion: at a constant closing speed 1/size falls linearly in time, so
    TTC = (1/s) / -(d(1/s)/dt) holds without knowing the range. Sideways: the fitted rate of the
    box centre's ground position (ahead * tan(bearing): both its change of range and of bearing),
    less what the bend adds. On a bend of curvature k = yaw / speed, anything keeping to its lane
    `a` m ahead sits k * a^2 / 2 further right in our frame than its lane's offset, so the fit runs
    over right - k * a^2 / 2: a parked car's slide as we close on it around the bend, and a car
    taking the bend with us, both come out as no sideways motion. None: not enough of the track
    yet, or not closing."""
    out: Dict[str, Optional[float]] = {"ttc_s": None, "toward_center_mps": None}
    sized = [(t, 1.0 / s) for t, s, _r, _a, _w, _v in history if s]
    if _enough(sized):
        slope, inv_now = _slope(sized)
        if slope < 0 and inv_now > 0 and inv_now / -slope <= FLOW_MAX_TTC_S:
            out["ttc_s"] = round(inv_now / -slope, 2)
    bends = [w / v for _t, _s, _r, _a, w, v in history if v > 0.5]  # standing still: no bend to take out
    curvature = sum(bends) / len(bends) if bends else 0.0
    placed = [(t, r - curvature * a * a / 2.0) for t, _s, r, a, _w, _v in history]
    if _enough(placed):
        lateral, _now = _slope(placed)  # right positive, the bend taken out
        side = 1.0 if right_m > 0 else -1.0 if right_m < 0 else 0.0
        out["toward_center_mps"] = round(-side * lateral, 2)
    return out


class Tracker:
    """Matches each object to the same kind nearby in the previous frame, for a closing speed.

    Pairs are one to one, nearest first. A pair that would mean more than 40 m/s is two different
    objects. After a gap of more than 1.5 s (one perception cycle can take most of a second), or if
    time runs backwards (a reload), nothing is matched. An unmatched object's closing speed is
    None: unknown, not zero (zero would mean it drives away at our own speed).

    Objects with a pixel box (`box_flow_fields`) also carry their box flow (#75): `ttc_s` and
    `toward_center_mps`, from the matched track's recent boxes. `yaw_rps` and `speed_mps` are the
    car's own gyro and odometer when the frame was taken (yaw positive turning right): with them a
    bend is not read as the others moving sideways.
    """

    MAX_GAP_S = 1.5
    MAX_SPEED_MPS = 40.0

    def __init__(self, gate_m: float = 3.0) -> None:
        self.gate_m = gate_m
        self.prev: List[Dict[str, Any]] = []
        self.prev_t: Optional[float] = None
        self.history: List[List[tuple[float, Optional[float], float, float, float, float]]] = []  # per entry of prev

    def update(self, objects: List[Dict[str, Any]], t: float, yaw_rps: float = 0.0, speed_mps: float = 0.0) -> List[Dict[str, Any]]:
        dt = None if self.prev_t is None else t - self.prev_t
        closing: List[Optional[float]] = [None] * len(objects)
        matched: List[Optional[int]] = [None] * len(objects)
        if dt is not None and 0 < dt <= self.MAX_GAP_S:
            pairs = []
            for i, obj in enumerate(objects):
                for j, old in enumerate(self.prev):
                    if old["kind"] != obj["kind"]:
                        continue
                    d = math.hypot(old["ahead_m"] - obj["ahead_m"], old["right_m"] - obj["right_m"])
                    # Within the gate plus what a car could cover in dt, and not faster than 40 m/s.
                    if d <= self.gate_m + 12.0 * dt and d / dt <= self.MAX_SPEED_MPS:
                        pairs.append((d, i, j))
            used_i, used_j = set(), set()
            for _, i, j in sorted(pairs):
                if i in used_i or j in used_j:
                    continue
                used_i.add(i)
                used_j.add(j)
                closing[i] = (self.prev[j]["ahead_m"] - objects[i]["ahead_m"]) / dt
                matched[i] = j
        out, history = [], []
        for obj, c, j in zip(objects, closing, matched):
            row = {**obj, "closing_mps": None if c is None else round(c, 2)}
            past = [h for h in self.history[j] if t - h[0] <= FLOW_WINDOW_S] if j is not None else []
            if "box_px" in obj:
                scale = obj.get("scale_px")
                past = past + [(t, float(scale) if scale and scale > 0 else None, float(obj["right_m"]), float(obj["ahead_m"]),
                                float(yaw_rps or 0.0), float(speed_mps or 0.0))]
                row.update(box_flow(past, float(obj["ahead_m"]), float(obj["right_m"])))
            out.append(row)
            history.append(past)
        self.prev, self.prev_t, self.history = out, t, history
        return out


def pick_device(cuda: Optional[bool] = None) -> Optional[str]:
    """Where the detector runs: CUDA when there is one, the CPU only when asked for
    (SEMIF_PERCEPTION_DEVICE=cpu; r50 at 640x640 per frame is slow there), else nowhere."""
    if os.environ.get("SEMIF_PERCEPTION", "1") == "0":
        return None
    asked = os.environ.get("SEMIF_PERCEPTION_DEVICE")
    if asked:
        return asked
    if cuda is None:
        try:
            import torch

            cuda = bool(torch.cuda.is_available())
        except Exception:
            cuda = False
    return "cuda" if cuda else None


class Detector:
    """RT-DETR with its pre- and post-processing done here (transformers' image processors need
    torchvision, which is not a dependency). The weights load in a background thread on first
    use; until then each frame reports "loading" instead of waiting (status: off / loading /
    ready / failed)."""

    def __init__(self, model_id: Optional[str] = None, device: Optional[str] = None, threshold: float = 0.35) -> None:
        self.model_id = model_id or os.environ.get("SEMIF_DETECTOR", DEFAULT_DETECTOR)
        self.device = device
        self.threshold = threshold
        self.status = "off"
        self._model = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _build(self, device: str) -> Any:
        import torch
        from transformers import AutoModelForObjectDetection

        self._torch = torch
        return AutoModelForObjectDetection.from_pretrained(self.model_id).to(device).eval()

    def _load(self, device: str) -> None:
        try:
            self._model = self._build(device)
            self.device = device
            self.status = "ready"
            logger.info("perception: %s on %s", self.model_id, device)
        except Exception as err:  # no weights, no torch, no network: Vision mode must know
            logger.warning("perception: detector unavailable (%s)", err)
            self.status = "failed"

    def start(self) -> None:
        """Begin loading the weights in the background (once)."""
        with self._lock:
            if self._thread is not None or self.status != "off":
                return
            device = self.device or pick_device()
            if device is None:
                self.status = "failed"
                return
            self.status = "loading"
            self._thread = threading.Thread(target=self._load, args=(device,), name="perception-load", daemon=True)
            self._thread.start()

    def wait(self, timeout: Optional[float] = None) -> str:
        """Block until loading finishes (benchmarks and tests); returns the status."""
        self.start()
        if self._thread is not None:
            self._thread.join(timeout)
        return self.status

    def detect_or_status(self, image: Any) -> tuple:
        """(status, detections in pixels of `image`); detections only when the model is ready."""
        if self.status == "off":
            self.start()
        if self.status != "ready":
            return self.status, None
        return "ready", self._detect(image)

    def detect(self, image: Any) -> Optional[List[Dict[str, Any]]]:
        return self.detect_or_status(image)[1]

    def _detect(self, image: Any) -> List[Dict[str, Any]]:
        torch = self._torch
        rgb = image.convert("RGB")
        width, height = rgb.size
        pixels = np.asarray(rgb.resize((640, 640)), dtype=np.float32) / 255.0
        x = torch.from_numpy(pixels).permute(2, 0, 1)[None].to(self.device)
        with torch.no_grad():
            out = self._model(pixel_values=x)
        return decode_detections(
            out.logits[0].float().cpu().numpy(),
            out.pred_boxes[0].float().cpu().numpy(),
            self._model.config.id2label,
            (width, height),
            self.threshold,
        )


# The narrow camera's reading counts only from a head near enough to govern the coming stop line.
# Coast junctions are at least 100 m apart, and the next junction's near-side head stands about
# 101 m past this junction's line; this junction's own heads are within 75 m while the car is up
# to about 60 m out (closer in, the wide camera reads them). Range comes from size, as drawn
# (semif-scenery.js restyleSignals): a boxed head with its backplate is 2.05 m tall, a lamp found
# from pixels 0.368 m. A one-row error in a 3-4 px lamp is about 25%, inside the 75-101 m gap.
NARROW_MAX_RANGE_M = 75.0
HEAD_HEIGHT_M = {"detector": 2.05, "lamp": 0.368}


def _within_narrow_range(signal: Dict[str, Any], camera: CameraModel) -> Dict[str, Any]:
    box = signal.get("box")
    if signal.get("state") == "unknown" or not box:
        return signal
    tall = float(box[3]) - float(box[1])
    if tall <= 0:
        return {"state": "unknown", "conf": 0.0}
    range_m = camera.fx * HEAD_HEIGHT_M.get(signal.get("source", "detector"), HEAD_HEIGHT_M["detector"]) / tall
    if range_m > NARROW_MAX_RANGE_M:
        return {"state": "unknown", "conf": 0.0}
    return {**signal, "range_m": round(range_m, 1)}


class Perception:
    """The detector and the tracker behind /v1/vision's `perception` field."""

    def __init__(self, detector: Optional[Detector] = None) -> None:
        self.detector = detector or Detector()
        self.tracker = Tracker()
        self.lanes = LaneTracker()
        # Lane lines (#80) are read only when asked: nothing drives on them yet, and they cost about
        # 6 ms of CPU per frame (benchmarks/eval_lanes.py). SEMIF_LANES=1 turns them on.
        self.lanes_on = os.environ.get("SEMIF_LANES", "0") == "1"

    def front(self, image: Any, t: Optional[float] = None, narrow: Any = None, yaw_rps: float = 0.0,
              speed_mps: float = 0.0) -> Dict[str, Any]:
        """Objects and the light from the wide front camera; with `narrow`, the light comes from the
        narrow camera whenever it can read one (2.5 times the magnification)."""
        t0 = time.perf_counter()
        width, height = image.size
        status, detections = self.detector.detect_or_status(image)
        out = perceive(
            detections,
            np.asarray(image.convert("RGB")),
            CameraModel(width=width, height=height),
            backend=self.detector.model_id if detections is not None else "none",
            tracker=self.tracker,
            t=t,
            yaw_rps=yaw_rps,
            speed_mps=speed_mps,
        )
        out["signal"]["camera"] = "front"
        if self.lanes_on and detections is not None:  # the painted lines need no detector, but share its frames (#80)
            out["lane"] = self.lanes.update(np.asarray(image.convert("RGB")), CameraModel(width=width, height=height),
                                            time.monotonic() if t is None else t)
        if "signal_read" in out:
            out["signal_read"]["camera"] = "front"
        if narrow is not None and detections is not None:
            _, far = self.detector.detect_or_status(narrow)
            if far is not None:
                lights = [d for d in far if d["kind"] == "traffic_light"]
                nw, nh = narrow.size
                narrow_cam = CameraModel(width=nw, height=nh, hfov_deg=NARROW_HFOV_DEG)
                seen = perceive(lights, np.asarray(narrow.convert("RGB")), narrow_cam)
                out["signal"] = _merge_narrow(out["signal"], _within_narrow_range(seen["signal"], narrow_cam))
                if "signal_read" in out and "signal_read" in seen:
                    out["signal_read"] = _merge_narrow(out["signal_read"], _within_narrow_range(seen["signal_read"], narrow_cam))
        out["status"] = status  # loading / failed / ready: why a frame has no detections
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return out


def _merge_narrow(wide: Dict[str, Any], seen: Dict[str, Any]) -> Dict[str, Any]:
    """The wide camera's reading, or the narrow one's when the wide one has none. The narrow
    camera may be reading the next junction: two readings that disagree give no answer."""
    if wide["state"] == "unknown" and not wide.get("conflict"):
        if seen["state"] != "unknown" or seen.get("conflict"):
            return {**seen, "camera": "narrow"}
        return wide
    if seen["state"] != "unknown" and seen["state"] != wide["state"]:
        return {"state": "unknown", "conf": 0.0, "conflict": sorted({seen["state"], wide["state"]}), "camera": "both"}
    return wide


_perception: Optional[Perception] = None


def get_perception() -> Perception:
    global _perception
    if _perception is None:
        _perception = Perception()
    return _perception
