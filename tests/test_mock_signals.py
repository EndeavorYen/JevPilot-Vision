"""The mock arbiter obeys signals and stop signs (#17).

Candidate vectors are the web client's six columns:
[speed, steer, route_error, offroad_fraction, collision, stop_at_line].
"""

from __future__ import annotations

import pytest

from demo.server import DecisionEngine


@pytest.fixture(scope="module")
def engine():
    return DecisionEngine(use_mock=True)


CANDIDATES = {
    "fast": [13.4, 0.0, 0.1, 0.0, False, False],
    "mid": [9.0, 0.0, 0.2, 0.0, False, False],
    "slow": [4.0, 0.0, 0.2, 0.0, False, False],
    "walk": [3.0, 0.0, 0.2, 0.0, False, False],
    "crawl": [1.2, 0.0, 0.3, 0.0, False, False],
    "crash": [0.5, 0.0, 0.0, 0.0, True, False],
}


def ask(engine, intersection, speed=13.4, motion=False):
    questions = {"vector": {"type": "choice", "instructions": "Choose a path.", "criteria": {k: None for k in CANDIDATES}}}
    if motion:
        questions["motion"] = {"type": "choice", "instructions": "Stop means zero target now.", "criteria": {"drive": None, "stop": None}}
    state = {"speed_mps": speed, "on_road": True, "candidates": CANDIDATES}
    if intersection is not None:
        state["intersection"] = {"control": "signal", "stop_completed": False, "already_entered": False, **intersection}
    answers = engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]
    return answers["vector"]["choice"], answers.get("motion", {}).get("choice")


def test_t1_red_far_ahead_slows_onto_the_stopping_curve(engine):
    # 45 m left at 13.4 m/s: sqrt(2 * 2.0 * (45 - 13.4 * 1.6 - 1)) = 9.5 m/s, so "mid" (9.0) is the fastest that fits.
    assert ask(engine, {"signal": "red", "distance_to_line_m": 45}) == ("mid", None)


def test_the_curve_leaves_room_for_a_dropped_decision(engine):
    """The client drops an answer when the light changes colour while it is in flight, so the
    curve allows for two decisions (1.6 s), not one: 30 m at 13.4 m/s -> 5.5 m/s, "slow" (4.0)."""
    assert ask(engine, {"signal": "red", "distance_to_line_m": 30}) == ("slow", None)


def test_t2_red_close_takes_the_slowest_safe_candidate(engine):
    # 8 m left at 9 m/s: nothing fits the curve, so the slowest candidate that does not collide.
    assert ask(engine, {"signal": "red", "distance_to_line_m": 8}, speed=9.0) == ("crawl", None)


def test_t3_motion_stops_at_the_line(engine):
    assert ask(engine, {"signal": "red", "distance_to_line_m": 1.5}, speed=1.0, motion=True)[1] == "stop"
    assert ask(engine, {"control": "stop", "signal": None, "distance_to_line_m": 2.0}, speed=0.8, motion=True)[1] == "stop"
    # Not yet: at 3 m/s it can hold its speed 1.5 s and still brake 0.5 m short of a line 10 m off
    # (6 m was too close; see the test below).
    assert ask(engine, {"signal": "red", "distance_to_line_m": 10}, speed=3.0, motion=True)[1] == "drive", "not yet at the line"


@pytest.mark.parametrize(
    "intersection, speed",
    [
        (None, 13.4),
        ({"signal": "green", "distance_to_line_m": 20}, 13.4),
        ({"signal": "red", "distance_to_line_m": 20, "already_entered": True}, 13.4),
        ({"signal": "red", "distance_to_line_m": -3, "already_entered": True}, 13.4),
        ({"signal": "amber", "distance_to_line_m": 8}, 13.4),  # 13.4^2 / 16 = 11.2 m > 8 m: past the point of stopping
        ({"control": "stop", "signal": None, "distance_to_line_m": 1.0, "stop_completed": True}, 3.0),
    ],
)
def test_t4_no_required_stop_keeps_the_fastest_path_and_drives(engine, intersection, speed):
    assert ask(engine, intersection, speed=speed, motion=True) == ("fast", "drive")


def test_amber_the_car_can_still_stop_for_is_a_stop(engine):
    """Amber lasts 2 s and the client's own stop-line speed cap slows the car through it anyway,
    so the mock stops whenever the client's hard-braking distance (v^2 / 16) still fits."""
    assert ask(engine, {"signal": "amber", "distance_to_line_m": 24.7}, speed=13.7)[0] != "fast"
    assert ask(engine, {"signal": "amber", "distance_to_line_m": 40})[0] != "fast"


def test_creeping_up_to_a_red_line_never_overruns_it_between_decisions(engine):
    """Stopped 4 m short of a red line: the next 0.8 s decision may close at most half of what is
    left past a 2 m margin ((4 - 2) / 1.6 = 1.25 m/s), so "walk" (3 m/s) would overrun and "crawl" fits."""
    assert ask(engine, {"signal": "red", "distance_to_line_m": 4}, speed=0.0) == ("crawl", None)


def test_stopping_never_picks_a_reversing_candidate(engine):
    """Reverse candidates (negative speed) are for recovery, not for stopping at a line."""
    with_reverse = {**CANDIDATES, "back": [-0.6, 0.0, 0.2, 0.0, False, False]}
    questions = {"vector": {"type": "choice", "instructions": "Choose a path.", "criteria": {k: None for k in with_reverse}}}
    state = {"speed_mps": 9.0, "on_road": True, "candidates": with_reverse,
             "intersection": {"control": "stop", "signal": None, "distance_to_line_m": 8, "stop_completed": False, "already_entered": False}}
    choice = engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]["vector"]["choice"]
    assert choice == "crawl"


def _choose(engine, cands, intersection, speed):
    questions = {"vector": {"type": "choice", "instructions": "Choose a path.", "criteria": {k: None for k in cands}}}
    state = {"speed_mps": speed, "on_road": True, "candidates": cands,
             "intersection": {"control": "signal", "stop_completed": False, "already_entered": False, **intersection}}
    return engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]["vector"]["choice"]


def test_a_stop_at_line_candidate_is_preferred_when_one_is_offered(engine):
    """Review: such a trajectory brakes to the line on its own, a backup if an answer is dropped."""
    cands = {**CANDIDATES, "halt": [8.0, 0.0, 0.2, 0.0, False, True]}
    assert _choose(engine, cands, {"signal": "red", "distance_to_line_m": 30}, 13.4) == "halt"


def test_route_error_breaks_ties_and_nan_candidates_are_skipped(engine):
    cands = {
        "off": [4.05, 0.3, 3.0, 0.0, False, False],
        "on": [4.0, 0.0, 0.2, 0.0, False, False],
        "nan": [float("nan"), 0.0, 0.0, 0.0, False, False],
    }
    assert _choose(engine, cands, {"signal": "red", "distance_to_line_m": 30}, 13.4) == "on"


def test_a_nose_over_the_line_on_red_holds_until_the_car_has_entered(engine):
    """#18: distance_to_line_m is measured from the nose, entry from the centre. A car that stopped
    with its nose 1.7 m over the line has not entered the junction and must hold, not creep on."""
    vector, motion = ask(engine, {"signal": "red", "distance_to_line_m": -1.7, "already_entered": False}, speed=0.0, motion=True)
    assert motion == "stop"
    assert vector == "crawl"


def test_when_every_candidate_collides_the_slowest_forward_one_is_taken(engine):
    """#18 regression: a car stopped ahead flagged every candidate; the first (fastest) one won the
    tie and the car drove into it. With no safe path left, brake hardest."""
    cands = {
        "fast": [13.0, 0.0, 0.1, 0.0, True, False],
        "mid": [7.2, 0.0, 0.2, 0.0, True, False],
        "slow": [3.9, 0.0, 0.2, 0.0, True, False],
        "back": [-0.6, 0.0, 0.2, 0.0, True, False],
    }
    questions = {"vector": {"type": "choice", "instructions": "Choose a path.", "criteria": {k: None for k in cands}}}
    state = {"speed_mps": 12.0, "on_road": True, "candidates": cands}
    choice = engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]["vector"]["choice"]
    assert choice == "slow"


def test_a_stop_offered_before_the_line_is_taken_when_the_car_could_not_stop_after_the_next_decision(engine):
    """#18: on the coast the stop is offered from further out (BUNDLE_PATCHES.md vision-stop-offer),
    because the next decision can come 1.5 s later and the car sheds little speed toward a slower
    path in that time (3.3 -> 2.7 m/s in 1.5 s, measured). Holding its speed until then and braking
    at 2.5 m/s^2 must still stop it 0.5 m short of the line, or it stops now: at 3.3 m/s that needs
    3.3 * 1.5 + 3.3^2 / 5 + 0.5 = 7.6 m, so 6.6 m out it stops (it rolled 0.1 m over when it drove
    on), 12 m out it drives on (the stopping curve picks its path)."""
    cands = {"a": [1.6, 0.0, 0.1, 0.0, False, False], "b": [3.4, 0.0, 0.1, 0.0, False, False]}
    questions = {
        "vector": {"type": "choice", "instructions": "Choose a path.", "criteria": {k: None for k in cands}},
        "motion": {"type": "choice", "instructions": "Stop means zero target now.", "criteria": {"drive": None, "stop": None}},
    }

    def motion(dist):
        inter = {"control": "signal", "signal": "red", "distance_to_line_m": dist, "stop_completed": False, "already_entered": False}
        state = {"speed_mps": 3.3, "on_road": True, "candidates": cands, "intersection": inter}
        answers = engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]
        return answers["motion"]["choice"], answers["vector"]["choice"]

    assert motion(6.6)[0] == "stop"
    assert motion(12.0)[0] == "drive"


def test_an_amber_the_car_cannot_stop_for_at_the_stop_brake_is_driven_through(engine):
    """Review #18: a stop brakes at about 2.5 m/s^2, so amber at 6 m/s with the line 5 m ahead
    (6 * 0.2 + 36 / 5 = 8.4 m to stop) would leave the car in the junction mouth as it turns red:
    drive through. A red there is still a stop."""
    questions = {
        "vector": {"type": "choice", "instructions": "Choose a path.", "criteria": {k: None for k in CANDIDATES}},
        "motion": {"type": "choice", "instructions": "Stop means zero target now.", "criteria": {"drive": None, "stop": None}},
    }

    def motion(signal):
        inter = {"control": "signal", "signal": signal, "distance_to_line_m": 5.0, "stop_completed": False, "already_entered": False}
        state = {"speed_mps": 6.0, "on_road": True, "candidates": CANDIDATES, "intersection": inter}
        return engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]["motion"]["choice"]

    assert motion("amber") == "drive"
    assert motion("red") == "stop"


def test_the_bundle_offers_the_stop_at_least_as_far_out_as_the_mock_needs_it():
    """The coast stop window in the bundle and the mock's stop threshold are one model; if either
    changes alone, the stop may not be offered when the mock needs it."""
    import re
    from pathlib import Path

    main = (Path(__file__).resolve().parents[1] / "jevpilot_vision" / "web" / "assets" / "main-CvLEeHjW.js").read_text(encoding="utf-8")
    gap, quad, extra = map(float, re.search(r"\(V=>V\*([\d.]+)\+V\*V/([\d.]+)\+([\d.]+)\)", main).groups())
    for v in (0.0, 1.0, 2.5, 4.0, 6.0, 9.0, 13.0):
        window = max(2.5, v * gap + v * v / quad + extra)
        need = v * DecisionEngine.DECISION_GAP_S + v * v / (2 * DecisionEngine.STOP_DECEL_MPS2) + 0.5
        assert window >= need, (v, window, need)
    assert DecisionEngine._may_cross_before_next({"speed_mps": "fast"}, 10.0) is True
