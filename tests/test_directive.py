from jevpilot_vision.directive import fail_safe_choice, plan_directive


def test_plan_directive_never_returns_a_trajectory_id():
    red = plan_directive({"signal": "red", "event": "RED signal ahead, mandatory stop"})
    assert red["intent"] == "RED_LIGHT_STOP"
    assert "t0" not in red["intent"] and "v0" not in red["directive"]
    cut = plan_directive({"event": "caution: vehicle cutting toward frame center, growing in the camera"})
    assert cut["intent"] == "YIELD_CUT_IN"
    cruise = plan_directive({})
    assert cruise["intent"] == "CRUISE"


def test_fail_safe_overrides_collision_even_on_cruise():
    cands = {
        "v0": [16.0, 0.0, 0.1, 0.0, True, False],
        "v1": [0.0, 0.0, 0.0, 0.0, False, True],
    }
    assert fail_safe_choice(cands, "v0", {"intent": "CRUISE"}) == "v1"


def test_red_light_stop_picks_halt_leaf():
    cands = {
        "v0": [12.0, 0.0, 0.1, 0.0, False, False],
        "v1": [0.2, 0.0, 0.0, 0.0, False, True],
        "v2": [8.0, -0.1, 0.2, 0.0, False, False],
    }
    assert fail_safe_choice(cands, "v0", {"intent": "RED_LIGHT_STOP"}) == "v1"


def test_red_light_without_halt_leaf_does_not_invent_one():
    cands = {
        "v0": [12.0, 0.0, 0.1, 0.0, False, False],
        "v1": [8.0, 0.0, 0.2, 0.0, False, False],
    }
    assert fail_safe_choice(cands, "v0", {"intent": "RED_LIGHT_STOP"}) == "v0"


def _privileged(intersection_signal, vision_signal, event="road clear ahead, maintain lane"):
    return {
        "speed_mps": 10.0,
        "on_road": True,
        "intersection": {"control": "signal", "signal": intersection_signal, "distance_to_line_m": 30.0},
        "vision": {"signal": vision_signal, "event": event},
        "lateral_offset_m": 0.1,
        "candidates": {"t00": [10.0, 0.0, 0.1, 0.0, False, False], "t01": [0.0, 0.0, 0.1, 0.0, False, True]},
    }


def test_issue84_an_unknown_camera_signal_does_not_hide_a_true_red():
    from jevpilot_vision.drive import _signal, finish_drive_choice, prepare_drive_request

    state = _privileged("red", "unknown")
    assert _signal(state) == "red"
    assert plan_directive(state["vision"], state["intersection"])["intent"] == "RED_LIGHT_STOP"
    body = {"mode": "flat", "state": state, "questions": {"vector": {"type": "choice", "instructions": "Choose.", "criteria": {"t00": None, "t01": None}}}}
    tags = prepare_drive_request(body)["questions"]["vector"]["criteria"]
    assert tags["t00"] != "10.0m/s +0.00 centering clear go", tags  # the run-red option is marked
    result = {"answers": {"vector": {"choice": "t00", "probabilities": {"t00": 0.9, "t01": 0.1}}}}
    assert finish_drive_choice(body, result)["answers"]["vector"]["choice"] == "t01", "the local veto halts"


def test_issue84_a_camera_signal_counts_where_the_intersection_has_none():
    from jevpilot_vision.drive import _signal

    state = _privileged(None, "green")
    assert _signal(state) == "green"
    assert plan_directive({"signal": "red"}, {})["intent"] == "RED_LIGHT_STOP"


def test_issue84_the_intersection_wins_over_a_different_camera_colour_but_a_red_event_still_stops():
    from jevpilot_vision.drive import _signal

    state = _privileged("green", "red")
    assert _signal(state) == "green"
    assert plan_directive(state["vision"], state["intersection"])["intent"] == "CRUISE"
    cautious = _privileged("green", "unknown", event="RED signal ahead, mandatory stop")
    assert _signal(cautious) == "red", "the conservative red-in-event override is kept"


def test_issue84_review_a_vehicle_that_appeared_is_not_a_red_light():
    """'appeared' contains 'red': the conservative override must read the word, not the letters."""
    from jevpilot_vision.drive import _signal

    state = _privileged("green", "unknown", event="a vehicle appeared in frame")
    assert _signal(state) == "green"
    assert _signal(_privileged("green", "unknown", event="RED signal ahead, mandatory stop")) == "red"
