"""Vision mode (#18 part B): decisions read the cameras and the map, never the simulator.

A Vision request keeps ego odometry, the route and the map's stop lines. It loses the true signal
colour, every true object and the bundle's collision column; the signal comes from perception
(unseen counts as red), collisions are swept against perceived objects, and stale or missing
perception fails closed.
"""

from __future__ import annotations

import copy
import json

import pytest

from demo.server import DecisionEngine
from jevpilot_vision import vision_mode


def _perception(objects=(), signal="unknown", backend="PekingU/rtdetr_r50vd"):
    return {"backend": backend, "status": "ready", "objects": list(objects), "signal": {"state": signal, "conf": 0.8 if signal != "unknown" else 0.0}}


def _payload(perception=None, *, signal_truth="green", line=60.0, speed=12.0, candidates=None, mode="vision", age_ms=200):
    state = {
        "speed_mps": speed,
        "on_road": True,
        "intersection": {"control": "signal", "signal": signal_truth, "distance_to_line_m": line, "stop_completed": False, "already_entered": False},
        "pedestrian": {"distance_m": 9.0, "lateral_offset_m": 0.1},
        "roadside_obstacle": {"distance_m": 30.0},
        "scene": {"nearby": [{"id": "car-3", "ahead_m": 8.0}]},
        "traffic": {"queue": True},
        "stop_reasons": [],
        "candidates": candidates or {
            "fast": [12.0, 0.0, 0.1, 0.0, False, False],
            "mid": [7.0, 0.0, 0.2, 0.0, False, False],
            "slow": [2.0, 0.0, 0.3, 0.0, False, False],
        },
        "vision": {"signal": "unknown", "event": "", "perception": perception if perception is not None else _perception()},
        "vision_age_ms": age_ms,
    }
    body = {"mode": "flat", "state": state, "questions": {"vector": {"type": "choice", "instructions": "Choose.", "criteria": {k: None for k in state["candidates"]}}}}
    if mode:
        body["drive_mode"] = mode
    return body


def test_a_vision_request_loses_every_privileged_field_and_keeps_the_map():
    payload = vision_mode.prepare(_payload(_perception(signal="green")))
    state = payload["state"]
    for key in ("pedestrian", "roadside_obstacle", "scene", "traffic"):
        assert key not in state, key
    inter = state["intersection"]
    assert inter["control"] == "signal" and inter["distance_to_line_m"] == 60.0, "the map's stop line stays"
    assert inter["signal"] == "green" and inter["signal_source"] == "perception", "the colour is what the camera saw"


def test_an_unseen_light_counts_as_red_and_stale_perception_is_no_perception():
    seen = vision_mode.prepare(_payload(_perception(signal="unknown")))["state"]["intersection"]
    assert seen["signal"] == "red" and seen["signal_source"] == "assumed"
    stale = vision_mode.prepare(_payload(_perception(signal="green"), age_ms=4000))["state"]
    assert stale["intersection"]["signal"] == "red" and stale["perception_ok"] is False
    missing = vision_mode.prepare(_payload(_perception(signal="green", backend="none")))["state"]
    assert missing["perception_ok"] is False


def test_collisions_are_swept_against_perceived_objects_not_the_bundles_column():
    # Driving at 5 m/s, a parked car 11 m ahead (closing at our own speed).
    car = {"kind": "car", "ahead_m": 11.0, "right_m": 0.0, "closing_mps": 5.0}
    candidates = {
        "fast": [12.0, 0.0, 0.1, 0.0, False, False],  # the bundle saw nothing in the way
        "slow": [1.0, 0.0, 0.3, 0.0, False, False],
        "wall": [1.0, 0.0, 0.1, 0.0, True, False],  # the bundle's flag: in Vision mode it sees buildings only
    }
    out = vision_mode.prepare(_payload(_perception([car], signal="green"), candidates=candidates, line=200.0, speed=5.0))["state"]["candidates"]
    assert out["fast"][4] is True, "speeding up into a parked car 11 m ahead is a collision"
    assert out["slow"][4] is False
    assert out["wall"][4] is True, "a building in the way (map data) still counts"
    ped_left = {"kind": "pedestrian", "ahead_m": 7.0, "right_m": -4.0, "closing_mps": 12.0}
    out = vision_mode.prepare(_payload(_perception([ped_left], signal="green"), candidates=candidates, line=200.0, speed=5.0))["state"]["candidates"]
    assert out["fast"][4] is False, "a person on the pavement 4 m to the left is not in the way"


def test_privileged_requests_are_left_exactly_as_they_were():
    payload = _payload(_perception(signal="green"), mode=None)
    assert vision_mode.prepare(copy.deepcopy(payload)) == payload


@pytest.fixture(scope="module")
def engine():
    return DecisionEngine(use_mock=True)


def _choice(engine, payload):
    from jevpilot_vision.drive import score_drive_request

    return score_drive_request(engine, payload)["answers"]["vector"]["choice"]


def test_the_mock_stops_for_an_unseen_light_and_goes_on_a_seen_green(engine):
    assert _choice(engine, _payload(_perception(signal="unknown"), signal_truth="green", line=25.0)) != "fast"
    assert _choice(engine, _payload(_perception(signal="green"), signal_truth="red", line=25.0)) == "fast", "it follows its eyes, not the simulator"


def test_the_mock_avoids_a_perceived_car_and_fails_closed_without_perception(engine):
    car = {"kind": "car", "ahead_m": 13.0, "right_m": 0.0, "closing_mps": 5.0}
    assert _choice(engine, _payload(_perception([car], signal="green"), line=200.0, speed=5.0)) == "slow"
    assert _choice(engine, _payload(_perception(signal="green", backend="none"), line=200.0)) == "slow"


def test_the_clients_remembered_light_wins_while_its_evidence_is_fresh():
    """The page keeps a light it read for 2.5 s (semif-layer.js updateSeenSignal) and sends it."""
    payload = _payload(_perception(signal="unknown"))
    payload["state"]["seen_signal"] = "green"
    assert vision_mode.prepare(payload)["state"]["intersection"]["signal"] == "green"
    stale = _payload(_perception(signal="unknown"), age_ms=4000)
    stale["state"]["seen_signal"] = "green"
    assert vision_mode.prepare(stale)["state"]["intersection"]["signal"] == "red", "stale evidence remembers nothing"


def test_an_object_of_unknown_speed_is_treated_as_standing_still():
    """A car seen once (no closing speed yet) is not assumed to drive away at our speed."""
    car = {"kind": "car", "ahead_m": 14.0, "right_m": 0.0, "closing_mps": None}
    cands = {"fast": [9.0, 0.0, 0.1, 0.0, False, False], "crawl": [0.5, 0.0, 0.2, 0.0, False, False]}
    out = vision_mode.prepare(_payload(_perception([car], signal="green"), candidates=cands, line=200.0, speed=9.0))["state"]["candidates"]
    assert out["fast"][4] is True and out["crawl"][4] is False



def test_review_h3_without_perception_only_a_crawl_or_a_stop_is_safe():
    cands = {"cruise": [12.0, 0.0, 0.1, 0.0, False, False], "crawl": [0.8, 0.0, 0.2, 0.0, False, False]}
    out = vision_mode.prepare(_payload(_perception(signal="green", backend="none"), candidates=cands, line=200.0))["state"]["candidates"]
    assert out["cruise"][4] is True and out["crawl"][4] is False


def test_review_h4_the_sweep_follows_the_planners_own_path_when_it_is_sent():
    """The planner re-steers to follow the lane; a constant steer of 0.1 would bend 4 m clear of a
    car parked 20 m ahead that the real (lane-following, straight) path hits."""
    car = {"kind": "car", "ahead_m": 20.0, "right_m": 0.0, "closing_mps": 10.0}
    cands = {"lane": [10.0, 0.1, 0.1, 0.0, False, False]}
    straight = [[round(0.2 * k, 1), round(10.0 * 0.2 * k, 2), 0.0, 0.0] for k in range(1, 16)]
    payload = _payload(_perception([car], signal="green"), candidates=cands, line=200.0, speed=10.0)
    payload["state"]["candidate_paths"] = {"lane": straight}
    assert vision_mode.prepare(payload)["state"]["candidates"]["lane"][4] is True
    payload["state"].pop("candidate_paths")
    assert vision_mode.prepare(payload)["state"]["candidates"]["lane"][4] is False, "the fallback model is the old constant steer"


def test_review_h5_objects_are_moved_by_the_age_of_the_evidence():
    """A parked car 18 m ahead in a frame taken 1 s ago at 10 m/s is 8 m ahead now."""
    car = {"kind": "car", "ahead_m": 18.0, "right_m": 0.0, "closing_mps": 10.0}
    cands = {"slow": [2.0, 0.0, 0.1, 0.0, False, False]}
    fresh = vision_mode.prepare(_payload(_perception([car], signal="green"), candidates=cands, line=200.0, speed=10.0, age_ms=0))
    old = vision_mode.prepare(_payload(_perception([car], signal="green"), candidates=cands, line=200.0, speed=10.0, age_ms=1000))
    assert fresh["state"]["candidates"]["slow"][4] is False
    assert old["state"]["candidates"]["slow"][4] is True


def test_review_h6_no_signal_is_claimed_where_there_is_no_light():
    payload = _payload(_perception(signal="unknown"))
    payload["state"]["intersection"] = None
    state = vision_mode.prepare(payload)["state"]
    assert state["vision"]["signal"] == "unknown", "open road: no assumed red for the arbiter's directive"
    stop = _payload(_perception(signal="unknown"))
    stop["state"]["intersection"]["control"] = "stop"
    assert vision_mode.prepare(stop)["state"]["vision"]["signal"] == "unknown"


def test_review_m4_reversing_into_what_the_front_camera_cannot_see_counts_as_a_collision():
    cands = {"back": [-1.5, 0.0, 0.1, 0.0, False, False], "crawl": [0.5, 0.0, 0.1, 0.0, False, False]}
    out = vision_mode.prepare(_payload(_perception(signal="green"), candidates=cands, line=200.0, speed=0.0))["state"]["candidates"]
    assert out["back"][4] is True and out["crawl"][4] is False


def test_review_l4_a_malformed_object_is_ignored_not_a_crash():
    bad = {"kind": "car", "ahead_m": "near", "right_m": 0.0, "closing_mps": "fast"}
    good = {"kind": "car", "ahead_m": 30.0, "right_m": 0.0, "closing_mps": "?"}
    out = vision_mode.prepare(_payload(_perception([bad, good], signal="green"), line=200.0))
    assert out["state"]["perceived_objects"][0]["ahead_m"] == 30.0


def test_a_car_in_our_lane_is_never_assumed_to_drive_back_at_us():
    """#18 regression: ranging noise put a stopped car's closing speed above our own, which reads as
    the car reversing toward us, and flagged even the slowest candidate. Traffic ahead in our lane
    moves away or stands; only a car in another lane may come toward us."""
    noisy = {"kind": "car", "ahead_m": 25.0, "right_m": 0.0, "closing_mps": 16.0}
    cands = {"slow": [2.0, 0.0, 0.1, 0.0, False, False]}
    out = vision_mode.prepare(_payload(_perception([noisy], signal="green"), candidates=cands, line=200.0, speed=10.0, age_ms=0))
    assert out["state"]["candidates"]["slow"][4] is False
    oncoming = {"kind": "car", "ahead_m": 25.0, "right_m": -2.0, "closing_mps": 20.0}
    out = vision_mode.prepare(_payload(_perception([oncoming], signal="green"), candidates=cands, line=200.0, speed=10.0, age_ms=0))
    assert out["state"]["candidates"]["slow"][4] is True, "a car over the centre line still comes toward us"


def test_review2_h1_an_open_road_with_no_sighting_is_not_a_red_light():
    """The page sends seen_signal null when it saw nothing; the arbiter's directive must not become
    RED_LIGHT_STOP away from a signalled line."""
    from jevpilot_vision.drive import prepare_drive_request

    payload = _payload(_perception(signal="unknown"))
    payload["state"]["intersection"] = None
    payload["state"]["seen_signal"] = None
    state = vision_mode.prepare(payload)["state"]
    assert state["vision"]["signal"] == "unknown"
    assert "RED_LIGHT_STOP" not in json.dumps(prepare_drive_request(vision_mode.prepare(payload)))


def test_review2_m3_a_green_reading_is_trusted_for_0_8_s_from_when_it_was_taken():
    """A green the page did not remember (or an old client that sends nothing) counts only while the
    frame is under 0.8 s old: past that, an amber could have come and gone before the decision acts."""
    fresh = vision_mode.prepare(_payload(_perception(signal="green"), age_ms=500))["state"]
    old = vision_mode.prepare(_payload(_perception(signal="green"), age_ms=1200))["state"]
    red = vision_mode.prepare(_payload(_perception(signal="red"), age_ms=1200))["state"]
    assert fresh["intersection"]["signal"] == "green"
    assert old["intersection"]["signal"] == "red" and old["intersection"]["signal_source"] == "assumed"
    assert red["intersection"]["signal"] == "red" and red["intersection"]["signal_source"] == "perception"


def test_review2_l5_evidence_from_the_future_is_not_fresh():
    state = vision_mode.prepare(_payload(_perception(signal="green"), age_ms=-400))["state"]
    assert state["perception_ok"] is False


def _blob_event_from_silhouette():
    """The issue's frame (#65): a dark block in the lower half, no detector involved."""
    from PIL import Image, ImageDraw

    from jevpilot_vision.vision import blobs_from_frame, event_from_motion, frame_motion

    image = Image.new("RGB", (224, 224), (127, 127, 127))
    ImageDraw.Draw(image).rectangle((90, 140, 130, 210), fill=(32, 35, 38))
    blobs = blobs_from_frame(image)
    assert "pedestrian" in blobs, "the colour mask still reads the block as a person"
    return event_from_motion(frame_motion(None, blobs), "unknown")


def test_issue65_the_colour_mask_never_reaches_the_prompt_or_the_directive():
    from jevpilot_vision.directive import plan_directive
    from jevpilot_vision.drive import prepare_drive_request

    event = _blob_event_from_silhouette()
    assert "person" in event
    payload = _payload(_perception(signal="green"), line=200.0)
    payload["state"]["vision"]["event"] = event
    prepared = vision_mode.prepare(payload)
    vision = prepared["state"]["vision"]
    assert "person" not in vision["event"]
    assert plan_directive(vision, prepared["state"]["intersection"])["intent"] != "CAUTION"
    prompt = prepare_drive_request(prepared)["state"]["_semif_prompt_state"]
    assert "person" not in json.dumps(prompt)


def test_issue65_a_red_in_the_event_text_does_not_outvote_the_light_the_camera_read(engine):
    from jevpilot_vision.directive import plan_directive
    from jevpilot_vision.drive import _signal

    payload = _payload(_perception(signal="green"), line=25.0)
    payload["state"]["vision"]["event"] = "RED signal ahead, mandatory stop"
    state = vision_mode.prepare(copy.deepcopy(payload))["state"]
    assert _signal(state) == "green"
    assert plan_directive(state["vision"], state["intersection"])["intent"] != "RED_LIGHT_STOP"
    assert _choice(engine, payload) == "fast"


def test_issue65_the_event_names_what_the_detector_saw():
    person = {"kind": "pedestrian", "ahead_m": 9.0, "right_m": 0.3, "closing_mps": 9.0}
    state = vision_mode.prepare(_payload(_perception([person], signal="green"), line=200.0, speed=9.0))["state"]
    assert "pedestrian" in state["vision"]["event"]
    assert "traffic light is green" in state["vision"]["event"]
    assert state["candidates"]["fast"][4] is True, "the sweep still flags the perceived person"
    unseen = vision_mode.prepare(_payload(_perception(signal="unknown"), line=40.0))["state"]["vision"]["event"]
    assert unseen.startswith("RED signal ahead"), "an unseen light at a signalled line is the assumed red"


def test_issue65_review_blind_is_not_a_clear_road_and_the_line_fits_the_prompt():
    blind = vision_mode.prepare(_payload(_perception(signal="green", backend="none"), line=200.0))["state"]
    assert "clear" not in blind["vision"]["event"] and "unavailable" in blind["vision"]["event"]
    crowd = [
        {"kind": "pedestrian", "ahead_m": 9.0, "right_m": 0.3, "closing_mps": 0.0},
        {"kind": "car", "ahead_m": 22.0, "right_m": 0.0, "closing_mps": 0.0},
        {"kind": "motorcycle", "ahead_m": 31.0, "right_m": 2.0, "closing_mps": 0.0},
    ]
    event = vision_mode.prepare(_payload(_perception(crowd, signal="unknown"), line=40.0))["state"]["vision"]["event"]
    assert len(event) <= 96 and "motorcycle" in event, event


# --- #75: box flow in the new Vision ------------------------------------------------------------

def test_issue75_only_the_expansion_rate_says_danger_and_the_candidate_is_hit():
    # Ranging says the car ahead keeps its distance; its box says contact in 2 s.
    car = {"kind": "car", "ahead_m": 14.0, "right_m": 0.0, "closing_mps": 0.0, "ttc_s": 2.0}
    straight = [8.0, 0.0, 0, 0, False, False]
    assert vision_mode.sweep_collision(straight, [car], speed=8.0) is False, "ranging alone: no hit"
    assert vision_mode.sweep_collision(straight, [car], speed=8.0, use_flow=True) is True
    # the more dangerous of the two wins: a far TTC does not hide a fast range closing
    near = {"kind": "car", "ahead_m": 9.0, "right_m": 0.0, "closing_mps": 8.0, "ttc_s": 30.0}
    assert vision_mode.sweep_collision(straight, [near], speed=8.0, use_flow=True) is True


def test_issue75_the_ablation_switch_picks_one_closing_source(monkeypatch):
    straight = [8.0, 0.0, 0, 0, False, False]
    flow_only = {"kind": "car", "ahead_m": 14.0, "right_m": 0.0, "closing_mps": 0.0, "ttc_s": 2.0}
    range_only = {"kind": "car", "ahead_m": 14.0, "right_m": 0.0, "closing_mps": 7.0, "ttc_s": None}
    monkeypatch.setenv("SEMIF_VISION_CLOSING", "range")
    assert vision_mode.sweep_collision(straight, [flow_only], speed=8.0, use_flow=True) is False
    monkeypatch.setenv("SEMIF_VISION_CLOSING", "flow")
    assert vision_mode.sweep_collision(straight, [flow_only], speed=8.0, use_flow=True) is True
    # without a TTC, "flow" knows no speed: the car is taken as standing, the cautious reading
    assert vision_mode.sweep_collision(straight, [range_only], speed=8.0, use_flow=True) is True
    monkeypatch.setenv("SEMIF_VISION_CLOSING", "nonsense")
    assert vision_mode.closing_source() == "both"


def test_issue75_the_new_vision_reads_box_flow_and_vision_map_does_not():
    def payload(stage):
        p = _payload(_perception([{"kind": "car", "ahead_m": 14.0, "right_m": 0.0, "closing_mps": 0.0, "ttc_s": 2.0}], signal="green"),
                     candidates={"keep": [8.0, 0.0, 0.0, 0.0, False, False]}, speed=8.0)
        if stage is not None:
            p["vision_stage"] = stage
        return p
    assert vision_mode.prepare(payload(None))["state"]["candidates"]["keep"][4] is False
    assert vision_mode.prepare(payload(1))["state"]["candidates"]["keep"][4] is True


def test_issue75_the_event_says_how_a_car_moves_within_the_prompt_cap():
    objects = [
        {"kind": "car", "ahead_m": 14.0, "right_m": 0.0, "ttc_s": 2.1, "toward_center_mps": 0.0},
        {"kind": "pedestrian", "ahead_m": 9.0, "right_m": 4.0},
        {"kind": "motorcycle", "ahead_m": 22.0, "right_m": 3.6, "toward_center_mps": 1.2},
    ]
    text = vision_mode.perception_event("red", objects, flow=True)
    assert "TTC 2.1 s" in text and len(text) <= 96, text
    assert text.startswith("RED signal ahead"), "the light is never the clause dropped"
    cut = vision_mode.perception_event("green", [objects[2]], flow=True)
    assert "cutting in from right" in cut, cut
    assert "TTC" not in vision_mode.perception_event("red", objects), "Vision (map) keeps its words"


# --- #75 review --------------------------------------------------------------------------------

def test_issue75_review_vision_map_keeps_its_event_words_exactly():
    objects = [
        {"kind": "pedestrian", "ahead_m": 30.0, "right_m": 0.0, "ttc_s": 1.0},
        {"kind": "car", "ahead_m": 10.0, "right_m": 0.0, "ttc_s": 2.0},
        {"kind": "motorcycle", "ahead_m": 44.4, "right_m": 3.0, "toward_center_mps": 2.0},
    ]
    # kind order (pedestrian, vehicle, motorcycle), never ranked, never cut here
    assert vision_mode.perception_event("red", objects) == (
        "RED signal ahead, mandatory stop; pedestrian at 30 m; vehicle at 10 m; motorcycle at 44 m")
    assert vision_mode.perception_event("green", objects, ok=False).endswith("camera evidence unavailable")


def test_issue75_review_box_jitter_on_a_parked_car_is_not_a_car_reversing_at_us():
    parked = {"kind": "car", "ahead_m": 30.0, "right_m": 0.0, "closing_mps": 8.0, "ttc_s": 1.0}  # jitter: 30 m/s
    assert vision_mode.sweep_collision([8.0, 0.0, 0, 0, False, False], [parked], speed=8.0, use_flow=True) is False


def test_issue75_review_the_server_takes_the_pages_gyro_with_the_frames(monkeypatch):
    import asyncio

    from jevpilot_vision import http

    seen = {}
    monkeypatch.setattr(http._vision_slot, "submit", lambda image: (seen.setdefault("image", image), None, None) and (0, None, 0))
    import base64
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (64, 36), (90, 90, 90)).save(buf, format="JPEG")
    frame = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    for yaw, kept in ((0.15, 0.15), (float("nan"), None), (9.0, None), (True, None)):
        seen.clear()
        try:
            asyncio.run(http.vision_endpoint({"frames": {"front": frame}, "t_ms": 5.0, "yaw_rps": yaw}))
        except Exception:
            pass
        assert seen["image"].get("_yaw_rps") == kept, (yaw, seen["image"])


def test_issue75_review_the_flow_ablation_reads_box_flow_for_cars_in_our_lane(monkeypatch):
    straight = [8.0, 0.0, 0, 0, False, False]
    # 14 m ahead; its box says we close at 2 m/s (TTC 7 s), ranging knows nothing
    slow = {"kind": "car", "ahead_m": 14.0, "right_m": 0.0, "closing_mps": None, "ttc_s": 7.0}
    monkeypatch.setenv("SEMIF_VISION_CLOSING", "flow")
    assert vision_mode.sweep_collision(straight, [slow], speed=8.0, use_flow=True) is False
    monkeypatch.setenv("SEMIF_VISION_CLOSING", "range")
    assert vision_mode.sweep_collision(straight, [slow], speed=8.0, use_flow=True) is True, "unknown: standing"


def test_issue75_review_the_server_takes_the_pages_odometer_with_the_frames(monkeypatch):
    import asyncio
    import base64
    from io import BytesIO

    from PIL import Image

    from jevpilot_vision import http

    seen = {}
    monkeypatch.setattr(http._vision_slot, "submit", lambda image: (seen.setdefault("image", image), None, None) and (0, None, 0))
    buf = BytesIO()
    Image.new("RGB", (64, 36), (90, 90, 90)).save(buf, format="JPEG")
    frame = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    for speed, kept in ((9.5, 9.5), (-1.0, None), (float("inf"), None), (None, None)):
        seen.clear()
        try:
            asyncio.run(http.vision_endpoint({"frames": {"front": frame}, "t_ms": 5.0, "speed_mps": speed}))
        except Exception:
            pass
        assert seen["image"].get("_speed_mps") == kept, (speed, seen["image"])

