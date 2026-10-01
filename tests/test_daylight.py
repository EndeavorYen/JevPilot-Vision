"""Solmare Coast day cycle (jevpilot_vision/web/semif-world/daylight.js).

The light model is plain functions of the hour, so node evaluates it directly. The onboard camera
reads lights, construction, warning lights and people by colour; every hour of the cycle must keep
the coast's colours out of those masks, as the fixed daylight did.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest

from test_scenery import FACTORS, _colours, _hits_camera_mask

REPO = Path(__file__).resolve().parents[1]
RENDER = REPO / "jevpilot_vision" / "web" / "semif-world"


def _day(body: str):
    script = (
        "import { pathToFileURL } from 'url';"
        "const D = await import(pathToFileURL(process.argv[1] + '/daylight.js'));"
        "const K = await import(pathToFileURL(process.argv[1] + '/kit.js'));"
        "const out = (v) => process.stdout.write(JSON.stringify(v));" + body
    )
    proc = subprocess.run(["node", "--input-type=module", "-e", script, str(RENDER)], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


HOURS = [6.25 + 0.25 * i for i in range(55)]  # 06:15 .. 19:45


@pytest.fixture(scope="module")
def day() -> dict:
    return _day(
        f"const hours = {json.dumps(HOURS)};"
        "out({ day: D.DAY, presets: D.PRESETS, palette: K.PALETTE,"
        "  at: hours.map((h) => ({ h, sun: D.sunDirection(h), light: D.lightAt(h), tint: D.tint(h) })) });"
    )


def test_the_sun_rises_in_the_east_crosses_the_south_and_sets_in_the_west(day):
    at = {round(a["h"], 2): a for a in day["at"]}
    dawn, noon, dusk = at[6.25]["sun"], at[13.0]["sun"], at[19.75]["sun"]
    assert dawn["x"] > 0.9 and dusk["x"] < -0.9, "east is +x, west is -x"
    assert noon["z"] > 0.3 and abs(noon["x"]) < 0.05, "at noon the sun stands over the sea (+z, south)"
    elevations = [a["sun"]["y"] for a in day["at"]]
    assert min(elevations) > 0.04, "the cycle never shows a set sun"
    assert max(elevations) == pytest.approx(at[13.0]["sun"]["y"], abs=0.01)
    for a in day["at"]:
        assert math.hypot(a["sun"]["x"], a["sun"]["y"], a["sun"]["z"]) == pytest.approx(1)


def test_the_clock_loops_through_the_day_in_fifteen_minutes():
    got = _day(
        "const D0 = D.DAY; let h = D0.start, t = 0;"
        "while (t < 899) { h = D.advance(h, 1); t += 1; }"
        "out({ day: D0, nearEnd: h, wrapped: D.advance(D0.end - 0.001, 1), fixed: D.parseTime('17:30'), bad: [D.parseTime('25:00'), D.parseTime('nope'), D.parseTime(null)] });"
    )
    assert got["day"]["start"] == pytest.approx(6.25) and got["day"]["end"] == pytest.approx(19.75)
    assert got["day"]["start"] < got["day"]["default"] < got["day"]["end"]
    assert got["nearEnd"] == pytest.approx(got["day"]["end"], abs=0.02)
    assert got["day"]["start"] <= got["wrapped"] < got["day"]["start"] + 0.02
    assert got["fixed"] == pytest.approx(17.5)
    assert got["bad"] == [None, None, None]


def test_presets_cover_dawn_to_dusk(day):
    hours = [h for _, h in day["presets"]]
    assert hours == sorted(hours)
    assert day["day"]["start"] <= hours[0] < 8 and 18.5 < hours[-1] <= day["day"]["end"]


def test_every_hour_keeps_the_lit_palette_out_of_the_camera_masks(day):
    offenders = []
    palette = [(n, h) for n, h in _colours(day["palette"]) if not n.startswith("minimap")]
    for a in day["at"]:
        tint = a["tint"]
        for name, hex_colour in palette:
            n = int(hex_colour[1:], 16)
            base = ((n >> 16) & 255, (n >> 8) & 255, n & 255)
            for factor in FACTORS:
                r, g, b = (min(255, round(c * t * factor)) for c, t in zip(base, tint))
                hits = _hits_camera_mask(r, g, b)
                if hits:
                    offenders.append((a["h"], name, hex_colour, factor, hits))
    assert offenders[:10] == []


def test_every_hour_keeps_the_sky_and_fog_out_of_the_camera_masks(day):
    offenders = []
    for a in day["at"]:
        for key in ("zenith", "horizon", "fog", "glow"):
            n = int(a["light"][key][1:], 16)
            base = ((n >> 16) & 255, (n >> 8) & 255, n & 255)
            for factor in (0.85, 1.0, 1.15):
                r, g, b = (min(255, round(c * factor)) for c in base)
                hits = _hits_camera_mask(r, g, b)
                if hits:
                    offenders.append((a["h"], key, a["light"][key], factor, hits))
    assert offenders[:10] == []


def test_exposure_keeps_every_hour_about_as_bright_as_noon(day):
    """Shadows stay above the pedestrian mask's darkness only if dawn and dusk are not much dimmer
    than noon after exposure; the masks were tuned on daylight."""
    for a in day["at"]:
        r, g, b = a["tint"]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        assert 0.9 <= luma <= 1.15, (a["h"], a["tint"])


def test_low_sun_is_warm_and_high_sun_is_near_white(day):
    at = {round(a["h"], 2): a["tint"] for a in day["at"]}
    golden, noon = at[19.0], at[13.0]
    assert golden[0] > golden[2] + 0.12, "golden hour is warm"
    assert abs(noon[0] - noon[2]) < 0.06, "noon is neutral"
