"""#7: the rear camera sees the emergency vehicle; the planner now pulls right and holds."""

import pytest

from jevpilot_vision.surround import COAST_S, track_obstacles
from jevpilot_vision.trajectory_sampler import (
    MAX_SAMPLES,
    PULL_OVER_OFFSET_M,
    rollout,
    sample_trajectories,
)

pytest.importorskip("PIL")


def _car(rel_x, rel_z, **extra):
    return {"kind": "vehicle", "rel_x": rel_x, "rel_z": rel_z, **extra}


def test_tracker_reads_a_car_catching_up_from_behind():
    tracked = track_obstacles([_car(0.0, -8.0)], [_car(0.0, -7.2)], 0.1)
    assert tracked[0]["rel_vz_mps"] == pytest.approx(8.0)
    parked = track_obstacles([_car(1.2, 30.0)], [_car(1.2, 28.4)], 0.1)
    assert parked[0]["rel_vz_mps"] == pytest.approx(-16.0)


def test_tracker_coasts_an_overtaking_car_through_the_blind_spot():
    frames = [_car(-1.4, -2.0, rel_vz_mps=6.0)]
    for _ in range(4):
        frames = track_obstacles(frames, [], 0.1)
    assert len(frames) == 1
    assert frames[0]["rel_z"] == pytest.approx(0.4, abs=0.01)
    assert frames[0]["coasted_s"] == pytest.approx(0.4)
    for _ in range(int(COAST_S / 0.1) + 1):
        frames = track_obstacles(frames, [], 0.1)
    assert frames == []


def test_tracker_does_not_coast_a_car_falling_behind():
    assert track_obstacles([_car(0.0, -8.0, rel_vz_mps=-3.0)], [], 0.1) == []


def test_rollout_brings_a_small_steer_back_to_center_like_the_plant():
    """The plant replaces |steer| <= 0.28 with a lane-keep PD. The rollout must predict that."""
    from benchmarks.benchmark_jevpilot_hierarchical import JevPilot2Simulator

    env = JevPilot2Simulator("speed_zone_city", seed=1)
    env.use_camera_obstacles = False
    env.x = 1.0
    predicted = rollout(env.x, env.z, env.speed_mps, env.speed_mps, 0.1, env.track_curvature, None, [])
    for _ in range(31):
        env.step([env.speed_mps, 0.1], False)
    assert abs(predicted["end_x"]) < 0.3
    assert predicted["end_x"] == pytest.approx(env.x, abs=0.05)


def test_pull_over_is_sampled_every_frame_and_the_plant_holds_it():
    from benchmarks.benchmark_jevpilot_hierarchical import JevPilot2Simulator

    plain = sample_trajectories(ego_x=0.0, ego_z=0.0, speed=16.0, seed=5)
    assert len(plain) <= MAX_SAMPLES
    pull = [s for s in plain.values() if s.hold_offset_m == PULL_OVER_OFFSET_M]
    assert pull, "pull-over is geometry; it does not wait for a label"
    assert all(s.end_x == pytest.approx(PULL_OVER_OFFSET_M, abs=0.3) for s in pull)
    assert all(s.meta()["hold_offset_m"] == PULL_OVER_OFFSET_M for s in pull)
    assert all("hold_offset_m" not in s.meta() for s in plain.values() if s.hold_offset_m is None)

    env = JevPilot2Simulator("speed_zone_city", seed=1)
    env.use_camera_obstacles = False
    for _ in range(40):
        env.step([env.speed_mps, pull[0].steer], False, hold_offset_m=PULL_OVER_OFFSET_M)
    assert env.x == pytest.approx(PULL_OVER_OFFSET_M, abs=0.25)


def test_car_closing_from_behind_blocks_the_lane_but_not_the_pull_over():
    rear = [_car(0.0, -8.0, rel_vz_mps=8.0)]
    samples = sample_trajectories(ego_x=0.0, ego_z=0.0, speed=16.0, obstacles=rear, seed=5)
    lane = [s for s in samples.values() if s.hold_offset_m is None and abs(s.end_x) < 0.3]
    pull = [s for s in samples.values() if s.hold_offset_m is not None]
    assert lane and all(s.collision for s in lane)
    assert pull and not any(s.collision for s in pull)

    static = sample_trajectories(ego_x=0.0, ego_z=0.0, speed=16.0, obstacles=[_car(0.0, -8.0)], seed=5)
    assert not any(s.collision for s in static.values()), "a parked car behind is never hit going forward"


def _drive(scenario, seconds, mode="heuristic", setup=None):
    from benchmarks.benchmark_jevpilot_hierarchical import run_jevpilot2_episode
    from benchmarks.sdi import scenario_seed
    from demo.server import DecisionEngine

    import benchmarks.benchmark_jevpilot_hierarchical as bench

    xs = []

    class _Capped(bench.JevPilot2Simulator):
        def reset(self):
            super().reset()
            if setup:
                setup(self)

        def step(self, *args, **kwargs):
            done, obs = super().step(*args, **kwargs)
            xs.append(self.x)
            return done or self.t >= seconds, obs

    original = bench.JevPilot2Simulator
    bench.JevPilot2Simulator = _Capped
    try:
        result = run_jevpilot2_episode(
            DecisionEngine(use_mock=True), mode, scenario, scenario_seed(42, scenario, 0)
        )
    finally:
        bench.JevPilot2Simulator = original
    return result, xs


@pytest.mark.parametrize("mode", ["heuristic", "flat"])
def test_rear_emergency_vehicle_gets_a_pull_over_right(mode):
    result, xs = _drive("emergency_vehicle", 2.5, mode=mode)
    assert result["completed"] is True
    assert result["emergency_violation"] is False
    assert max(xs) >= 0.7
    assert min(xs) > -0.2, "give way to the right"


def test_no_emergency_vehicle_no_pull_over():
    def far_away(env):
        env.emergency_vehicle["z"] = -500.0
        env.emergency_vehicle["speed_mps"] = 0.0

    _result, xs = _drive("emergency_vehicle", 2.5, setup=far_away)
    assert max(abs(x) for x in xs) < 0.3


def test_a_parked_car_beside_the_ego_is_still_a_box():
    """Passing a parked car: returning to center while alongside must read as contact."""
    parked = [_car(2.69, 2.08, rel_vz_mps=-3.6)]
    back = rollout(-1.47, 0.0, 3.6, 5.8, 0.06, 0.0, None, parked, current_steer=-0.1)
    assert back["collision"] is True
    ahead_only = rollout(-1.47, 0.0, 3.6, 5.8, 0.06, 0.0, None, [_car(2.69, 2.08)], current_steer=-0.1)
    assert ahead_only["collision"] is False, "untracked boxes keep the old ahead-only rule"


def test_emergency_stop_brakes_straight():
    from jevpilot_vision.directive import fail_safe_choice

    samples = sample_trajectories(ego_x=0.0, ego_z=0.0, speed=16.0, seed=5)
    brake = [s for s in samples.values() if s.description.startswith("brake in lane")]
    assert len(brake) == 1 and brake[0].speed == 0.0
    candidates = {
        "swerve": [0.0, -0.53, -9.0, 0.6, True, False],
        "straight": [0.0, 0.02, 0.0, 0.0, True, False],
        "fast": [18.0, 0.0, 0.0, 0.0, True, False],
    }
    assert fail_safe_choice(candidates, "fast") == "straight"
