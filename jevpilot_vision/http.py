"""JevPilot-Vision HTTP: latest-frame JPEG slot, /v1/vision, /v1/fleet, and the static driving page.

A slot item is one JPEG or one set of surround frames {front, right, rear, left}.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
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
    from jevpilot_vision import perception, vision

    narrow = None
    captured = None
    if isinstance(image, dict):
        narrow = image.get("narrow")
        captured = image.get("_captured_ms")
        cameras = {name: frame for name, frame in image.items() if name not in ("narrow", "_captured_ms")}
        evidence = vision.get_vision_encoder().infer_surround_b64(cameras)
        front = image["front"]
    else:
        evidence = vision.get_vision_encoder().infer_b64(image)
        front = image
    evidence["perception"] = _perceive_front(perception, vision.decode_image_bytes, front, narrow)
    if captured is not None:
        # The page's clock when these frames were grabbed: how old the evidence really is (#18).
        evidence["captured_ms"] = captured
    return evidence


def _perceive_front(perception: Any, decode: Any, front: str, narrow: Optional[str] = None) -> Dict[str, Any]:
    """Objects with range and the light ahead, from the front camera and, in Vision mode, the
    narrow camera (#18). A detector that fails says so (backend "none"): Vision mode must slow
    down, not read it as an empty road."""
    try:
        return perception.get_perception().front(decode(front), narrow=decode(narrow) if narrow else None)
    except Exception as err:
        return {"backend": "none", "objects": [], "signal": {"state": "unknown", "conf": 0.0}, "error": str(err)[:200]}


_CAMERA_NAMES = frozenset({"front", "right", "rear", "left", "narrow"})


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
        t_ms = payload.get("t_ms")
        if isinstance(t_ms, (int, float)) and not isinstance(t_ms, bool):
            image["_captured_ms"] = float(t_ms)
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


FLEET_MAX_AGENTS = 64
_WORLD_KEYS = frozenset({"x", "z", "world_x", "world_z", "position"})


class _FleetTracks:
    """Per-car box history, so each car gets rel_vz_mps from its own frames.

    Keyed by (session, car id) and timed on the client's sim clock when it sends one;
    a clock that runs backwards (a restarted world) starts the track over.
    """

    def __init__(self, ttl_s: float = 2.0) -> None:
        self._lock = threading.Lock()
        self._ttl_s = ttl_s
        self._tracks: Dict[tuple[str, str], tuple[float, float, List[Dict[str, Any]]]] = {}

    def track(self, key: tuple[str, str], boxes: List[Dict[str, Any]], t: float) -> List[Dict[str, Any]]:
        from jevpilot_vision.surround import track_obstacles

        wall = time.monotonic()
        with self._lock:
            self._tracks = {k: v for k, v in self._tracks.items() if wall - v[0] <= self._ttl_s}
            previous = self._tracks.get(key)
        if previous is not None and t <= previous[1]:
            previous = None
        tracked = track_obstacles(previous[2] if previous else None, boxes, t - previous[1] if previous else 0.0)
        with self._lock:
            self._tracks[key] = (wall, t, tracked)
        return tracked


_fleet_tracks = _FleetTracks()


def _fleet_boxes(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="obstacles must be a list")
    boxes = []
    for item in raw:
        if not isinstance(item, dict) or _WORLD_KEYS & set(item):
            raise HTTPException(status_code=422, detail="obstacles are ego-relative rel_x/rel_z only")
        try:
            box = {"kind": str(item.get("kind") or "vehicle"), "rel_x": float(item["rel_x"]), "rel_z": float(item["rel_z"])}
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=422, detail="each obstacle needs numeric rel_x and rel_z")
        boxes.append(box)
    return boxes


def _fleet_decide(get_engine: Callable[[], Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    from jevpilot_vision.fleet import POLICIES, SENSOR_RANGE_M, agent_state, decide

    policy = payload.get("policy", "semif")
    if policy not in POLICIES:
        raise HTTPException(status_code=422, detail=f"policy must be one of {sorted(POLICIES)}")
    agents = payload.get("agents")
    if not isinstance(agents, list) or len(agents) > FLEET_MAX_AGENTS:
        raise HTTPException(status_code=422, detail=f"agents must be a list of at most {FLEET_MAX_AGENTS}")
    engine = get_engine()
    session = str(payload.get("session") or "")
    try:
        now = float(payload["t"]) if payload.get("t") is not None else time.monotonic()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="t is the sender's clock in seconds")
    started = time.perf_counter()
    decisions: Dict[str, Any] = {}
    for agent in agents:
        if not isinstance(agent, dict) or _WORLD_KEYS & set(agent):
            raise HTTPException(status_code=422, detail="an agent is described by what it senses, not where it is")
        car_id = str(agent.get("id") or "")
        if not car_id:
            raise HTTPException(status_code=422, detail="each agent needs an id")
        boxes = [
            box for box in _fleet_boxes(agent.get("obstacles", []))
            if (box["rel_x"] ** 2 + box["rel_z"] ** 2) ** 0.5 <= SENSOR_RANGE_M
        ]
        intersection = agent.get("intersection") if isinstance(agent.get("intersection"), dict) else None
        try:
            state = agent_state(
                speed_mps=float(agent.get("speed_mps", 0.0)),
                speed_ceiling_mps=float(agent.get("speed_ceiling_mps", 13.4)),
                obstacles=_fleet_tracks.track((session, car_id), boxes, now),
                intersection=intersection,
                lateral_offset_m=float(agent.get("lateral_offset_m", 0.0)),
                seed=int(agent.get("seed", 0)),
                steers=bool(agent.get("steers", True)),
            )
        except (TypeError, ValueError, KeyError):
            raise HTTPException(status_code=422, detail=f"agent {car_id} has a bad speed, offset, seed or stop line")
        decisions[car_id] = decide(engine, policy, state)
    return {
        "policy": policy,
        "decisions": decisions,
        "fleet_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }


def mount(app: FastAPI, get_engine: Optional[Callable[[], Any]] = None) -> None:
    app.add_api_route("/v1/vision", vision_endpoint, methods=["POST"])
    if get_engine is not None:

        async def fleet_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
            return await asyncio.to_thread(_fleet_decide, get_engine, payload)

        app.add_api_route("/v1/fleet", fleet_endpoint, methods=["POST"])
    if _WEB_DIR.exists():
        app.mount("/jevpilot", StaticFiles(directory=str(_WEB_DIR), html=True), name="jevpilot")
