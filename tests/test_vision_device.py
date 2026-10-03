"""SigLIP runs where RT-DETR runs (#57): CUDA when there is one, unless SEMIF_VISION_DEVICE says otherwise."""

from __future__ import annotations

import importlib


def _mod(name):
    """The module as code imports it now: tests/test_server.py drops jevpilot_vision from sys.modules
    and re-imports it, so a module object taken at collection time may be stale (#86)."""
    return importlib.import_module(name)


def test_cuda_when_there_is_one_and_the_environment_wins(monkeypatch):
    vision = _mod("jevpilot_vision.vision")
    monkeypatch.delenv("SEMIF_VISION_DEVICE", raising=False)
    assert vision.vision_device(cuda=True) == "cuda"
    assert vision.vision_device(cuda=False) == "cpu", "no CUDA: SigLIP still runs, on the CPU"
    monkeypatch.setenv("SEMIF_VISION_DEVICE", "cpu")
    assert vision.vision_device(cuda=True) == "cpu"


def test_the_shared_encoder_is_built_on_the_picked_device(monkeypatch):
    vision = _mod("jevpilot_vision.vision")
    built = []

    class Encoder:
        def __init__(self, device="cpu"):
            built.append(device)
            self._model = object()

    monkeypatch.delenv("SEMIF_VISION_DEVICE", raising=False)
    monkeypatch.setattr(vision, "VisionEncoder", Encoder)
    monkeypatch.setattr(vision, "_encoder", None)
    monkeypatch.setattr(vision, "vision_device", lambda cuda=None: "cuda")
    vision.get_vision_encoder()
    assert built == ["cuda"]


def test_the_vision_reply_says_where_each_model_ran(monkeypatch):
    vision = _mod("jevpilot_vision.vision")
    http = _mod("jevpilot_vision.http")
    perception = _mod("jevpilot_vision.perception")
    from tests.test_perception import _jpeg

    class Encoder:
        device = "cuda"
        _model = object()

        def infer_surround_b64(self, frames):
            return {"backend": "stub", "signal": "unknown", "event": ""}

    class Detector:
        device = "cuda"
        _model = object()

    class Fake:
        detector = Detector()

        def front(self, image, t=None, narrow=None):
            return {"backend": "fake", "objects": [], "signal": {"state": "unknown", "conf": 0.0}}

    monkeypatch.setattr(vision, "get_vision_encoder", lambda: Encoder())
    monkeypatch.setattr(perception, "get_perception", lambda: Fake())
    frames = {"front": _jpeg(640, 360), "right": _jpeg(320, 180), "rear": _jpeg(320, 180), "left": _jpeg(320, 180)}
    assert http._infer_latest_jpeg(frames)["device"] == {"siglip": "cuda", "detector": "cuda"}
    Encoder._model = None  # SigLIP fell back to the stub
    assert http._infer_latest_jpeg(frames)["device"]["siglip"] is None, "the stub runs nowhere"


def test_review_a_cuda_we_picked_that_fails_falls_back_to_the_cpu(monkeypatch):
    vision = _mod("jevpilot_vision.vision")
    built = []

    class Encoder:
        def __init__(self, device="cpu"):
            built.append(device)
            self.device = device
            self._model = object() if device == "cpu" else None

    monkeypatch.delenv("SEMIF_VISION_DEVICE", raising=False)
    monkeypatch.setattr(vision, "VisionEncoder", Encoder)
    monkeypatch.setattr(vision, "_encoder", None)
    monkeypatch.setattr(vision, "vision_device", lambda cuda=None: "cuda")
    assert vision.get_vision_encoder().device == "cpu" and built == ["cuda", "cpu"]
    monkeypatch.setattr(vision, "_encoder", None)
    monkeypatch.setenv("SEMIF_VISION_DEVICE", "cuda")
    built.clear()
    assert vision.get_vision_encoder().device == "cuda" and built == ["cuda"], "an asked-for device is kept"
