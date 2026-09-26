"""Phase 6 report gate: CUDA rows, clean rate, and JSON checksum."""

import hashlib
import json

from benchmarks.benchmark_jevpilot_hierarchical import ALL_SCENARIOS
from benchmarks.driving_quality import driving_quality
from benchmarks.sdi import scenario_seed


def _episodes(drop_last: bool = False):
    rows = []
    for scenario in ALL_SCENARIOS:
        for vision_mode in ("off", "siglip"):
            rows.append(
                {
                    "scenario": scenario,
                    "vision_mode": vision_mode,
                    "seed": scenario_seed(42, scenario, 0),
                    "completed": True,
                    "collision": False,
                    "off_track": False,
                    "red_light_violation": False,
                    "pedestrian_casualty": False,
                }
            )
    if drop_last:
        rows.pop()
    return rows


def _report(episodes):
    return {
        "device": "cuda",
        "mock": False,
        "model": "Qwen/Qwen2.5-3B-Instruct",
        "seed": 42,
        "mode": "flat",
        "raw_mode": False,
        "world": "pinhole-scenario-camera",
        "episodes": episodes,
        "clean_completion_rate": driving_quality(episodes)["clean_completion_rate"],
    }


def test_phase6_refuses_mock_and_writes_nothing(tmp_path):
    from benchmarks.phase6_vision import write_phase6_report

    path = tmp_path / "phase6-jevpilot-vision-cuda.json"
    report = _report(_episodes())
    report["mock"] = True
    assert write_phase6_report(path, report) is False
    assert not path.exists()
    assert not path.with_name(path.name + ".SHA256SUMS").exists()


def test_phase6_writes_json_sha256_and_clean_rate(tmp_path):
    from benchmarks.phase6_vision import write_phase6_report

    path = tmp_path / "phase6-jevpilot-vision-cuda.json"
    episodes = _episodes()
    report = _report(episodes)
    assert write_phase6_report(path, report) is True
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["clean_completion_rate"] == 1.0
    assert path.name == "phase6-jevpilot-vision-cuda.json"
    payload = path.read_bytes()
    assert payload == json.dumps(report, indent=2).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    sums = path.with_name(path.name + ".SHA256SUMS")
    assert sums.read_text(encoding="utf-8") == f"{digest}  {path.name}\n"


def test_phase6_refuses_when_a_row_is_missing(tmp_path):
    from benchmarks.phase6_vision import write_phase6_report

    path = tmp_path / "phase6-jevpilot-vision-cuda.json"
    report = _report(_episodes(drop_last=True))
    assert write_phase6_report(path, report) is False
    assert not path.exists()
    assert not path.with_name(path.name + ".SHA256SUMS").exists()
