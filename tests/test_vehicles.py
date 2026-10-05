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
        "  paint: [...new Set(pieces.filter((n) => n.material.metalness >= 0.5 && n.material.roughness >= 0.35).map(colour))],"
        "  satin: pieces.filter((n) => colour(n) === K.PALETTE.car.champagne).every((n) => n.material.roughness >= 0.35), champagne: K.PALETTE.car.champagne });"
    )
    assert got["glassRear"] < 1.0, "no rear window: the fastback behind the roof is painted"
    assert got["front"] and min(got["front"]) < -2.3, "a full-width light bar across the nose"
    assert got["rear"] and max(got["rear"]) > 2.3, "and across the tail"
    assert set(got["paint"]) == {got["champagne"]}, "one paint: the champagne"
    assert got["satin"], "#90: a satin finish, not gloss"


# ---- #90: the Cybercab rebuilt from photos -----------------------------------------------------

def test_issue90_the_cybercab_has_big_wheels_at_the_corners_and_a_painted_roof():
    """From the show-car photos: wheels about a sixth of the length pushed to the corners, glass only
    in the windscreen and side windows (the roof is champagne), a lip overhanging the tail face."""
    got = _render(
        _BOX
        + "const car = V.buildHero('cybercab'); const b = box(car);"
        "const wheels = ['wheel_fl', 'wheel_rl'].map((n) => all(car).find((x) => x.name === n));"
        "const glass = all(car).filter((n) => n.material && n.material.name === 'Glass');"
        "let roofGlass = 0; for (const g of glass) { const p = g.geometry.attributes.position.array; const idx = g.geometry.index; const ids = Array.from(idx.array || idx);"
        "  for (let i = 0; i < ids.length; i += 3) { const c = [0, 1, 2].map((k) => [0, 1, 2].reduce((s, j) => s + p[3 * ids[i + j] + k], 0) / 3);"
        "    if (Math.abs(c[0]) < 0.35 && c[2] > -0.4 && c[1] > 1.3) roofGlass++; } }"
        "const K = await mod('kit.js'); const body = all(car).find((n) => n.name === 'body');"
        "const pts = (n) => { const p = n.geometry.attributes.position.array, o = []; for (let i = 0; i < p.length; i += 3) o.push([p[i], p[i + 1], p[i + 2]]); return o; };"
        "const tris = (n) => { const v = pts(n), idx = n.geometry.index, ids = Array.from(idx.array || idx), o = []; for (let i = 0; i < ids.length; i += 3) o.push([v[ids[i]], v[ids[i + 1]], v[ids[i + 2]]]); return o; };"
        "const col = (n) => n.material.color?.hex ?? n.material.color;"
        "const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];"
        "const near = (p, [a, b, c]) => { const ab = sub(b, a), ac = sub(c, a), ap = sub(p, a); const d1 = dot(ab, ap), d2 = dot(ac, ap); if (d1 <= 0 && d2 <= 0) return a;"
        "  const bp = sub(p, b), d3 = dot(ab, bp), d4 = dot(ac, bp); if (d3 >= 0 && d4 <= d3) return b; const vc = d1 * d4 - d3 * d2;"
        "  if (vc <= 0 && d1 >= 0 && d3 <= 0) { const v = d1 / (d1 - d3); return [a[0] + v * ab[0], a[1] + v * ab[1], a[2] + v * ab[2]]; }"
        "  const cp = sub(p, c), d5 = dot(ab, cp), d6 = dot(ac, cp); if (d6 >= 0 && d5 <= d6) return c; const vb = d5 * d2 - d1 * d6;"
        "  if (vb <= 0 && d2 >= 0 && d6 <= 0) { const w = d2 / (d2 - d6); return [a[0] + w * ac[0], a[1] + w * ac[1], a[2] + w * ac[2]]; }"
        "  const va = d3 * d6 - d5 * d4; if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) { const w = (d4 - d3) / (d4 - d3 + d5 - d6); return [b[0] + w * (c[0] - b[0]), b[1] + w * (c[1] - b[1]), b[2] + w * (c[2] - b[2])]; }"
        "  const den = 1 / (va + vb + vc), v = vb * den, w = vc * den; return [a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w]; };"
        "const paint = body.children.filter((n) => col(n) === K.PALETTE.car.champagne), shell = paint.flatMap(pts), faces = paint.flatMap(tris);"
        "const bar = body.children.filter((n) => col(n) === K.PALETTE.car.lens).flatMap(pts);"
        "const gap = Math.max(...bar.map((q) => Math.min(...faces.filter((f) => Math.min(f[0][2], f[1][2], f[2][2]) - 0.05 < q[2] && Math.max(f[0][2], f[1][2], f[2][2]) + 0.05 > q[2]).map((f) => { const c = near(q, f); return Math.hypot(c[0] - q[0], c[1] - q[1], c[2] - q[2]); }))));"
        "out({ minZ: b.minZ, maxZ: b.maxZ, r: wheels[0].userData.radius, fz: wheels[0].position.z, rz: wheels[1].position.z, roofGlass,"
        "  shellTail: Math.max(...shell.map((v) => v[2])), bar: bar.length, gap });"
    )
    assert got["r"] >= 0.4, "big wheels"
    assert got["fz"] - got["minZ"] <= 0.75 and got["maxZ"] - got["rz"] <= 0.8, "short overhangs: the wheels sit at the corners"
    assert got["roofGlass"] == 0, "the roof is painted, not glass"
    assert got["maxZ"] - got["shellTail"] >= 0.04, "the duckbill lip overhangs the tail face"
    assert got["bar"] and got["gap"] < 0.03, "the light bar lies on the body, not in the air"


def test_issue107_the_paint_is_matte_and_the_hood_and_fenders_are_split():
    """#107: matte paint, and the shut lines and the light bar sit just outside the paint faces.

    Distance is to the containing face, including the interior of each light-bar triangle and
    each hood-shut triangle. A vertex can sit outside the paint while the quad between two
    stations cuts back through it.
    """
    got = _render(
        _BOX
        + "const K = await mod('kit.js'); const car = V.buildHero('cybercab');"
        "const pieces = all(car).filter((n) => n.geometry && n.geometry.attributes.position);"
        "const colour = (n) => { const c = n.material && n.material.color; return typeof c === 'string' ? c : c && c.hex; };"
        "const body = all(car).find((n) => n.name === 'body');"
        "const faces = body.children.filter((n) => colour(n) === K.PALETTE.car.champagne).flatMap((n) => {"
        "  const p = n.geometry.attributes.position.array; const idx = n.geometry.index; const ids = idx ? Array.from(idx.array || idx) : null; const o = [];"
        "  const push = (i0, i1, i2) => o.push([[p[3*i0], p[3*i0+1], p[3*i0+2]], [p[3*i1], p[3*i1+1], p[3*i1+2]], [p[3*i2], p[3*i2+1], p[3*i2+2]]]);"
        "  if (ids) for (let i = 0; i < ids.length; i += 3) push(ids[i], ids[i+1], ids[i+2]); else for (let v = 0; v < p.length / 3; v += 3) push(v, v+1, v+2); return o; });"
        "const front = faces.filter((t) => Math.min(t[0][2], t[1][2], t[2][2]) < -1.85);"
        "const verts = (hex) => pieces.filter((n) => colour(n) === hex).flatMap((n) => { const p = n.geometry.attributes.position.array, o = [];"
        "  for (let i = 0; i < p.length; i += 3) o.push([p[i], p[i+1], p[i+2]]); return o; });"
        "const bary = (u, v, a0, a1, b0, b1, c0, c1) => { const den = (b1-c1)*(a0-c0)+(c0-b0)*(a1-c1); if (Math.abs(den) < 1e-10) return null;"
        "  const w0 = ((b1-c1)*(u-c0)+(c0-b0)*(v-c1))/den, w1 = ((c1-a1)*(u-c0)+(a0-c0)*(v-c1))/den, w2 = 1-w0-w1;"
        "  return (w0 < -1e-3 || w1 < -1e-3 || w2 < -1e-3) ? null : [w0, w1, w2]; };"
        "const skinY = (p) => { let best = null; for (const [a,b,c] of faces) {"
        "  if (a[2] < -2.4 && b[2] < -2.4 && c[2] < -2.4) continue; if (a[2] > -1.2 && b[2] > -1.2 && c[2] > -1.2) continue;"
        "  const w = bary(p[0], p[2], a[0], a[2], b[0], b[2], c[0], c[2]); if (!w) continue;"
        "  const y = w[0]*a[1]+w[1]*b[1]+w[2]*c[1]; if (best === null || y > best) best = y; } return best; };"
        "const skinZ = (p) => { let best = null; for (const [a,b,c] of front) { if (Math.min(a[2], b[2], c[2]) > -2.1) continue;"
        "  const w = bary(p[0], p[1], a[0], a[1], b[0], b[1], c[0], c[1]); if (!w) continue;"
        "  const z = w[0]*a[2]+w[1]*b[2]+w[2]*c[2]; if (best === null || z < best) best = z; } return best; };"
        "const skinX = (p) => { const sign = Math.sign(p[0]) || 1; let best = null; for (const [a,b,c] of front) {"
        "  if (a[0]*sign < 0.05 && b[0]*sign < 0.05 && c[0]*sign < 0.05) continue; if (Math.min(a[2], b[2], c[2]) > -1.9) continue;"
        "  const w = bary(p[1], p[2], a[1], a[2], b[1], b[2], c[1], c[2]); if (!w) continue;"
        "  const x = w[0]*a[0]+w[1]*b[0]+w[2]*c[0]; if (best === null || x*sign > best*sign) best = x; } return best; };"
        "const champ = pieces.filter((n) => colour(n) === K.PALETTE.car.champagne);"
        "const tv = verts(K.PALETTE.car.trim), lens = verts(K.PALETTE.car.lens);"
        "const hood = tv.filter((p) => Math.abs(p[2] + 1.52) < 0.006 && p[1] > 0.85);"
        "const fender = tv.filter((p) => p[1] > 0.7 && p[2] < -1.55 && p[2] > -2.20 && Math.abs(Math.abs(p[0]) - 0.62) < 0.02);"
        "const nose = lens.filter((p) => p[2] < -2.331);"
        "const side = lens.filter((p) => p[2] >= -2.331 && p[2] < -1.95 && Math.abs(p[0]) > 0.2);"
        "const cents = pieces.filter((n) => colour(n) === K.PALETTE.car.lens).flatMap((n) => {"
        "  const p = n.geometry.attributes.position.array; const idx = n.geometry.index; const ids = idx ? Array.from(idx.array || idx) : null; const o = [];"
        "  const push = (i0, i1, i2) => { const a = [p[3*i0], p[3*i0+1], p[3*i0+2]], b = [p[3*i1], p[3*i1+1], p[3*i1+2]], c = [p[3*i2], p[3*i2+1], p[3*i2+2]];"
        "    o.push([(a[0]+b[0]+c[0])/3, (a[1]+b[1]+c[1])/3, (a[2]+b[2]+c[2])/3]); };"
        "  if (ids) for (let i = 0; i < ids.length; i += 3) push(ids[i], ids[i+1], ids[i+2]); else for (let v = 0; v < p.length / 3; v += 3) push(v, v+1, v+2); return o; });"
        "const noseC = cents.filter((p) => p[2] < -2.3315);"
        "const sideC = cents.filter((p) => p[2] >= -2.3295 && p[2] < -1.95 && Math.abs(p[0]) > 0.2);"
        "const onHood = (p) => Math.abs(p[2] + 1.52) < 0.006 && p[1] > 0.85;"
        "const hoodC = pieces.filter((n) => colour(n) === K.PALETTE.car.trim).flatMap((n) => {"
        "  const p = n.geometry.attributes.position.array; const idx = n.geometry.index; const ids = idx ? Array.from(idx.array || idx) : null; const o = [];"
        "  const push = (i0, i1, i2) => { const a = [p[3*i0], p[3*i0+1], p[3*i0+2]], b = [p[3*i1], p[3*i1+1], p[3*i1+2]], c = [p[3*i2], p[3*i2+1], p[3*i2+2]];"
        "    if (!onHood(a) || !onHood(b) || !onHood(c)) return;"
        "    o.push([(a[0]+b[0]+c[0])/3, (a[1]+b[1]+c[1])/3, (a[2]+b[2]+c[2])/3]); };"
        "  if (ids) for (let i = 0; i < ids.length; i += 3) push(ids[i], ids[i+1], ids[i+2]); else for (let v = 0; v < p.length / 3; v += 3) push(v, v+1, v+2); return o; });"
        "const off = (p) => { const s = skinY(p); return s !== null && p[1] - s > 0.001 && p[1] - s < 0.008; };"
        "const band = (lo, hi) => (g) => g !== null && g > lo && g < hi;"
        "const ahead = (p) => { const s = skinZ(p); return band(0.0002, 0.007)(s === null ? null : s - p[2]); };"
        "const outboard = (p) => { const s = skinX(p); return band(0.0002, 0.007)(s === null ? null : (p[0]-s)*Math.sign(p[0])); };"
        "const face = (pts, gap) => { let hit = 0, min = Infinity, max = -Infinity; for (const p of pts) { const g = gap(p); if (g === null) continue; hit++; if (g < min) min = g; if (g > max) max = g; } return { n: pts.length, hit, min, max }; };"
        "out({ matte: champ.length > 0 && champ.every((n) => n.material.roughness >= 0.62 && (n.material.clearcoat ?? 1) <= 0.05 && n.material.metalness >= 0.5),"
        "  hoodL: hood.some((p) => p[0] < -0.3), hoodR: hood.some((p) => p[0] > 0.3),"
        "  fenderL: fender.some((p) => p[0] < -0.45), fenderR: fender.some((p) => p[0] > 0.45),"
        "  hoodOut: hood.length >= 80 && hood.every(off), fenderOut: fender.length >= 60 && fender.every(off),"
        "  noseOut: nose.length >= 16 && nose.every(ahead) && Math.min(...nose.map((p) => p[0])) < -0.4 && Math.max(...nose.map((p) => p[0])) > 0.4,"
        "  sideOut: side.length >= 40 && side.every(outboard),"
        "  noseFace: face(noseC, (p) => { const s = skinZ(p); return s === null ? null : s - p[2]; }),"
        "  sideFace: face(sideC, (p) => { const s = skinX(p); return s === null ? null : (p[0]-s)*Math.sign(p[0]); }),"
        "  hoodFace: face(hoodC, (p) => { const s = skinY(p); return s === null ? null : p[1] - s; }) });"
    )
    assert got["matte"], "champagne body and covers are matte: rough, almost no clearcoat"
    assert got["hoodL"] and got["hoodR"], "a shut line crosses the hood ahead of the windscreen"
    assert got["fenderL"] and got["fenderR"], "each front fender has a shut line"
    assert got["hoodOut"], "the hood shut line sits just outside the paint"
    assert got["fenderOut"], "the fender shut lines sit just outside the paint"
    assert got["noseOut"], "the nose light-bar vertices sit just ahead of the nose skin"
    assert got["sideOut"], "the light-bar vertices stay just outside the front fenders"
    for name, band in (("noseFace", got["noseFace"]), ("sideFace", got["sideFace"])):
        assert band["n"] >= 1000 and band["hit"] == band["n"], band
        assert 0.0002 < band["min"] and band["max"] < 0.007, (name, band)
    hood_face = got["hoodFace"]
    assert hood_face["n"] >= 80 and hood_face["hit"] == hood_face["n"], hood_face
    assert 0.001 < hood_face["min"] and hood_face["max"] < 0.008, hood_face

