"""#3: fleet mode. Every car can drive on the player's decision core."""

from __future__ import annotations

import pytest

from benchmarks.benchmark_fleet import (
    CYCLE_S,
    RING_M,
    FleetSimulator,
    ring_gap,
    run_fleet_episode,
    signal_color,
)
from jevpilot_vision.fleet import POLICIES, SENSOR_RANGE_M, agent_state, decide


@pytest.fixture(scope="module")
def engine():
    from demo.server import DecisionEngine

    return DecisionEngine(use_mock=True)


def test_ring_gap_wraps_both_ways():
    assert ring_gap(590.0, 10.0) == pytest.approx(20.0)
    assert ring_gap(10.0, 590.0) == pytest.approx(-20.0)
    assert abs(ring_gap(0.0, RING_M / 2.0)) == pytest.approx(RING_M / 2.0)


def test_signal_cycles_green_yellow_red():
    colors = [signal_color(t, 0.0) for t in (0.0, 10.5, 12.5, CYCLE_S + 0.1)]
    assert colors == ["green", "yellow", "red", "green"]


def test_a_car_sees_others_only_as_ego_relative_boxes_in_range():
    sim = FleetSimulator(n_traffic=14, seed=7)
    car = sim.cars[3]
    boxes = sim.boxes_seen_by(car)
    assert boxes, "neighbours on a 600 m ring with 15 cars are in camera range"
    for box in boxes:
        assert set(box) == {"kind", "rel_x", "rel_z"}
        assert (box["rel_x"] ** 2 + box["rel_z"] ** 2) ** 0.5 <= SENSOR_RANGE_M
    state = sim.observe(car, 3)
    assert "x" not in state and "z" not in state
    assert state["candidates"] and state["candidate_meta"]


def test_fleet_mode_decides_for_every_car_and_off_only_for_the_player():
    on = FleetSimulator(n_traffic=5, seed=1, fleet_mode=True)
    off = FleetSimulator(n_traffic=5, seed=1, fleet_mode=False)
    assert all(car.decides for car in on.cars)
    assert [car.decides for car in off.cars] == [True] + [False] * 5


def test_decide_returns_one_of_the_sampled_trajectories(engine):
    state = agent_state(speed_mps=10.0, speed_ceiling_mps=13.4, obstacles=[], seed=3)
    for policy in POLICIES:
        picked = decide(engine, policy, state)
        assert picked["choice"] in state["candidates"]
        assert picked["vector"] == state["candidates"][picked["choice"]]
    with pytest.raises(ValueError):
        decide(engine, "chaos", state)


def test_semif_fleet_stops_for_red_where_heuristic_fleet_runs_it(engine):
    """Same town, same seed: the signal veto is what separates the fleets."""
    runs = {
        policy: run_fleet_episode(engine, policy, n_traffic=14, seed=42, fleet_mode=True, seconds=30.0)
        for policy in ("heuristic", "semif")
    }
    assert runs["heuristic"]["deciding_cars"] == runs["heuristic"]["cars"] == 15
    assert runs["heuristic"]["red_light_violations"] >= 5
    assert runs["semif"]["red_light_violations"] < runs["heuristic"]["red_light_violations"]
    assert runs["semif"]["collisions"] == 0
    assert runs["semif"]["fail_safe_vetoes"] > 0


def test_scripted_traffic_leaves_one_deciding_car(engine):
    run = run_fleet_episode(engine, "semif", n_traffic=5, seed=42, fleet_mode=False, seconds=5.0)
    assert run["deciding_cars"] == 1
    assert run["decisions"] == 50


def test_v1_fleet_scores_each_car_from_ego_relative_boxes():
    from fastapi.testclient import TestClient
    from demo.server import app

    client = TestClient(app)
    agents = [
        {
            "id": "vehicle-0",
            "speed_mps": 10.0,
            "speed_ceiling_mps": 13.4,
            "obstacles": [{"kind": "vehicle", "rel_x": 0.0, "rel_z": 9.0}],
            "intersection": {"control": "traffic_light", "distance_to_line_m": 20.0, "signal": "red"},
        },
        {"id": "vehicle-1", "speed_mps": 8.0, "obstacles": []},
    ]
    res = client.post("/v1/fleet", json={"policy": "semif", "agents": agents})
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["decisions"]) == {"vehicle-0", "vehicle-1"}
    assert all(d["choice"].startswith("t") for d in body["decisions"].values())

    world = [{"id": "vehicle-0", "speed_mps": 5.0, "obstacles": [{"x": 3.0, "z": 40.0}]}]
    assert client.post("/v1/fleet", json={"policy": "semif", "agents": world}).status_code == 422
    placed = [{"id": "vehicle-0", "x": 3.0, "z": 40.0, "speed_mps": 5.0, "obstacles": []}]
    assert client.post("/v1/fleet", json={"policy": "semif", "agents": placed}).status_code == 422
    assert client.post("/v1/fleet", json={"policy": "chaos", "agents": []}).status_code == 422
    too_many = [{"id": f"v{i}", "obstacles": []} for i in range(65)]
    assert client.post("/v1/fleet", json={"policy": "semif", "agents": too_many}).status_code == 422
