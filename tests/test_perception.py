"""Onboard perception for Vision mode (#18): what the front camera's pixels say about the road.

Detections come from a COCO detector; range comes from the ground plane (flat world, camera at a
known height, looking level); a traffic light's state comes from the pixels inside its box.
Nothing here reads the simulator.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from jevpilot_vision.perception import (
    CameraModel,
    Tracker,
    classify_light,
    decode_detections,
    perceive,
)

CAM = CameraModel(width=320, height=180, hfov_deg=100.0, height_m=1.45)


def test_the_camera_model_ranges_points_on_the_ground():
    assert CAM.fx == pytest.approx(160 / math.tan(math.radians(50)), rel=1e-6)
    ahead, right = CAM.ground_point(160, 90 + CAM.fx * 1.45 / 10.0)
    assert ahead == pytest.approx(10.0, rel=1e-6) and right == pytest.approx(0.0, abs=1e-9)
    ahead, right = CAM.ground_point(200, 90 + CAM.fx * 1.45 / 10.0)
    assert right == pytest.approx(40 * 10.0 / CAM.fx, rel=1e-6), "right of the image is right of the car"
    assert CAM.ground_point(160, 90) is None and CAM.ground_point(160, 60) is None, "nothing on the ground at or above the horizon"
    # A larger frame of the same camera gives the same answer.
    big = CameraModel(width=640, height=360, hfov_deg=100.0, height_m=1.45)
    assert big.ground_point(320, 180 + big.fx * 1.45 / 10.0)[0] == pytest.approx(10.0, rel=1e-6)


def _crop(rgb, lamp=None, size=(24, 10)):
    h, w = size
    img = np.full((h, w, 3), (40, 44, 48), dtype=np.uint8)  # the housing
    if lamp:
        img[2:7, 3:7] = lamp
    return img


def test_a_lights_state_is_read_from_its_lit_lamp():
    # Lit coast lamps as the onboard camera sees them after ACES (BUNDLE_PATCHES.md coast-signal-lamps).
    assert classify_light(_crop(None, (254, 63, 37))) == "red"
    assert classify_light(_crop(None, (70, 250, 110))) == "green"
    assert classify_light(_crop(None, (254, 205, 30))) == "amber"
    assert classify_light(_crop(None, None)) == "unknown"
    # Sky, foliage and a dim housing behind the box are not lamps.
    assert classify_light(_crop(None, (143, 171, 208))) == "unknown"
    assert classify_light(_crop(None, (70, 87, 59))) == "unknown"
    # 15-20 m away the lamp is a few soft pixels (JPEG, bloom): pale but clearly green and bright.
    assert classify_light(_crop(None, (190, 233, 144))) == "green"
    # A box that caught sunlit sand around a dark lamp is not amber: a lamp outshines its box.
    sand = np.full((24, 10, 3), (205, 182, 143), dtype=np.uint8)
    assert classify_light(sand) == "unknown"


def test_detector_output_decodes_to_pixel_boxes_of_the_kinds_we_drive_around():
    id2label = {0: "person", 1: "car", 2: "traffic light", 3: "dog", 4: "truck"}
    logits = np.full((5, 5), -9.0)
    logits[0, 0] = 3.0  # person, sure
    logits[1, 1] = 0.5  # car, 0.62
    logits[2, 2] = -2.0  # traffic light, too unsure
    logits[3, 3] = 4.0  # a dog is not on the list
    logits[4, 4] = 2.0  # a truck drives like a car
    boxes = np.array([[0.5, 0.5, 0.1, 0.2]] * 5)
    dets = decode_detections(logits, boxes, id2label, (320, 180), threshold=0.35)
    assert [d["kind"] for d in dets] == ["pedestrian", "car", "car"]
    assert dets[0]["box"] == pytest.approx([144.0, 72.0, 176.0, 108.0])
    assert dets[0]["conf"] == pytest.approx(1 / (1 + math.exp(-3.0)), rel=1e-6)


def _det(kind, x0, y0, x1, y1, conf=0.8):
    return {"kind": kind, "conf": conf, "box": [x0, y0, x1, y1]}


def test_perceive_ranges_people_and_cars_and_drops_impossible_shapes():
    v10 = 90 + CAM.fx * 1.45 / 10.0  # the ground row 10 m ahead
    person_h = CAM.fx * 1.7 / 10.0  # a 1.7 m person at 10 m, in pixels
    car_h = CAM.fx * 1.5 / 10.0
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    dets = [
        _det("pedestrian", 150, v10 - person_h, 158, v10),
        _det("pedestrian", 220, v10 - 3 * person_h, 226, v10),  # a lamp post: three times too tall
        _det("car", 120, v10 - car_h, 180, v10),
        _det("car", 10, 60, 40, 80),  # entirely above the horizon
    ]
    out = perceive(dets, frame, CAM)
    kinds = [(o["kind"], round(o["ahead_m"], 1)) for o in out["objects"]]
    assert kinds == [("pedestrian", 10.0), ("car", 10.0)]
    ped = out["objects"][0]
    assert ped["right_m"] == pytest.approx((154 - 160) * 10.0 / CAM.fx, abs=0.01)
    assert out["signal"]["state"] == "unknown"


def test_perceive_reads_the_light_ahead_not_one_off_to_the_side():
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[40:46, 162:166] = (254, 63, 37)  # a red lamp near the centre
    frame[40:46, 12:16] = (70, 250, 110)  # a green lamp far to the left, for the cross street
    dets = [_det("traffic_light", 158, 36, 170, 60, 0.7), _det("traffic_light", 8, 36, 20, 60, 0.9)]
    out = perceive(dets, frame, CAM)
    assert out["signal"]["state"] == "red"
    assert out["signal"]["conf"] == pytest.approx(0.7)


def test_the_tracker_gives_a_closing_speed():
    tracker = Tracker()
    a = tracker.update([{"kind": "car", "ahead_m": 20.0, "right_m": 0.2}], t=10.0)
    b = tracker.update([{"kind": "car", "ahead_m": 18.0, "right_m": 0.3}], t=10.5)
    assert a[0]["closing_mps"] is None, "a first sighting has no known speed"
    assert b[0]["closing_mps"] == pytest.approx(4.0)
    c = tracker.update([{"kind": "pedestrian", "ahead_m": 18.0, "right_m": 0.3}], t=11.0)
    assert c[0]["closing_mps"] is None, "a different kind is a different object"


def test_without_a_detector_perception_says_so_instead_of_reporting_a_clear_road():
    out = perceive(None, np.zeros((180, 320, 3), dtype=np.uint8), CAM)
    assert out["backend"] == "none" and out["objects"] == [] and out["signal"]["state"] == "unknown"


def _jpeg(width, height):
    import base64
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), (90, 90, 90)).save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def test_vision_evidence_carries_the_front_cameras_perception(monkeypatch):
    import jevpilot_vision.http as http
    import jevpilot_vision.perception as perception
    import jevpilot_vision.vision as vision

    class Encoder:
        def infer_surround_b64(self, frames):
            return {"backend": "stub", "signal": "unknown", "event": "", "seen": sorted(frames)}

    seen = {}

    class Fake:
        def front(self, image, t=None, narrow=None, yaw_rps=0.0):
            seen["size"] = image.size
            return {"backend": "fake", "objects": [{"kind": "car", "ahead_m": 12.0}], "signal": {"state": "red", "conf": 0.8}}

    monkeypatch.setattr(vision, "get_vision_encoder", lambda: Encoder())
    monkeypatch.setattr(perception, "get_perception", lambda: Fake())
    frames = {"front": _jpeg(640, 360), "right": _jpeg(320, 180), "rear": _jpeg(320, 180), "left": _jpeg(320, 180)}
    evidence = http._infer_latest_jpeg(frames)
    assert evidence["seen"] == ["front", "left", "rear", "right"]
    assert seen["size"] == (640, 360), "perception reads the front camera at full resolution"
    assert evidence["perception"]["objects"][0]["kind"] == "car"
    assert evidence["perception"]["signal"]["state"] == "red"

    class Broken:
        def front(self, image, t=None, narrow=None, yaw_rps=0.0):
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(perception, "get_perception", lambda: Broken())
    evidence = http._infer_latest_jpeg(frames)
    assert evidence["perception"]["backend"] == "none", "a failed detector is reported, never a clear road"
    assert evidence["perception"]["objects"] == [] and "error" in evidence["perception"]


def test_a_saturated_amber_core_is_still_amber():
    """Review: when red and green both clip, the lamp's core is pure yellow (hue 60)."""
    assert classify_light(_crop(None, (255, 255, 40))) == "amber"


def test_the_tracker_rejects_impossible_speeds_resets_after_a_gap_and_pairs_one_to_one():
    tracker = Tracker()
    tracker.update([{"kind": "car", "ahead_m": 10.0, "right_m": 0.0}], t=0.0)
    jump = tracker.update([{"kind": "car", "ahead_m": 12.9, "right_m": 0.0}], t=0.05)
    assert jump[0]["closing_mps"] is None, "58 m/s apart is a different car, not a fast one"
    tracker.update([{"kind": "car", "ahead_m": 20.0, "right_m": 0.0}], t=1.0)
    gap = tracker.update([{"kind": "car", "ahead_m": 18.0, "right_m": 0.0}], t=2.0)
    assert gap[0]["closing_mps"] == pytest.approx(2.0), "a second between frames (slow inference) still pairs"
    late = tracker.update([{"kind": "car", "ahead_m": 17.0, "right_m": 0.0}], t=5.0)
    assert late[0]["closing_mps"] is None, "after a long gap (reload, pause) nothing is matched"
    back = tracker.update([{"kind": "car", "ahead_m": 16.0, "right_m": 0.0}], t=4.0)
    assert back[0]["closing_mps"] is None, "time going backwards resets"
    tracker = Tracker()
    tracker.update([{"kind": "pedestrian", "ahead_m": 10.0, "right_m": 0.0}], t=0.0)
    two = tracker.update([{"kind": "pedestrian", "ahead_m": 9.8, "right_m": 0.0}, {"kind": "pedestrian", "ahead_m": 9.9, "right_m": 0.3}], t=0.25)
    assert [o["closing_mps"] for o in two] == [0.8, None], "one earlier object pairs with one current object"


def test_disagreeing_lights_read_unknown_and_the_biggest_central_light_governs():
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    frame[30:36, 150:154] = (254, 63, 37)  # red, big and central
    frame[40:42, 200:202] = (70, 250, 110)  # green, small, farther off centre
    dets = [_det("traffic_light", 146, 26, 160, 56, 0.6), _det("traffic_light", 198, 38, 204, 50, 0.9)]
    out = perceive(dets, frame, CAM)
    assert out["signal"]["state"] == "unknown", "two readable lights that disagree are not a green light"
    frame[40:42, 200:202] = (254, 63, 37)
    assert perceive(dets, frame, CAM)["signal"]["state"] == "red"


def test_without_cuda_the_detector_stays_off_unless_cpu_is_asked_for(monkeypatch):
    import jevpilot_vision.perception as P

    monkeypatch.setenv("SEMIF_PERCEPTION", "1")
    monkeypatch.delenv("SEMIF_PERCEPTION_DEVICE", raising=False)
    assert P.pick_device(cuda=False) is None
    assert P.pick_device(cuda=True) == "cuda"
    monkeypatch.setenv("SEMIF_PERCEPTION_DEVICE", "cpu")
    assert P.pick_device(cuda=False) == "cpu"
    monkeypatch.setenv("SEMIF_PERCEPTION", "0")
    assert P.pick_device(cuda=True) is None


def test_the_detector_loads_in_the_background_and_reports_loading_meanwhile(monkeypatch):
    import threading

    import jevpilot_vision.perception as P

    gate = threading.Event()

    class Slow(P.Detector):
        def _build(self, device):
            gate.wait(2)
            return "model"

    monkeypatch.setattr(P, "pick_device", lambda cuda=None: "cuda")
    d = Slow()
    assert d.detect_or_status(None) == ("loading", None), "the first frame does not wait for weights"
    gate.set()
    d._thread.join(2)
    assert d.status == "ready"


def test_the_narrow_camera_reads_the_light_when_the_wide_one_cannot():
    """#18: a narrow forward camera (HFOV 40 degrees, like a production car's) reads lights 30 m
    away that are a few pixels in the wide camera. Objects still come from the wide camera."""
    from PIL import Image

    import jevpilot_vision.perception as P

    wide = Image.new("RGB", (640, 360), (90, 90, 90))
    narrow_px = np.full((360, 640, 3), 90, dtype=np.uint8)
    narrow_px[120:128, 318:324] = (70, 250, 110)  # a green lamp
    narrow = Image.fromarray(narrow_px)
    v10 = 180 + P.CameraModel(640, 360).fx * 1.45 / 10.0

    class Fake(P.Detector):
        def detect_or_status(self, image):
            if image is narrow:
                return "ready", [{"kind": "traffic_light", "conf": 0.7, "box": [310, 110, 332, 150]}]
            return "ready", [{"kind": "car", "conf": 0.9, "box": [300, v10 - 25, 340, v10]}]

    out = P.Perception(Fake()).front(wide, narrow=narrow)
    assert out["signal"]["state"] == "green" and out["signal"]["camera"] == "narrow"
    assert [o["kind"] for o in out["objects"]] == ["car"]
    assert P.NARROW_HFOV_DEG == 40.0


def test_a_lit_lamp_in_a_dark_housing_is_found_even_when_the_detector_misses_the_head():
    """#18: the detector does not always box our square signal heads; a bright coloured blob
    inside a dark housing is a lamp. A sunlit warm hillside is not (nothing dark around it)."""
    from jevpilot_vision.perception import find_lamps

    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[:, :] = (143, 171, 208)  # sky
    img[60:110, 480:505] = (40, 52, 48)  # the housing
    img[88:96, 488:497] = (203, 234, 175)  # its lit (bottom, green) lamp
    img[200:260, 50:200] = (205, 182, 143)  # a bright sandy hillside
    lamps = find_lamps(img, P_CAM_NARROW)
    assert [lamp["state"] for lamp in lamps] == ["green"]
    out = perceive([], img, P_CAM_NARROW)
    assert out["signal"]["state"] == "green" and out["signal"]["source"] == "lamp"


P_CAM_NARROW = CameraModel(width=640, height=360, hfov_deg=40.0)



def test_review_m5_the_narrow_camera_does_not_overrule_a_readable_front_light():
    from PIL import Image

    import jevpilot_vision.perception as P

    front_px = np.full((360, 640, 3), 90, dtype=np.uint8)
    front_px[60:68, 318:324] = (254, 63, 37)  # red, readable in the wide camera
    narrow_px = np.full((360, 640, 3), 90, dtype=np.uint8)
    narrow_px[120:128, 318:324] = (70, 250, 110)  # the next junction's green, far away
    front, narrow = Image.fromarray(front_px), Image.fromarray(narrow_px)

    class Fake(P.Detector):
        def detect_or_status(self, image):
            box = [310, 50, 332, 90] if image is front else [310, 110, 332, 150]
            return "ready", [{"kind": "traffic_light", "conf": 0.7, "box": box}]

    out = P.Perception(Fake()).front(front, narrow=narrow)
    assert out["signal"]["state"] == "unknown" and out["signal"].get("conflict") == ["green", "red"]


def test_review_m6_a_frame_full_of_bright_colour_is_not_searched_pixel_by_pixel():
    import time as _time

    from jevpilot_vision.perception import find_lamps

    rng = np.random.default_rng(3)
    noise = rng.integers(0, 256, size=(360, 640, 3), dtype=np.uint8)
    t0 = _time.perf_counter()
    find_lamps(noise, CameraModel(width=640, height=360, hfov_deg=40.0))
    assert _time.perf_counter() - t0 < 0.05


def test_review_l3_a_moving_car_is_still_paired_after_a_slow_cycle():
    tracker = Tracker()
    tracker.update([{"kind": "car", "ahead_m": 30.0, "right_m": 0.0}], t=0.0)
    # we drove 10 m in a second towards a car that drove 4 m: it is 6 m nearer
    later = tracker.update([{"kind": "car", "ahead_m": 24.0, "right_m": 0.0}], t=1.0)
    assert later[0]["closing_mps"] == pytest.approx(6.0)



def test_review_h1_evidence_says_when_its_frame_was_grabbed(monkeypatch):
    import jevpilot_vision.http as http
    import jevpilot_vision.perception as perception
    import jevpilot_vision.vision as vision

    class Encoder:
        def infer_surround_b64(self, frames):
            assert "_captured_ms" not in frames
            return {"backend": "stub"}

    times = []

    class Fake:
        def front(self, image, t=None, narrow=None, yaw_rps=0.0):
            times.append(t)
            return {"backend": "fake", "objects": [], "signal": {"state": "unknown"}}

    monkeypatch.setattr(vision, "get_vision_encoder", lambda: Encoder())
    monkeypatch.setattr(perception, "get_perception", lambda: Fake())
    frames = {"front": _jpeg(64, 36), "right": _jpeg(32, 18), "_captured_ms": 1234.5}
    assert http._infer_latest_jpeg(frames)["captured_ms"] == 1234.5
    # Review #18: the tracker times closing speeds by when the frames were taken, not by when the
    # server got to them (upload and a busy slot add jitter that reads as a slower closing).
    assert times == [pytest.approx(1.2345)]


def test_review2_m4_the_narrow_camera_does_not_read_a_light_beyond_this_junction():
    """The narrow camera fills in only with a head near enough to govern the coming stop line. A
    2.05 m head (with its backplate) 12 px tall in the 40 degree camera is about 150 m away: the
    next junction (coast junctions are at least 100 m apart)."""
    from PIL import Image

    import jevpilot_vision.perception as P

    wide = Image.new("RGB", (640, 360), (90, 90, 90))
    narrow_px = np.full((360, 640, 3), 90, dtype=np.uint8)
    narrow_px[120:124, 319:322] = (70, 250, 110)
    narrow = Image.fromarray(narrow_px)

    class Fake(P.Detector):
        def __init__(self, box):
            self.box = box
            self.model_id = "fake"

        def detect_or_status(self, image):
            if image is narrow:
                return "ready", [{"kind": "traffic_light", "conf": 0.7, "box": self.box}]
            return "ready", []

    far = P.Perception(Fake([316, 116, 325, 128])).front(wide, narrow=narrow)
    near = P.Perception(Fake([310, 110, 332, 150])).front(wide, narrow=narrow)
    assert far["signal"]["state"] == "unknown"
    assert near["signal"]["state"] == "green" and near["signal"]["range_m"] == pytest.approx(45.1, abs=0.5)


def test_review3_the_next_junctions_head_100_m_away_is_not_read_by_either_path():
    """The heads are drawn larger than a bare housing (a 2.05 m backplate, 0.368 m lamps): sized by
    a bare housing, the next junction's near-side head about 100 m away read as 81 m and passed."""
    from PIL import Image

    import jevpilot_vision.perception as P

    wide = Image.new("RGB", (640, 360), (90, 90, 90))
    fx = P.CameraModel(640, 360, hfov_deg=P.NARROW_HFOV_DEG).fx

    def narrow_with_lamp(rows):
        px = np.full((360, 640, 3), 30, dtype=np.uint8)
        px[120:120 + rows, 319:322] = (70, 250, 110)
        return Image.fromarray(px)

    class Fake(P.Detector):
        def __init__(self, narrow, box):
            self.narrow, self.box, self.model_id = narrow, box, "fake"

        def detect_or_status(self, image):
            if image is self.narrow and self.box:
                return "ready", [{"kind": "traffic_light", "conf": 0.7, "box": self.box}]
            return "ready", []

    tall = fx * 2.05 / 100.0  # the backplate's box at 100 m
    boxed = narrow_with_lamp(3)
    far_box = P.Perception(Fake(boxed, [314, 120 - tall / 2, 326, 120 + tall / 2])).front(wide, narrow=boxed)
    assert far_box["signal"]["state"] == "unknown"
    for rows, readable in ((4, False), (8, True)):  # a lamp at about 81 m (rounded up from 100 m), then about 40 m
        lamp = narrow_with_lamp(rows)
        got = P.Perception(Fake(lamp, None)).front(wide, narrow=lamp)["signal"]
        assert (got["state"] == "green") is readable, (rows, got)
    assert P.NARROW_MAX_RANGE_M <= 75.0


# --- #75: optical flow B, from the tracked boxes ------------------------------------------------

def _box_seen(cam, ahead, right, width_m=1.9, height_m=1.5):
    """The detector's box of a car `ahead` m away and `right` m aside, from the pinhole model."""
    u = cam.cx + right * cam.fx / ahead
    v_bottom = cam.cy + cam.height_m * cam.fx / ahead
    half = width_m * cam.fx / ahead / 2
    return [u - half, v_bottom - height_m * cam.fx / ahead, u + half, v_bottom]


def _flow_track(path, cam=CAM, dt=0.25):
    from jevpilot_vision.perception import Tracker, box_flow_fields

    tracker = Tracker()
    out = None
    for k, (ahead, right) in enumerate(path):
        obj = {"kind": "car", "ahead_m": ahead, "right_m": right, **box_flow_fields(_box_seen(cam, ahead, right), cam)}
        out = tracker.update([obj], t=10.0 + k * dt)
    return out[0]


def test_issue75_a_steadily_closing_car_has_the_ttc_its_box_grows_by():
    # 30 m to 20 m at 5 m/s, a frame every 0.25 s: 4 s to contact at the last frame
    last = _flow_track([(30.0 - 5.0 * 0.25 * k, 0.0) for k in range(9)])
    assert last["ttc_s"] == pytest.approx(20.0 / 5.0, rel=0.1)


def test_issue75_a_car_holding_its_distance_or_pulling_away_has_no_ttc():
    assert _flow_track([(15.0, 0.0)] * 6)["ttc_s"] is None
    assert _flow_track([(15.0 + 0.5 * k, 0.0) for k in range(6)])["ttc_s"] is None
    first = _flow_track([(20.0, 0.0)])
    assert first["ttc_s"] is None and first["toward_center_mps"] is None, "one sighting has no motion"


def test_issue75_a_car_sliding_toward_our_line_is_seen_cutting_in():
    # 15 m ahead, from 3.5 m to the right toward the centre at 1 m/s
    right_side = _flow_track([(15.0, 3.5 - 0.25 * k) for k in range(6)])
    assert right_side["toward_center_mps"] == pytest.approx(1.0, abs=0.2)
    left_side = _flow_track([(15.0, -3.5 + 0.25 * k) for k in range(6)])
    assert left_side["toward_center_mps"] == pytest.approx(1.0, abs=0.2)
    steady = _flow_track([(15.0, 3.5)] * 6)
    assert abs(steady["toward_center_mps"]) < 0.1


def test_issue75_box_flow_survives_detector_jitter_without_a_false_ttc():
    import random

    from jevpilot_vision.perception import Tracker, box_flow_fields

    rnd = random.Random(7)
    tracker = Tracker()
    for k in range(12):
        box = [x + rnd.uniform(-1.0, 1.0) for x in _box_seen(CAM, 15.0, 0.0)]
        out = tracker.update([{"kind": "car", "ahead_m": 15.0, "right_m": 0.0, **box_flow_fields(box, CAM)}], t=k * 0.25)
    assert out[0]["ttc_s"] is None or out[0]["ttc_s"] > 8.0, out[0]


def test_issue75_a_walkers_ttc_comes_from_its_height_not_its_swinging_stride():
    from jevpilot_vision.perception import Tracker, box_flow_fields

    tracker = Tracker()
    for k in range(9):
        ahead = 12.0 - 2.0 * 0.25 * k  # 12 m to 8 m at 2 m/s: 4 s at the last frame
        x0, y0, x1, y1 = _box_seen(CAM, ahead, 0.0, width_m=0.5, height_m=1.7)
        stride = 1.0 + 0.35 * (-1) ** k  # legs apart, legs together
        mid, half = (x0 + x1) / 2, (x1 - x0) / 2 * stride
        box = [mid - half, y0, mid + half, y1]
        out = tracker.update([{"kind": "pedestrian", "ahead_m": ahead, "right_m": 0.0, **box_flow_fields(box, CAM, "pedestrian")}], t=k * 0.25)
    assert out[0]["ttc_s"] == pytest.approx(4.0, rel=0.1)


def test_issue75_the_ttc_evaluation_scores_flow_against_the_true_gap_over_closing():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
    import eval_perception as ev

    near = [{"type": "car", "ahead": 22.15, "right": 0.0, "closing": 5.0, "depth": 4.2},
            {"type": "car", "ahead": 15.0, "right": 0.0, "closing": -1.0, "depth": 4.2}]
    # gap to the near face: 22.15 - 2.1 - 0.15 = 19.9 m at 5 m/s
    assert ev.true_ttc(near[0]) == pytest.approx(3.98)
    assert ev.true_ttc(near[1]) is None, "a car pulling away has no TTC"
    objects = [{"kind": "car", "ahead_m": 22.0, "right_m": 0.1, "ttc_s": 4.4, "closing_mps": 4.0}]
    (want, flow, ranged), = ev.ttc_pairs(near, objects)
    assert (round(want, 2), flow, ranged) == (3.98, 4.4, 5.5)
    lines = ev.ttc_report([(2.0, 2.2, None), (4.0, None, 4.0)])
    assert lines[0].startswith("TTC box flow: given 1/2") and "missed 0/1" in lines[0]
    assert lines[1].startswith("TTC ranged: given 1/2") and "missed 1/1" in lines[1]
    assert lines[2].startswith("TTC both, worse: given 2/2") and "missed 0/1" in lines[2]


# --- #75 review: sideways motion with the gap changing and the car turning ----------------------

def _flow_track_yaw(path, yaw=0.0, cam=CAM, dt=0.25):
    from jevpilot_vision.perception import Tracker, box_flow_fields

    tracker = Tracker()
    out = None
    for k, (ahead, right) in enumerate(path):
        obj = {"kind": "car", "ahead_m": ahead, "right_m": right, **box_flow_fields(_box_seen(cam, ahead, right), cam)}
        out = tracker.update([obj], t=k * dt, yaw_rps=yaw)
    return out[0]


def test_issue75_review_a_car_pulling_away_in_the_next_lane_is_not_cutting_in():
    # left lane, 3.5 m aside, the gap growing at 5 m/s: its bearing shrinks, it does not move over
    away = _flow_track_yaw([(15.0 + 1.25 * k, -3.5) for k in range(7)])
    assert abs(away["toward_center_mps"]) < 0.2, away


def test_issue75_review_a_car_cutting_in_while_we_close_on_it_is_seen():
    # we close at 5 m/s while it moves 1 m/s toward our line from the right
    cut = _flow_track_yaw([(25.0 - 1.25 * k, 3.5 - 0.25 * k) for k in range(7)])
    assert cut["toward_center_mps"] == pytest.approx(1.0, abs=0.2), cut


def test_issue75_review_our_own_turning_is_not_read_as_the_others_moving():
    import math

    # a car standing 20 m ahead, 9 m to the left, while we turn left at 0.2 rad/s: in our frame it
    # sweeps right; the gyro takes that out
    yaw, path = -0.2, []
    for k in range(7):
        a = -yaw * 0.25 * k  # we have turned this far left
        x, y = 20.0, -9.0  # where it stood, in the frame we started in
        path.append((x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)))
    seen = _flow_track_yaw(path, yaw=yaw)
    assert abs(seen["toward_center_mps"]) < 0.3, seen
    blind = _flow_track_yaw(path, yaw=0.0)
    assert blind["toward_center_mps"] > 2.0, "without the gyro the turn reads as a cut-in"


def test_issue75_review_a_box_cut_by_the_frames_edge_gives_no_ttc():
    from jevpilot_vision.perception import Tracker, box_flow_fields

    tracker = Tracker()
    for k in range(8):
        # entering from the right edge: the visible part widens though the car keeps its distance
        box = [CAM.width - 10.0 - 4.0 * k, 90.0, float(CAM.width), 120.0]
        out = tracker.update([{"kind": "car", "ahead_m": 15.0, "right_m": 6.0, **box_flow_fields(box, CAM)}], t=k * 0.25)
    assert out[0]["scale_px"] is None and out[0]["ttc_s"] is None

