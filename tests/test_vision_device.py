"""SigLIP runs where RT-DETR runs (#57): CUDA when there is one, unless SEMIF_VISION_DEVICE says otherwise."""

from __future__ import annotations

import jevpilot_vision.vision as vision


def test_cuda_when_there_is_one_and_the_environment_wins(monkeypatch):
    monkeypatch.delenv("SEMIF_VISION_DEVICE", raising=False)
    assert vision.vision_device(cuda=True) == "cuda"
    assert vision.vision_device(cuda=False) == "cpu", "no CUDA: SigLIP still runs, on the CPU"
    monkeypatch.setenv("SEMIF_VISION_DEVICE", "cpu")
    assert vision.vision_device(cuda=True) == "cpu"


def test_the_shared_encoder_is_built_on_the_picked_device(monkeypatch):
    built = []

    class Encoder:
        def __init__(self, device="cpu"):
            built.append(device)

    monkeypatch.delenv("SEMIF_VISION_DEVICE", raising=False)
    monkeypatch.setattr(vision, "VisionEncoder", Encoder)
    monkeypatch.setattr(vision, "_encoder", None)
    monkeypatch.setattr(vision, "vision_device", lambda cuda=None: "cuda")
    vision.get_vision_encoder()
    assert built == ["cuda"]


def test_the_vision_reply_says_where_each_model_ran(monkeypatch):
    import jevpilot_vision.http as http
    import jevpilot_vision.perception as perception
    from tests.test_perception import _jpeg

    class Encoder:
        device = "cuda"

        def infer_surround_b64(self, frames):
            return {"backend": "stub", "signal": "unknown", "event": ""}

    class Detector:
        device = "cuda"

    class Fake:
        detector = Detector()

        def front(self, image, t=None, narrow=None):
            return {"backend": "fake", "objects": [], "signal": {"state": "unknown", "conf": 0.0}}

    monkeypatch.setattr(vision, "get_vision_encoder", lambda: Encoder())
    monkeypatch.setattr(perception, "get_perception", lambda: Fake())
    frames = {"front": _jpeg(640, 360), "right": _jpeg(320, 180), "rear": _jpeg(320, 180), "left": _jpeg(320, 180)}
    assert http._infer_latest_jpeg(frames)["device"] == {"siglip": "cuda", "detector": "cuda"}
