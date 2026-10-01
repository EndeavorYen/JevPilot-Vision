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
class Obj { constructor() { this.children = []; this.userData = {}; this.name = ""; this.position = { copy(v) { this.v = v; } }; } add(...c) { this.children.push(...c); } }
class Geo { constructor() { this.attributes = {}; } setAttribute(k, v) { this.attributes[k] = v; } setIndex(i) { this.index = i; } computeVertexNormals() {} }
class Mesh extends Obj { constructor(g, m) { super(); this.geometry = g; this.material = m; } }
class Color { constructor(hex) { this.set(hex || "#000000"); } set(hex) { this.hex = hex; const n = parseInt(hex.slice(1), 16); this.r = (n >> 16) / 255; this.g = ((n >> 8) & 255) / 255; this.b = (n & 255) / 255; return this; } copy(c) { return this.set(c.hex); } }
class Vec3 { constructor(x = 0, y = 0, z = 0) { this.set(x, y, z); } set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; } copy(v) { return this.set(v.x, v.y, v.z); } }
class ShaderMaterial { constructor(o) { Object.assign(this, o); } }
class SphereGeometry extends Geo { constructor(r) { super(); this.radius = r; } }
const kit = { Group: Obj, Mesh, BufferGeometry: Geo, Float32BufferAttribute: function (a, n) { this.array = a; this.itemSize = n; },
  MeshStandardMaterial: function (o) { Object.assign(this, o); this.userData = {}; }, Color, Vector3: Vec3, ShaderMaterial, SphereGeometry,
  TextureLoader: class { load(url) { return { url }; } }, RepeatWrapping: 1000, SRGBColorSpace: "srgb" };
globalThis.location = { search: process.argv[3] || "" };
globalThis.document = { createElement: () => ({ style: {}, set textContent(v) { this.text = v; }, get textContent() { return this.text; }, addEventListener() {} }),
  head: { appendChild() {} }, body: { appendChild(el) { globalThis.__clock = el; } }, addEventListener() {} };
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
const find = (o, name) => o.name === name ? o : (o.children || []).map((c) => find(c, name)).find(Boolean);
const meshes = (o) => [...(o.geometry ? [o] : []), ...o.children.flatMap(meshes)];
const out = (v) => process.stdout.write(JSON.stringify(v));
"""


def _render(body: str, search: str = ""):
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", _PRELUDE + body, str(WEB / "semif-worldgen.js"), str(RENDER), search],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


def test_on_the_coast_the_hooks_draw_the_world_and_elsewhere_they_go_to_the_old_layer():
    got = _render(
        "const scene = new Obj(); api.built({ sim: { world }, scene, _sceneryHooks: ['old'], render() {} });"
        "const root = scene.children[0]; const coast = { root: root.name, parts: root.children.map((c) => c.name),"
        "  building: api.object(null, { type: 'building' }, null), lamp: api.object(null, { type: 'streetlight' }, null), calls: calls.slice() };"
        "window.SEMIF_SIM = { world: { type: 'city' } }; const city = new Obj();"
        "const legacy = [api.object(null, { type: 'building' }, null), api.built({ scene: city }), api.minimap(null, { type: 'city' }), city.children.length];"
        "out({ coast, legacy, calls, palette: api.palette });"
    )
    assert got["coast"]["root"] == "semif-world"
    assert got["coast"]["parts"] == ["semif-sky", "semif-terrain", "semif-sea", "semif-roads", "semif-buildings"]
    assert got["coast"]["building"] is True and got["coast"]["lamp"] is False
    assert got["coast"]["calls"] == ["kit"], "the old layer only sees the kit on the coast"
    assert got["legacy"][0] == "legacy" and got["legacy"][3] == 0
    assert got["calls"] == ["kit", "object", "built", "minimap"]
    assert got["palette"] == {"legacy": True}


def test_sun_and_present_hooks_take_over_only_on_the_coast():
    got = _render(
        "const pos = { set(x, y, z) { this.v = [x, y, z]; return this; } };"
        "const view = { sim: { world }, scene: new Obj(), camera: { far: 1200, updateProjectionMatrix() {} }, renderer: { render(s, c) { view.rendered = (view.rendered || 0) + 1; } },"
        "  sun: { position: pos, target: { position: { set() {} } }, shadow: { camera: {} }, color: { setRGB() {} } }, render(dt, draw) { return 'base'; } };"
        "api.built(view);"
        "const coast = { sun: api.sun(view, { x: 10, z: 20 }), sunAt: pos.v, present: api.present(view), rendered: view.rendered, far: view.camera.far, frame: view.render(0.016, true) };"
        "window.SEMIF_SIM = { world: { type: 'city' } };"
        "const city = { sun: api.sun(view, { x: 10, z: 20 }), present: api.present(view), rendered: view.rendered };"
        "out({ coast, city });"
    )
    assert got["coast"]["sun"] is True and got["coast"]["sunAt"] is not None
    assert got["coast"]["present"] is True and got["coast"]["rendered"] == 1
    assert got["coast"]["far"] >= 2600, "the coast is 2.5 km across"
    assert got["coast"]["frame"] == "base", "the per-frame wrapper still runs the bundle's render"
    assert not got["city"]["sun"] and not got["city"]["present"] and got["city"]["rendered"] == 1


_VIEW = (
    "const hemi = { isHemisphereLight: true, color: new Color(), groundColor: new Color(), intensity: 0 };"
    "const scene = new Obj(); scene.add(hemi); scene.fog = { color: new Color(), near: 0, far: 0 }; scene.background = 'hdr';"
    "const sun = { position: new Vec3(), target: { position: new Vec3() }, color: new Color(), intensity: 0,"
    "  shadow: { camera: { updateProjectionMatrix() { this.updated = true; } } } };"
    "const view = { sim: { world }, scene, sun, camera: { far: 1200, position: new Vec3(5, 2, 7), updateProjectionMatrix() {} },"
    "  renderer: { toneMappingExposure: 0, render() {} }, render() {} };"
    "api.built(view); api.sun(view, { x: 100, z: -50 }); view.render(0.016, true);"
    "const D = await mod('daylight.js');"
)


def test_a_fixed_time_lights_the_coast_from_the_day_model():
    got = _render(
        _VIEW + "const L = D.lightAt(19); const dir = D.sunDirection(19);"
        "out({ exposure: view.renderer.toneMappingExposure, want: L.exposure, sunI: sun.intensity, wantI: L.sunIntensity,"
        "  sunColor: sun.color.hex, wantColor: L.sun, hemi: [hemi.color.hex, hemi.groundColor.hex, hemi.intensity], wantHemi: [L.hemiSky, L.hemiGround, L.hemiIntensity],"
        "  fog: scene.fog.color.hex, background: scene.background, sky: !!find(scene, 'semif-sky'),"
        "  sunPos: [sun.position.x - 100, sun.position.y, sun.position.z + 50], dir, target: [sun.target.position.x, sun.target.position.z],"
        "  shadow: sun.shadow.camera, clock: globalThis.__clock && globalThis.__clock.textContent });",
        "?time=19:00",
    )
    assert got["exposure"] == pytest.approx(got["want"]) and got["sunI"] == pytest.approx(got["wantI"])
    assert got["sunColor"] == got["wantColor"] and got["hemi"] == got["wantHemi"]
    assert got["background"] is None and got["sky"] is True
    for p, d in zip(got["sunPos"], (got["dir"]["x"], got["dir"]["y"], got["dir"]["z"])):
        assert p == pytest.approx(d * 300, abs=0.01), "the sun sits 300 m from the player along its direction"
    assert got["target"] == [100, -50]
    assert got["shadow"]["right"] >= 120 and got["shadow"]["far"] >= 600 and got["shadow"]["updated"]
    assert "19:00" in got["clock"]


def test_the_clock_runs_unless_the_time_is_fixed():
    running = _render(_VIEW + "const a = globalThis.__clock.textContent; for (let i = 0; i < 60; i++) view.render(1, true); out([a, globalThis.__clock.textContent]);")
    fixed = _render(_VIEW + "const a = globalThis.__clock.textContent; for (let i = 0; i < 60; i++) view.render(1, true); out([a, globalThis.__clock.textContent]);", "?time=09:30")
    paused = _render(_VIEW + "const a = globalThis.__clock.textContent; for (let i = 0; i < 60; i++) view.render(1, true); out([a, globalThis.__clock.textContent]);", "?daycycle=0")
    assert "16:30" in running[0] and running[0] != running[1], "free driving opens at 16:30 and the clock moves"
    assert fixed[0] == fixed[1] and "09:30" in fixed[0]
    assert paused[0] == paused[1] and "16:30" in paused[0]


def test_asphalt_covers_every_road_and_every_ground_triangle_faces_up():
    got = _render(
        "const roads = (await mod('roads.js')).buildRoads(world); const terrain = (await mod('terrain.js')).buildTerrain(world, (await mod('heights.js')).createHeightField(world));"
        "const area = (m) => { const p = m.geometry.attributes.position.array; let a = 0, down = 0;"
        "  for (let i = 0; i < p.length; i += 9) { const ux = p[i + 3] - p[i], uz = p[i + 5] - p[i + 2], vx = p[i + 6] - p[i], vz = p[i + 8] - p[i + 2];"
        "    const y = uz * vx - ux * vz; a += Math.abs(y) / 2; if (y < -1e-9) down++; } return { a, down }; };"
        "const parts = meshes(roads).map((m) => ({ color: m.material.color, ...area(m) }));"
        "const expect = world.connectorRoads.reduce((s, r) => s + r.points.at(-1).s * r.width, 0);"
        "const tp = terrain.geometry.attributes.position.array, ti = terrain.geometry.index; let tdown = 0;"
        "for (let k = 0; k < ti.length; k += 3) { const [a, b, c] = [ti[k] * 3, ti[k + 1] * 3, ti[k + 2] * 3];"
        "  const ux = tp[b] - tp[a], uz = tp[b + 2] - tp[a + 2], vx = tp[c] - tp[a], vz = tp[c + 2] - tp[a + 2]; if (uz * vx - ux * vz < -1e-9) tdown++; }"
        "out({ parts, expect, terrain: { down: tdown, triangles: ti.length / 3 } });"
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


def test_the_terrain_mesh_follows_the_height_field_and_the_sea_sits_at_sea_level():
    got = _render(
        "const H = await mod('heights.js'); const field = H.createHeightField(world);"
        "const mesh = (await mod('terrain.js')).buildTerrain(world, field);"
        "const p = mesh.geometry.attributes.position.array, s = mesh.geometry.attributes.aSplat.array;"
        "let worst = 0, splatOff = 0, minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;"
        "for (let i = 0; i < p.length; i += 3 * 97) worst = Math.max(worst, Math.abs(p[i + 1] - field.heightAt(p[i], p[i + 2])));"
        "for (let i = 0; i < s.length; i += 4) splatOff = Math.max(splatOff, Math.abs(s[i] + s[i + 1] + s[i + 2] + s[i + 3] - 1));"
        "for (let i = 0; i < p.length; i += 3) { minX = Math.min(minX, p[i]); maxX = Math.max(maxX, p[i]); minZ = Math.min(minZ, p[i + 2]); maxZ = Math.max(maxZ, p[i + 2]); }"
        "out({ worst, splatOff, extent: [minX, maxX, minZ, maxZ], vertices: p.length / 3, sea: (await mod('water.js')).SEA_LEVEL, level: H.SEA_LEVEL, bounds: world.bounds });"
    )
    assert got["worst"] < 1e-4
    assert got["splatOff"] < 1e-4
    b = got["bounds"]
    assert got["extent"][0] <= b["minX"] - 800 and got["extent"][1] >= b["maxX"] + 800
    assert got["extent"][2] <= b["minZ"] - 800 and got["extent"][3] >= b["maxZ"] + 800
    assert got["vertices"] < 260_000
    assert got["sea"] == got["level"]


def test_the_sea_covers_every_wet_part_of_the_ground_at_sea_level():
    got = _render(
        "const H = await mod('heights.js'); const field = H.createHeightField(world);"
        "const ground = (await mod('terrain.js')).buildTerrain(world, field); const { xs, zs, heights } = ground.userData.grid;"
        "const sea = (await mod('water.js')).buildSea(ground.userData.grid); const near = find(sea, 'semif-sea-near');"
        "const p = near.geometry.attributes.position.array, d = near.geometry.attributes.aDepth.array;"
        "const ys = new Set(); for (let i = 1; i < p.length; i += 3) ys.add(p[i]);"
        "const at = new Set(); for (let i = 0; i < p.length; i += 3) at.add(p[i] + ':' + p[i + 2]);"
        "let missing = 0; for (let j = 0; j < zs.length; j++) for (let i = 0; i < xs.length; i++) if (heights[j * xs.length + i] < H.SEA_LEVEL - 0.5 && !at.has(xs[i] + ':' + zs[j])) missing++;"
        "out({ ys: [...ys], minDepth: Math.min(...d), maxDepth: Math.max(...d), missing, far: !!find(sea, 'semif-sea-far'), level: H.SEA_LEVEL });"
    )
    assert got["ys"] == [got["level"]]
    assert got["minDepth"] >= 0 and got["maxDepth"] > 20
    assert got["missing"] == 0 and got["far"] is True


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
        if path.name == "daylight.js":
            continue  # light, sky and fog colours, checked hour by hour in tests/test_daylight.py
        source = path.read_text(encoding="utf-8")
        if path.name == "kit.js":
            source = source[source.index("// The bundle's three.js classes"):]
        literals = set(re.findall(r'"#[0-9a-fA-F]{6}"', source))
        assert literals <= {'"#ffffff"'}, (path.name, literals)


def _page_setting(search: str) -> dict:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = re.search(r"<script>\s*(\(function \(\) \{.*?\}\)\(\);)\s*</script>", html, re.S).group(1)
    harness = (
        "const window = {}; const location = { search: %s };"
        "const HTMLCanvasElement = function () {}; HTMLCanvasElement.prototype.getContext = function () {};"
        "%s process.stdout.write(JSON.stringify({ world: window.SEMIF_DEFAULT_WORLD ?? null, map: window.SEMIF_MAP }));"
    ) % (json.dumps(search), script)
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def test_free_driving_opens_on_the_coast_and_a_benchmark_lap_keeps_the_city():
    assert _page_setting("?seed=42")["world"] == "coast:festival"
    assert _page_setting("?seed=42&start=pass")["world"] == "coast:pass"
    assert _page_setting("?start=moon")["world"] == "coast:festival"
    lap = _page_setting("?seed=42&lap=1")
    assert lap["world"] is None
    assert lap["map"] == {"size": 5, "cityTraffic": 28, "townTraffic": 14}


def test_page_start_points_match_the_generator():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    listed = json.loads(re.search(r"var starts = (\[.*?\]);", html).group(1))
    got = subprocess.run(
        ["node", "-e", "require(process.argv[1]); process.stdout.write(JSON.stringify(Object.keys(globalThis.SEMIF_WORLDGEN.STARTS)))", str(WEB / "semif-worldgen.js")],
        capture_output=True, text=True, check=True,
    )
    assert listed == json.loads(got.stdout)


def test_page_loads_the_generator_and_renderer_before_the_bundle():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    gen = html.index('<script src="/jevpilot/semif-worldgen.js')
    render = html.index('<script type="module" src="/jevpilot/semif-world/index.js')
    bundle = html.index('<script type="module" crossorigin src="/jevpilot/assets/index-')
    assert gen < bundle and render < bundle
    tag = re.search(r'<script src="/jevpilot/semif-worldgen\.js[^"]*"([^>]*)>', html).group(1)
    assert "defer" not in tag and "async" not in tag and "module" not in tag
