"""JevPilot-Vision HTTP: latest-frame JPEG slot, /v1/vision, and the static driving page.

A slot item is one JPEG or one set of surround frames {front, right, rear, left}.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

_WEB_DIR = Path(__file__).resolve().parent / "web"


class _LatestVisionSlot:
    """One frame slot. A busy worker finishes, then infers whatever is newest."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._image: Any = None
        self._gen = 0
        self._running = False
        self._last: Optional[Dict[str, Any]] = None
        self._last_gen: Optional[int] = None

    def submit(self, image: Any) -> tuple[bool, Optional[Dict[str, Any]], Optional[int]]:
        with self._lock:
            self._gen += 1
            self._image = image
            last = dict(self._last) if isinstance(self._last, dict) else None
            last_gen = self._last_gen
            if self._running:
                return False, last, last_gen
            self._running = True
            return True, last, last_gen

    def run_until_idle(self, infer) -> tuple[Dict[str, Any], float, int]:
        """Infer the frame that started this cycle, then at most the newest one."""
        caught_up = False
        evidence: Dict[str, Any] = {}
        encode_ms = 0.0
        while True:
            with self._lock:
                image = self._image
                gen = self._gen
            if not image:
                with self._lock:
                    self._running = False
                raise RuntimeError("vision slot had no frame")
            t0 = time.perf_counter()
            try:
                evidence = infer(image)
            except Exception:
                with self._lock:
                    superseded = self._gen != gen
                    if (not superseded) or caught_up:
                        self._running = False
                if superseded and not caught_up:
                    caught_up = True
                    continue
                raise
            encode_ms = (time.perf_counter() - t0) * 1000.0
            with self._lock:
                if isinstance(evidence, dict):
                    self._last = evidence
                    self._last_gen = gen
                if self._gen != gen and not caught_up:
                    caught_up = True
                    continue
                self._running = False
                return evidence, encode_ms, gen


_vision_slot = _LatestVisionSlot()


def reset_vision_slot() -> None:
    global _vision_slot
    _vision_slot = _LatestVisionSlot()


def _infer_latest_jpeg(image: Any) -> Dict[str, Any]:
    from jevpilot_vision.vision import get_vision_encoder

    if isinstance(image, dict):
        return get_vision_encoder().infer_surround_b64(image)
    return get_vision_encoder().infer_b64(image)


_CAMERA_NAMES = frozenset({"front", "right", "rear", "left"})


def _surround_frames(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    frames = payload.get("frames")
    if not isinstance(frames, dict) or not isinstance(frames.get("front"), str):
        return None
    if not set(frames) <= _CAMERA_NAMES:
        return None
    if not all(isinstance(value, str) and len(value) >= 64 for value in frames.values()):
        return None
    return dict(frames)


async def vision_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "frames" in payload:
        image: Any = _surround_frames(payload)
        if image is None:
            return {"error": "frames need a front camera and a JPEG (data URL or base64) per camera"}
    else:
        image = payload.get("image") or payload.get("image_base64")
        if not isinstance(image, str) or len(image) < 64:
            return {"error": "image (data URL or base64) required"}
    start, last, last_gen = _vision_slot.submit(image)
    if not start:
        body: Dict[str, Any] = {}
        if isinstance(last, dict):
            body["vision"] = last
            if isinstance(last_gen, int):
                body["vision_gen"] = last_gen
        return body
    evidence, vision_encode_ms, vision_gen = await asyncio.to_thread(
        _vision_slot.run_until_idle, _infer_latest_jpeg
    )
    return {
        "vision": evidence,
        "vision_encode_ms": vision_encode_ms,
        "vision_gen": vision_gen,
    }


def mount(app: FastAPI) -> None:
    app.add_api_route("/v1/vision", vision_endpoint, methods=["POST"])
    if _WEB_DIR.exists():
        app.mount("/jevpilot", StaticFiles(directory=str(_WEB_DIR), html=True), name="jevpilot")
