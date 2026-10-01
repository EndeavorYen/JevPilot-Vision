"""Solmare Coast renderer (jevpilot_vision/web/semif-world/) and the page that loads it.

Node imports the renderer's modules against a small fake of the three.js kit the bundle hands
over, so the hooks and the geometry are tested without a browser or a GPU.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from test_scenery import FACTORS, _colours, _hits_camera_mask

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "jevpilot_vision" / "web"
RENDER = WEB / "semif-world"

_PRELUDE = r"""
import { createRequire } from "module";
import { pathToFileURL } from "url";
const require = createRequire(import.meta.url);
const [worldgen, renderDir] = process.argv.slice(1, 3);
require(worldgen);
class Obj { constructor() { this.children = []; this.userData = {}; this.name = ""; } add(...c) { this.children.push(...c); } }
class Geo { constructor() { this.attributes = {}; } setAttribute(k, v) { this.attributes[k] = v; } computeVertexNormals() {} }
class Mesh extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; } }
class Color { constructor(hex) { const n = parseInt(hex.slice(1), 16); this.r = (n >> 16) / 255; this.g = ((n >> 8) & 255) / 255; this.b = (n & 255) / 255; } }
const kit = { Group: Obj, Mesh, BufferGeometry: Geo, Float32BufferAttribute: function (a, n) { this.array = a; this.itemSize = n; },
  MeshStandardMaterial: function (o) { Object.assign(this, o); }, Color };
const calls = [];
globalThis.window = { SEMIF_SCENERY: {
  palette: { legacy: true },
  kit() { calls.push("kit"); }, object() { calls.push("object"); return "legacy"; },
  built() { calls.push("built"); }, minimap() { calls.push("minimap"); } } };
const world = globalThis.SEMIF_WORLDGEN.generate(42, "coast:festival");
window.SEMIF_SIM = { world };
const mod = (name) => import(pathToFileURL(`${renderDir}/${name}`));
await mod("index.js");
const api = window.SEMIF_SCENERY;
api.kit(kit);
const find = (o, name) => o.name === name ? o : o.children.map((c) => find(c, name)).find(Boolean);
const meshes = (o) => [...(o.geometry ? [o] : []), ...o.children.flatMap(meshes)];
const out = (v) => process.stdout.write(JSON.stringify(v));
"""


def _render(body: str):
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", _PRELUDE + body, str(WEB / "semif-worldgen.js"), str(RENDER)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


def test_on_the_coast_the_hooks_draw_the_world_and_elsewhere_they_go_to_the_old_layer():
    got = _render(
        "const scene = new Obj(); api.built({ sim: { world }, scene, _sceneryHooks: ['old'] });"
        "const root = scene.children[0]; const coast = { root: root.name, parts: root.children.map((c) => c.name),"
        "  building: api.object(null, { type: 'building' }, null), lamp: api.object(null, { type: 'streetlight' }, null), calls: calls.slice() };"
        "window.SEMIF_SIM = { world: { type: 'city' } }; const city = new Obj();"
        "const legacy = [api.object(null, { type: 'building' }, null), api.built({ scene: city }), api.minimap(null, { type: 'city' }), city.children.length];"
        "out({ coast, legacy, calls, palette: api.palette });"
    )
    assert got["coast"]["root"] == "semif-world"
    assert got["coast"]["parts"] == ["semif-terrain", "semif-sea", "semif-roads", "semif-buildings"]
    assert got["coast"]["building"] is True and got["coast"]["lamp"] is False
    assert got["coast"]["calls"] == ["kit"], "the old layer only sees the kit on the coast"
    assert got["legacy"][0] == "legacy" and got["legacy"][3] == 0
    assert got["calls"] == ["kit", "object", "built", "minimap"]
    assert got["palette"] == {"legacy": True}


def test_asphalt_covers_every_road_and_every_ground_triangle_faces_up():
    got = _render(
        "const roads = (await mod('roads.js')).buildRoads(world); const terrain = (await mod('terrain.js')).buildTerrain(world);"
        "const area = (m) => { const p = m.geometry.attributes.position.array; let a = 0, down = 0;"
        "  for (let i = 0; i < p.length; i += 9) { const ux = p[i + 3] - p[i], uz = p[i + 5] - p[i + 2], vx = p[i + 6] - p[i], vz = p[i + 8] - p[i + 2];"
        "    const y = uz * vx - ux * vz; a += Math.abs(y) / 2; if (y < -1e-9) down++; } return { a, down }; };"
        "const parts = meshes(roads).map((m) => ({ color: m.material.color, ...area(m) }));"
        "const expect = world.connectorRoads.reduce((s, r) => s + r.points.at(-1).s * r.width, 0);"
        "out({ parts, expect, terrain: area(terrain) });"
    )
    asphalt = got["parts"][0]
    assert asphalt["color"] == "#4d5257"
    assert asphalt["a"] == pytest.approx(got["expect"], rel=0.05)
    assert all(p["down"] == 0 for p in got["parts"])
    assert got["terrain"]["down"] == 0


def test_signal_junctions_get_crosswalks_and_every_approach_a_stop_bar():
    got = _render(
        "const roads = (await mod('roads.js')).buildRoads(world);"
        "const marking = meshes(roads).find((m) => m.material.color === '#e9e6da').geometry.attributes.position.array;"
        # each rectangle is two triangles (18 numbers); count rectangles by their centre's distance
        "const near = (n, r0, r1) => { let k = 0; for (let i = 0; i < marking.length; i += 18) { let x = 0, z = 0;"
        "  for (let j = 0; j < 18; j += 3) { x += marking[i + j] / 6; z += marking[i + j + 2] / 6; }"
        "  const d = Math.hypot(x - n.x, z - n.z); if (d >= r0 && d <= r1) k++; } return k; };"
        "out(world.nodes.filter((n) => n.townJunction).map((n) => ({ id: n.id, control: n.control, legs: n.neighbors.length,"
        "  crosswalk: near(n, 5, 9.6), bars: near(n, 10, 12.2) })));"
    )
    for n in got:
        if n["control"] == "signal":
            assert n["crosswalk"] >= 6 * n["legs"], n
        assert n["bars"] >= n["legs"], n


def test_buildings_stand_exactly_on_their_collision_boxes():
    got = _render(
        "const g = (await mod('buildings.js')).buildBuildings(world);"
        "const p = meshes(g).flatMap((m) => Array.from(m.geometry.attributes.position.array));"
        "const boxes = world.objects.filter((o) => o.type === 'building');"
        "const outside = [];"
        "for (let i = 0; i < p.length; i += 3) {"
        "  const hit = boxes.some((b) => Math.abs(p[i] - b.x) <= b.width / 2 + 0.31 && Math.abs(p[i + 2] - b.z) <= b.depth / 2 + 0.31 && p[i + 1] <= b.height + 0.51);"
        "  if (!hit) outside.push([p[i], p[i + 1], p[i + 2]]); }"
        "out({ n: boxes.length, outside: outside.slice(0, 3) });"
    )
    assert got["n"] > 50 and got["outside"] == []


def test_the_ground_is_flat_on_land_and_shelves_down_under_the_sea():
    got = _render(
        "const t = await mod('terrain.js');"
        "out({ festival: t.groundHeight(world, { x: 0, z: 250 }), harbour: t.groundHeight(world, { x: -950, z: 200 }),"
        "  shore: t.groundHeight(world, { x: 0, z: 570 }), offshore: t.groundHeight(world, { x: 0, z: 900 }),"
        "  sea: (await mod('water.js')).SEA_LEVEL });"
    )
    assert got["festival"] == got["harbour"] == -0.05
    assert got["sea"] < got["festival"]
    assert got["offshore"] < got["shore"] < got["festival"]
    assert got["offshore"] < got["sea"], "open water is deeper than the surface"


def _palette() -> dict:
    return _render("out((await mod('kit.js')).PALETTE);")


def test_renderer_palette_stays_out_of_the_camera_colour_masks():
    offenders = []
    for name, hex_colour in _colours(_palette()):
        n = int(hex_colour[1:], 16)
        base = ((n >> 16) & 255, (n >> 8) & 255, n & 255)
        for factor in FACTORS:
            r, g, b = (min(255, round(c * factor)) for c in base)
            hits = _hits_camera_mask(r, g, b)
            if hits:
                offenders.append((name, hex_colour, factor, hits))
    assert offenders == []


def test_renderer_colours_are_all_in_the_palette():
    """A colour literal outside PALETTE would escape the mask test above."""
    for path in RENDER.glob("*.js"):
        source = path.read_text(encoding="utf-8")
        if path.name == "kit.js":
            source = source[source.index("// The bundle's three.js classes"):]
        literals = set(re.findall(r'"#[0-9a-fA-F]{6}"', source))
        assert literals <= {'"#ffffff"'}, (path.name, literals)
