"""Score the traffic-light readers on captured frames against the simulator's true light (#76).

Folders come from `benchmarks/capture_perception.py --mode privileged`: each frame carries the
true light of the junction ahead and the distance to its stop line. Ground truth is used here only,
to score. For every frame 8-60 m before a signalled line (the near head is in the front camera's
view from about 6 m out), the governing head the detector boxes is read by the hue threshold, by
its three lamp cells, and by the two together (`signal_read`); the report gives accuracy by
distance and a confusion matrix. Thresholds are picked on tuning-seed captures only (--sweep).

    python benchmarks/eval_lights.py <folder> [<folder> ...] [--sweep]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout, not an installed copy

from jevpilot_vision.perception import CameraModel, Detector, perceive, read_lamp_cells  # noqa: E402

STATES = ("red", "amber", "green")
NEAR_M, FAR_M = 8.0, 60.0
BANDS = ((NEAR_M, 20.0), (20.0, 40.0), (40.0, FAR_M))


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """{truth: {read: count}} over STATES plus unknown."""
    out: dict[str, dict[str, int]] = {s: {} for s in STATES}
    for want, got in pairs:
        row = out.setdefault(want, {})
        row[got] = row.get(got, 0) + 1
    return out


def report(name: str, pairs: list[tuple[str, str]]) -> list[str]:
    n = len(pairs)
    right = sum(1 for want, got in pairs if want == got)
    wrong = sum(1 for want, got in pairs if got in STATES and got != want)
    lines = [f"{name}: correct {right}/{n} ({100 * right / max(n, 1):.0f}%), wrong colour {wrong}/{n}, unknown {n - right - wrong}/{n}"]
    for want, row in confusion(pairs).items():
        lines.append(f"  true {want:5}: " + ", ".join(f"{got} {row[got]}" for got in sorted(row)))
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--sweep", action="store_true", help="also score other lamp-cell thresholds (for picking them)")
    args = ap.parse_args()
    detector = Detector()
    if detector.wait() != "ready":
        raise SystemExit("perception: no detector (needs CUDA, or SEMIF_PERCEPTION_DEVICE=cpu)")
    crops, truth, dists, heights, hue, cells, both, read_ms = [], [], [], [], [], [], [], []
    for folder in args.folders:
        rows = json.loads(Path(folder, "truth.json").read_text(encoding="utf-8"))
        for row in rows:
            light = row.get("light") or {}
            want, dist = light.get("signal"), light.get("distance_to_line_m")
            if want not in STATES or dist is None or not (NEAR_M <= dist <= FAR_M):
                continue
            image = Image.open(Path(folder, row["file"])).convert("RGB")
            pixels = np.asarray(image)
            camera = CameraModel(width=image.width, height=image.height)
            dets = detector.detect(image) or []
            t0 = time.perf_counter()
            read = perceive([d for d in dets if d["kind"] == "traffic_light"], pixels, camera)["signal_read"]
            read_ms.append((time.perf_counter() - t0) * 1000.0)
            box = read.get("box") if read.get("cells") is not None else None
            h, w = pixels.shape[:2]  # clamped as the live reader clamps
            crops.append(pixels[max(0, int(box[1])) : min(h, int(np.ceil(box[3]))), max(0, int(box[0])) : min(w, int(np.ceil(box[2])))] if box else None)
            truth.append(want)
            dists.append(dist)
            heights.append(round(box[3] - box[1]) if box else None)
            hue.append(read.get("hue") or "unknown")
            cells.append(read.get("cells") or "unknown")
            both.append(read["state"])
    print(f"{len(truth)} frames {NEAR_M:.0f}-{FAR_M:.0f} m before a signalled line, "
          f"{sum(c is not None for c in crops)} with a boxed head; true: " + ", ".join(f"{s} {truth.count(s)}" for s in STATES))
    for name, reads in (("hue threshold", hue), ("lamp cells", cells), ("both (signal_read)", both)):
        for line in report(name, list(zip(truth, reads))):
            print(line)
    for lo, hi in BANDS:
        idx = [i for i, d in enumerate(dists) if lo <= d < hi or (hi == FAR_M and d == hi)]
        tall = sorted(heights[i] for i in idx if heights[i] is not None)
        boxed = sum(1 for i in idx if crops[i] is not None)
        cell = lambda xs: f"{sum(1 for i in idx if xs[i] == truth[i])}/{len(idx)} ({sum(1 for i in idx if xs[i] in STATES and xs[i] != truth[i])} wrong)"
        print(f"{lo:.0f}-{hi:.0f} m: {len(idx)} frames, {boxed} boxed (head {tall[len(tall) // 2] if tall else '-'} px tall): "
              f"hue {cell(hue)}, cells {cell(cells)}, both {cell(both)}")
    if args.sweep:
        for contrast in (1.15, 1.3, 1.5, 2.0):
            for luma in (0.15, 0.25, 0.4):
                reads = [read_lamp_cells(c, contrast, luma)[0] if c is not None and c.size else "unknown" for c in crops]
                right = sum(1 for w, g in zip(truth, reads) if w == g)
                wrong = sum(1 for w, g in zip(truth, reads) if g in STATES and g != w)
                print(f"sweep contrast {contrast} luma {luma}: correct {right}/{len(truth)}, wrong {wrong}")
    read_ms.sort()
    if read_ms:
        print(f"reading the light (both readers, per frame): p50 {read_ms[len(read_ms) // 2]:.2f} ms, "
              f"p95 {read_ms[int(0.95 * (len(read_ms) - 1))]:.2f} ms over {len(read_ms)} frames (CPU)")


if __name__ == "__main__":
    main()
