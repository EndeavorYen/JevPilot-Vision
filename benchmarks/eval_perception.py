"""Score jevpilot_vision.perception on captured onboard frames against simulator ground truth (#18).

Each folder holds front-camera JPEGs and a truth.json written at the instant each frame was
grabbed: [{"file": "f000.jpg", "near": [{"type", "ahead", "right", "signal"?}, ...]}, ...]
(ego frame: ahead and right in metres). Capture them from the page by wrapping the PIP canvas's
toDataURL and reading window.SEMIF_SIM at that moment.

usage: python benchmarks/eval_perception.py <folder> [<folder> ...]
"""

from __future__ import annotations

import json
import math
import sys

from PIL import Image

from jevpilot_vision.perception import Detector, Perception


def main(folders: list[str]) -> None:
    perception = Perception(Detector())
    if perception.detector.wait() != "ready":
        raise SystemExit("perception: no detector (needs CUDA, or SEMIF_PERCEPTION_DEVICE=cpu)")
    bands = {"<=15m": [0, 0, 0], "15-25m": [0, 0, 0], "25-50m": [0, 0, 0]}
    found: dict[str, list] = {}
    latency = []
    for folder in folders:
        with open(f"{folder}/truth.json", encoding="utf-8") as fh:
            rows = json.load(fh)
        for row in rows:
            out = perception.front(Image.open(f"{folder}/{row['file']}"))
            latency.append(out["latency_ms"])
            lights = [n for n in row["near"] if n["type"] == "traffic_light" and 3 < n["ahead"] < 50 and abs(n["right"]) < 8]
            if lights:
                want = min(lights, key=lambda n: abs(n["right"]))
                band = "<=15m" if want["ahead"] <= 15 else "15-25m" if want["ahead"] <= 25 else "25-50m"
                got = out["signal"]["state"]
                bands[band][1] += 1
                if got == want["signal"]:
                    bands[band][0] += 1
                elif got != "unknown":
                    bands[band][2] += 1
            for n in row["near"]:
                # In view (100 degree camera) and within 40 m.
                if n["type"] not in ("pedestrian", "car") or n["ahead"] > 40 or abs(n["right"]) > n["ahead"] * 1.1:
                    continue
                stat = found.setdefault(n["type"], [0, 0, []])
                stat[1] += 1
                hits = [
                    o for o in out["objects"]
                    if o["kind"] == n["type"] and math.hypot(o["ahead_m"] - n["ahead"], o["right_m"] - n["right"]) <= max(2.5, 0.2 * n["ahead"])
                ]
                if hits:
                    best = min(hits, key=lambda o: abs(o["ahead_m"] - n["ahead"]))
                    stat[0] += 1
                    stat[2].append(abs(best["ahead_m"] - n["ahead"]) / n["ahead"])
    for kind, (hit, total, errors) in found.items():
        median = sorted(errors)[len(errors) // 2] if errors else float("nan")
        print(f"{kind}: recall {hit}/{total} = {100 * hit / max(total, 1):.0f}%, median range error {100 * median:.0f}%")
    for band, (ok, total, wrong) in bands.items():
        print(f"signal {band}: correct {ok}/{total}, wrong {wrong}")
    print(f"latency median {sorted(latency)[len(latency) // 2]:.1f} ms over {len(latency)} frames")


if __name__ == "__main__":
    main(sys.argv[1:])
