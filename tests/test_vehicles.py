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
        "for (const model of V.HERO_MODELS) { const a = V.buildHero(model), b = V.buildHero(model);"
        "  const wheels = ['wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr'].map((name) => all(a).find((n) => n.name === name));"
        "  const geoA = new Set(all(a).filter((n) => n.geometry).map((n) => n.geometry));"
        "  out2[model] = { box: box(a), wheels: wheels.map((w) => w && { x: w.position.x, z: w.position.z, front: w.userData.front, radius: w.userData.radius, rotor: !!(w.children[0] && all(w.children[0]).some((n) => n.geometry)) }),"
        "    ud: a.userData, glass: all(a).some((n) => n.material?.name === 'Glass'), instanced: all(a).some((n) => n.count !== undefined && n.setMatrixAt),"
        "    shared: all(b).filter((n) => n.geometry && geoA.has(n.geometry)).length, meshes: all(a).filter((n) => n.geometry).length }; }"
        "out(out2);"
    )


@pytest.mark.parametrize("model", ["gt", "roadster", "rally"])
def test_hero_cars_fill_the_bundles_footprint_and_stand_on_the_ground(heroes, model):
    box = heroes[model]["box"]
    assert abs(box["length"] - 4.75) < 0.03, box
    assert 1.8 <= box["width"] <= 1.9 + 1e-6, box
    assert 1.0 <= box["height"] <= 1.75, box
    assert -0.01 <= box["minY"] <= 0.02, "the tyres touch the ground"
    assert heroes[model]["meshes"] >= 12, "a real car: body, glass, lights, four wheels of several parts"


@pytest.mark.parametrize("model", ["gt", "roadster", "rally"])
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
