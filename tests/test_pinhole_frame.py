"""Pinhole frames replace schematic color blocks in the offline loop."""

import pytest

from benchmarks.benchmark_jevpilot_hierarchical import JevPilot2Simulator, run_jevpilot2_episode
from benchmarks.sdi import scenario_seed
from demo.server import DecisionEngine
from jevpilot_vision.ipm import camera_obstacles_from_blobs
from jevpilot_vision.vision import blobs_from_frame, render_scenario_frame


def _env(**attrs):
    env = type("Env", (), {})()
    env.x = 0.0
    env.z = 0.0
    for key, value in attrs.items():
        setattr(env, key, value)
    return env


def _pedestrian_pixels(image) -> float:
    blob = blobs_from_frame(image).get("pedestrian")
    assert blob is not None
    width, height = image.size
    return float(blob["area"]) * width * height


def test_near_pedestrian_has_more_mask_pixels():
    from jevpilot_vision.pinhole_frame import render_pinhole_frame

    near = render_pinhole_frame(
        "pedestrian_jaywalking",
        _env(pedestrian={"z": 8.0, "x": 0.0}),
    )
    far = render_pinhole_frame(
        "pedestrian_jaywalking",
        _env(pedestrian={"z": 30.0, "x": 0.0}),
    )
    assert _pedestrian_pixels(near) > _pedestrian_pixels(far)


def test_red_light_pixels_differ_from_schematic():
    pytest.importorskip("PIL")
    from jevpilot_vision.pinhole_frame import render_pinhole_frame

    env = _env(
        intersection={
            "stop_line_ahead_m": 55.0,
            "signal": "red",
        }
    )
    pinhole = render_pinhole_frame("traffic_light_red", env)
    schematic = render_scenario_frame("traffic_light_red", env)
    assert list(pinhole.getdata()) != list(schematic.getdata())
    assert any(r > 180 and g < 90 and b < 90 for r, g, b in pinhole.getdata())
    assert camera_obstacles_from_blobs(blobs_from_frame(pinhole)) == []


def test_observation_skips_schematic_frame(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("schematic frame")

    monkeypatch.setattr("jevpilot_vision.vision.render_scenario_frame", _boom)
    env = JevPilot2Simulator("traffic_light_red", seed=42)
    env.use_camera_obstacles = True
    obs = env.get_observation()
    assert env.last_frame is not None
    assert "candidates" in obs
    obstacles = camera_obstacles_from_blobs(blobs_from_frame(env.last_frame))
    assert all("x" not in item and "z" not in item for item in obstacles)


def test_siglip_sets_vision_and_keeps_candidate_keys(monkeypatch):
    calls = []

    def _boom(*_args, **_kwargs):
        calls.append("render")
        raise AssertionError("schematic frame")

    class _Encoder:
        def infer_pil(self, _image):
            return {
                "backend": "siglip",
                "signal": "red",
                "red": 0.9,
                "green": 0.0,
                "pedestrian": 0.0,
                "vehicle": 0.0,
                "construction": 0.0,
                "prefix_tokens": 0,
            }

    monkeypatch.setattr("jevpilot_vision.vision.render_scenario_frame", _boom)
    monkeypatch.setattr("jevpilot_vision.vision.get_vision_encoder", lambda: _Encoder())
    seed = scenario_seed(42, "traffic_light_red", 0)

    def _capture(bucket):
        def _on_step(_env, _chosen_id, _chosen_vec, last_obs):
            if "obs" not in bucket and isinstance(last_obs, dict):
                bucket["obs"] = last_obs
        return _on_step

    siglip_bucket = {}
    off_bucket = {}
    engine = DecisionEngine(use_mock=True)
    run_jevpilot2_episode(
        engine,
        "flat",
        "traffic_light_red",
        seed,
        raw_mode=False,
        vision_mode="siglip",
        on_step=_capture(siglip_bucket),
    )
    run_jevpilot2_episode(
        engine,
        "flat",
        "traffic_light_red",
        seed,
        raw_mode=False,
        vision_mode="off",
        on_step=_capture(off_bucket),
    )
    sig = siglip_bucket["obs"]
    off = off_bucket["obs"]
    assert sig["vision"]["backend"] == "siglip"
    assert sig["vision"]["signal"] == "red"
    assert "vision" not in off
    assert set(sig["candidates"]) == set(off["candidates"])
    assert calls == []
