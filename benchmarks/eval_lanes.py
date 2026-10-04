"""Score the camera's lane estimate (perception.lane_from_frame) against the map's lane (#80).

Folders come from `benchmarks/capture_perception.py` (any mode): each frame carries the planner's
own lane offset and half width, from the map and the true pose. Ground truth is used here only, to
score. Every frame goes through one LaneTracker, as on the server; frames with a truth are scored.

Two truths. "map": the planner's lane (lane.offset_m, half_width_m). "painted": the lane as painted,
from the centre line to the edge line (rural roads, half - 0.35 m out) or the kerb (harbour and
festival streets, half out), from the road under the car (captures with "road"; expressways, two
lanes a side, are left out). They differ where the map's 6 m lane is wider than its paint (#60, #66):
the first measures what the planner would get, the second whether the camera reads the paint.
Reports, per folder and in all, how often the camera read a lane in that frame (conf >= --min-conf,
not a held one), the offset and width errors of those (median, P90), how often the offset was off
by more than 0.5 m, how many more frames only held an earlier lane, and the time per frame.

    python benchmarks/eval_lanes.py <folder> [<folder> ...] [--min-conf 0.3] [--overlay out.jpg]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout, not an installed copy

from jevpilot_vision.perception import LANE_FAR_M, LANE_NEAR_M, CameraModel, LaneTracker  # noqa: E402

URBAN = {"harbour", "festival"}  # semif-world/roads.js: kerbs, no edge lines
EDGE_INSET_M = 0.35  # semif-world/roads.js: rural edge lines at half - 0.35


def painted(road: dict | None) -> dict | None:
    """The painted lane under the car, in the planner's terms: offset right of its centre, width."""
    if not road or road.get("kind") == "expressway" or road.get("width") is None or road.get("lateral_m") is None:
        return None
    edge = road["width"] / 2 - (0 if road["kind"] in URBAN else EDGE_INSET_M)
    if not 0 < road["lateral_m"] < edge:
        return None  # not in the right-hand lane (overtaking, a junction)
    return {"offset_m": road["lateral_m"] - edge / 2, "width_m": edge, "kind": road["kind"]}


def pick(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def summary(name: str, rows: list[dict]) -> str:
    seen = [r for r in rows if r["got"]]
    held = sum(1 for r in rows if r.get("held"))
    off = [abs(r["offset"]) for r in seen]
    wid = [abs(r["width"]) for r in seen]
    far = sum(1 for e in off if e > 0.5)
    return (f"{name}: lane read {len(seen)}/{len(rows)} (+{held} held); offset |error| median {pick(off, 0.5):.2f} m P90 {pick(off, 0.9):.2f} m, "
            f">0.5 m {far}/{len(seen)}; width |error| median {pick(wid, 0.5):.2f} m P90 {pick(wid, 0.9):.2f} m")


def overlay(path: Path, lane: dict, camera: CameraModel) -> Image.Image:
    """The frame with the two fitted lines drawn back onto it (green), for the PR."""
    img = Image.open(path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for key in ("left", "right"):
        a, b, c = lane[key]
        pts = []
        for ahead in np.arange(LANE_NEAR_M, LANE_FAR_M + 0.1, 0.5):
            right = a + b * ahead + c * ahead * ahead
            pts.append((camera.cx + right * camera.fx / ahead, camera.cy + camera.height_m * camera.fx / ahead))
        draw.line(pts, fill=(60, 230, 120), width=3)
    draw.text((8, 8), f"offset {lane['offset_m']:+.2f} m  width {lane['width_m']:.2f} m  conf {lane['conf']:.2f}", fill=(255, 255, 255))
    return img


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--min-conf", type=float, default=0.3)
    ap.add_argument("--truth", choices=["map", "painted"], default="map")
    ap.add_argument("--overlay", default="", help="save a sheet of frames with the fitted lines drawn")
    args = ap.parse_args()
    every, ms, shown = [], [], []
    for folder in args.folders:
        rows = []
        lanes = LaneTracker()  # one drive, as the server sees it
        for row in json.loads(Path(folder, "truth.json").read_text(encoding="utf-8")):
            image = np.asarray(Image.open(Path(folder, row["file"])).convert("RGB"))
            camera = CameraModel(width=image.shape[1], height=image.shape[0])
            t0 = time.perf_counter()
            lane = lanes.update(image, camera, row.get("t", 0.0))
            ms.append((time.perf_counter() - t0) * 1000.0)
            if args.truth == "painted":
                truth = painted(row.get("road"))
                if not truth:
                    continue
                truth = {"offset_m": truth["offset_m"], "half_width_m": truth["width_m"] / 2}
            else:
                truth = row.get("lane")
                if not truth or truth.get("half_width_m") is None:
                    continue
            fresh = lane.get("held_s", 0.0) == 0.0
            got = lane["conf"] >= args.min_conf and fresh
            rows.append({"held": lane["conf"] > 0 and not fresh, "got": got, "offset": (lane.get("offset_m", 0) - truth["offset_m"]) if got else None,
                         "width": (lane.get("width_m", 0) - 2 * truth["half_width_m"]) if got else None})
            if got and len(shown) < 6 and len(rows) % 40 == 0:
                shown.append(overlay(Path(folder, row["file"]), lane, camera))
        print(summary(Path(folder).name, rows))
        every += rows
    print(summary("all", every))
    ms.sort()
    if ms:
        print(f"per frame (CPU): p50 {ms[len(ms) // 2]:.1f} ms, p95 {ms[int(0.95 * (len(ms) - 1))]:.1f} ms over {len(ms)} frames")
    if args.overlay and shown:
        w, h = shown[0].size
        sheet = Image.new("RGB", (w * 2, h * ((len(shown) + 1) // 2)), (0, 0, 0))
        for i, img in enumerate(shown):
            sheet.paste(img, ((i % 2) * w, (i // 2) * h))
        sheet.save(args.overlay, quality=88)


if __name__ == "__main__":
    main()
