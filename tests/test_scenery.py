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
    "map-size-city": ("size:5,traffic:28,buildings:.97,limit:18", "size:7,traffic:40,buildings:.97,limit:18"),
    "map-size-town": ("size:5,traffic:14,buildings:.62,limit:14", "size:7,traffic:22,buildings:.62,limit:14"),
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
    for key in ("Mesh", "BoxGeometry", "InstancedMesh", "CanvasTexture", "mergeGeometries", "loadModelY", "materials"):
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
class Object3D {
  constructor() { this.children = []; this.position = new Vec(); this.rotation = new Vec(); this.scale = new Vec(); this.visible = true; this.userData = {}; }
  add(c) { this.children.push(c); c.parent = this; }
  remove(c) { this.children = this.children.filter((x) => x !== c); }
}
class Mesh extends Object3D { constructor(g, m) { super(); this.geometry = g; this.material = m; this.isMesh = true; } }
class Material { constructor(o) { Object.assign(this, o || {}); this.userData = {}; this.uuid = Math.random().toString(36); } }
const kit = {
  Mesh, Group: Object3D, Object3D, BoxGeometry, PlaneGeometry: Geo, CylinderGeometry: Geo, SphereGeometry: Geo, ConeGeometry: Geo,
  BufferGeometry: Geo, Float32BufferAttribute: function () { return { count: 0 }; }, InstancedMesh: Mesh,
  MeshStandardMaterial: Material, MeshPhysicalMaterial: Material, MeshBasicMaterial: Material,
  CanvasTexture: function (c) { this.image = c; }, Color: function () { this.set = () => this; },
  Vector3: Vec, SRGBColorSpace: "srgb", RepeatWrapping: 1000, mergeGeometries: (list) => new Geo(),
  materials: new Map(), quality: { anisotropy: 8 },
};

vm.createContext(Object.assign(global, { window, document, location }));
vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"));
const api = window.SEMIF_SCENERY;
if (spec.cmd === "off") {
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


def test_minimap_draws_buildings_and_parks_turned_with_the_map():
    ops = _run({"cmd": "build"})["minimap"]
    rects = [op for op in ops if op[0] == "rect"]
    # The shop is turned 90 degrees: 20 m by 10 m on the map, at scale 2.
    assert rects[0] == ["rect", 40, 20]
    assert rects[1] == ["rect", 60, 60]
    assert len(rects) == 2, "plain parcels and trees are not drawn"


# Colour masks from jevpilot_vision/vision.py::blobs_from_frame, minus the neutral-gray vehicle and
# near-black pedestrian masks that plain asphalt and tyres already hit.
def _hits_light_or_hazard(r: int, g: int, b: int) -> list[str]:
    hits = []
    if r > 180 and g < 90 and b < 90:
        hits.append("light_red")
    if g > 150 and r < 90 and b < 90:
        hits.append("light_green")
    if r > 180 and 70 < g < 190 and b < 90:
        hits.append("construction")
    if b > 180 and r < 80 and g < 110:
        hits.append("emergency")
    return hits


def _colours(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _colours(item)


def test_scenery_palette_stays_out_of_the_camera_colour_masks():
    """The onboard camera reads red / green lights, construction and warning lights by colour.
    New facades, shopfronts and car paint must not look like one under daylight."""
    palette = _run({"cmd": "palette"})
    offenders = []
    for name, value in palette.items():
        for hex_colour in _colours(value):
            n = int(hex_colour[1:], 16)
            base = ((n >> 16) & 255, (n >> 8) & 255, n & 255)
            # Daylight 0.55-1.3, times the tiles' own highlights (bricks x1.1, glass x1.65).
            for factor in (0.55, 0.7, 0.85, 1.0, 1.15, 1.3, 1.45, 1.65):
                r, g, b = (min(255, round(c * factor)) for c in base)
                hits = _hits_light_or_hazard(r, g, b)
                if hits:
                    offenders.append((name, hex_colour, factor, hits))
    assert offenders == []


def test_onboard_cameras_hide_the_cabin():
    layer = (WEB / "semif-layer.js").read_text(encoding="utf-8")
    assert 'const ONBOARD_HIDDEN = new Set(["Glass", "Interior"]);' in layer
    assert 'leather.name = "Interior"' in SCENERY.read_text(encoding="utf-8")
