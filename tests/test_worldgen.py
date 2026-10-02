"""Solmare Coast map generator (jevpilot_vision/web/semif-worldgen.js).

Node runs the generator, which has no DOM and no three.js, and each test checks one property the
bundle's simulation relies on. tests/test_coast_patches.py then drives the bundle itself on it.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORLDGEN = REPO / "jevpilot_vision" / "web" / "semif-worldgen.js"
STARTS = ["festival", "harbour", "coast", "pass", "highway"]


def _js(body: str):
    """Run `body` after loading the generator as G; it must print one JSON value."""
    script = "require(process.argv[1]); const G = globalThis.SEMIF_WORLDGEN;\n" + body
    proc = subprocess.run(["node", "-e", script, str(WORLDGEN)], cwd=str(REPO), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


def _world(seed: int = 42, start: str = "festival") -> dict:
    return _js(
        f"const w = G.generate({seed}, 'coast:{start}');"
        "const plain = JSON.parse(JSON.stringify({ ...w, byId: undefined }));"
        "process.stdout.write(JSON.stringify(plain));"
    )


@pytest.fixture(scope="module")
def world() -> dict:
    return _world()


def _heading(a: dict, b: dict) -> float:
    return math.atan2(b["x"] - a["x"], a["z"] - b["z"])


def _segment_distance(p1, p2, q1, q2) -> float:
    def point(p, a, b):
        dx, dz = b["x"] - a["x"], b["z"] - a["z"]
        length = dx * dx + dz * dz
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((p["x"] - a["x"]) * dx + (p["z"] - a["z"]) * dz) / length))
        return math.hypot(p["x"] - a["x"] - t * dx, p["z"] - a["z"] - t * dz)

    return min(point(p1, q1, q2), point(p2, q1, q2), point(q1, p1, p2), point(q2, p1, p2))


def test_same_seed_same_world_and_the_seed_never_moves_a_road():
    a, b, c = _world(42), _world(42), _world(7)
    assert a == b
    assert [e["centerline"] for e in a["edges"]] == [e["centerline"] for e in c["edges"]]
    assert [n["offset"] for n in a["nodes"]] != [n["offset"] for n in c["nodes"]]


def test_every_start_point_builds_and_an_unknown_one_falls_back_to_the_festival():
    out = _js(
        "const r = {};"
        "for (const s of Object.keys(G.STARTS)) { const w = G.generate(1, 'coast:' + s); r[s] = [w.type, w.start, w.selectValue, w.startNode, w.nextNode]; }"
        "const x = G.generate(1, 'coast:moon'); r.unknown = [x.type, x.start]; r.bare = G.generate(1, 'coast').start;"
        "process.stdout.write(JSON.stringify(r));"
    )
    assert sorted(k for k in out if k not in ("unknown", "bare")) == sorted(STARTS)
    for start in STARTS:
        assert out[start][:3] == ["coast", start, f"coast:{start}"]
        assert out[start][3] != out[start][4]
    assert out["unknown"] == ["coast", "festival"]
    assert out["bare"] == "festival"


def test_the_network_has_no_dead_ends_and_every_node_reaches_every_other(world):
    by_id = {n["id"]: n for n in world["nodes"]}
    assert all(len(n["neighbors"]) >= 2 for n in world["nodes"])
    for start in world["nodes"]:
        seen, queue = {start["id"]}, [start["id"]]
        while queue:
            for nxt in by_id[queue.pop()]["neighbors"]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        assert len(seen) == len(world["nodes"]), start["id"]


def test_every_edge_is_two_way_with_a_path_a_centreline_and_the_same_lane_offset(world):
    for e in world["edges"]:
        assert e["oneWay"] is False and e["laneOffset"] == 3, e["id"]
        assert len(e["path"]) > 1 and len(e["centerline"]) > 1, e["id"]
        assert e["length"] == pytest.approx(e["path"][-1]["s"]), e["id"]
        steps = [math.hypot(b["x"] - a["x"], b["z"] - a["z"]) for a, b in zip(e["path"], e["path"][1:])]
        assert max(steps) <= 1.5 + 1e-6, e["id"]


def test_roads_meet_only_at_their_shared_junctions(world):
    """The simulation is flat: two roads that cross anywhere but a junction would collide."""
    by_id = {n["id"]: n for n in world["nodes"]}
    edges = world["edges"]
    for i, a in enumerate(edges):
        for b in edges[i + 1:]:
            shared = [by_id[n] for n in {a["a"], a["b"]} & {b["a"], b["b"]}]
            need = (a["width"] + b["width"]) / 2 + 4
            pa, pb = a["centerline"][::2], b["centerline"][::2]
            for p, p2 in zip(pa, pa[1:]):
                if any(math.hypot(p["x"] - n["x"], p["z"] - n["z"]) < 30 for n in shared):
                    continue
                for q, q2 in zip(pb, pb[1:]):
                    assert _segment_distance(p, p2, q, q2) >= need, (a["id"], b["id"], p)


def test_every_road_leaves_a_junction_straight_and_on_an_axis_for_25_m(world):
    by_id = {n["id"]: n for n in world["nodes"]}
    for e in world["edges"]:
        for node_id, points in ((e["a"], e["centerline"]), (e["b"], e["centerline"][::-1])):
            if not by_id[node_id].get("townJunction"):
                continue
            h = _heading(points[0], points[1])
            assert min(abs(h - k * math.pi / 2) for k in range(-2, 3)) < 1e-6, (e["id"], node_id)
            for p in points:
                if math.hypot(p["x"] - points[0]["x"], p["z"] - points[0]["z"]) > 25:
                    break
                across = (p["x"] - points[0]["x"]) * math.cos(h) + (p["z"] - points[0]["z"]) * math.sin(h)
                assert abs(across) < 0.05, (e["id"], node_id, p)


def test_speed_limits_keep_lateral_acceleration_under_3_mps2_and_no_bend_is_tighter_than_60_m(world):
    """On a tighter bend the bundle's traffic loses a slowing car ahead (it looks along its own
    heading) and runs into it; the player was rear-ended in a 35 m hairpin."""
    for e in world["edges"]:
        if e["minRadius"] is not None:
            assert e["minRadius"] >= 60, e["id"]
            assert e["speedLimit"] ** 2 / e["minRadius"] <= 3.0 + 1e-6, e["id"]
    limits = {e["kind"]: max(x["speedLimit"] for x in world["edges"] if x["kind"] == e["kind"]) for e in world["edges"]}
    assert limits["harbour"] == pytest.approx(13.8)
    assert limits["pass"] == pytest.approx(9.7)
    assert limits["expressway"] == pytest.approx(27.7)


def test_no_road_turns_more_than_110_degrees_within_150_m(world):
    """The planner looks a few seconds ahead; facing a 180-degree switchback in one view, the mock
    driver chose to reverse and backed into the car behind."""
    for e in world["edges"]:
        pts = e["centerline"]
        heads = [_heading(a, b) for a, b in zip(pts, pts[1:])]
        turn = [0.0]
        for h0, h1 in zip(heads, heads[1:]):
            turn.append(turn[-1] + math.atan2(math.sin(h1 - h0), math.cos(h1 - h0)))
        j = 0
        for i in range(len(turn)):
            while pts[i]["s"] - pts[j]["s"] > 150:
                j += 1
            assert abs(turn[i] - turn[j]) <= math.radians(110), (e["id"], pts[i])


def test_every_junction_approach_has_its_signal_or_stop_sign(world):
    by_id = {n["id"]: n for n in world["nodes"]}
    signs = [o for o in world["objects"] if o["type"] in ("traffic_light", "stop_sign")]
    for n in world["nodes"]:
        mine = [o for o in signs if o["nodeId"] == n["id"]]
        if not n.get("townJunction"):
            assert n["control"] == "none" and not mine, n["id"]
            continue
        near = [o for o in mine if "-far-" not in o["id"]]
        far = [o for o in mine if "-far-" in o["id"]]
        assert len(near) == len(n["neighbors"]), n["id"]
        assert {o["type"] for o in mine} == {"traffic_light" if n["control"] == "signal" else "stop_sign"}, n["id"]
        # #18: every signalled approach also has a far-side head, across the junction on the right,
        # which the onboard camera can still see (and read) from the stop line.
        assert len(far) == (len(n["neighbors"]) if n["control"] == "signal" else 0), n["id"]
        for o in mine:
            # 9 m before (near) or past (far) the junction on the arriving car's right, facing its approach
            assert math.hypot(o["x"] - n["x"], o["z"] - n["z"]) == pytest.approx(math.hypot(9, 6.9), abs=0.01)
            assert min(abs(o["approach"] - k * math.pi / 2) for k in range(-2, 3)) < 1e-6
            fwd = (math.sin(o["approach"]), -math.cos(o["approach"]))
            along = (o["x"] - n["x"]) * fwd[0] + (o["z"] - n["z"]) * fwd[1]
            assert along == pytest.approx(9 if o in far else -9, abs=0.01), o["id"]
    assert by_id["harbour-0-2"]["control"] == "stop", "a two-leg corner stops, it has no cross traffic"
    assert by_id["pass-foot"]["control"] == "stop"


def test_buildings_are_axis_aligned_and_clear_of_every_road(world):
    buildings = [o for o in world["objects"] if o["type"] == "building"]
    assert len(buildings) > 50
    for b in buildings:
        assert b["rotation"] == 0
        for road in world["connectorRoads"]:
            for p in road["points"][::3]:
                dx = max(abs(p["x"] - b["x"]) - b["width"] / 2, 0)
                dz = max(abs(p["z"] - b["z"]) - b["depth"] / 2, 0)
                assert math.hypot(dx, dz) > road["width"] / 2 + 1.5, (b["id"], road["id"])


def test_roads_stay_on_land_at_least_25_m_from_the_sea(world):
    shore = world["visual"]["shoreline"]
    for road in world["connectorRoads"]:
        for p in road["points"][::5]:
            gap = min(_segment_distance(p, p, a, b) for a, b in zip(shore, shore[1:]))
            assert gap >= 25, (road["id"], p)
    bounds = world["bounds"]
    for road in world["connectorRoads"]:
        for p in road["points"]:
            assert bounds["minX"] + 50 < p["x"] < bounds["maxX"] - 50 and bounds["minZ"] + 50 < p["z"] < bounds["maxZ"] - 50


def test_pedestrians_use_the_bundle_format_on_straight_pavements_and_signal_crosswalks():
    out = _js(
        "const w = G.generate(42, 'coast:festival'); let a = 5; const r = () => ((a = (a * 16807) % 2147483647) / 2147483647);"
        "const peds = w.pedestrians(r);"
        "process.stdout.write(JSON.stringify({ peds, nodes: w.nodes.map((n) => ({ id: n.id, control: n.control, legs: n.legs })) }));"
    )
    nodes = {n["id"]: n for n in out["nodes"]}
    peds = out["peds"]
    assert len(peds) == 28
    for p in peds:
        assert set(p) >= {"id", "type", "nodeId", "x", "z", "progress", "walkPath", "direction", "crossing", "jaywalker", "walking", "speed", "width", "depth", "height"}
        assert p["walkPath"]["length"] > 0
        node = nodes[p["nodeId"]]
        if p["crossing"]:
            assert node["control"] == "signal" and "north" in node["legs"], p["id"]
        assert p["jaywalker"] is False, "a jaywalker can hold a junction for good"
    assert any(p["crossing"] for p in peds) and any(not p["crossing"] for p in peds)


def test_free_driving_goes_round_the_destinations_in_order():
    out = _js(
        "const w = G.generate(3, 'coast:harbour'); const seen = [w.destination];"
        "for (let i = 0; i < 6; i++) { const t = w.peekDestination(); w.commitDestination(t.id); seen.push(t.id); }"
        "process.stdout.write(JSON.stringify({ seen, last: w.destination, chain: G.DESTINATIONS }));"
    )
    chain = out["chain"]
    assert out["seen"][0] == "coast-bay", "harbour's next stop round the coast"
    for a, b in zip(out["seen"], out["seen"][1:]):
        assert chain.index(b) == (chain.index(a) + 1) % len(chain)
    assert out["last"] == out["seen"][-1]


def test_the_chain_moves_on_only_when_a_route_to_the_next_stop_is_committed():
    """The bundle asks for the next stop every tick until a route to it builds; asking must not
    skip stops, or a failed reroute would race the chain ahead."""
    out = _js(
        "const w = G.generate(3, 'coast:harbour');"
        "const asked = [w.peekDestination().id, w.peekDestination().id, w.peekDestination().id];"
        "const before = w.destination; w.commitDestination(asked[0]);"
        "process.stdout.write(JSON.stringify({ asked, before, after: w.destination, next: w.peekDestination().id }));"
    )
    assert out["asked"] == ["pass-belvedere"] * 3
    assert out["before"] == "coast-bay" and out["after"] == "pass-belvedere"
    assert out["next"] == "ss1-e400"


def test_navigation_and_crossings_cover_every_road_kind(world):
    out = _js(
        "process.stdout.write(JSON.stringify({ left: G.navigation('left'), straight: G.navigation('straight'), kinds: G.CROSSING_KINDS }));"
    )
    kinds = {e["kind"] for e in world["edges"]}
    assert kinds <= set(out["left"]) and kinds <= set(out["kinds"])
    for kind in kinds:
        text, turn = out["left"][kind]
        assert "left" in text and turn == "left"
        assert out["straight"][kind][1] == "straight"


def test_the_picker_lists_start_points_on_the_coast_and_the_old_maps_elsewhere():
    out = _js(
        "process.stdout.write(JSON.stringify({ coast: G.options('coast:pass'), city: G.options('city'),"
        " labels: [G.pickerLabel('coast:pass'), G.pickerLabel('city')] }));"
    )
    for start in STARTS:
        assert f'value="coast:{start}"' in out["coast"]
    assert 'value="city"' not in out["coast"]
    assert "Horizon" not in out["coast"] and "Solmare Festival" in out["coast"], "no Forza trademark in the UI"
    assert out["city"].count("<option") == 3 and 'value="city"' in out["city"]
    assert out["labels"] == ["Start from", "Change map"]
