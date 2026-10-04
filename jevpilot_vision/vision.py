"""Visual evidence for JevPilot. Leaves stay sampled trajectories.

Default encoder is SigLIP (#48). Patch tokens (32–64) are a visual prefix for
the sliced head; compact scores are HUD-only. Tests use synthetic labels.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

VISION_FIELDS = (
    "backend",
    "signal",
    "event",
    "red",
    "green",
    "pedestrian",
    "vehicle",
    "construction",
    "prefix_tokens",
    "scoring_error",
)

# Event text when SigLIP cannot score (#70): it must not read as a clear road.
CLASSIFIER_DOWN_EVENT = "camera classifier unavailable; signal and hazards unknown"

SURROUND_ORDER = ("front", "right", "rear", "left")
HAZARD_FIELDS = ("pedestrian", "vehicle", "construction")
# Blob kinds read only by jevpilot_vision.surround; not motion events.
SURROUND_ONLY_BLOBS = frozenset({"emergency"})

_PROMPTS = (
    ("red", "a red traffic light facing the camera"),
    ("green", "a green traffic light facing the camera"),
    ("pedestrian", "a pedestrian on the road in front of the car"),
    ("vehicle", "the rear of a car on the road ahead"),
    ("construction", "orange traffic cones and a construction barrier on the road"),
    ("clear", "an empty asphalt road with no people or cars"),
)


class _BoxAcc:
    def __init__(self) -> None:
        self.n = 0
        self.xmin = 10**9
        self.xmax = -1
        self.ymin = 10**9
        self.ymax = -1

    def add(self, x: int, y: int) -> None:
        self.n += 1
        if x < self.xmin:
            self.xmin = x
        if x > self.xmax:
            self.xmax = x
        if y < self.ymin:
            self.ymin = y
        if y > self.ymax:
            self.ymax = y

    def as_dict(self, width: int, height: int) -> Optional[Dict[str, float]]:
        if self.n < 12:
            return None
        bw = max(1, self.xmax - self.xmin + 1)
        bh = max(1, self.ymax - self.ymin + 1)
        return {
            "cx": (self.xmin + self.xmax) / 2.0 / float(width),
            "cy": (self.ymin + self.ymax) / 2.0 / float(height),
            "w": bw / float(width),
            "h": bh / float(height),
            "area": self.n / float(width * height),
        }


def _bbox_from_mask(mask: Any, width: int, height: int) -> Optional[Dict[str, float]]:
    import numpy as np

    ys, xs = np.where(mask)
    if xs.size < 12:
        return None
    xmin, xmax = int(xs.min()), int(xs.max())
    ymin, ymax = int(ys.min()), int(ys.max())
    bw = max(1, xmax - xmin + 1)
    bh = max(1, ymax - ymin + 1)
    return {
        "cx": (xmin + xmax) / 2.0 / float(width),
        "cy": (ymin + ymax) / 2.0 / float(height),
        "w": bw / float(width),
        "h": bh / float(height),
        "area": float(xs.size) / float(width * height),
    }


def blobs_from_frame(image: Any, ground_row: Optional[int] = None) -> Dict[str, Dict[str, float]]:
    """Axis-aligned blobs from RGB pixels. No world coordinates.

    ``ground_row`` is the horizon row. Vehicles are read from the rows below
    it; without it the band starts at 55% of the height.
    """
    import numpy as np

    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[0], arr.shape[1]
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]
    yy = np.arange(height)[:, None]
    upper = yy < int(height * 0.48)
    mid = yy > int(height * 0.48)
    lower = yy > int(height * 0.50)
    bottom = yy > (int(ground_row) if ground_row is not None else int(height * 0.55))
    masks = {
        "light_red": upper & (r > 180) & (g < 90) & (b < 90),
        "light_green": upper & (g > 150) & (r < 90) & (b < 90),
        "construction": mid & (r > 180) & (g > 70) & (g < 190) & (b < 90),
        "pedestrian": lower & (r < 40) & (g < 40) & (b < 40),
        "emergency": mid & (b > 180) & (r < 80) & (g < 110),
        "vehicle": bottom
        & (
            ((r >= 85) & (r <= 130) & (np.abs(r.astype(int) - g.astype(int)) < 18) & (np.abs(g.astype(int) - b.astype(int)) < 18))
            | ((r > 160) & (g < 80) & (b < 80))
        ),
    }
    out: Dict[str, Dict[str, float]] = {}
    for key, mask in masks.items():
        packed = _bbox_from_mask(mask, width, height)
        if packed is not None:
            out[key] = packed
    return out


def frame_motion(
    prev: Optional[Dict[str, Dict[str, float]]],
    curr: Dict[str, Dict[str, float]],
) -> list[Dict[str, Any]]:
    """Pixel-space onset / grow / cut-in. Tau is not emitted as seconds."""
    prev = prev or {}
    events: list[Dict[str, Any]] = []
    for kind, now in curr.items():
        if kind in SURROUND_ONLY_BLOBS:
            continue
        was = prev.get(kind)
        if was is None:
            events.append({"kind": kind, "onset": True, "growing": False, "cut_in": False})
            continue
        growing = now["w"] > was["w"] + max(0.015, 0.08 * was["w"])
        toward_center = abs(now["cx"] - 0.5) + 0.03 < abs(was["cx"] - 0.5)
        shifted = abs(now["cx"] - was["cx"]) > 0.03
        events.append(
            {
                "kind": kind,
                "onset": False,
                "growing": growing,
                "cut_in": toward_center and shifted,
            }
        )
    return events


def event_from_motion(motion: list[Dict[str, Any]], signal: str = "unknown") -> str:
    clauses: list[str] = []
    if signal == "red" or any(m["kind"] == "light_red" for m in motion):
        clauses.append("RED signal ahead, mandatory stop")
    elif signal == "green" or any(m["kind"] == "light_green" for m in motion):
        clauses.append("traffic light is green")
    for item in motion:
        kind = item["kind"]
        if kind.startswith("light_"):
            continue
        name = {"vehicle": "vehicle", "pedestrian": "person", "construction": "cones or barrier"}.get(kind, kind)
        if item["onset"]:
            clauses.append(f"a {name} appeared in frame")
        elif kind == "vehicle" and item["cut_in"] and item["growing"]:
            clauses.append("caution: vehicle cutting toward frame center, growing in the camera")
        elif item["growing"]:
            clauses.append(f"caution: {name} closing, growing in the camera")
        elif item["cut_in"]:
            clauses.append(f"caution: {name} sliding toward frame center")
        elif kind == "vehicle":
            clauses.append("vehicle visible ahead")
        elif kind == "pedestrian":
            clauses.append("pedestrian visible ahead")
        elif kind == "construction":
            clauses.append("construction or cones visible ahead")
    if not clauses:
        return "road clear ahead, maintain lane"
    # Keep one sentence for the prompt.
    return "; ".join(clauses[:3])


def camera_event(curr: Dict[str, Any], prev: Optional[Dict[str, Any]] = None) -> str:
    """Score-delta fallback when the frame has no trackable blob."""
    clauses: list[str] = []
    signal = str(curr.get("signal") or "unknown")
    if signal == "red":
        clauses.append("RED signal ahead, mandatory stop")
    elif signal == "green":
        clauses.append("traffic light is green")

    def rise(key: str, floor: float = 0.28, jump: float = 0.12) -> tuple[bool, bool]:
        now = float(curr.get(key) or 0.0)
        was = float((prev or {}).get(key) or 0.0)
        return now >= floor, (now - was) >= jump

    veh_hot, veh_up = rise("vehicle")
    if veh_hot and veh_up:
        clauses.append("a vehicle appeared in frame")
    elif veh_hot:
        clauses.append("vehicle visible ahead")
    ped_hot, ped_up = rise("pedestrian")
    if ped_hot and ped_up:
        clauses.append("a person appeared in frame")
    elif ped_hot:
        clauses.append("pedestrian visible ahead")
    con_hot, _con_up = rise("construction")
    if con_hot:
        clauses.append("construction or cones visible ahead")
    if not clauses:
        return "road clear ahead, maintain lane"
    return "; ".join(clauses)


def compact_vision(vision: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(vision, dict):
        return None
    packed: Dict[str, Any] = {}
    for key in VISION_FIELDS:
        if key in vision and vision[key] is not None:
            packed[key] = vision[key]
    return packed or None


def synthetic_vision(**labels: Any) -> Dict[str, Any]:
    """Fixture evidence. Not a substitute for GPU CLIP scores."""
    red = float(labels.get("red", 0.0))
    green = float(labels.get("green", 0.0))
    signal = "unknown"
    if red >= 0.35 and red >= green:
        signal = "red"
    elif green >= 0.35:
        signal = "green"
    out = {
        "backend": "synthetic",
        "signal": signal,
        "red": round(red, 3),
        "green": round(green, 3),
        "pedestrian": round(float(labels.get("pedestrian", 0.0)), 3),
        "vehicle": round(float(labels.get("vehicle", 0.0)), 3),
        "construction": round(float(labels.get("construction", 0.0)), 3),
        "prefix_tokens": 0,
    }
    out["event"] = camera_event(out, None)
    return out


def render_scenario_frame(scenario: str, env: Any = None) -> Any:
    """Draw a crude forward view so CLIP has pixels. Not a camera from 3D."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (224, 224), (120, 170, 220))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 120, 224, 224), fill=(70, 75, 78))
    draw.polygon([(112, 120), (40, 224), (184, 224)], fill=(50, 52, 54))
    dist = 30.0
    if env is not None:
        dist = max(4.0, 55.0 - float(getattr(env, "z", 0.0)))
    scale = max(8, int(80 * (20.0 / dist)))
    cx = 112
    if scenario == "traffic_light_red":
        draw.rectangle((cx - 10, 20, cx + 10, 90), fill=(30, 30, 30))
        draw.ellipse((cx - 14, 24, cx + 14, 52), fill=(220, 30, 30))
    elif scenario == "speed_zone_city":
        draw.rectangle((cx - 10, 20, cx + 10, 90), fill=(30, 30, 30))
        draw.ellipse((cx - 14, 54, cx + 14, 82), fill=(30, 180, 50))
    elif scenario == "pedestrian_jaywalking":
        draw.rectangle((cx - 8, 130, cx + 8, 130 + scale), fill=(20, 20, 20))
        draw.ellipse((cx - 10, 118, cx + 10, 138), fill=(40, 30, 25))
    elif scenario in ("cut_in_vehicle", "roadside_parked_hazard", "emergency_vehicle", "ambiguous_priority"):
        w = scale
        draw.rectangle((cx - w, 150, cx + w, 150 + int(scale * 0.8)), fill=(180, 40, 40) if scenario == "emergency_vehicle" else (90, 90, 95))
    elif scenario == "construction_detour":
        for x in (70, 100, 130):
            draw.polygon([(x, 200), (x + 16, 140), (x + 32, 200)], fill=(230, 120, 20))
    return img


def vision_from_scenario(scenario: str) -> Dict[str, Any]:
    """Map a closed-loop scenario name to synthetic visual evidence."""
    table: Dict[str, Dict[str, float]] = {
        "traffic_light_red": {"red": 0.82, "green": 0.04},
        "speed_zone_city": {"green": 0.4},
        "pedestrian_jaywalking": {"pedestrian": 0.88},
        "roadside_parked_hazard": {"vehicle": 0.7},
        "cut_in_vehicle": {"vehicle": 0.8},
        "construction_detour": {"construction": 0.85},
        "emergency_vehicle": {"vehicle": 0.55},
        "ambiguous_priority": {"vehicle": 0.45},
        "sharp_curve": {},
        "sensor_anomaly": {},
    }
    return synthetic_vision(**table.get(scenario, {}))


def decode_image_bytes(image_b64: str) -> Any:
    raw = image_b64.split(",", 1)[-1]
    blob = base64.b64decode(raw)
    from PIL import Image

    return Image.open(io.BytesIO(blob)).convert("RGB")


def prefix_count() -> int:
    raw = os.environ.get("SEMIF_VISION_PATCHES", "32")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 32
    return max(32, min(64, n))


class VisionEncoder:
    def __init__(self, model_id: Optional[str] = None, device: str = "cpu"):
        self.model_id = model_id or os.environ.get(
            "SEMIF_VISION_MODEL",
            "google/siglip-base-patch16-224",
        )
        self.device = device
        self.backend = "stub"
        self._model = None
        self._processor = None
        self._tokenizer = None
        self._image_proc = None
        self.last_patches = None
        self.last_scores = None
        self.last_blobs = None
        self._null_patches = None
        self._scoring_failed = False
        self.scoring_error: Optional[str] = None
        self._load()

    def _load(self) -> None:
        try:
            import torch

            self._torch = torch
            if "clip-vit" in self.model_id and "siglip" not in self.model_id.lower():
                self._load_clip()
            else:
                try:
                    self._load_auto()
                except Exception:
                    if "siglip" in self.model_id.lower():
                        raise
                    self._load_clip()
            logger.info("vision: %s on %s", self.model_id, self.device)
        except Exception:
            logger.warning("vision: %s did not load on %s; scores are synthetic", self.model_id, self.device, exc_info=True)
            self.backend = "stub"
            self._model = None
            self._processor = None
            self._tokenizer = None
            self._image_proc = None
            self.last_patches = None

    def _load_auto(self) -> None:
        from transformers import AutoModel, SiglipImageProcessor

        # AutoProcessor needs SentencePiece; AutoImageProcessor needs torchvision.
        # Image processor + AutoModel is enough for patch tokens (#48).
        self._image_proc = SiglipImageProcessor.from_pretrained(self.model_id)
        self._processor = None
        try:
            from transformers import AutoProcessor

            self._processor = AutoProcessor.from_pretrained(self.model_id)
        except Exception as exc:
            self._processor = None
            # The patches still work, but no text prompt can be scored (#70).
            self.scoring_error = f"SigLIP text side did not load ({type(exc).__name__}); install sentencepiece"
            logger.error("vision: %s; signal and hazard scores are unavailable", self.scoring_error, exc_info=True)
        self._model = AutoModel.from_pretrained(self.model_id)
        self._model.to(self.device)
        self._model.eval()
        self.backend = self.model_id

    def _load_clip(self) -> None:
        from tokenizers import processors as tok_processors
        from transformers.models.clip import tokenization_clip as clip_tok

        orig = tok_processors.RobertaProcessing

        def _roberta(sep, cls=None, cls_token=None, trim_offsets=True, add_prefix_space=True, **_kw):
            token = cls_token if cls_token is not None else cls
            return orig(sep, token, trim_offsets=trim_offsets, add_prefix_space=add_prefix_space)

        tok_processors.RobertaProcessing = _roberta
        clip_tok.processors.RobertaProcessing = _roberta

        from transformers import CLIPImageProcessor, CLIPModel, CLIPTokenizer

        self._tokenizer = CLIPTokenizer.from_pretrained(self.model_id)
        self._image_proc = CLIPImageProcessor.from_pretrained(self.model_id)
        self._model = CLIPModel.from_pretrained(self.model_id)
        self._model.to(self.device)
        self._model.eval()
        self.backend = self.model_id

    def encode_patches(self, image: Any):
        """Return [prefix_count, dim] patch tokens. None if the encoder is a stub."""
        if self._model is None:
            return None
        from jevpilot_vision.visual_prefix import pool_patches

        torch = self._torch
        pixel = self._pixel_values(image)
        vision = getattr(self._model, "vision_model", None)
        if vision is None:
            return None
        with torch.no_grad():
            out = vision(pixel_values=pixel)
        hidden = getattr(out, "last_hidden_state", None)
        if hidden is None:
            hidden = out[0]
        if hidden.shape[1] > 1:
            # Drop class token when the sequence is patches+1.
            maybe_cls = hidden[:, 1:, :]
            if maybe_cls.shape[1] in {49, 196, 256, 729} or maybe_cls.shape[1] % 7 == 0:
                hidden = maybe_cls
        pooled = pool_patches(hidden, prefix_count())
        return pooled[0].detach()

    def _pixel_values(self, image: Any):
        torch = self._torch
        if self._processor is not None:
            packed = self._processor(images=image, return_tensors="pt")
            pixel = packed["pixel_values"]
        else:
            packed = self._image_proc(images=image, return_tensors="pt")
            pixel = packed["pixel_values"]
        return pixel.to(self.device)

    def null_patches(self):
        if self._null_patches is not None:
            return self._null_patches
        from PIL import Image

        blank = Image.new("RGB", (224, 224), (127, 127, 127))
        self._null_patches = self.encode_patches(blank)
        return self._null_patches

    def _score_batch(self, images: list) -> list:
        """One SigLIP forward over every image. One prompt-score dict per image."""
        torch = self._torch
        texts = [text for _key, text in _PROMPTS]
        try:
            if self._processor is not None:
                inputs = self._processor(text=texts, images=images, padding=True, return_tensors="pt")
            else:
                text_inputs = self._tokenizer(texts, padding=True, return_tensors="pt")
                image_inputs = self._image_proc(images=images, return_tensors="pt")
                inputs = {**text_inputs, **image_inputs}
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with torch.no_grad():
                out = self._model(**inputs)
                rows = out.logits_per_image.softmax(dim=-1).tolist()
            return [{key: float(prob) for (key, _prompt), prob in zip(_PROMPTS, row)} for row in rows]
        except Exception as exc:
            log = logger.debug if getattr(self, "_scoring_failed", False) else logger.error
            log("SigLIP scoring failed for %d image(s); scores are unavailable", len(images), exc_info=True)
            self._scoring_failed = True
            if not getattr(self, "scoring_error", None):
                self.scoring_error = f"SigLIP scoring failed ({type(exc).__name__})"
            # All zeros, not "clear": a failed classifier has seen nothing either way (#70).
            return [{key: 0.0 for key, _prompt in _PROMPTS} for _image in images]

    def _pack(self, scores: Dict[str, float], image: Any, n_prefix: int) -> Dict[str, Any]:
        signal = "unknown"
        if scores["red"] >= 0.28 and scores["red"] >= scores["green"]:
            signal = "red"
        elif scores["green"] >= 0.28:
            signal = "green"
        packed = {
            "backend": self.backend,
            "signal": signal,
            "red": round(scores["red"], 3),
            "green": round(scores["green"], 3),
            "pedestrian": round(scores["pedestrian"], 3),
            "vehicle": round(scores["vehicle"], 3),
            "construction": round(scores["construction"], 3),
            "prefix_tokens": n_prefix,
        }
        blobs = blobs_from_frame(image)
        motion = frame_motion(self.last_blobs, blobs)
        scoring_error = getattr(self, "scoring_error", None)
        if scoring_error:
            packed["scoring_error"] = scoring_error
        if motion:
            packed["event"] = event_from_motion(motion, packed["signal"])
        elif scoring_error:
            packed["event"] = CLASSIFIER_DOWN_EVENT
        else:
            packed["event"] = camera_event(packed, self.last_scores)
        self.last_blobs = blobs
        self.last_scores = {
            "signal": packed["signal"],
            "red": packed["red"],
            "green": packed["green"],
            "pedestrian": packed["pedestrian"],
            "vehicle": packed["vehicle"],
            "construction": packed["construction"],
        }
        return packed

    def infer_pil(self, image: Any) -> Dict[str, Any]:
        patches = self.encode_patches(image)
        self.last_patches = patches
        n_prefix = int(patches.shape[0]) if patches is not None else 0
        if self._model is None:
            ev = synthetic_vision()
            ev["prefix_tokens"] = 0
            return ev
        return self._pack(self._score_batch([image])[0], image, n_prefix)

    def infer_surround(self, frames: Dict[str, Any]) -> Dict[str, Any]:
        """Four camera frames in one batch. Signal and event follow the front camera;
        hazard scores take the highest camera. ``cameras`` keeps each camera's scores."""
        names = [name for name in SURROUND_ORDER if name in frames]
        if "front" not in names:
            raise ValueError("surround frames need a front camera")
        front = frames["front"]
        patches = self.encode_patches(front)
        self.last_patches = patches
        n_prefix = int(patches.shape[0]) if patches is not None else 0
        if self._model is None:
            ev = synthetic_vision()
            ev["prefix_tokens"] = 0
            ev["cameras"] = {name: {key: 0.0 for key in ("red", "green") + HAZARD_FIELDS} for name in names}
            return ev
        rows = self._score_batch([frames[name] for name in names])
        per_camera = {
            name: {key: round(row[key], 3) for key in ("red", "green") + HAZARD_FIELDS}
            for name, row in zip(names, rows)
        }
        # Event text says "ahead", so it is built from the front camera alone.
        packed = self._pack(rows[names.index("front")], front, n_prefix)
        for key in HAZARD_FIELDS:
            packed[key] = round(max(row[key] for row in rows), 3)
        packed["cameras"] = per_camera
        return packed

    def infer_b64(self, image_b64: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        image = decode_image_bytes(image_b64)
        evidence = self.infer_pil(image)
        evidence["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return evidence

    def infer_surround_b64(self, frames_b64: Dict[str, str]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        frames = {name: decode_image_bytes(image) for name, image in frames_b64.items()}
        evidence = self.infer_surround(frames)
        evidence["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return evidence


_encoder: Optional[VisionEncoder] = None


def vision_device(cuda: Optional[bool] = None) -> str:
    """Where SigLIP runs (#57): SEMIF_VISION_DEVICE when set, else CUDA when there is one, as the
    detector does (perception.pick_device); without CUDA it still runs, on the CPU."""
    asked = os.environ.get("SEMIF_VISION_DEVICE")
    if asked:
        return asked
    if cuda is None:
        try:
            import torch

            cuda = bool(torch.cuda.is_available())
        except Exception:
            cuda = False
    return "cuda" if cuda else "cpu"


def get_vision_encoder() -> VisionEncoder:
    global _encoder
    if _encoder is None:
        device = vision_device()
        _encoder = VisionEncoder(device=device)
        if getattr(_encoder, "_model", None) is None and device != "cpu" and not os.environ.get("SEMIF_VISION_DEVICE"):
            # A CUDA we picked ourselves failed (VRAM taken by the detector, a driver): the CPU still runs it.
            _encoder = VisionEncoder(device="cpu")
    return _encoder
