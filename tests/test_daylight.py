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
                hits = [m for m in _hits_camera_mask(r, g, b) if not (name == "people.silhouette" and m == "pedestrian")]
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
    # Mildly: the bluish sky light makes up for a low sun, and the strong warm look is the main
    # view's grade (gradeAt), which the cameras never see.
    assert golden[0] > golden[2] + 0.06, "golden hour is warm"
    assert abs(noon[0] - noon[2]) < 0.06, "noon is neutral"


def test_the_main_view_grade_is_neutral_at_noon_and_warm_and_moody_at_dusk():
    got = _day("out([13, 17.75, 19.5, 6.5].map((h) => D.gradeAt(h)));")
    noon, golden, dusk, dawn = got
    assert noon["exposure"] == pytest.approx(1.0) and noon["warmth"] == pytest.approx(0, abs=0.02)
    for g in (golden, dusk, dawn):
        assert g["warmth"] > 0.05 and g["contrast"] >= noon["contrast"]
    assert dusk["exposure"] < golden["exposure"] < noon["exposure"] + 1e-9
    for g in got:
        assert 0.75 <= g["exposure"] <= 1.05 and 0.9 <= g["saturation"] <= 1.35 and 0 <= g["vignette"] <= 0.5


# The onboard cameras render to a target semif-layer.js flags as XR, which the bundle's three.js
# tone-maps like the screen: ACES Filmic at toneMappingExposure. This is three's own fit.
def _aces(rgb, exposure):
    v = [c * exposure / 0.6 for c in rgb]
    cols_in = ((0.59719, 0.07600, 0.02840), (0.35458, 0.90834, 0.13383), (0.04823, 0.01566, 0.83777))
    v = [sum(cols_in[k][i] * v[k] for k in range(3)) for i in range(3)]
    v = [(x * (x + 0.0245786) - 0.000090537) / (x * (0.983729 * x + 0.4329510) + 0.238081) for x in v]
    cols_out = ((1.60475, -0.10208, -0.00327), (-0.53108, 1.10813, -0.07276), (-0.07367, -0.00605, 1.07602))
    v = [sum(cols_out[k][i] * v[k] for k in range(3)) for i in range(3)]
    return [min(1.0, max(0.0, x)) for x in v]


def _to_linear(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c):
    c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return round(max(0.0, min(1.0, c)) * 255)


def _rgb(hex_colour):
    n = int(hex_colour[1:], 16)
    return ((n >> 16) & 255, (n >> 8) & 255, n & 255)


def test_onboard_pixels_stay_out_of_the_masks_after_lighting_and_aces(day):
    """Surface colour x Lambert x (sun at incidence cos + sky light), through ACES and sRGB, for
    every hour: a wall facing a low, boosted sun is the brightest and warmest case."""
    # The sea and the sky have their own shaders. Shade and grazing light are checked for the colour
    # masks only: without the bundle's environment light they are darker than the screen ever is,
    # and the old maps' shadows read as dark "pedestrian" pixels too.
    palette = [(n, h) for n, h in _colours(day["palette"]) if not n.startswith(("minimap", "sea"))]
    offenders = []
    for a in day["at"]:
        light = a["light"]
        sun = [_to_linear(c) for c in _rgb(light["sun"])]
        sky = [_to_linear(c) for c in _rgb(light["hemiSky"])]
        for cosine in (1.0, 0.6, 0.3, 0.0):
            irradiance = [light["sunIntensity"] * cosine * s + light["hemiIntensity"] * k for s, k in zip(sun, sky)]
            for name, hex_colour in palette:
                albedo = [_to_linear(c) for c in _rgb(hex_colour)]
                radiance = [al * e / math.pi for al, e in zip(albedo, irradiance)]
                r, g, b = (_to_srgb(c) for c in _aces(radiance, light["exposure"]))
                hits = [m for m in _hits_camera_mask(r, g, b) if (cosine >= 0.6 or m != "pedestrian") and not (name == "people.silhouette" and m == "pedestrian")]
                if hits:
                    offenders.append((a["h"], cosine, name, hex_colour, (r, g, b), hits))
    assert offenders[:10] == []


def test_derived_and_glowing_colours_stay_out_of_the_masks_after_lighting_and_aces(day):
    """The facade shades (shade() of walls, shutters, doors) and the festival screen, which adds its
    own glow on top of the light, through the same lighting and ACES as the palette above."""
    extra = _day(
        "const B = await import(pathToFileURL(process.argv[1] + '/buildings.js'));"
        "const F = await import(pathToFileURL(process.argv[1] + '/festival.js'));"
        "out({ shades: B.derivedColours(), screen: F.SCREEN });"
    )
    surfaces = [(f"shade {h}", h, 0.0) for h in extra["shades"]]
    surfaces += [(f"screen {h}", h, extra["screen"]["emissive"]) for h in extra["screen"]["colours"]]
    assert len(extra["shades"]) >= 6 and extra["screen"]["colours"]
    offenders = []
    for a in day["at"]:
        light = a["light"]
        sun = [_to_linear(c) for c in _rgb(light["sun"])]
        sky = [_to_linear(c) for c in _rgb(light["hemiSky"])]
        for cosine in (1.0, 0.6, 0.3, 0.0):
            irradiance = [light["sunIntensity"] * cosine * s + light["hemiIntensity"] * k for s, k in zip(sun, sky)]
            for name, hex_colour, glow in surfaces:
                albedo = [_to_linear(c) for c in _rgb(hex_colour)]
                radiance = [al * e / math.pi + glow * al for al, e in zip(albedo, irradiance)]
                r, g, b = (_to_srgb(c) for c in _aces(radiance, light["exposure"]))
                hits = [m for m in _hits_camera_mask(r, g, b) if cosine >= 0.6 or glow or m != "pedestrian"]
                if hits:
                    offenders.append((a["h"], cosine, name, (r, g, b), hits))
    assert offenders[:10] == []
