"""Solmare Coast trees, shrubs and vineyards (jevpilot_vision/web/semif-world/vegetation.js).

Placement is a plain function of the world, its height field and the ground grid, so node checks it
without three.js: nothing on the roads, in the sea or inside a building; everything on the ground.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "jevpilot_vision" / "web"


def _plants(body: str, seed: int = 42):
    script = (
        "import { createRequire } from 'module'; import { pathToFileURL } from 'url';"
        "const require = createRequire(import.meta.url); require(process.argv[1]);"
        "const mod = (n) => import(pathToFileURL(process.argv[2] + '/' + n));"
        "const H = await mod('heights.js'); const V = await mod('vegetation.js'); const G = await mod('terrain.js');"
        f"const world = globalThis.SEMIF_WORLDGEN.generate({seed}, 'coast:festival');"
        "const field = H.createHeightField(world); const grid = G.groundGrid(world, field);"
        "const plants = V.placeVegetation(world, field, grid);"
        "const out = (v) => process.stdout.write(JSON.stringify(v));" + body
    )
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(WEB / "semif-worldgen.js"), str(WEB / "semif-world")],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def summary() -> dict:
    return _plants(
        "const counts = {}; for (const p of plants) counts[p.species] = (counts[p.species] || 0) + 1;"
        "let onRoad = 0, nearRoad = 0, wet = 0, inBuilding = 0, floating = 0;"
        "const buildings = world.objects.filter((o) => o.type === 'building');"
        "for (const p of plants) {"
        "  const edge = field.roadEdge(p.x, p.z);"
        "  if (edge < 2.5) onRoad++;"
        "  if (p.species !== 'palm' && edge < 6) nearRoad++;"
        "  if (field.heightAt(p.x, p.z) < H.SEA_LEVEL + 1) wet++;"
        "  if (buildings.some((b) => Math.abs(p.x - b.x) < b.width / 2 + 1 && Math.abs(p.z - b.z) < b.depth / 2 + 1)) inBuilding++;"
        "  if (Math.abs(p.y - grid.heightAt(p.x, p.z)) > 0.05) floating++; }"
        "const villas = (await mod('buildings.js')).placeVillas(world, field, grid);"
        "const inVilla = plants.filter((p) => villas.some((v) => Math.abs(p.x - v.x) < v.width / 2 + 1 && Math.abs(p.z - v.z) < v.depth / 2 + 1)).length;"
        "out({ counts, total: plants.length, onRoad, nearRoad, wet, inBuilding, inVilla, floating, species: V.SPECIES });"
    )


def test_every_species_is_planted_in_believable_numbers(summary):
    counts = summary["counts"]
    for species in ("cypress", "pine", "olive", "palm", "shrub", "vine"):
        assert counts.get(species, 0) > 30, (species, counts)
    assert sorted(counts) == sorted(summary["species"])
    assert summary["total"] < 40_000


def test_nothing_grows_on_a_road_in_the_sea_or_inside_a_building(summary):
    assert summary["onRoad"] == 0
    assert summary["nearRoad"] == 0, "only street palms stand on the pavement"
    assert summary["wet"] == 0
    assert summary["inBuilding"] == 0
    assert summary["inVilla"] == 0, "no tree grows through a hillside villa"


def test_every_plant_stands_on_the_ground(summary):
    assert summary["floating"] == 0


def test_palms_line_the_town_streets():
    got = _plants(
        "const palms = plants.filter((p) => p.species === 'palm');"
        "const street = palms.filter((p) => { const e = field.roadEdge(p.x, p.z); return e > 2.5 && e < 4.5; });"
        "out({ palms: palms.length, street: street.length });"
    )
    assert got["street"] > 40


def test_placement_is_deterministic_and_the_seed_varies_it():
    a = _plants("out(plants.slice(0, 50));", 42)
    b = _plants("out(plants.slice(0, 50));", 42)
    c = _plants("out(plants.slice(0, 50));", 7)
    assert a == b and a != c
