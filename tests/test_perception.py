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
    assert a[0]["closing_mps"] == 0.0
    assert b[0]["closing_mps"] == pytest.approx(4.0)
    c = tracker.update([{"kind": "pedestrian", "ahead_m": 18.0, "right_m": 0.3}], t=11.0)
    assert c[0]["closing_mps"] == 0.0, "a different kind is a different object"


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
        def front(self, image, t=None):
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
        def front(self, image, t=None):
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(perception, "get_perception", lambda: Broken())
    evidence = http._infer_latest_jpeg(frames)
    assert evidence["perception"]["backend"] == "none", "a failed detector is reported, never a clear road"
    assert evidence["perception"]["objects"] == [] and "error" in evidence["perception"]
