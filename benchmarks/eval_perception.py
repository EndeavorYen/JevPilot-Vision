"""Score jevpilot_vision.perception on captured onboard frames against simulator ground truth (#18).

Each folder holds front-camera JPEGs and a truth.json written at the instant each frame was
grabbed: [{"file": "f000.jpg", "near": [{"type", "ahead", "right", "signal"?}, ...]}, ...]
(ego frame: ahead and right in metres). Capture them from the page by wrapping the PIP canvas's
toDataURL and reading window.SEMIF_SIM at that moment.

Folders from benchmarks/capture_perception.py also carry each frame's time and every object's
true closing speed: their frames run through one tracker in order, and the box flow's TTC (#75)
is scored against the true TTC (gap to the object's near face over the closing speed), next to
the TTC the ranged closing speed gives. Ground truth is used here only, to score.

usage: python benchmarks/eval_perception.py <folder> [<folder> ...]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image

# Score this checkout's perception, not an installed copy (a worktree's sys.path starts at benchmarks/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jevpilot_vision.perception import Detector, Perception, Tracker  # noqa: E402
from jevpilot_vision.vision_mode import CAMERA_AHEAD_M  # noqa: E402

TTC_KINDS = ("car", "motorcycle", "pedestrian")


def true_ttc(n: dict) -> float | None:
    """Seconds until the camera reaches the object's near face at the current closing speed."""
    gap = n["ahead"] - n.get("depth", 0.0) / 2.0 - CAMERA_AHEAD_M
    closing = n.get("closing")
    if closing is None or closing <= 0.3 or gap <= 0.5:
        return None
    return gap / closing


def ttc_pairs(near: list[dict], objects: list[dict]) -> list[tuple[float, float | None, float | None]]:
    """(true TTC, box-flow TTC, ranged TTC) for each closing object in view within 40 m and 20 s
    that the detector found (matched as in the recall count)."""
    out = []
    for n in near:
        want = true_ttc(n)
        if n["type"] not in TTC_KINDS or want is None or want > 20.0 or n["ahead"] > 40 or abs(n["right"]) > n["ahead"] * 1.1:
            continue
        hits = [o for o in objects if o["kind"] == n["type"] and math.hypot(o["ahead_m"] - n["ahead"], o["right_m"] - n["right"]) <= max(2.5, 0.2 * n["ahead"])]
        if not hits:
            continue
        o = min(hits, key=lambda o: abs(o["ahead_m"] - n["ahead"]))
        ranged = o["ahead_m"] / o["closing_mps"] if (o.get("closing_mps") or 0) > 0.3 else None
        out.append((want, o.get("ttc_s"), ranged))
    return out


def ttc_report(pairs: list[tuple[float, float | None, float | None]]) -> list[str]:
    """Per estimator: how often it gave a TTC, its relative error, and how often it missed a
    close one (true TTC under 3 s, estimate missing or over 6 s). "both, worse" is what the new
    Vision's sweep uses: the shorter of the two."""
    lines = []
    both = lambda p: min(v for v in (p[1], p[2]) if v is not None) if p[1] is not None or p[2] is not None else None
    pairs = [(*p[:3], both(p)) for p in pairs]
    for name, k in (("box flow", 1), ("ranged", 2), ("both, worse", 3)):
        given = [(p[0], p[k]) for p in pairs if p[k] is not None]
        rel = sorted(abs(got - want) / want for want, got in given)
        signed = sorted((got - want) / want for want, got in given)
        close = [p for p in pairs if p[0] < 3.0]
        missed = sum(1 for p in close if p[k] is None or p[k] > 6.0)
        pick = lambda xs, q: xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")
        lines.append(f"TTC {name}: given {len(given)}/{len(pairs)}, |error| median {100 * pick(rel, 0.5):.0f}% "
                     f"P90 {100 * pick(rel, 0.9):.0f}%, bias {100 * pick(signed, 0.5):+.0f}%, "
                     f"missed {missed}/{len(close)} with true TTC < 3 s")
    return lines


def main(folders: list[str]) -> None:
    perception = Perception(Detector())
    if perception.detector.wait() != "ready":
        raise SystemExit("perception: no detector (needs CUDA, or SEMIF_PERCEPTION_DEVICE=cpu)")
    bands = {"<=15m": [0, 0, 0], "15-25m": [0, 0, 0], "25-50m": [0, 0, 0]}
    found: dict[str, list] = {}
    latency = []
    pairs: list[tuple[float, float | None, float | None]] = []
    for folder in folders:
        with open(f"{folder}/truth.json", encoding="utf-8") as fh:
            rows = json.load(fh)
        perception.tracker = Tracker()  # one drive, one track history
        for row in rows:
            out = perception.front(Image.open(f"{folder}/{row['file']}"), t=row.get("t"), yaw_rps=row.get("yaw_rps") or 0.0)
            if "t" in row:
                pairs += ttc_pairs(row["near"], out["objects"])
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
    if pairs:
        for line in ttc_report(pairs):
            print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
