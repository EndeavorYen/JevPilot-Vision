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
    assert ask(engine, {"signal": "red", "distance_to_line_m": 6}, speed=3.0, motion=True)[1] == "drive", "not yet at the line"


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


def test_a_stop_offered_before_the_line_is_taken_when_the_slowest_path_could_cross_first(engine):
    """#18: on the coast the stop is offered from further out (BUNDLE_PATCHES.md vision-stop-offer),
    because a decision comes only every 0.7-1.0 s plus 0.2 s to answer. 4.5 m short of a red line
    at 3.8 m/s with nothing slower than 3.6 m/s offered, the next decision may come after the car
    has crossed (3.6 m/s * 1.2 s = 4.3 m > 4.5 - 0.5 m): stop now. With a 1 m/s path offered, drive on."""
    fast_only = {"a": [3.6, 0.0, 0.1, 0.0, False, False], "b": [4.2, 0.0, 0.1, 0.0, False, False]}
    questions = {
        "vector": {"type": "choice", "instructions": "Choose a path.", "criteria": {k: None for k in fast_only}},
        "motion": {"type": "choice", "instructions": "Stop means zero target now.", "criteria": {"drive": None, "stop": None}},
    }
    inter = {"control": "signal", "signal": "red", "distance_to_line_m": 4.5, "stop_completed": False, "already_entered": False}
    state = {"speed_mps": 3.8, "on_road": True, "candidates": fast_only, "intersection": inter}
    answers = engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]
    assert answers["motion"]["choice"] == "stop"
    slow = {**fast_only, "c": [1.0, 0.0, 0.1, 0.0, False, False]}
    state = {**state, "candidates": slow}
    questions["vector"]["criteria"] = {k: None for k in slow}
    answers = engine.classify_jev({"mode": "flat", "state": state, "questions": questions})["answers"]
    assert answers["motion"]["choice"] == "drive" and answers["vector"]["choice"] == "c"
