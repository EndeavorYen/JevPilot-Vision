"""Phase 6 offline report: ten scenarios, vision off and SigLIP, CUDA gate.

The official two-lap web-city file stays in ``web_city_vision``. This writer
refuses mock, non-CUDA, and any row set other than the twenty contracted rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.benchmark_jevpilot_hierarchical import ALL_SCENARIOS, run_jevpilot2_episode
from benchmarks.driving_quality import driving_quality
from benchmarks.sdi import scenario_seed
from demo.server import DecisionEngine

PHASE6_REPORT = ROOT / "results" / "phase6-jevpilot-vision-cuda.json"
WORLD = "pinhole-scenario-camera"


def _rows_match(episodes: List[Dict[str, Any]]) -> bool:
    if len(episodes) != 20 or len(ALL_SCENARIOS) != 10:
        return False
    expected = []
    for scenario in ALL_SCENARIOS:
        for vision_mode in ("off", "siglip"):
            expected.append((scenario, vision_mode, scenario_seed(42, scenario, 0)))
    actual = []
    for episode in episodes:
        if not isinstance(episode, dict):
            return False
        actual.append(
            (
                episode.get("scenario"),
                episode.get("vision_mode"),
                episode.get("seed"),
            )
        )
    return actual == expected


def write_phase6_report(path: Path, report: dict) -> bool:
    path = Path(path)
    episodes = report.get("episodes")
    if not isinstance(episodes, list):
        return False
    model = report.get("model")
    rate = report.get("clean_completion_rate")
    official = (
        report.get("device") == "cuda"
        and report.get("mock") is False
        and isinstance(model, str)
        and model not in ("", "MockDecisionEngine")
        and report.get("seed") == 42
        and report.get("mode") == "flat"
        and report.get("raw_mode") is False
        and report.get("world") == WORLD
        and _rows_match(episodes)
        and rate == driving_quality(episodes)["clean_completion_rate"]
    )
    if not official:
        return False
    payload = json.dumps(report, indent=2).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    sums = Path(str(path) + ".SHA256SUMS")
    sums.write_bytes(f"{digest}  {path.name}\n".encode("utf-8"))
    return True


def build_report(engine: DecisionEngine, seed: int = 42) -> Dict[str, Any]:
    engine.sync_scorer_device()
    episodes = []
    for scenario in ALL_SCENARIOS:
        for vision_mode in ("off", "siglip"):
            episodes.append(
                run_jevpilot2_episode(
                    engine,
                    "flat",
                    scenario,
                    scenario_seed(seed, scenario, 0),
                    raw_mode=False,
                    vision_mode=vision_mode,
                )
            )
    return {
        "benchmark": "JevPilot phase 6 pinhole SigLIP",
        "world": WORLD,
        "seed": int(seed),
        "mode": "flat",
        "raw_mode": False,
        "mock": bool(engine.use_mock),
        "device": engine.device,
        "model": engine.model_name,
        "episodes": episodes,
        "clean_completion_rate": driving_quality(episodes)["clean_completion_rate"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(PHASE6_REPORT))
    args = parser.parse_args()
    engine = DecisionEngine(use_mock=False)
    report = build_report(engine, seed=args.seed)
    written = write_phase6_report(Path(args.output), report)
    print(json.dumps({
        "output": str(args.output) if written else None,
        "written": written,
        "device": report["device"],
        "model": report["model"],
        "clean_completion_rate": report["clean_completion_rate"],
    }, indent=2))
    if not written:
        sys.exit(1)


if __name__ == "__main__":
    main()
