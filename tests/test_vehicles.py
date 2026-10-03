"""Solmare Coast procedural vehicles (jevpilot_vision/web/semif-world/vehicles.js, #25).

The bundle drives these meshes: wheel pivots `wheel_fl/fr/rl/rr` with `userData.radius` and
`userData.front` whose `children[0]` spins, `userData.wheelbase/eyeHeight/eyeForward`, a `Glass`
material it hides in the hood view, and per-instance geometry its crash code dents in place.
"""

from __future__ import annotations

import pytest

from test_world_render import _render

# Model-space bounding box of a group: our builders bake every rotation into the vertices, so the
# box is the sum of node offsets plus vertex positions.
_BOX = r"""
const box = (root) => { const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
  const walk = (n, ox, oy, oz) => { const x = ox + (n.position?.x || 0), y = oy + (n.position?.y || 0), z = oz + (n.position?.z || 0);
    const p = n.geometry?.attributes?.position?.array; if (p) for (let i = 0; i < p.length; i += 3) { const v = [x + p[i], y + p[i + 1], z + p[i + 2]]; for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], v[k]); hi[k] = Math.max(hi[k], v[k]); } }
    (n.children || []).forEach((c) => walk(c, x, y, z)); };
  walk(root, -(root.position?.x || 0), -(root.position?.y || 0), -(root.position?.z || 0));
  return { length: hi[2] - lo[2], width: hi[0] - lo[0], height: hi[1] - lo[1], minY: lo[1], minZ: lo[2], maxZ: hi[2] }; };
const all = (o) => [o, ...(o.children || []).flatMap(all)];
const V = await mod('vehicles.js');
"""


@pytest.fixture(scope="module")
def heroes() -> dict:
    return _render(
        _BOX
        + "const out2 = {};"
        "for (const model of V.PROCEDURAL_HEROES) { const a = V.buildHero(model), b = V.buildHero(model);"
        "  const wheels = ['wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr'].map((name) => all(a).find((n) => n.name === name));"
        "  const geoA = new Set(all(a).filter((n) => n.geometry).map((n) => n.geometry));"
        "  out2[model] = { box: box(a), wheels: wheels.map((w) => w && { x: w.position.x, z: w.position.z, front: w.userData.front, radius: w.userData.radius, rotor: !!(w.children[0] && all(w.children[0]).some((n) => n.geometry)) }),"
        "    ud: a.userData, glass: all(a).some((n) => n.material?.name === 'Glass'), instanced: all(a).some((n) => n.count !== undefined && n.setMatrixAt),"
        "    shared: all(b).filter((n) => n.geometry && geoA.has(n.geometry)).length, meshes: all(a).filter((n) => n.geometry).length }; }"
        "out(out2);"
    )


@pytest.mark.parametrize("model", ["cybercab"])
def test_hero_cars_fill_the_bundles_footprint_and_stand_on_the_ground(heroes, model):
    box = heroes[model]["box"]
    assert abs(box["length"] - 4.75) < 0.03, box
    assert 1.8 <= box["width"] <= 1.9 + 1e-6, box
    assert 1.0 <= box["height"] <= 1.75, box
    assert -0.01 <= box["minY"] <= 0.02, "the tyres touch the ground"
    assert heroes[model]["meshes"] >= 12, "a real car: body, glass, lights, four wheels of several parts"


@pytest.mark.parametrize("model", ["cybercab"])
def test_hero_cars_keep_the_bundles_wheel_and_camera_contract(heroes, model):
    hero = heroes[model]
    wheels = dict(zip(["fl", "fr", "rl", "rr"], hero["wheels"]))
    assert all(wheels.values()), "four named wheel pivots"
    for name, w in wheels.items():
        assert w["front"] == (name[0] == "f") and (w["z"] < 0) == w["front"], (name, w)
        assert (w["x"] < 0) == (name[1] == "l"), (name, w)
        assert 0.28 <= w["radius"] <= 0.42 and w["rotor"], (name, w)
    assert abs(hero["ud"]["wheelbase"] - abs(wheels["fl"]["z"] - wheels["rl"]["z"])) < 1e-6
    assert 0.9 <= hero["ud"]["eyeHeight"] <= 1.5 and isinstance(hero["ud"]["eyeForward"], (int, float))
    assert hero["glass"], "the hood view hides the Glass material"
    assert hero["shared"] == 0 and not hero["instanced"], "crash dents rewrite each car's own geometry"


def test_traffic_models_fit_their_footprints_and_paint_is_picked_per_car():
    got = _render(
        _BOX
        + "const kinds = {}; for (const kind of V.TRAFFIC_KINDS) { const car = V.buildTraffic(kind, '#e9e8e3'); kinds[kind] = { box: box(car), wheels: all(car).filter((n) => /^wheel_(fl|fr|rl|rr)$/.test(n.name)).length }; }"
        "const moto = box(V.buildMotorcycle('#2e3d5c'));"
        "const looks = Array.from({ length: 300 }, (_, i) => V.trafficLook({ id: `car-${i}`, type: i % 10 === 0 ? 'motorcycle' : 'car' }));"
        "const again = V.trafficLook({ id: 'car-7', type: 'car' });"
        "out({ kinds, moto, looks, again, palette: (await mod('kit.js')).PALETTE.paint, n: V.TRAFFIC_KINDS.length });"
    )
    assert got["n"] == 6
    for kind, v in got["kinds"].items():
        assert abs(v["box"]["length"] - 4.2) < 0.03 and 1.75 <= v["box"]["width"] <= 1.9 + 1e-6, (kind, v)
        assert -0.01 <= v["box"]["minY"] <= 0.02 and v["wheels"] == 4, (kind, v)
    assert abs(got["moto"]["length"] - 2.3) < 0.05 and got["moto"]["width"] <= 0.8 + 1e-6, got["moto"]
    paints = set(got["palette"])
    assert len(paints) == 8
    assert all(look["paint"] in paints for look in got["looks"])
    assert {look["kind"] for look in got["looks"]} == {"hatch", "sedan", "wagon", "suv", "van", "pickup", "motorcycle"}
    assert all(look["kind"] == "motorcycle" for i, look in enumerate(got["looks"]) if i % 10 == 0)
    assert got["again"] == got["looks"][7], "the same car always looks the same"


def test_lathes_face_outward_on_every_axis_and_loft_caps_have_their_own_vertices():
    """Review: lathes around x and z were inside out; caps shared ring vertices, so ends shaded like domes."""
    got = _render(
        "const S = await mod('shapes.js');"
        "const normalAt = (part, i) => { const p = part.positions, [a, b, c] = part.index.slice(i, i + 3).map((k) => [p[3 * k], p[3 * k + 1], p[3 * k + 2]]);"
        "  const u = b.map((v, k) => v - a[k]), w = c.map((v, k) => v - a[k]); const n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];"
        "  const centre = [0, 1, 2].map((k) => (a[k] + b[k] + c[k]) / 3); return { n, centre }; };"
        "const outward = (axis) => { const part = S.lathe([[1, -0.5], [1, 0.5]], { axis, segments: 12 }); let ok = 0, all = 0;"
        "  for (let i = 0; i < part.index.length; i += 3) { const { n, centre } = normalAt(part, i); const k = { x: 0, y: 1, z: 2 }[axis];"
        "    const radial = centre.map((v, j) => (j === k ? 0 : v)); all++; if (n[0] * radial[0] + n[1] * radial[1] + n[2] * radial[2] > 0) ok++; } return ok / all; };"
        "const body = S.loft({ z0: -1, z1: 1, half: () => 1, bottom: () => 0, top: () => 1, around: 12, step: 0.5 });"
        "const rings = body.positions.length / 3; const sideMax = 5 * 12;"
        "const capIdx = body.index.slice(4 * 12 * 6);"
        "out({ x: outward('x'), y: outward('y'), z: outward('z'), shared: capIdx.filter((k) => k < sideMax).length });"
    )
    assert got["x"] == 1 and got["y"] == 1 and got["z"] == 1, got
    assert got["shared"] == 0, "cap triangles use their own copies of the end rings"


def test_a_failing_hero_build_rejects_instead_of_throwing_into_the_bundle():
    got = _render(
        "const K = await mod('kit.js'); const Group = K.T.Group; K.T.Group = undefined;"  # the build cannot make a group
        "let threw = false, rejected = false;"
        "try { const p = window.SEMIF_WORLD_KIT.hero({ sim: { world } }); await p.then(() => {}, () => { rejected = true; }); } catch (e) { threw = true; }"
        "K.T.Group = Group;"
        "out({ threw, rejected });"
    )
    assert got == {"threw": False, "rejected": True}


# ---- #47: the hero is a Tesla ------------------------------------------------------------------

def test_the_heroes_are_a_cybercab_style_car_and_the_model_y():
    got = _render(_BOX + "out({ heroes: V.HERO_MODELS, procedural: V.PROCEDURAL_HEROES, fallback: V.buildHero('gt').name });")
    assert got["heroes"] == ["cybercab", "model-y"]
    assert got["procedural"] == ["cybercab"], "the Model Y is the bundle's own glb"
    assert got["fallback"] == "semif-hero-cybercab", "an old name builds the default"


def test_the_cybercab_has_no_rear_window_full_width_light_bars_and_champagne_paint():
    # Classified lofts share one vertex array per piece: measure only the vertices the index uses.
    # The nose and tail are rounded (about 1.4 m across at the very ends): a bar of 1.3 m or more spans them.
    got = _render(
        _BOX
        + "const K = await mod('kit.js'); const car = V.buildHero('cybercab');"
        "const pieces = all(car).filter((n) => n.geometry && n.geometry.attributes.position);"
        "const span = (n) => { const p = n.geometry.attributes.position.array; const idx = n.geometry.index; const ids = idx ? Array.from(idx.array || idx) : null;"
        "  let x0 = 1e9, x1 = -1e9, z0 = 1e9, z1 = -1e9; const use = (v) => { x0 = Math.min(x0, p[3 * v]); x1 = Math.max(x1, p[3 * v]); z0 = Math.min(z0, p[3 * v + 2]); z1 = Math.max(z1, p[3 * v + 2]); };"
        "  if (ids) ids.forEach(use); else for (let v = 0; v < p.length / 3; v++) use(v); return { w: x1 - x0, z0, z1 }; };"
        "const colour = (n) => { const c = n.material && n.material.color; return typeof c === 'string' ? c : c && c.hex; };"
        "const glass = pieces.filter((n) => n.material.name === 'Glass').map(span);"
        "const bars = (hex) => pieces.filter((n) => colour(n) === hex).map(span).filter((s) => s.w >= 1.3);"
        "out({ glassRear: Math.max(...glass.map((g) => g.z1)), front: bars(K.PALETTE.car.lens).map((s) => s.z0), rear: bars(K.PALETTE.car.taillight).map((s) => s.z1),"
        "  paint: pieces.filter((n) => n.material.clearcoat === 1 && n.material.name !== 'Glass').map(colour), champagne: K.PALETTE.paint[2] });"
    )
    assert got["glassRear"] < 1.0, "no rear window: the fastback behind the roof is painted"
    assert got["front"] and min(got["front"]) < -2.3, "a full-width light bar across the nose"
    assert got["rear"] and max(got["rear"]) > 2.3, "and across the tail"
    assert set(got["paint"]) == {got["champagne"]}
