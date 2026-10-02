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
) -> Dict[str, Any]:
    """Objects on the road with range, and the state of the light ahead."""
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
        })
    objects.sort(key=lambda o: o["ahead_m"])
    if tracker is not None:
        objects = tracker.update(objects, time.monotonic() if t is None else t)

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
    if readable:
        readable.sort(key=lambda r: -r[0])
        states = {state for _, state, _ in readable}
        if len(states) == 1:
            _, state, det = readable[0]
            signal = {"state": state, "conf": round(float(det["conf"]), 3), "box": [round(v, 1) for v in det["box"]]}
        else:
            signal = {"state": "unknown", "conf": 0.0, "conflict": sorted(states)}
    return {"backend": backend, "objects": objects, "signal": signal}


class Tracker:
    """Matches each object to the same kind nearby in the previous frame, for a closing speed.

    Pairs are one to one, nearest first. A pair that would mean more than 40 m/s is two different
    objects. After a gap of more than half a second, or if time runs backwards (a reload), nothing
    is matched.
    """

    MAX_GAP_S = 0.5
    MAX_SPEED_MPS = 40.0

    def __init__(self, gate_m: float = 3.0) -> None:
        self.gate_m = gate_m
        self.prev: List[Dict[str, Any]] = []
        self.prev_t: Optional[float] = None

    def update(self, objects: List[Dict[str, Any]], t: float) -> List[Dict[str, Any]]:
        dt = None if self.prev_t is None else t - self.prev_t
        closing = [0.0] * len(objects)
        if dt is not None and 0 < dt <= self.MAX_GAP_S:
            pairs = []
            for i, obj in enumerate(objects):
                for j, old in enumerate(self.prev):
                    if old["kind"] != obj["kind"]:
                        continue
                    d = math.hypot(old["ahead_m"] - obj["ahead_m"], old["right_m"] - obj["right_m"])
                    if d <= self.gate_m and d / dt <= self.MAX_SPEED_MPS:
                        pairs.append((d, i, j))
            used_i, used_j = set(), set()
            for _, i, j in sorted(pairs):
                if i in used_i or j in used_j:
                    continue
                used_i.add(i)
                used_j.add(j)
                closing[i] = (self.prev[j]["ahead_m"] - objects[i]["ahead_m"]) / dt
        out = [{**obj, "closing_mps": round(c, 2)} for obj, c in zip(objects, closing)]
        self.prev, self.prev_t = out, t
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


class Perception:
    """The detector and the tracker behind /v1/vision's `perception` field."""

    def __init__(self, detector: Optional[Detector] = None) -> None:
        self.detector = detector or Detector()
        self.tracker = Tracker()

    def front(self, image: Any, t: Optional[float] = None) -> Dict[str, Any]:
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
        )
        out["status"] = status  # loading / failed / ready: why a frame has no detections
        out["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return out


_perception: Optional[Perception] = None


def get_perception() -> Perception:
    global _perception
    if _perception is None:
        _perception = Perception()
    return _perception
