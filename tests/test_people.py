"""Solmare Coast people (jevpilot_vision/web/semif-world/people.js, #25).

Sim pedestrians are what the onboard camera's `pedestrian` mask looks for: their lower body is
the one palette colour allowed in that mask (PALETTE.people.silhouette). Decorative crowds are not
in the simulation, never wear it, and keep 8 m from the lanes.
"""

from __future__ import annotations

from test_world_render import _render

_PEOPLE = r"""
const all = (o) => [o, ...(o.children || []).flatMap(all)];
const P = await mod('people.js');
const K = (await mod('kit.js')).PALETTE;
const height = (root) => { let lo = 1e9, hi = -1e9; const walk = (n, oy) => { const y = oy + (n.position?.y || 0); const p = n.geometry?.attributes?.position?.array;
  if (p) for (let i = 1; i < p.length; i += 3) { lo = Math.min(lo, y + p[i]); hi = Math.max(hi, y + p[i]); } (n.children || []).forEach((c) => walk(c, y)); }; walk(root, -(root.position?.y || 0)); return { lo, hi }; };
"""


def test_sim_pedestrians_have_limbs_a_dark_lower_body_and_vary():
    got = _render(
        _PEOPLE
        + "const people = Array.from({ length: 40 }, (_, i) => P.buildPedestrian(`ped-${i}`));"
        "const one = people[3];"
        "const legMeshes = one.userData.limbs.legs.flatMap(all).filter((n) => n.geometry);"
        "const pelvis = all(one).filter((n) => n.name === 'pelvis').flatMap(all).filter((n) => n.geometry);"
        "const others = all(one).filter((n) => n.geometry && !legMeshes.includes(n) && !pelvis.includes(n));"
        "const tops = new Set(people.map((p) => P.pedestrianLook(p.userData.id).top));"
        "out({ legs: one.userData.limbs.legs.length, arms: one.userData.limbs.arms.length, h: height(one),"
        "  legColours: [...new Set(legMeshes.map((m) => m.material.color))], otherSilhouette: others.filter((m) => m.material.color === K.people.silhouette).length,"
        "  tops: tops.size, same: JSON.stringify(P.pedestrianLook('ped-3')) === JSON.stringify(P.pedestrianLook('ped-3')), silhouette: K.people.silhouette });"
    )
    assert got["legs"] == 2 and got["arms"] == 2
    assert 1.5 <= got["h"]["hi"] - got["h"]["lo"] <= 1.95 and abs(got["h"]["lo"]) < 0.03, got["h"]
    assert got["silhouette"] in got["legColours"], "the camera's pedestrian mask reads the lower body"
    assert got["otherSilhouette"] == 0, "only the lower body (legs, pelvis) wears the silhouette colour"
    assert got["tops"] >= 4 and got["same"]


def test_crowds_fill_the_festival_cafes_and_beach_away_from_the_lanes():
    got = _render(
        _PEOPLE
        + "const H = await mod('heights.js'); const field = H.createHeightField(world); const grid = (await mod('terrain.js')).groundGrid(world, field);"
        "const spots = P.placeCrowds(world, field, grid); const again = P.placeCrowds(world, field, grid);"
        "const sea = H.seaPolygon(world.visual.shoreline, world.bounds);"
        "const g = P.buildCrowds(spots); const colours = [...new Set(all(g).filter((n) => n.material).map((n) => n.material.color))];"
        "out({ n: spots.length, places: [...new Set(spots.map((s) => s.place))].sort(), near: spots.filter((s) => field.roadEdge(s.x, s.z) < 6.25).length,"
        "  wet: spots.filter((s) => H.inside(sea, s)).length, floating: spots.filter((s) => Math.abs(s.y - grid.heightAt(s.x, s.z)) > 0.05).length,"
        "  same: JSON.stringify(spots) === JSON.stringify(again), silhouette: colours.includes(K.people.silhouette), name: g.name });"
    )
    assert got["n"] >= 150 and got["places"] == ["beach", "cafe", "festival"]
    assert got["near"] == 0, "lane centre lines are at least 8 m away (road edge >= 6.25 m)"
    assert got["wet"] == 0 and got["floating"] == 0 and got["same"]
    assert not got["silhouette"], "crowds never look like sim pedestrians to the camera"
    assert got["name"] == "semif-crowds"


def test_nothing_hides_a_sim_pedestrians_lower_body_and_caps_leave_the_face_clear():
    """Review: a dress over the hips hid the silhouette the camera reads; a cap swallowed the head."""
    got = _render(
        _PEOPLE
        + "const lows = [], caps = [];"
        "for (let i = 0; i < 120; i++) { const id = `ped-${i}`, look = P.pedestrianLook(id), g = buildIt(id);"
        "  for (const n of all(g)) { const p = n.geometry?.attributes?.position?.array; if (!p || !n.material) continue;"
        "    const oy = (n.parent?.position?.y || 0);"
        "    if (n.material.color === look.top) for (let k = 1; k < p.length; k += 3) if (p[k] + oy < 0.9 * look.scale) { lows.push(id); break; }"
        "    if (look.style === 'cap' && n.material.color === look.hat) for (let k = 1; k < p.length; k += 3) if (p[k] < 1.6 * look.scale - 0.005) { caps.push(id); break; } } }"
        "out({ lows: [...new Set(lows)].slice(0, 5), caps: [...new Set(caps)].slice(0, 5) });"
        .replace("buildIt(id)", "(() => { const g = P.buildPedestrian(id); const fix = (n) => { (n.children || []).forEach((c) => { c.parent = n; fix(c); }); }; fix(g); return g; })()")
    )
    assert got["lows"] == [], "no top-coloured cloth below the hips"
    assert got["caps"] == [], "a cap sits on the head, above the face"


def test_crowd_clothes_skin_and_hair_are_picked_independently_and_never_the_silhouette():
    got = _render(
        _PEOPLE
        + "const H = await mod('heights.js'); const field = H.createHeightField(world); const grid = (await mod('terrain.js')).groundGrid(world, field);"
        "const g = P.buildCrowds(P.placeCrowds(world, field, grid));"
        "const by = Object.fromEntries(g.children.map((m) => [m.name, m.colours]));"
        "const legs = by['crowd-legs'], skin = by['crowd-head'];"
        "const pair = new Set(legs.map((c, i) => `${K.people.bottom.indexOf(c)}:${K.people.skin.indexOf(skin[i])}`));"
        "out({ n: legs.length, legOk: legs.every((c) => K.people.bottom.includes(c)), skinOk: skin.every((c) => K.people.skin.includes(c)),"
        "  silhouette: Object.values(by).some((list) => list.includes(K.people.silhouette)), pairs: pair.size });"
    )
    assert got["legOk"] and got["skinOk"] and not got["silhouette"]
    assert got["pairs"] >= 10, "trousers do not decide skin (4 x 4 combinations should mostly appear)"
