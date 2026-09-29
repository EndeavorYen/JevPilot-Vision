"""#11: the scenery layer and the bundle patches that load it.

The node harness runs jevpilot_vision/web/semif-scenery.js against a small fake of the three.js
kit the bundle hands over, so the hooks are tested without a browser or a GPU.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "jevpilot_vision" / "web"
BUNDLE = WEB / "assets" / "main-CvLEeHjW.js"
SCENERY = WEB / "semif-scenery.js"

PATCHES = {
    "map-size-city": (
        "size:5,traffic:28,buildings:.97,limit:18",
        "size:window.SEMIF_MAP?.size??7,traffic:window.SEMIF_MAP?.cityTraffic??40,buildings:.97,limit:18",
    ),
    "map-size-town": (
        "size:5,traffic:14,buildings:.62,limit:14",
        "size:window.SEMIF_MAP?.size??7,traffic:window.SEMIF_MAP?.townTraffic??22,buildings:.62,limit:14",
    ),
    "scenery-kit": (
        "build(){this.scenery&&(this.scenery.active=!1)",
        "build(){window.SEMIF_SCENERY?.kit?.({Mesh:K,",
    ),
    "scenery-object": (
        "for(let e of n.objects){if(e.type===`hill`)",
        "for(let e of n.objects){if(window.SEMIF_SCENERY?.object?.(r,e,this))continue;if(e.type===`hill`)",
    ),
    "scenery-built": (
        "this.ready=Promise.all([t,d,this.scenery.ready])}",
        "this.ready=Promise.all([t,d,this.scenery.ready]),window.SEMIF_SCENERY?.built?.(this)}",
    ),
    "scenery-minimap": (
        "$.rotate(-n.heading),$.lineCap=`round`",
        "$.rotate(-n.heading),window.SEMIF_SCENERY?.minimap?.($,e,i,r),$.lineCap=`round`",
    ),
}


def test_bundle_patches_are_applied_once():
    text = BUNDLE.read_text(encoding="utf-8")
    for name, (old, new) in PATCHES.items():
        assert text.count(new) == 1, name
        if not new.startswith(old):
            assert text.count(old) == 0, f"{name}: original still present"
    kit = re.search(r"window\.SEMIF_SCENERY\?\.kit\?\.\(\{(.*?)\}\)", text).group(1)
    for key in ("Mesh", "BoxGeometry", "InstancedMesh", "CanvasTexture", "mergeGeometries", "GLTFLoader", "DRACOLoader", "loadModelY", "materials"):
        assert f"{key}:" in kit
    doc = (WEB / "BUNDLE_PATCHES.md").read_text(encoding="utf-8")
    for name in PATCHES:
        assert f"`{name}`" in doc


def test_scenery_loads_before_the_bundle_runs():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    tag = re.search(r'<script src="/jevpilot/semif-scenery\.js[^"]*"([^>]*)>', html)
    assert tag, "index.html must load semif-scenery.js"
    assert "defer" not in tag.group(1) and "async" not in tag.group(1) and "module" not in tag.group(1)


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const spec = JSON.parse(process.argv[2]);

function ctx2d() {
  return new Proxy({}, {
    get(t, k) {
      if (k === "createLinearGradient") return () => ({ addColorStop() {} });
      if (k in t) return t[k];
      return () => {};
    },
    set(t, k, v) { t[k] = v; return true; },
  });
}
const document = { createElement: () => ({ width: 0, height: 0, getContext: () => ctx2d() }) };
const window = { SEMIF_SCENERY: undefined };
const location = { search: spec.search || "" };

class Vec { constructor() { this.x = 0; this.y = 0; this.z = 0; } set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; } setScalar(v) { return this.set(v, v, v); } }
class Attr {
  constructor(n) { this.count = n; this.a = new Float32Array(n * 2); }
  getX(i) { return this.a[i * 2]; } getY(i) { return this.a[i * 2 + 1]; }
  setXY(i, x, y) { this.a[i * 2] = x; this.a[i * 2 + 1] = y; }
}
class Geo {
  constructor() { this.attributes = { position: { count: 24 }, uv: new Attr(24) }; this.index = { count: 36 }; this.morphAttributes = {}; }
  translate() { return this; } rotateX() { return this; } dispose() {} setAttribute(k, v) { this.attributes[k] = v; } setIndex() {} computeVertexNormals() {}
}
class BoxGeometry extends Geo {
  constructor(w, h, d) { super(); this.parameters = { width: w, height: h, depth: d }; for (let i = 0; i < 24; i++) this.attributes.uv.setXY(i, i % 2, (i >> 1) % 2); }
}
class Mat4 { constructor() { this.elements = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]; } clone() { return new Mat4(); } identity() { return this; } multiplyMatrices() { return this; } }
class Object3D {
  constructor() { this.children = []; this.position = new Vec(); this.rotation = new Vec(); this.scale = new Vec(); this.visible = true; this.userData = {}; this.matrix = new Mat4(); this.matrixWorld = new Mat4(); }
  add(c) { this.children.push(c); c.parent = this; }
  remove(c) { this.children = this.children.filter((x) => x !== c); }
  updateMatrix() {} updateMatrixWorld() {}
  traverse(fn) { fn(this); this.children.forEach((c) => c.traverse(fn)); }
}
class Mesh extends Object3D { constructor(g, m) { super(); this.geometry = g; this.material = m; this.isMesh = true; } }
class InstancedMesh extends Mesh {
  constructor(g, m, n) { super(g, m); this.isInstancedMesh = true; this.count = n; this.at = []; this.instanceMatrix = {}; this.instanceColor = {}; }
  setMatrixAt(i) { this.at[i] = true; } setColorAt() {} getMatrixAt() {} computeBoundingSphere() {} dispose() {}
}
class Material { constructor(o) { Object.assign(this, o || {}); this.userData = {}; this.uuid = Math.random().toString(36); this.color = { set() {} }; } clone() { return new Material(this); } }
const kit = {
  Mesh, Group: Object3D, Object3D, BoxGeometry, PlaneGeometry: Geo, CylinderGeometry: Geo, SphereGeometry: Geo, ConeGeometry: Geo,
  BufferGeometry: Geo, Float32BufferAttribute: function () { return { count: 0 }; }, InstancedMesh,
  MeshStandardMaterial: Material, MeshPhysicalMaterial: Material, MeshBasicMaterial: Material,
  CanvasTexture: function (c) { this.image = c; }, Color: function () { this.set = () => this; },
  Vector3: Vec, SRGBColorSpace: "srgb", RepeatWrapping: 1000, mergeGeometries: (list) => new Geo(),
  materials: new Map(), quality: { anisotropy: 8 },
};

vm.createContext(Object.assign(global, { window, document, location }));
vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"));
const api = window.SEMIF_SCENERY;
async function builtWorld() {
  const model = new Object3D();
  model.add(new Mesh(new Geo(), new Material({ name: "paint" })));
  kit.materials.set("model-y-paint", model.children[0].material);
  kit.loadModelY = async () => model;
  api.kit(kit);
  const head = new Object3D();
  const housing = new Mesh(new BoxGeometry(0.65, 1.65, 0.38), new Material());
  housing.position.set(0, 4.2, 0);
  head.add(housing);
  const bulbs = [0, 1, 2].map(() => { const b = new Mesh(new Geo(), new Material()); head.add(b); return b; });
  const cars = [0, 1, 2].map((i) => ({ id: `vehicle-${i}`, type: "car", x: i * 40, z: 0, heading: 0 }));
  cars.push({ id: "vehicle-3", type: "car", x: 1000, z: 0, heading: 0 });
  const vehicles = new Map(cars.map((c) => { const g = new Object3D(); g.add(new Mesh(new Geo(), new Material())); return [c.id, g]; }));
  const peds = [{ id: "p-near", x: 30, z: 0 }, { id: "p-far", x: 300, z: 0 }];
  const people = new Map(peds.map((p) => [p.id, new Object3D()]));
  const scene = new Object3D();
  scene.fog = { color: { set() {} } };
  const world = {
    scene, lights: bulbs.map((mesh, index) => ({ mesh, index })), vehicles, people,
    sim: { traffic: cars, pedestrians: peds, player: { x: 0, z: 0 }, crash: null, world: { seed: 1, type: "city" } },
    renderer: { shadowMap: {} }, sun: { color: { set() {} } }, ready: Promise.resolve(),
    renders: 0, render() { this.renders += 1; },
  };
  api.built(world);
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
  return { world, head, housing, bulbs, scene };
}

if (spec.cmd === "built") {
  (async () => {
    const { world, head, housing } = await builtWorld();
    world.render(0.016, true);
    const inst = world.scene.children.find((c) => c.name === "traffic-model");
    const shown = (id) => world.vehicles.get(id).visible;
    const lowPoly = (id) => world.vehicles.get(id).children[0].visible;
    const out = {
      signalChildren: head.children.length,
      housingMerged: housing.geometry.parameters === undefined,
      housingAt: [housing.position.x, housing.position.y, housing.position.z],
      renders: world.renders,
      detailed: inst ? inst.count : null,
      lowPolyNear: lowPoly("vehicle-0"),
      farCarShown: shown("vehicle-3"),
      nearPed: world.people.get("p-near").visible,
      farPed: world.people.get("p-far").visible,
    };
    world.sim.crash = { object_id: "vehicle-0" };
    world.render(0.016, true);
    out.crashDetailed = inst.count;
    out.crashLowPoly = lowPoly("vehicle-0");
    const hooks = world._sceneryHooks.length;
    api.built(world);
    out.hooksAfterRebuild = world._sceneryHooks.length;
    out.hooksBefore = hooks;
    process.stdout.write(JSON.stringify(out));
  })().catch((err) => { process.stderr.write(String(err.stack || err)); process.exit(1); });
} else if (spec.cmd === "off") {
  process.stdout.write(JSON.stringify({ installed: !!api }));
} else if (spec.cmd === "palette") {
  process.stdout.write(JSON.stringify(api.palette));
} else if (spec.cmd === "build") {
  api.kit(kit);
  const out = {};
  const world = { sim: { world: { seed: 42, type: "city" } } };
  for (const style of ["skyscraper", "apartment", "shop", "cottage", "modern", "townhouse"]) {
    const root = new Object3D();
    const took = api.object(root, { id: `building-${style}`, type: "building", style, x: 10, z: -4, width: 16, depth: 14, height: style === "skyscraper" ? 80 : 12, rotation: Math.PI / 2 }, world);
    const meshes = [];
    const walk = (o) => { if (o.isMesh) meshes.push(o); o.children.forEach(walk); };
    walk(root);
    const facades = meshes.filter((m) => m.material && m.material.map);
    out[style] = {
      took,
      group: root.children.length === 1 ? { x: root.children[0].position.x, z: root.children[0].position.z, rot: root.children[0].rotation.y } : null,
      meshes: meshes.length,
      facades: facades.length,
      batchable: facades.every((m) => m.material.userData.metersPerTile > 0),
      tallest: Math.max(...meshes.map((m) => m.position.y)),
    };
  }
  out.tree = api.object(new Object3D(), { type: "tree", x: 0, z: 0 }, world);
  const ops = [];
  const c2d = { set fillStyle(v) { ops.push(["fill", v]); }, fillRect(x, y, w, h) { ops.push(["rect", w, h]); } };
  api.minimap(c2d, { objects: [
    { type: "building", style: "shop", x: 0, z: 0, width: 10, depth: 20, rotation: Math.PI / 2 },
    { type: "parcel", park: true, x: 5, z: 5, width: 30, depth: 30 },
    { type: "parcel", park: false, x: 5, z: 5, width: 30, depth: 30 },
    { type: "tree", x: 1, z: 1 },
  ] }, (o) => [o.x * 2, o.z * 2], 2);
  out.minimap = ops;
  process.stdout.write(JSON.stringify(out));
}
"""


def _run(spec: dict):
    proc = subprocess.run(
        ["node", "-e", _HARNESS, str(SCENERY), json.dumps(spec)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


def test_scenery_is_off_with_the_query_switch():
    assert _run({"cmd": "off", "search": "?scenery=0"}) == {"installed": False}
    assert _run({"cmd": "off", "search": "?seed=4"}) == {"installed": True}


def test_every_building_style_gets_facades_that_batch():
    out = _run({"cmd": "build"})
    for style in ("skyscraper", "apartment", "shop", "cottage", "modern", "townhouse"):
        row = out[style]
        assert row["took"] is True, style
        assert row["group"] == {"x": 10, "z": -4, "rot": pytest.approx(1.5708, abs=1e-3)}, style
        assert row["meshes"] >= 3, style
        assert row["facades"] >= 1, style
        assert row["batchable"], f"{style}: textured facades must join the bundle's static batches"
    assert out["skyscraper"]["tallest"] >= 80, "a tower reaches its height (plus its roof plant)"
    assert out["tree"] is False, "only buildings are taken over"


def test_built_hook_restyles_signals_culls_far_actors_and_details_near_cars():
    out = _run({"cmd": "built"})
    assert out["signalChildren"] == 4, "housing, backplate and visors stay one mesh next to the three lamps"
    assert out["housingMerged"] is True
    assert out["housingAt"] == [0, 0, 0], "the merged head carries its own offsets"
    assert out["renders"] == 1, "the frame hook still calls the bundle's render"
    assert out["detailed"] == 3, "cars within 140 m get a detailed model; the one 1 km away does not"
    assert out["lowPolyNear"] is False
    assert out["farCarShown"] is False, "cars past 260 m are not drawn"
    assert out["nearPed"] is True and out["farPed"] is False
    assert out["crashDetailed"] == 2, "the struck car goes back to the body the impact effect dents"
    assert out["crashLowPoly"] is True
    assert out["hooksAfterRebuild"] == 1, "a rebuilt world starts with fresh hooks"


def test_minimap_draws_buildings_and_parks_turned_with_the_map():
    ops = _run({"cmd": "build"})["minimap"]
    rects = [op for op in ops if op[0] == "rect"]
    # The shop is turned 90 degrees: 20 m by 10 m on the map, at scale 2.
    assert rects[0] == ["rect", 40, 20]
    assert rects[1] == ["rect", 60, 60]
    assert len(rects) == 2, "plain parcels and trees are not drawn"


# Colour masks from jevpilot_vision/vision.py::blobs_from_frame. The neutral-gray vehicle mask is
# left out: plain asphalt (#73817e) already fills it.
def _hits_camera_mask(r: int, g: int, b: int) -> list[str]:
    hits = []
    if r > 180 and g < 90 and b < 90:
        hits.append("light_red")
    if g > 150 and r < 90 and b < 90:
        hits.append("light_green")
    if r > 180 and 70 < g < 190 and b < 90:
        hits.append("construction")
    if b > 180 and r < 80 and g < 110:
        hits.append("emergency")
    if r < 40 and g < 40 and b < 40:
        hits.append("pedestrian")
    return hits


def _colours(value, name=""):
    if isinstance(value, str):
        yield name, value
    elif isinstance(value, list):
        for item in value:
            yield from _colours(item, name)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _colours(item, f"{name}.{key}" if name else key)


# Daylight from deep shade (x0.55) to full sun (x1.3), times the tiles' own shading: bricks up
# to x1.1, glass highlights up to x1.65 and its dark end x0.85.
FACTORS = (0.55, 0.7, 0.85, 1.0, 1.15, 1.3, 1.45, 1.65)


def test_scenery_palette_stays_out_of_the_camera_colour_masks():
    """The onboard camera reads lights, construction, warning lights and people by colour.
    Facades, shopfronts, signals and car paint must not look like one in daylight or shade."""
    palette = _run({"cmd": "palette"})
    offenders = []
    for name, hex_colour in _colours(palette):
        n = int(hex_colour[1:], 16)
        base = ((n >> 16) & 255, (n >> 8) & 255, n & 255)
        factors = FACTORS + ((0.55 * 0.85,) if name == "glass" else ())
        for factor in factors:
            r, g, b = (min(255, round(c * factor)) for c in base)
            hits = _hits_camera_mask(r, g, b)
            if hits:
                offenders.append((name, hex_colour, round(factor, 3), hits))
    assert offenders == []


def test_scenery_colours_are_all_in_the_palette():
    """A colour literal outside PALETTE would escape the mask test above."""
    source = SCENERY.read_text(encoding="utf-8")
    body = source[source.index("const SHOP_NAMES"):]
    literals = set(re.findall(r'"#[0-9a-fA-F]{6}"', body))
    assert literals <= {'"#ffffff"'}, literals


def _map_setting(search: str) -> dict:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = re.search(r"<script>\s*(\(function \(\) \{.*?\}\)\(\);)\s*</script>", html, re.S).group(1)
    harness = (
        "const window = {}; const location = { search: %s };"
        "const HTMLCanvasElement = function () {}; HTMLCanvasElement.prototype.getContext = function () {};"
        "%s process.stdout.write(JSON.stringify(window.SEMIF_MAP));"
    ) % (json.dumps(search), script)
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def test_benchmark_laps_keep_the_published_map_size():
    """The official web lap (lap=1) was scored on the 5 x 5 grid; free driving gets 7 x 7."""
    assert _map_setting("?seed=42&lap=1") == {"size": 5, "cityTraffic": 28, "townTraffic": 14}
    assert _map_setting("?seed=42") == {"size": 7, "cityTraffic": 40, "townTraffic": 22}
    assert _map_setting("?lap=1&size=7")["size"] == 7
    assert _map_setting("?size=42")["size"] == 7, "out of range falls back"
