"""Four onboard cameras, one ego-relative list. No world (x, z), no top-down camera."""

import pytest

from jevpilot_vision.ipm import CAMERAS, ground_uv_to_ego
from jevpilot_vision.surround import (
    emergency_from_surround,
    surround_blobs,
    surround_obstacles,
)

pytest.importorskip("PIL")


def _env(**attrs):
    env = type("Env", (), {})()
    env.x = 0.0
    env.z = 0.0
    for key, value in attrs.items():
        setattr(env, key, value)
    return env


def _frames(scenario, env):
    from jevpilot_vision.pinhole_frame import render_surround_frames

    return render_surround_frames(scenario, env)


def test_rig_is_four_cameras_about_100_degrees():
    assert [cam.name for cam in CAMERAS] == ["front", "right", "rear", "left"]
    assert [cam.yaw_deg for cam in CAMERAS] == [0.0, 90.0, 180.0, 270.0]
    assert all(95.0 <= cam.hfov_deg <= 105.0 for cam in CAMERAS)


@pytest.mark.parametrize(
    ("camera", "sign_x", "sign_z"),
    [("front", 0, 1), ("right", 1, 0), ("rear", 0, -1), ("left", -1, 0)],
)
def test_center_ground_pixel_lands_in_that_camera_direction(camera, sign_x, sign_z):
    cam = next(c for c in CAMERAS if c.name == camera)
    ego = ground_uv_to_ego(112, 170, camera=cam)
    assert ego is not None
    assert set(ego) == {"rel_x", "rel_z"}
    for key, sign in (("rel_x", sign_x), ("rel_z", sign_z)):
        if sign == 0:
            assert abs(ego[key]) < 0.05
        else:
            assert ego[key] * sign > 1.0


@pytest.mark.parametrize(
    ("where", "sign_x", "sign_z"),
    [((0.0, 12.0), 0, 1), ((6.0, 0.0), 1, 0), ((0.0, -12.0), 0, -1), ((-6.0, 0.0), -1, 0)],
)
def test_vehicle_on_each_side_comes_back_in_that_quadrant(where, sign_x, sign_z):
    rel_x, rel_z = where
    env = _env(cut_in_vehicle={"x": rel_x, "z": rel_z})
    obstacles = surround_obstacles(surround_blobs(_frames("cut_in_vehicle", env)))
    vehicles = [o for o in obstacles if o["kind"] == "vehicle"]
    assert len(vehicles) == 1
    got = vehicles[0]
    assert all("x" not in o and "z" not in o for o in obstacles)
    assert got["rel_x"] == pytest.approx(rel_x, abs=1.5)
    assert got["rel_z"] == pytest.approx(rel_z, abs=1.5)
    if sign_z:
        assert got["rel_z"] * sign_z > 0
    if sign_x:
        assert got["rel_x"] * sign_x > 0


def test_overlap_between_adjacent_cameras_reports_one_object():
    env = _env(cut_in_vehicle={"x": 7.0, "z": 7.0})
    blobs = surround_blobs(_frames("cut_in_vehicle", env))
    assert "vehicle" in blobs["front"] and "vehicle" in blobs["right"]
    vehicles = [o for o in surround_obstacles(blobs) if o["kind"] == "vehicle"]
    assert len(vehicles) == 1


def test_rear_emergency_vehicle_is_seen_behind():
    env = _env(emergency_vehicle={"x": 0.0, "z": -8.0, "siren": True})
    seen = emergency_from_surround(surround_blobs(_frames("emergency_vehicle", env)))
    assert seen is not None
    assert seen["behind"] is True
    assert seen["distance_m"] == pytest.approx(8.0, abs=1.0)
    assert "x" not in seen and "z" not in seen


def test_rear_plain_car_is_not_an_emergency_vehicle():
    env = _env(cut_in_vehicle={"x": 0.0, "z": -8.0})
    blobs = surround_blobs(_frames("cut_in_vehicle", env))
    assert "vehicle" in blobs["rear"]
    assert emergency_from_surround(blobs) is None


def test_simulator_emergency_position_comes_from_the_rear_camera():
    from benchmarks.benchmark_jevpilot_hierarchical import JevPilot2Simulator

    env = JevPilot2Simulator("emergency_vehicle", seed=42)
    env.use_camera_obstacles = True
    obs = env.get_observation()
    assert set(env.last_frames) == {"front", "right", "rear", "left"}
    emergency = obs["emergency_vehicle"]
    assert emergency["siren"] is True
    assert emergency["behind"] is True
    assert emergency["distance_m"] == pytest.approx(8.0, abs=1.0)

    env.emergency_vehicle["z"] = -200.0
    unseen = env.get_observation()["emergency_vehicle"]
    assert unseen["siren"] is True
    assert unseen["behind"] is False
    assert unseen["distance_m"] is None


def test_rear_camera_evidence_drives_the_give_way_intent():
    """Evidence layer only. Pulling over is the planner's job (follow-up issue)."""
    from benchmarks.benchmark_jevpilot_hierarchical import JevPilot2Simulator
    from demo.server import DecisionEngine

    engine = DecisionEngine(use_mock=True)
    env = JevPilot2Simulator("emergency_vehicle", seed=42)
    env.use_camera_obstacles = True
    assert engine._determine_tier1_maneuver(env.get_observation())["intent"] == "GIVE_WAY_EMERGENCY"
    env.emergency_vehicle["z"] = -200.0
    assert engine._determine_tier1_maneuver(env.get_observation())["intent"] != "GIVE_WAY_EMERGENCY"


def test_warning_light_blob_stays_out_of_the_event_text():
    from jevpilot_vision.vision import blobs_from_frame, event_from_motion, frame_motion

    env = _env(emergency_vehicle={"x": 0.0, "z": 8.0})
    front = _frames("emergency_vehicle", env)["front"]
    blobs = blobs_from_frame(front)
    assert "emergency" in blobs
    motion = frame_motion(None, blobs)
    assert all(m["kind"] != "emergency" for m in motion)
    assert "emergency" not in event_from_motion(motion)


@pytest.mark.parametrize("lateral_m", [-1.8, 0.0, 1.8, 2.7])
@pytest.mark.parametrize("behind_m", [20.0, 30.0, 40.0])
def test_rear_emergency_is_seen_past_the_give_way_range(behind_m, lateral_m):
    """Give-way acts at 40 m, so the rear camera has to see that far, in and beside the lane."""
    env = _env(emergency_vehicle={"x": lateral_m, "z": -behind_m})
    seen = emergency_from_surround(surround_blobs(_frames("emergency_vehicle", env)))
    assert seen is not None
    assert seen["behind"] is True
    assert seen["distance_m"] == pytest.approx(behind_m, rel=0.35)
