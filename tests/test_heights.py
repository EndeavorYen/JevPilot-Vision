"""Solmare Coast terrain heights (jevpilot_vision/web/semif-world/heights.js).

The simulation is flat: every road stays at y=0. Ground rises only beyond each road's shoulder,
the sea lies well below the roads (a cliff coast), and the heights never depend on the seed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "jevpilot_vision" / "web"


def _heights(body: str):
    script = (
        "import { createRequire } from 'module'; import { pathToFileURL } from 'url';"
        "const require = createRequire(import.meta.url); require(process.argv[1]);"
        "const H = await import(pathToFileURL(process.argv[2] + '/heights.js'));"
        "const world = globalThis.SEMIF_WORLDGEN.generate(42, 'coast:festival');"
        "const field = H.createHeightField(world);"
        "const out = (v) => process.stdout.write(JSON.stringify(v));" + body
    )
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(WEB / "semif-worldgen.js"), str(WEB / "semif-world")],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


def test_every_road_and_its_shoulder_is_flat_at_zero():
    worst = _heights(
        "let worst = 0;"
        "for (const r of world.connectorRoads) for (const p of r.points) for (const side of [-1, 0, 1]) {"
        "  const i = r.points.indexOf(p), q = r.points[Math.min(i + 1, r.points.length - 1)], o = r.points[Math.max(i - 1, 0)];"
        "  const h = Math.atan2(q.x - o.x, o.z - q.z) + Math.PI / 2, d = side * (r.width / 2 + 3);"
        "  worst = Math.max(worst, Math.abs(field.heightAt(p.x + Math.sin(h) * d, p.z - Math.cos(h) * d))); }"
        "out(worst);"
    )
    assert worst < 1e-6


def test_the_sea_lies_well_below_the_roads_and_the_shore_meets_it():
    got = _heights(
        "out({ level: H.SEA_LEVEL, offshore: field.heightAt(0, 800), bay: field.heightAt(500, 760),"
        "  shore: world.visual.shoreline.slice(1, -1).map((p) => field.heightAt(p.x, p.z)) });"
    )
    assert got["level"] <= -8, "a cliff coast: the roads stand well above the water"
    assert got["offshore"] < got["level"] - 5 and got["bay"] < got["level"] - 3
    for h in got["shore"]:
        assert got["level"] - 1.5 <= h <= got["level"] + 1.5, "the land meets the water at the shoreline"


def test_mountains_rise_in_the_north_and_the_towns_stay_level():
    got = _heights(
        "const peak = Math.max(...Array.from({ length: 60 }, (_, i) => field.heightAt(-1200 + i * 40, -1000)));"
        "const harbour = [];"
        "for (let x = -1090; x <= -810; x += 20) for (let z = 110; z <= 290; z += 20) harbour.push(field.heightAt(x, z));"
        "const festival = [];"
        "for (let x = -60; x <= 60; x += 20) for (let z = 270; z <= 420; z += 20) festival.push(field.heightAt(x, z));"
        "out({ peak, harbour: Math.max(...harbour.map(Math.abs)), festival: Math.max(...festival.map(Math.abs)) });"
    )
    assert got["peak"] > 100
    assert got["harbour"] < 2.5 and got["festival"] < 2.5


def test_heights_are_finite_and_do_not_depend_on_the_seed():
    got = _heights(
        "const other = H.createHeightField(globalThis.SEMIF_WORLDGEN.generate(7, 'coast:pass'));"
        "let same = true, finite = true;"
        "for (let x = -1800; x <= 1800; x += 37) for (let z = -1400; z <= 1400; z += 41) {"
        "  const a = field.heightAt(x, z); if (!Number.isFinite(a)) finite = false; if (a !== other.heightAt(x, z)) same = false; }"
        "out({ same, finite });"
    )
    assert got == {"same": True, "finite": True}


def test_surface_weights_follow_slope_height_and_shore():
    got = _heights(
        "const w = (x, z) => field.surface(x, z);"
        "out({ beach: w(30, 556), cliff: w(1150, 120), meadow: w(-500, -200), sum: [w(30, 556), w(1150, 120), w(-500, -200)].map((s) => s.reduce((a, b) => a + b, 0)) });"
    )
    grass, dry, rock, sand = range(4)
    assert got["beach"][sand] > 0.5
    assert got["cliff"][rock] > 0.4
    assert got["meadow"][grass] + got["meadow"][dry] > 0.6
    assert got["sum"] == pytest.approx([1, 1, 1])
