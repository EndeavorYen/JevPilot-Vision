# Solmare Coast 第 1 期：路網可開 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自由駕駛改開全新的 Solmare Coast 開放世界地圖：新的路網由打包檔的物理、號誌、交通車與規劃器照常驅動，畫面由新的渲染器畫出地面、海、道路與簡易建築；`lap=1` 維持舊地圖。

**Architecture:** `semif-worldgen.js` 是不碰 DOM 的生成器，主執行緒用 `<script>` 載入，規劃器 worker 在檔頭 import；它輸出和打包檔 Interstate 08 同格式的世界（每條路帶 `path`、`centerline`、`laneOffset`）。打包檔以 37 處精確字串補丁接上生成器，並關掉自己在新地圖上的地面與路面。`semif-world/` 是 ES module 渲染器，包住舊場景層的 hook：新地圖由它畫，其他地圖照舊交給 `semif-scenery.js`。

**Tech Stack:** 打包檔內的 three.js（經 `kit()` hook 交出）、純 JavaScript（不打包、不加相依）、Python pytest + node 子行程測試、Playwright 實機驗證。

**Spec:** `docs/superpowers/specs/2026-10-01-solmare-coast-design.md`（第 1 期 = §8 第 1 項，另含 §3 版圖、§4 架構、§7 測試）

## Global Constraints

- 打包檔沒有原始碼：每處修改都是「原字串只出現一次」的精確替換，列在 `tests/test_coast_patches.py::COAST_PATCHES` 並寫進 `jevpilot_vision/web/BUNDLE_PATCHES.md`。
- 主執行緒（`main-CvLEeHjW.js`）與 worker（`planner.worker-DFdG3q6n.js`）各有一份模擬，兩邊都要修補，並且同一個 seed 與地圖名稱要建出同一個世界。
- `lap=1`：預設世界仍是 `city`、5×5；`window.SEMIF_MAP` 的形狀 `{size, cityTraffic, townTraffic}` 不變（`tests/test_scenery.py::test_benchmark_laps_keep_the_published_map_size`）。
- 生成器：不碰 `window` 與 DOM；不用 `Math.random`；每條路都是雙向、`laneOffset` 3 m；在路口的最後 25 m 是軸向直線；限速下的側向加速度 ≤ 3 m/s²。
- 顏色：`semif-world/` 用到的每個顏色都在 `PALETTE`，在 ×0.55–×1.65 亮度下不落進相機色塊遮罩（`jevpilot_vision/vision.py`）；除了 `"#ffffff"` 之外沒有其他顏色字面值。
- 不新增貼圖或模型檔；不加 npm／pip 相依。測試需要 node（本機 v24；`--input-type=module` 需要 node ≥ 18）。
- 程式碼註解用英文，風格比照 `semif-scenery.js`：簡短，說明「為什麼」。

## Review Focus

1. **自駕車在斑馬線附近排隊時路口卡死**：打包檔的穿越行人若是「闖越者」，只要自駕車在 8–35 m 內就會一直重新過馬路，所有方向都在「禮讓行人」。新地圖的行人一律不闖越（Task 1 的 `jaywalker` 斷言、Task 2 的 `test_a_player_waiting_near_a_crosswalk_does_not_hold_the_junction`）。
2. **頁面內切換出發地點後 worker 建錯地圖**：worker 只收到 `type`，必須是含出發地點的 `coast:<start>`，否則它會在預設出發點的世界上規劃（Task 2 補丁 `coast-worker-message` 由 `test_coast_patches_are_applied_once_and_documented` 鎖住；Task 5 實機切換）。
3. **`lap=1` 或 `?world=city` 意外變成新地圖或新畫面**：預設世界、worker 的舊地圖、渲染器把 hook 轉交舊場景層，各有測試（Task 2 `test_old_maps_still_build_in_the_worker`、Task 3 `test_on_the_coast_the_hooks_draw...`、Task 4 `test_free_driving_opens_on_the_coast_and_a_benchmark_lap_keeps_the_city`）。
4. **抵達後的「下一站」路線建不出來**：打包檔把終點節點重複一次再交給路線產生器，`coast` 的路線產生器原本會丟例外（Task 2 補丁 `coast-same-node`；Task 1 `test_free_driving_goes_round_the_destinations_in_order`；Task 5 實機看到「Next destination」）。
5. **急彎上的追撞與倒車**：打包檔的交通車沿車頭方向找前車，彎太急就跟丟減速的前車；在 180° 連續急彎裡 mock 自駕會選倒車。實測 35 m 髮夾彎兩次被追撞。生成器拒絕半徑 < 60 m 的彎，測試另外鎖住「150 m 內轉向 ≤ 110°」（Task 1 `test_speed_limits_keep_lateral_acceleration_under_3_mps2_and_no_bend_is_tighter_than_60_m`、`test_no_road_turns_more_than_110_degrees_within_150_m`；Task 5 實機跑過山口）。路邊停車佔車道、讓車流永久排隊的問題，由 Task 2 `test_traffic_keeps_moving_for_two_minutes_without_a_crash` 斷言 `parked == 0` 鎖住。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `jevpilot_vision/web/semif-worldgen.js` | 新增 | 地圖生成：節點、道路（圓角折線）、號誌物件、港口建築、行人、目的地鏈、選單選項、導航文字 |
| `jevpilot_vision/web/semif-world/kit.js` | 新增 | 打包檔交出的 THREE 類別、`PALETTE`、材質快取、`Batch` 幾何工具 |
| `jevpilot_vision/web/semif-world/terrain.js` | 新增 | 地面與海床高度場（陸地平、岸外下沉）、海域多邊形 |
| `jevpilot_vision/web/semif-world/water.js` | 新增 | 海面 |
| `jevpilot_vision/web/semif-world/roads.js` | 新增 | 路面、人行道／路肩、標線、路口方塊、斑馬線、停止線 |
| `jevpilot_vision/web/semif-world/buildings.js` | 新增 | 第一版建築（牆與屋頂量體） |
| `jevpilot_vision/web/semif-world/index.js` | 新增 | 包住 `SEMIF_SCENERY` hook，新地圖時組裝場景、畫小地圖 |
| `jevpilot_vision/web/assets/main-CvLEeHjW.js` | 修補 | 22 處（見 Task 2） |
| `jevpilot_vision/web/assets/planner.worker-DFdG3q6n.js` | 修補 | 15 處（見 Task 2） |
| `jevpilot_vision/web/BUNDLE_PATCHES.md` | 修改 | 新增「Solmare Coast」一節 |
| `jevpilot_vision/web/index.html` | 修改 | 預設世界、載入生成器與渲染器 |
| `tests/test_worldgen.py` | 新增 | 生成器的地圖性質 |
| `tests/test_coast_patches.py` | 新增 | 補丁清單與套用、在 node 裡跑 worker 的模擬 |
| `tests/test_world_render.py` | 新增 | 渲染器 hook、幾何、色盤；頁面設定 |
| `docs/visual/solmare-coast/*.jpg`、`README.md` | 新增／修改 | 實機截圖與說明 |

---

### Task 1: 地圖生成器

**Files:**
- Create: `jevpilot_vision/web/semif-worldgen.js`
- Test: `tests/test_worldgen.py`

**Interfaces:**
- Consumes: 無。
- Produces: `globalThis.SEMIF_WORLDGEN = { THEME, KINDS, CROSSING_KINDS, STARTS, DESTINATIONS, JUNCTION_STRAIGHT, MAX_LATERAL, generate(seed, type), navigation(turn), options(type), pickerLabel(type) }`。
  - `generate(seed, "coast" | "coast:<start>")` 回傳世界：`{ seed, type: "coast", start, selectValue: "coast:<start>", theme, nodes, byId, edges, connectorRoads, objects, xs, zs, bounds, startNode, nextNode, destination, destinations, visual: { shoreline: [{x,z}] }, pedestrians(rng) → Pedestrian[28], nextDestination() → node }`。**不含 `route`**；路線由打包檔補丁（Task 2）用它自己的 Dijkstra 和路線產生器排出。
  - 節點：`{ id, x, z, neighbors, control: "signal"|"stop"|"none", offset, townJunction?, legs: ("north"|"east"|"south"|"west")[] }`。
  - 道路：`{ id, a, b, oneWay: false, width, speedLimit, kind, name, length, path, centerline, laneOffset: 3, laneHalfWidth, minRadius }`；`kind` ∈ `harbour | festival | coastal | valley | pass | expressway`。
  - `connectorRoads`：`{ id, points, width, kind, twoWay: true }`（打包檔用它算路面多邊形、畫小地圖；渲染器用它鋪路）。
  - 物件：`traffic_light` / `stop_sign`（`{nodeId, approach, height}`），`building`（`{x, z, width, depth, height, style, rotation: 0}`，同時是碰撞框）。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_worldgen.py`：

```python
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
        assert len(mine) == len(n["neighbors"]), n["id"]
        assert {o["type"] for o in mine} == {"traffic_light" if n["control"] == "signal" else "stop_sign"}, n["id"]
        for o in mine:
            # 9 m before the junction on the arriving car's right, facing its approach
            assert math.hypot(o["x"] - n["x"], o["z"] - n["z"]) == pytest.approx(math.hypot(9, 6.9), abs=0.01)
            assert min(abs(o["approach"] - k * math.pi / 2) for k in range(-2, 3)) < 1e-6
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
        "for (let i = 0; i < 6; i++) seen.push(w.nextDestination().id);"
        "process.stdout.write(JSON.stringify({ seen, last: w.destination, chain: G.DESTINATIONS }));"
    )
    chain = out["chain"]
    assert out["seen"][0] == "coast-bay", "harbour's next stop round the coast"
    for a, b in zip(out["seen"], out["seen"][1:]):
        assert chain.index(b) == (chain.index(a) + 1) % len(chain)
    assert out["last"] == out["seen"][-1]


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
    assert out["city"].count("<option") == 3 and 'value="city"' in out["city"]
    assert out["labels"] == ["Start from", "Change map"]
```

- [ ] **Step 2: 執行，確認失敗**

Run: `python -m pytest -q tests/test_worldgen.py`
Expected: 全部 FAIL，訊息含 `Cannot find module` …`semif-worldgen.js`。

- [ ] **Step 3: 寫生成器**

建立 `jevpilot_vision/web/semif-worldgen.js`：

```js
// Solmare Coast: the open-world map (docs/superpowers/specs/2026-10-01-solmare-coast-design.md).
//
// One hand-laid road network. The seed changes signal offsets, buildings, traffic and people, not
// the roads. The world has the shape of the bundle's own Interstate 08 world (every edge carries a
// path, a centreline and a lane offset; junctions are townJunction nodes), so the bundle's physics,
// signals, traffic and planner drive it unchanged. It runs in the page and in the planner worker:
// no window, no DOM, and the same seed gives the same world in both.
(function (root) {
  "use strict";

  const STEP = 1.5; // path sample spacing, as in the bundle
  const LANE_OFFSET = 3; // every edge is driven 3 m right of its centreline
  const JUNCTION_STRAIGHT = 25; // straight, axis-aligned run every road keeps at a junction
  const MAX_LATERAL = 3; // m/s^2 at the speed limit on the tightest corner of an edge
  // No corner is tighter than this. The bundle's traffic finds the car ahead along its own heading
  // (within 2.35 m sideways), so on a tighter bend it loses a slowing car ahead and runs into it.
  const MIN_RADIUS = 60;
  const KMH = 1 / 3.6;

  const THEME = { name: "Solmare Coast", subtitle: "Sun, sea and the open road.", size: 0, traffic: 36, buildings: 0, limit: 100 * KMH };
  const BOUNDS = { minX: -1250, maxX: 1250, minZ: -800, maxZ: 800 };

  // Road kinds: nominal limit (the tightest corner may lower an edge's own), width, lane half width.
  const KINDS = {
    harbour: { limit: 50 * KMH, width: 12, laneHalfWidth: 3 },
    festival: { limit: 50 * KMH, width: 12, laneHalfWidth: 3 },
    coastal: { limit: 80 * KMH, width: 11, laneHalfWidth: 3 },
    valley: { limit: 70 * KMH, width: 10, laneHalfWidth: 3 },
    pass: { limit: 35 * KMH, width: 10, laneHalfWidth: 3 },
    expressway: { limit: 100 * KMH, width: 22, laneHalfWidth: 2 },
  };
  const CROSSING_KINDS = Object.keys(KINDS);

  // Porto Solmare: a 4 x 3 grid of junctions.
  const HX = [-1100, -1000, -900, -800];
  const HZ = [100, 200, 300];
  const hb = (c, r) => `harbour-${c}-${r}`;

  const NODES = [
    ...HZ.flatMap((z, r) => HX.map((x, c) => ({ id: hb(c, r), x, z }))),
    { id: "harbour-quay", x: -950, z: 300 },
    { id: "festival", x: 0, z: 250 },
    { id: "festival-gate", x: 0, z: 330 },
    { id: "coast-junction", x: 0, z: 520 },
    { id: "coast-bay", x: 555, z: 610 },
    { id: "pass-foot", x: 900, z: 250 },
    { id: "pass-belvedere", x: 1010, z: -10 },
    { id: "pass-top", x: 1120, z: -420 },
    { id: "ss1-west", x: -1100, z: -300 },
    { id: "ss1-w400", x: -400, z: -600 },
    { id: "ss1-junction", x: 0, z: -600 },
    { id: "ss1-e400", x: 400, z: -600 },
    { id: "ss1-e700", x: 700, z: -600 },
  ];
  // Junctions get signals or stop signs, crossings and turn smoothing; the rest are waypoints that
  // only split a road (same heading on both sides, so the lane path stays continuous).
  const JUNCTIONS = new Set([...HZ.flatMap((z, r) => HX.map((x, c) => hb(c, r))), "festival", "coast-junction", "ss1-junction", "pass-foot"]);
  const STOP_JUNCTIONS = new Set(["pass-foot"]);

  const ROW_NAMES = ["Via Garibaldi", "Via Roma", "Lungomare del Porto"];
  const COLUMN_NAMES = ["Via del Faro", "Via dei Pescatori", "Via delle Reti", "Via della Dogana"];

  // [from, to, kind, name, corners as [x, z, radius]]
  const ROADS = [
    ...HZ.flatMap((z, r) => [0, 1, 2].flatMap((c) =>
      r === 2 && c === 1
        ? [[hb(1, 2), "harbour-quay", "harbour", ROW_NAMES[r], []], ["harbour-quay", hb(2, 2), "harbour", ROW_NAMES[r], []]]
        : [[hb(c, r), hb(c + 1, r), "harbour", ROW_NAMES[r], []]])),
    ...[0, 1, 2, 3].flatMap((c) => [0, 1].map((r) => [hb(c, r), hb(c, r + 1), "harbour", COLUMN_NAMES[c], []])),
    [hb(3, 0), "festival", "valley", "Via delle Vigne", [[-620, 100, 90], [-480, -10, 90], [-330, -10, 90], [-200, 250, 90]]],
    ["festival", "pass-foot", "valley", "Strada dei Vigneti", [[180, 250, 100], [330, 120, 100], [520, 120, 100], [680, 250, 100]]],
    [hb(3, 2), "coast-junction", "coastal", "Lungomare Solmare", [[-640, 300, 150], [-420, 450, 150], [-240, 520, 150]]],
    ["coast-junction", "coast-bay", "coastal", "Lungomare Solmare", [[220, 520, 150], [450, 610, 150]]],
    ["coast-bay", "pass-foot", "coastal", "Lungomare Solmare", [[660, 610, 150], [900, 450, 120]]],
    ["festival", "festival-gate", "festival", "Viale del Festival", []],
    ["festival-gate", "coast-junction", "festival", "Viale del Festival", []],
    ["festival", "ss1-junction", "valley", "Strada del Colle", [[0, 120, 120], [-90, -60, 120], [-90, -200, 120], [0, -380, 120]]],
    [hb(0, 0), "ss1-west", "expressway", "SS-1 Costiera", []],
    ["ss1-west", "ss1-w400", "expressway", "SS-1 Costiera", [[-1100, -600, 300]]],
    ["ss1-w400", "ss1-junction", "expressway", "SS-1 Costiera", []],
    ["ss1-junction", "ss1-e400", "expressway", "SS-1 Costiera", []],
    ["ss1-e400", "ss1-e700", "expressway", "SS-1 Costiera", []],
    ["ss1-e700", "pass-top", "expressway", "SS-1 Costiera", [[1120, -600, 160]]],
    // Switchbacks: each bend turns 90 degrees, and two bends that turn the same way have 50 m of
    // straight between them, so the planner never faces a 180-degree turn within its horizon.
    ["pass-top", "pass-belvedere", "pass", "Passo del Falco", [[1120, -180, 60], [900, -180, 60], [900, -10, 60]]],
    ["pass-belvedere", "pass-foot", "pass", "Passo del Falco", [[1120, -10, 60], [1120, 160, 60], [900, 160, 60]]],
  ];
  // The SS-1 slows to 70 km/h on the harbour hill and 80 km/h either side of its junction.
  const EDGE_LIMITS = { [`${hb(0, 0)}>ss1-west`]: 70 * KMH, "ss1-w400>ss1-junction": 80 * KMH, "ss1-junction>ss1-e400": 80 * KMH };

  // Start points: [start node, first node to drive to]. Free driving goes round the destinations.
  const STARTS = {
    festival: ["festival-gate", "festival"],
    harbour: ["harbour-quay", hb(2, 2)],
    coast: ["coast-bay", "pass-foot"],
    pass: ["pass-belvedere", "pass-top"],
    highway: ["ss1-e400", "ss1-junction"],
  };
  const DESTINATIONS = ["festival-gate", "harbour-quay", "coast-bay", "pass-belvedere", "ss1-e400"];
  const START_LABELS = { festival: "Horizon festival", harbour: "Porto Solmare", coast: "Lungomare", pass: "Passo del Falco", highway: "SS-1 Costiera" };

  // The sea lies south and east of this line.
  const SHORELINE = [[-1300, 345], [-760, 345], [-600, 380], [-430, 500], [-240, 560], [220, 560], [450, 650], [660, 650], [800, 600], [960, 470], [980, 330], [1170, 250], [1180, -200], [1300, -300]];

  // --- geometry, in the bundle's conventions: x east, z south, heading 0 north and pi/2 east
  const dist = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);
  const headingOf = (a, b) => Math.atan2(b.x - a.x, a.z - b.z);
  const along = (p, h, d) => ({ x: p.x + Math.sin(h) * d, z: p.z - Math.cos(h) * d });
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

  // Same as the bundle's resampler: points every `step` metres, each with its arc length s.
  function resample(points, step) {
    const out = [{ x: points[0].x, z: points[0].z, s: 0 }];
    let s = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i], len = dist(a, b), n = Math.max(1, Math.ceil(len / step));
      for (let k = 1; k <= n; k++) {
        s += len / n;
        out.push({ x: a.x + (b.x - a.x) * k / n, z: a.z + (b.z - a.z) * k / n, s });
      }
    }
    return out;
  }

  // Same as the bundle's lane shift: each point moved `d` to the right of the local heading.
  function shift(points, d) {
    return points.map((p, i) => along(p, headingOf(points[Math.max(0, i - 1)], points[Math.min(points.length - 1, i + 1)]) + Math.PI / 2, d));
  }

  // Same generator as the bundle's seeded RNG.
  function rng(seed) {
    let t = Number(seed) >>> 0;
    return () => {
      t += 1831565813;
      let e = t;
      e = Math.imul(e ^ (e >>> 15), e | 1);
      e ^= e + Math.imul(e ^ (e >>> 7), e | 61);
      return ((e ^ (e >>> 14)) >>> 0) / 4294967296;
    };
  }
  const pick = (r, list) => list[Math.floor(r() * list.length)];

  // A polyline with each corner rounded to its own radius. Throws when two roundings overlap.
  function fillet(points, label) {
    const out = [{ x: points[0].x, z: points[0].z }];
    const tangent = points.map((p, i) => {
      if (i === 0 || i === points.length - 1 || !p.r) return 0;
      const turn = wrap(headingOf(p, points[i + 1]) - headingOf(points[i - 1], p));
      return p.r * Math.tan(Math.abs(turn) / 2);
    });
    for (let i = 1; i < points.length; i++) {
      if (tangent[i - 1] + tangent[i] > dist(points[i - 1], points[i]) + 1e-6) throw Error(`${label}: corners ${i - 1} and ${i} overlap`);
      if (points[i].r && points[i].r < MIN_RADIUS) throw Error(`${label}: corner ${i} is tighter than ${MIN_RADIUS} m`);
    }
    for (let i = 1; i < points.length - 1; i++) {
      const p = points[i];
      const h1 = headingOf(points[i - 1], p);
      const turn = wrap(headingOf(p, points[i + 1]) - h1);
      if (!tangent[i] || Math.abs(turn) < 1e-9) {
        out.push({ x: p.x, z: p.z });
        continue;
      }
      const side = Math.sign(turn); // +1 turns right
      const centre = along(along(p, h1, -tangent[i]), h1 + side * Math.PI / 2, p.r);
      const n = Math.max(2, Math.ceil((Math.abs(turn) * p.r) / 0.75));
      for (let k = 0; k <= n; k++) out.push(along(centre, h1 + (turn * k) / n - side * Math.PI / 2, p.r));
    }
    out.push({ x: points.at(-1).x, z: points.at(-1).z });
    return out;
  }

  function buildRoads(byId, seed) {
    const edges = [];
    const connectorRoads = [];
    for (const [a, b, kind, name, corners] of ROADS) {
      const A = byId[a], B = byId[b], spec = KINDS[kind];
      const control = [A, ...corners.map(([x, z, r]) => ({ x, z, r })), B];
      const centerline = resample(fillet(control, `${a}>${b}`), STEP);
      const path = resample(shift(centerline, LANE_OFFSET), STEP);
      const minRadius = Math.min(Infinity, ...corners.map((c) => c[2]));
      const cornerLimit = Math.sqrt(MAX_LATERAL * minRadius);
      const speedLimit = Math.floor(Math.min(EDGE_LIMITS[`${a}>${b}`] ?? spec.limit, cornerLimit) * 10) / 10;
      A.neighbors.push(b);
      B.neighbors.push(a);
      const id = `${a}-${b}`;
      edges.push({ id, a, b, oneWay: false, width: spec.width, speedLimit, kind, name, length: path.at(-1).s, path, centerline, laneOffset: LANE_OFFSET, laneHalfWidth: spec.laneHalfWidth, minRadius });
      const h0 = headingOf(centerline[0], centerline[1]);
      const h1 = headingOf(centerline.at(-2), centerline.at(-1));
      connectorRoads.push({ id, points: resample([along(centerline[0], h0, -0.25), ...centerline, along(centerline.at(-1), h1, 0.25)], STEP), width: spec.width, kind, twoWay: true });
    }
    return { edges, connectorRoads };
  }

  // Heading of each road where it reaches `node`, keyed by the neighbour it comes from.
  function approaches(node, edges) {
    const out = [];
    for (const e of edges) {
      if (e.a !== node.id && e.b !== node.id) continue;
      const c = e.centerline;
      const from = e.b === node.id ? e.a : e.b;
      const heading = e.b === node.id ? headingOf(c.at(-2), c.at(-1)) : headingOf(c[1], c[0]);
      out.push({ from, heading });
    }
    return out;
  }

  function controls(nodes, edges) {
    const objects = [];
    for (const n of nodes) {
      if (!n.townJunction) continue;
      for (const { from, heading } of approaches(n, edges)) {
        const p = along(along(n, heading, -9), heading + Math.PI / 2, 6.9);
        objects.push({ id: `${n.control}-${n.id}-${from}`, type: n.control === "stop" ? "stop_sign" : "traffic_light", x: p.x, z: p.z, nodeId: n.id, approach: heading, height: n.control === "stop" ? 2.8 : 4.8 });
      }
    }
    return objects;
  }

  // Harbour blocks: a ring of houses round each block, 17 m back from the street centre lines.
  // Buildings are the bundle's only collision objects, so they stay axis-aligned and off the roads.
  function harbourBuildings(r) {
    const out = [];
    const seen = new Set();
    for (let c = 0; c < HX.length - 1; c++) {
      for (let row = 0; row < HZ.length - 1; row++) {
        const x0 = HX[c] + 17, x1 = HX[c + 1] - 17, z0 = HZ[row] + 17, z1 = HZ[row + 1] - 17;
        const spots = [];
        for (let x = x0; x <= x1 + 1e-6; x += (x1 - x0) / 3) spots.push([x, z0], [x, z1]);
        for (let z = z0; z <= z1 + 1e-6; z += (z1 - z0) / 3) spots.push([x0, z], [x1, z]);
        for (const [x, z] of spots) {
          const key = `${Math.round(x)}:${Math.round(z)}`;
          if (seen.has(key)) continue;
          seen.add(key);
          out.push({ id: `building-${out.length}`, type: "building", style: pick(r, ["townhouse", "townhouse", "villa", "shop"]), x, z, width: 12 + Math.floor(r() * 3), depth: 12 + Math.floor(r() * 3), height: 8 + Math.floor(r() * 3) * 3, rotation: 0 });
        }
      }
    }
    return out;
  }

  // Pedestrians in the bundle's own format. Walkers pace a straight pavement 7.05 m off a street's
  // centre line; crossers use the bundle's crosswalk over the north leg of a signal junction. No one
  // jaywalks: a jaywalker re-crosses whenever the player is 8-35 m away, so a player queued at the
  // junction would hold every approach on "Yield to pedestrian" for ever.
  function pedestrians(world, r) {
    const streets = world.edges.filter((e) => e.kind === "harbour" || e.kind === "festival");
    const crossable = world.nodes.filter((n) => n.control === "signal" && n.legs.includes("north") && (n.id.startsWith("harbour") || n.id.startsWith("festival") || n.id === "coast-junction"));
    const out = [];
    for (let i = 0; i < 28; i++) {
      const e = pick(r, streets);
      const reverse = r() < 0.5;
      const from = world.byId[reverse ? e.b : e.a], to = world.byId[reverse ? e.a : e.b];
      const heading = headingOf(from, to);
      const side = r() < 0.5 ? -1 : 1;
      const start = along(along(from, heading, 14), heading + Math.PI / 2, 7.05 * side);
      const length = e.length - 28;
      const crossing = i % 2 === 0;
      const node = crossing ? pick(r, crossable) : from;
      const progress = crossing ? 0 : r() * length;
      const at = crossing ? { x: node.x - 8, z: node.z - 7.8 } : along(start, heading, progress);
      out.push({
        id: `pedestrian-${i}`, type: "pedestrian", nodeId: node.id, x: at.x, z: at.z, progress,
        walkPath: { start, heading, length }, direction: r() > 0.5 ? 1 : -1, crossing, jaywalker: false,
        walking: false, speed: 0, width: 0.6, depth: 0.6, height: 1.7,
      });
    }
    return out;
  }

  const LEG_NAMES = ["north", "east", "south", "west"];

  function generate(seed, type) {
    const startName = String(type ?? "").split(":")[1];
    const start = STARTS[startName] ? startName : "festival";
    const r = rng(Number(seed) + 7331);
    const nodes = NODES.map((n) => ({
      id: n.id, x: n.x, z: n.z, neighbors: [],
      control: JUNCTIONS.has(n.id) ? (STOP_JUNCTIONS.has(n.id) ? "stop" : "signal") : "none",
      offset: Math.floor(r() * 14),
      ...(JUNCTIONS.has(n.id) ? { townJunction: true } : {}),
    }));
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const { edges, connectorRoads } = buildRoads(byId, seed);
    for (const n of nodes) {
      // Legs are named by the direction a car leaves the junction in.
      n.legs = approaches(n, edges).map(({ heading }) => LEG_NAMES[((Math.round(wrap(heading + Math.PI) / (Math.PI / 2)) % 4) + 4) % 4]);
      if (n.control === "signal" && n.legs.length === 2) n.control = "stop";
    }
    const [startNode, nextNode] = STARTS[start];
    let destinationIndex = (DESTINATIONS.indexOf(startNode) + 1) % DESTINATIONS.length;
    const world = {
      seed, type: "coast", start, selectValue: `coast:${start}`, theme: THEME,
      nodes, byId, edges, connectorRoads,
      objects: [...controls(nodes, edges), ...harbourBuildings(r)],
      xs: [BOUNDS.minX, BOUNDS.maxX], zs: [BOUNDS.minZ, BOUNDS.maxZ], bounds: { ...BOUNDS },
      startNode, nextNode, destination: DESTINATIONS[destinationIndex], destinations: DESTINATIONS.slice(),
      visual: { shoreline: SHORELINE.map(([x, z]) => ({ x, z })) },
    };
    world.pedestrians = (sim) => pedestrians(world, sim);
    // Free driving: the next destination after an arrival is the next one round the coast.
    world.nextDestination = () => {
      destinationIndex = (destinationIndex + 1) % DESTINATIONS.length;
      world.destination = DESTINATIONS[destinationIndex];
      return byId[world.destination];
    };
    return world;
  }

  // Extra rows for the bundle's navigation table, keyed by road kind; `turn` is the next crossing's.
  function navigation(turn) {
    const turning = turn === "left" || turn === "right";
    return {
      harbour: [turning ? `Turn ${turn} in Porto Solmare` : "Continue through Porto Solmare", turn],
      festival: [turning ? `Turn ${turn} at the festival` : "Follow Viale del Festival", turn],
      coastal: [turning ? `Turn ${turn} off the Lungomare` : "Follow the Lungomare", turn],
      valley: [turning ? `Turn ${turn} at the vineyards` : "Follow the valley road", turn],
      pass: [turning ? `Turn ${turn} at the foot of the pass` : "Take the Passo del Falco", turn],
      expressway: [turning ? `Turn ${turn} off the SS-1` : "Follow the SS-1 Costiera", turn],
    };
  }

  // <option>s for the world picker: the start points on the coast, the old maps elsewhere.
  function options(type) {
    if (!String(type).startsWith("coast")) {
      return '<option value="city">Skyline City</option><option value="town">Small town</option><option value="highway">Interstate 08</option>';
    }
    return Object.entries(START_LABELS).map(([k, label]) => `<option value="coast:${k}">${label}</option>`).join("");
  }

  const pickerLabel = (type) => (String(type).startsWith("coast") ? "Start from" : "Change map");

  root.SEMIF_WORLDGEN = { THEME, KINDS, CROSSING_KINDS, STARTS, DESTINATIONS, JUNCTION_STRAIGHT, MAX_LATERAL, MIN_RADIUS, generate, navigation, options, pickerLabel };
})(globalThis);
```

- [ ] **Step 4: 執行，確認通過**

Run: `python -m pytest -q tests/test_worldgen.py`
Expected: `15 passed`

- [ ] **Step 5: Commit**

```bash
git add jevpilot_vision/web/semif-worldgen.js tests/test_worldgen.py
git commit -m "feat(web): Solmare Coast map generator"
```

---

### Task 2: 打包檔補丁（主執行緒與 worker）

**Files:**
- Modify: `jevpilot_vision/web/assets/main-CvLEeHjW.js`（由 `apply()` 套用，不手改）
- Modify: `jevpilot_vision/web/assets/planner.worker-DFdG3q6n.js`（同上）
- Modify: `jevpilot_vision/web/BUNDLE_PATCHES.md`（檔尾新增一節）
- Test: `tests/test_coast_patches.py`

**Interfaces:**
- Consumes: Task 1 的 `SEMIF_WORLDGEN.generate / THEME / navigation / CROSSING_KINDS / options / pickerLabel`，世界上的 `pedestrians(rng)`、`nextDestination()`、`selectValue`。
- Produces: 打包檔接受地圖名稱 `coast` 與 `coast:<start>`；`window.SEMIF_DEFAULT_WORLD`（Task 4 設定）決定沒指定 `world` 時開哪張圖；`world.type === "coast"` 時打包檔不畫自己的地面、路面、路口方塊與 glb 路燈。worker 從規劃訊息讀 `map`（即 `SEMIF_MAP`）。

- [ ] **Step 1: 寫失敗的測試（含補丁清單與套用函式）**

建立 `tests/test_coast_patches.py`：

```python
"""Solmare Coast: the bundle patches, and the bundle's own simulation driven on the coast map.

The page bundle (main) and the planner worker are prebuilt; BUNDLE_PATCHES.md lists every
exact-string patch and why. The worker carries a full copy of the simulation, so node runs it
headless here: routes, traffic, pedestrians and the planner on the coast map, without a browser.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "jevpilot_vision" / "web"
ASSETS = WEB / "assets"
MAIN = "main-CvLEeHjW.js"
WORKER = "planner.worker-DFdG3q6n.js"
WORKER_IMPORT = 'import"/jevpilot/semif-worldgen.js";'

# (name, file, original, replacement): the original occurs once before patching and the
# replacement once after. Apply them once with: python tests/test_coast_patches.py apply
COAST_PATCHES = [
    # --- the map itself, in the page and in the planner worker
    ("coast-generate", MAIN,
     "function pt(e,t=`town`){if(t===`highway`)return dt(e,ft.highway);",
     "function pt(e,t=`town`){if(String(t).startsWith(`coast`)&&globalThis.SEMIF_WORLDGEN){let n=globalThis.SEMIF_WORLDGEN.generate(e,t);return n.route=ht(n,[n.startNode,...mt(n,n.nextNode,n.destination,n.startNode)]),n}if(t===`highway`)return dt(e,ft.highway);"),
    ("coast-generate-worker", WORKER,
     "function y(e,t=`town`){if(t===`highway`)return _(e,v.highway);",
     "function y(e,t=`town`){if(String(t).startsWith(`coast`)&&globalThis.SEMIF_WORLDGEN){let n=globalThis.SEMIF_WORLDGEN.generate(e,t);return n.route=x(n,[n.startNode,...b(n,n.nextNode,n.destination,n.startNode)]),n}if(t===`highway`)return _(e,v.highway);"),
    ("coast-worker-import", WORKER,
     "(function(){let e=(e,t,n)=>Math.max(t,Math.min(n,e))",
     'import"/jevpilot/semif-worldgen.js";(function(){let e=(e,t,n)=>Math.max(t,Math.min(n,e))'),
    ("coast-theme", MAIN,
     "limit:28,laneOffset:9}}",
     "limit:28,laneOffset:9},...globalThis.SEMIF_WORLDGEN?{coast:globalThis.SEMIF_WORLDGEN.THEME}:{}}"),
    ("coast-theme-worker", WORKER,
     "limit:28,laneOffset:9}}",
     "limit:28,laneOffset:9},...globalThis.SEMIF_WORLDGEN?{coast:globalThis.SEMIF_WORLDGEN.THEME}:{}}"),
    # --- routes follow each road's own path
    ("coast-route", MAIN,
     "if(e.type===`highway`)return ut(e,t,n);",
     "if(e.type===`highway`||e.type===`coast`)return ut(e,t,n);"),
    ("coast-route-worker", WORKER,
     "if(e.type===`highway`)return g(e,t,n);",
     "if(e.type===`highway`||e.type===`coast`)return g(e,t,n);"),
    ("coast-same-node", MAIN,
     "if(!f)throw Error(`No drivable connection",
     "if(c===d)continue;if(!f)throw Error(`No drivable connection"),
    ("coast-same-node-worker", WORKER,
     "if(!_)throw Error(`No drivable connection",
     "if(p===g)continue;if(!_)throw Error(`No drivable connection"),
    ("coast-lane-width", MAIN,
     "laneHalfWidth:f.kind===`interstate`?2.25:3",
     "laneHalfWidth:f.laneHalfWidth??(f.kind===`interstate`?2.25:3)"),
    ("coast-lane-width-worker", WORKER,
     "laneHalfWidth:_.kind===`interstate`?2.25:3",
     "laneHalfWidth:_.laneHalfWidth??(_.kind===`interstate`?2.25:3)"),
    ("coast-road-polygons", MAIN,
     "for(let n of e.edges){let r=e.byId[n.a],i=e.byId[n.b],a=l(r,i);t.push(It(",
     "for(let n of e.edges){if(n.path)continue;let r=e.byId[n.a],i=e.byId[n.b],a=l(r,i);t.push(It("),
    ("coast-road-polygons-worker", WORKER,
     "for(let n of e.edges){let r=e.byId[n.a],i=e.byId[n.b],s=a(r,i);t.push(Q(",
     "for(let n of e.edges){if(n.path)continue;let r=e.byId[n.a],i=e.byId[n.b],s=a(r,i);t.push(Q("),
    # --- navigation and speed at junctions
    ("coast-navigation", MAIN,
     "town:[`Stop at the town destination`,`arrive`]}",
     "town:[`Stop at the town destination`,`arrive`],...globalThis.SEMIF_WORLDGEN?.navigation(a)}"),
    ("coast-navigation-worker", WORKER,
     "town:[`Stop at the town destination`,`arrive`]}",
     "town:[`Stop at the town destination`,`arrive`],...globalThis.SEMIF_WORLDGEN?.navigation(c)}"),
    ("coast-turn-distance", MAIN,
     "r&&[`local`,`ramp_turn`].includes(s.kind)",
     "r&&[`local`,`ramp_turn`,...globalThis.SEMIF_WORLDGEN?.CROSSING_KINDS??[]].includes(s.kind)"),
    ("coast-turn-distance-worker", WORKER,
     "o&&[`local`,`ramp_turn`].includes(d.kind)",
     "o&&[`local`,`ramp_turn`,...globalThis.SEMIF_WORLDGEN?.CROSSING_KINDS??[]].includes(d.kind)"),
    ("coast-turn-caps", MAIN, "l=e.phase?1/0:", "l=e.phase&&this.world.type!==`coast`?1/0:"),
    ("coast-turn-caps-worker", WORKER, "l=e.phase?1/0:", "l=e.phase&&this.world.type!==`coast`?1/0:"),
    # --- people and parked cars
    ("coast-pedestrians", MAIN,
     "this.pedestrians=[];for(let e=0;",
     "this.pedestrians=this.world.pedestrians?.(this.r)??[];for(let e=0;!this.world.pedestrians&&"),
    ("coast-pedestrians-worker", WORKER,
     "this.pedestrians=[];for(let e=0;",
     "this.pedestrians=this.world.pedestrians?.(this.r)??[];for(let e=0;!this.world.pedestrians&&"),
    ("coast-no-parked", MAIN,
     "(e===2||e===6)&&(g.parked=!0",
     "(e===2||e===6)&&this.world.type!==`coast`&&(g.parked=!0"),
    ("coast-no-parked-worker", WORKER,
     "(e===2||e===6)&&(g.parked=!0",
     "(e===2||e===6)&&this.world.type!==`coast`&&(g.parked=!0"),
    # --- the worker builds the same map as the page (also fixes 7 x 7 free driving from #11)
    ("coast-worker-message", MAIN,
     "seed:t.world.seed,type:t.world.type,snapshot:r})",
     "seed:t.world.seed,type:t.world.selectValue??t.world.type,map:window.SEMIF_MAP,snapshot:r})"),
    ("coast-worker-map", WORKER,
     "self.onmessage=({data:e})=>{let{id:t,key:n,seed:r,type:i,kind:a,snapshot:o}=e;",
     "self.onmessage=({data:e})=>{let{id:t,key:n,seed:r,type:i,kind:a,snapshot:o}=e;globalThis.SEMIF_MAP=e.map;"),
    ("map-size-city-worker", WORKER,
     "size:5,traffic:28,buildings:.97,limit:18",
     "get size(){return globalThis.SEMIF_MAP?.size??7},get traffic(){return globalThis.SEMIF_MAP?.cityTraffic??40},buildings:.97,limit:18"),
    ("map-size-town-worker", WORKER,
     "size:5,traffic:14,buildings:.62,limit:14",
     "get size(){return globalThis.SEMIF_MAP?.size??7},get traffic(){return globalThis.SEMIF_MAP?.townTraffic??22},buildings:.62,limit:14"),
    # --- picking the map and the start point
    ("coast-default-world", MAIN,
     "vh=gh.get(`world`)||`city`",
     "vh=gh.get(`world`)||window.SEMIF_DEFAULT_WORLD||`city`"),
    ("coast-world-fallback", MAIN,
     "ft[yh]?yh:`city`",
     "ft[yh]||String(yh).startsWith(`coast:`)&&ft.coast?yh:`city`"),
    ("coast-world-picker", MAIN,
     '<label for="world-select">Change map</label><select id="world-select" aria-label="Change map"><option value="city">Skyline City</option><option value="town">Small town</option><option value="highway">Interstate 08</option></select>',
     '<label for="world-select">${globalThis.SEMIF_WORLDGEN?.pickerLabel(yh)??`Change map`}</label><select id="world-select" aria-label="${globalThis.SEMIF_WORLDGEN?.pickerLabel(yh)??`Change map`}">${globalThis.SEMIF_WORLDGEN?.options(yh)??`<option value="city">Skyline City</option><option value="town">Small town</option><option value="highway">Interstate 08</option>`}</select>'),
    ("coast-picker-value", MAIN,
     "Z(`world-select`).value=e.type",
     "Z(`world-select`).value=e.selectValue??e.type"),
    ("coast-new-layout", MAIN,
     "async function ng(r=Q.world.seed,i=Q.world.type)",
     "async function ng(r=Q.world.seed,i=Q.world.selectValue??Q.world.type)"),
    ("coast-next-destination", MAIN,
     "let t=e[Math.floor(this.planRandom()*e.length)];",
     "let t=this.world.nextDestination?.()??e[Math.floor(this.planRandom()*e.length)];"),
    # --- the bundle's own scenery stays off the coast (semif-world/ draws it)
    ("coast-ground", MAIN,
     "X(r,3e3,.8,3e3,0,-.7,0,`#b2c5a0`)",
     "n.type!==`coast`&&X(r,3e3,.8,3e3,0,-.7,0,`#b2c5a0`)"),
    ("coast-roads-off", MAIN,
     "for(let e of n.type===`highway`?[]:n.edges){",
     "for(let e of n.type===`highway`||n.type===`coast`?[]:n.edges){"),
    ("coast-pads-off", MAIN,
     "for(let e of n.nodes.filter(e=>n.type!==`highway`||e.townJunction)){",
     "for(let e of n.nodes.filter(e=>n.type!==`coast`&&(n.type!==`highway`||e.townJunction))){"),
    ("coast-streetlights-off", MAIN,
     "async streetlights(){if(this.world.type===`highway`)return;",
     "async streetlights(){if(this.world.type===`highway`||this.world.type===`coast`)return;"),
]


def apply() -> None:
    texts = {}
    for name, file, old, new in COAST_PATCHES:
        text = texts.setdefault(file, (ASSETS / file).read_text(encoding="utf-8"))
        assert text.count(old) == 1, f"{name}: original found {text.count(old)} times"
        texts[file] = text.replace(old, new)
    for file, text in texts.items():
        (ASSETS / file).write_text(text, encoding="utf-8")


def test_coast_patches_are_applied_once_and_documented():
    texts = {f: (ASSETS / f).read_text(encoding="utf-8") for f in (MAIN, WORKER)}
    doc = (WEB / "BUNDLE_PATCHES.md").read_text(encoding="utf-8")
    for name, file, old, new in COAST_PATCHES:
        text = texts[file]
        assert text.count(new) == 1, name
        assert text.count(old) == (1 if old in new else 0), f"{name}: original still present"
        assert f"`{name}`" in doc, f"{name} missing from BUNDLE_PATCHES.md"
    assert texts[WORKER].startswith(WORKER_IMPORT), "the worker loads the generator before anything else"


# The worker file, run in node: its import is replaced by loading the generator directly, and its
# simulation class (Ae), Dijkstra (b), route builder (g) and map builder (y) are exposed.
_PRELUDE = r"""
const fs = require("fs");
const vm = require("vm");
const [worldgen, worker] = process.argv.slice(1, 3);
require(worldgen);
globalThis.self = globalThis;
let src = fs.readFileSync(worker, "utf8");
const IMPORT = %(imp)s;
if (!src.startsWith(IMPORT)) throw Error("worker does not import the generator");
src = src.slice(IMPORT.length).replace("self.onmessage=", "self.__test={Ae,b,g,y};self.onmessage=");
vm.runInThisContext(src);
const { Ae, b, g, y } = self.__test;
const dist = (p, q) => Math.hypot(p.x - q.x, p.z - q.z);
const out = (v) => process.stdout.write(JSON.stringify(v));
""" % {"imp": json.dumps(WORKER_IMPORT)}


def _sim(body: str):
    proc = subprocess.run(
        ["node", "-e", _PRELUDE + body, str(WEB / "semif-worldgen.js"), str(ASSETS / WORKER)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:] or "node failed")
    return json.loads(proc.stdout)


def test_every_move_through_a_node_keeps_a_continuous_lane():
    """Traffic picks any neighbour at a node; the bundle's own route builder must not jump lanes."""
    jumps = _sim(
        "const w = new Ae(42, 'coast:festival').world; const bad = [];"
        "for (const v of w.nodes) for (const u of v.neighbors) for (const x of v.neighbors) {"
        "  if (x === u) continue; const r = g(w, [u, v.id, x]);"
        "  for (let i = 1; i < r.points.length; i++) if (dist(r.points[i - 1], r.points[i]) > 2.2) { bad.push([u, v.id, x]); break; }"
        "}"
        "out(bad);"
    )
    assert jumps == []


def test_the_bundles_dijkstra_reaches_every_node_from_every_node():
    failures = _sim(
        "const w = new Ae(42, 'coast:festival').world; const bad = [];"
        "for (const s of w.nodes) for (const t of w.nodes) if (s !== t) { try { b(w, s.id, t.id); } catch (e) { bad.push([s.id, t.id]); } }"
        "out(bad);"
    )
    assert failures == []


@pytest.mark.parametrize("start", ["festival", "harbour", "coast", "pass", "highway"])
def test_each_start_point_gets_a_route_to_its_next_destination(start):
    got = _sim(
        f"const s = new Ae(42, 'coast:{start}'); const w = s.world;"
        "out({ type: w.type, ids: w.route.ids, startNode: w.startNode, destination: w.destination, length: w.route.length,"
        "  player: [s.player.x, s.player.z], first: w.route.points[0] });"
    )
    assert got["type"] == "coast"
    assert got["ids"][0] == got["startNode"] and got["ids"][-1] == got["destination"]
    assert 500 < got["length"] < 4000
    assert got["player"] == pytest.approx([got["first"]["x"], got["first"]["z"]])


def test_traffic_keeps_moving_for_two_minutes_without_a_crash():
    got = _sim(
        "const s = new Ae(42, 'coast:festival');"
        "Object.assign(s.player, { x: -1240, z: -790, speed: 0 });"  # parked out of the way
        "const moved = new Map(), last = new Map(s.traffic.map((c) => [c.id, { x: c.x, z: c.z }]));"
        "for (let i = 0; i < 2400; i++) { s.step(0.05);"
        "  for (const c of s.traffic) { const d = dist(last.get(c.id), c); if (d < 20) moved.set(c.id, (moved.get(c.id) || 0) + d); last.set(c.id, { x: c.x, z: c.z }); } }"
        "out({ n: s.traffic.length, parked: s.traffic.filter((c) => c.parked).length, slow: s.traffic.filter((c) => (moved.get(c.id) || 0) < 200).map((c) => c.id),"
        "  crash: s.crash, peds: s.pedestrians.length });"
    )
    assert got["n"] >= 30 and got["parked"] == 0
    assert got["slow"] == [], "every car drives at least 200 m in two minutes"
    assert got["crash"] is None
    assert got["peds"] == 28


def test_a_player_waiting_near_a_crosswalk_does_not_hold_the_junction():
    """A jaywalker re-crosses whenever the player is 8-35 m away; with one, a player queued at a
    junction kept every approach on "Yield to pedestrian" for good. Wait beside each crosswalk."""
    got = _sim(
        "const res = [];"
        "for (const seed of [42, 7]) { const s = new Ae(seed, 'coast:festival');"
        "  const n = s.world.byId[s.pedestrians.find((p) => p.crossing).nodeId];"
        "  Object.assign(s.player, { x: n.x - 9.5, z: n.z + 20, speed: 0 });"  # on the pavement, 22 m off
        "  const moved = new Map(), last = new Map(s.traffic.map((c) => [c.id, { x: c.x, z: c.z }]));"
        "  for (let i = 0; i < 2400; i++) { s.step(0.05);"
        "    for (const c of s.traffic) { const d = dist(last.get(c.id), c); if (d < 20) moved.set(c.id, (moved.get(c.id) || 0) + d); last.set(c.id, { x: c.x, z: c.z }); } }"
        "  res.push({ node: n.id, slow: s.traffic.filter((c) => (moved.get(c.id) || 0) < 200).map((c) => c.id), crash: s.crash }); }"
        "out(res);"
    )
    for r in got:
        assert r["slow"] == [] and r["crash"] is None, r


def test_the_planner_decides_all_along_each_start_route():
    got = _sim(
        "const res = [];"
        "for (const start of Object.keys(globalThis.SEMIF_WORLDGEN.STARTS)) {"
        "  const s = new Ae(42, 'coast:' + start); const pts = s.world.route.points;"
        "  for (let at = 0; at < s.world.route.length - 20; at += 150) {"
        "    const p = pts.find((q) => q.s >= at), q = pts.find((r) => r.s >= at + 2);"
        "    Object.assign(s.player, { x: p.x, z: p.z, s: p.s, heading: Math.atan2(q.x - p.x, p.z - q.z), speed: 8 });"
        "    s.lastPlan = null; const st = s.decisionState();"
        "    res.push({ start, at, vectors: Object.keys(st.vectors).length, limit: st.limit_mps });"
        "  }"
        "}"
        "out(res);"
    )
    assert len(got) > 40
    for r in got:
        assert r["vectors"] > 0, r
        assert 9 <= r["limit"] <= 28, r


def test_street_limits_hold_for_traffic_too():
    """Scripted and fleet cars both drive under the simulation's speed envelope."""
    got = _sim(
        "const s = new Ae(42, 'coast:festival'); const over = [];"
        "for (let i = 0; i < 600; i++) { s.step(0.05);"
        "  for (const c of s.traffic) { const sec = c.route.sections.find((x) => x.endS > c.s) || c.route.sections.at(-1);"
        "    const env = s.speedEnvelope(c).max; if (env > sec.speedLimit + 0.01) over.push([c.id, sec.kind, env, sec.speedLimit]); } }"
        "out(over.slice(0, 5));"
    )
    assert got == []


def test_the_worker_builds_the_map_size_the_page_uses():
    """The page sends its map size; before this the worker always planned on the 5 x 5 grid (#11)."""
    got = _sim(
        "globalThis.SEMIF_MAP = { size: 7, cityTraffic: 40, townTraffic: 22 }; const seven = new Ae(42, 'city').world.nodes.length;"
        "globalThis.SEMIF_MAP = { size: 5, cityTraffic: 28, townTraffic: 14 }; const five = new Ae(42, 'city').world.nodes.length;"
        "globalThis.SEMIF_MAP = undefined; const missing = new Ae(42, 'town').world.nodes.length;"
        "out({ seven, five, missing });"
    )
    assert got == {"seven": 49, "five": 25, "missing": 49}


def test_old_maps_still_build_in_the_worker():
    got = _sim(
        "globalThis.SEMIF_MAP = { size: 5, cityTraffic: 28, townTraffic: 14 };"
        "out(['city', 'town', 'highway'].map((t) => { const s = new Ae(42, t); return [s.world.type, s.pedestrians.length, s.traffic.filter((c) => c.parked).length]; }));"
    )
    assert got == [["city", 52, 2], ["town", 28, 2], ["highway", 0, 2]]


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["apply"]:
        apply()
        print(f"applied {len(COAST_PATCHES)} patches")
```

- [ ] **Step 2: 執行，確認失敗**

Run: `python -m pytest -q tests/test_coast_patches.py`
Expected: 全部 FAIL。`test_coast_patches_are_applied_once_and_documented` 是 `AssertionError: coast-generate`；模擬類測試是 `worker does not import the generator`。

- [ ] **Step 3: 套用補丁**

Run: `python tests/test_coast_patches.py apply`
Expected: `applied 37 patches`（只執行一次；第二次會因原字串不存在而停下）。

- [ ] **Step 4: 在 `BUNDLE_PATCHES.md` 檔尾加上這一節**

```markdown
## Solmare Coast（`coast` 地圖）

自由駕駛改開 `semif-worldgen.js` 生成的 Solmare Coast。打包檔裡有兩份模擬：頁面上的 `main-CvLEeHjW.js`（main），以及規劃器 worker `planner.worker-DFdG3q6n.js`（wk）。worker 拿到 seed 和地圖名稱後，會自己重建一次世界，所以兩份都要修補。原字串與替換字串的全文在 `tests/test_coast_patches.py::COAST_PATCHES`；該測試會鎖住每一處只出現一次，並在 node 裡用 worker 的模擬實際跑這張地圖。

| 名稱 | 檔案 | 改了什麼 | 為什麼 |
|---|---|---|---|
| `coast-generate`、`coast-generate-worker` | main、wk | `coast` 或 `coast:<出發地點>` 交給 `SEMIF_WORLDGEN.generate`，再用打包檔自己的 Dijkstra 和路線產生器排出第一條路線 | 新地圖的入口 |
| `coast-worker-import` | wk | 檔頭 `import"/jevpilot/semif-worldgen.js"` | worker 沒有 `window`，要自己載入生成器 |
| `coast-theme`、`coast-theme-worker` | main、wk | 主題表加入 `coast` | 交通車數量與最高速度；`?world=coast` 也要找得到 |
| `coast-route`、`coast-route-worker` | main、wk | `coast` 的路線沿每條路自己的 `path` 走 | 原本只有 Interstate 這樣做，棋盤圖會走直線 |
| `coast-same-node`、`coast-same-node-worker` | main、wk | 路線產生器跳過相鄰兩個相同的節點 | 自由駕駛的「下一站」路線會把終點節點重複一次，原本會丟例外 |
| `coast-lane-width`、`coast-lane-width-worker` | main、wk | 車道半寬先讀路段自己的 `laneHalfWidth` | SS-1 每條車道 4 m，其他路 6 m |
| `coast-road-polygons`、`coast-road-polygons-worker` | main、wk | 帶 `path` 的路段不再用兩端點的直線長方形當路面 | 彎路的路面改由 `connectorRoads` 提供 |
| `coast-navigation`、`coast-navigation-worker` | main、wk | 導航文字表加入新的路段種類 | 未知種類會讓每次導航都丟例外 |
| `coast-turn-distance`、`coast-turn-distance-worker` | main、wk | 新的路段種類以下一個路口算轉彎距離 | 原本只有 `local` 這樣算 |
| `coast-turn-caps`、`coast-turn-caps-worker` | main、wk | 路口轉彎的減速在 `coast` 照常生效 | 打包檔在路線帶路段資訊時會關掉它；港口的號誌路口需要它 |
| `coast-pedestrians`、`coast-pedestrians-worker` | main、wk | 行人由 `world.pedestrians()` 產生 | 原本的步道是兩節點間的直線，在彎路上會走到路外 |
| `coast-no-parked`、`coast-no-parked-worker` | main、wk | `coast` 不產生停在車道上的交通車 | 停車只右移 1.6 m，仍佔車道，後車不超車會永久排隊 |
| `coast-worker-message`、`coast-worker-map` | main、wk | 規劃請求附上地圖名稱（含出發地點）與 `SEMIF_MAP`，worker 先設好再建世界 | worker 才能建出和頁面相同的地圖 |
| `map-size-city-worker`、`map-size-town-worker` | wk | worker 的城市、小鎮尺寸改讀 `SEMIF_MAP`（getter） | 修正 #11 的問題：自由駕駛 7×7 時，worker 原本一直在 5×5 地圖上規劃。`lap=1` 本來就是 5×5，不受影響 |
| `coast-default-world`、`coast-world-fallback` | main | 沒指定 `world` 時，改用 `index.html` 設的 `SEMIF_DEFAULT_WORLD`；`coast:<出發地點>` 是合法的地圖名稱 | 自由駕駛預設開新地圖，`lap=1` 維持城市 |
| `coast-world-picker`、`coast-picker-value`、`coast-new-layout` | main | 新地圖上，選單改為「Start from」加 5 個出發地點；「New layout」保留出發地點 | 舊地圖不再列在新地圖的選單裡 |
| `coast-next-destination` | main | 抵達後的下一站依固定的目的地鏈 | 原本是隨機挑一個節點 |
| `coast-ground`、`coast-roads-off`、`coast-pads-off`、`coast-streetlights-off` | main | `coast` 不畫打包檔的地面、直線路面、路口方塊和 glb 路燈 | 這些都由 `semif-world/` 負責 |
```

- [ ] **Step 5: 執行，確認通過；舊補丁測試仍通過**

Run: `python -m pytest -q tests/test_coast_patches.py tests/test_scenery.py`
Expected: 全部 PASS（`test_coast_patches.py` 14 個，約 30 秒）。

- [ ] **Step 6: Commit**

```bash
git add jevpilot_vision/web/assets/main-CvLEeHjW.js jevpilot_vision/web/assets/planner.worker-DFdG3q6n.js jevpilot_vision/web/BUNDLE_PATCHES.md tests/test_coast_patches.py
git commit -m "feat(web): bundle drives the Solmare Coast; worker builds the page's map"
```

---

### Task 3: 渲染器 `semif-world/`

**Files:**
- Create: `jevpilot_vision/web/semif-world/kit.js`、`terrain.js`、`water.js`、`roads.js`、`buildings.js`、`index.js`
- Test: `tests/test_world_render.py`（本 Task 建立；Task 4 再加入頁面測試）

**Interfaces:**
- Consumes: 打包檔 `build()` 傳給 `SEMIF_SCENERY.kit()` 的 THREE 類別（`Group, Mesh, BufferGeometry, Float32BufferAttribute, MeshStandardMaterial, Color`）；`window.SEMIF_SIM.world`（Task 1 的世界）；`built(view)` 的 `view.sim.world`、`view.scene`。
- Produces: `window.SEMIF_SCENERY = { palette, kit, object, built, minimap }`，包住原本 `semif-scenery.js` 的同名 hook。`world.type === "coast"` 時，`built` 在 `view.scene` 加入名為 `semif-world` 的群組（子群組 `semif-terrain`、`semif-sea`、`semif-roads`、`semif-buildings`）；`object` 對 `building` 回傳 `true`（由我們畫）。其他地圖時每個 hook 都原樣轉交舊場景層。
  - `kit.js`：`PALETTE`、`T`、`setKit(kit)`、`resetCaches()`、`material(color, opts)`、`headingOf`、`along`、`headingAt`、`class Batch { tri, quad, ribbon, rect, box, empty, mesh }`。
  - `terrain.js`：`seaPolygon(shoreline, bounds)`、`inside(poly, p)`、`distanceToLine(line, p)`、`groundHeight(world, p)`、`buildTerrain(world)`。
  - `water.js`：`SEA_LEVEL`、`buildSea()`。`roads.js`：`buildRoads(world)`。`buildings.js`：`buildBuildings(world)`。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_world_render.py`（先只放渲染器測試；頁面測試在 Task 4 加入）：

```python
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
```

- [ ] **Step 2: 執行，確認失敗**

Run: `python -m pytest -q tests/test_world_render.py`
Expected: `6 failed, 1 passed`。失敗訊息含 `ERR_MODULE_NOT_FOUND` …`semif-world`；`test_renderer_colours_are_all_in_the_palette` 在資料夾還不存在時以空集合通過。

- [ ] **Step 3: 寫 `kit.js`**

```js
// Solmare Coast renderer: the bundle's three.js classes, the palette and small geometry helpers.
//
// The onboard camera reads lights, construction, warning lights and people by colour
// (jevpilot_vision/vision.py). Every colour the coast renderer uses is in PALETTE, so
// tests/test_world_render.py can keep it out of those masks; no other colour literal is allowed.

export const PALETTE = {
  asphalt: "#4d5257",
  marking: "#e9e6da",
  pavement: "#cfc6b2",
  shoulder: "#a89c84",
  median: "#a7a59d",
  grass: ["#9aa36b", "#a7a874", "#8f9a63"],
  sand: "#d8cba6",
  seabed: "#7fa79d",
  sea: "#3f8f93",
  stucco: ["#efe6d6", "#e9d8bf", "#f2e2cf", "#dfe3d6", "#e8d2c4"],
  roof: ["#b8826f", "#a9806f", "#9c8a7c"],
  minimap: { sea: "#cfe3ea", building: "#dcdfe4" },
};

// The bundle's three.js classes, handed over by its build() through the kit() hook.
export const T = {};
export function setKit(kit) {
  Object.assign(T, kit);
}

const materials = new Map();
export function resetCaches() {
  materials.clear();
}

export function material(color, opts = {}) {
  const key = `${color}|${JSON.stringify(opts)}`;
  if (!materials.has(key)) materials.set(key, new T.MeshStandardMaterial({ color, roughness: 0.9, metalness: 0, ...opts }));
  return materials.get(key);
}

// Geometry, in the bundle's conventions: x east, z south, heading 0 north and pi/2 east.
export const headingOf = (a, b) => Math.atan2(b.x - a.x, a.z - b.z);
export const along = (p, h, d) => ({ x: p.x + Math.sin(h) * d, z: p.z - Math.cos(h) * d });

// Heading of a polyline at point i, from its neighbours.
export function headingAt(points, i) {
  return headingOf(points[Math.max(0, i - 1)], points[Math.min(points.length - 1, i + 1)]);
}

// Triangles collected per material and drawn as one mesh.
export class Batch {
  constructor() {
    this.positions = [];
    this.colors = null;
  }

  // One upward-facing triangle; the winding is fixed here so callers need not care.
  tri(a, b, c) {
    const ux = b.x - a.x, uz = b.z - a.z, vx = c.x - a.x, vz = c.z - a.z;
    // y of (b - a) x (c - a) for points on the ground plane
    const up = uz * vx - ux * vz > 0;
    for (const p of up ? [a, b, c] : [a, c, b]) this.positions.push(p.x, p.y ?? 0, p.z);
  }

  quad(a, b, c, d) {
    this.tri(a, b, c);
    this.tri(a, c, d);
  }

  // A strip `left`..`right` metres to the right of a polyline (negative is left), at height y.
  ribbon(points, left, right, y, from = 0, to = points.length - 1) {
    for (let i = from; i < to; i++) {
      const h0 = headingAt(points, i), h1 = headingAt(points, i + 1);
      const a = { ...along(points[i], h0 + Math.PI / 2, left), y };
      const b = { ...along(points[i], h0 + Math.PI / 2, right), y };
      const c = { ...along(points[i + 1], h1 + Math.PI / 2, right), y };
      const d = { ...along(points[i + 1], h1 + Math.PI / 2, left), y };
      this.quad(a, b, c, d);
    }
  }

  // A rectangle centred on p, `length` along heading h and `width` across it.
  rect(p, h, length, width, y) {
    const f = along(p, h, length / 2), r = along(p, h, -length / 2);
    const s = h + Math.PI / 2;
    this.quad({ ...along(f, s, -width / 2), y }, { ...along(f, s, width / 2), y }, { ...along(r, s, width / 2), y }, { ...along(r, s, -width / 2), y });
  }

  // An axis-aligned box standing on the ground: four walls and a top.
  box(x, z, w, d, h, y0 = 0) {
    const x0 = x - w / 2, x1 = x + w / 2, z0 = z - d / 2, z1 = z + d / 2, y1 = y0 + h;
    const v = (px, py, pz) => [px, py, pz];
    const faces = [
      [v(x0, y1, z0), v(x0, y1, z1), v(x1, y1, z1), v(x1, y1, z0)], // top
      [v(x0, y0, z1), v(x1, y0, z1), v(x1, y1, z1), v(x0, y1, z1)], // south
      [v(x1, y0, z0), v(x0, y0, z0), v(x0, y1, z0), v(x1, y1, z0)], // north
      [v(x1, y0, z1), v(x1, y0, z0), v(x1, y1, z0), v(x1, y1, z1)], // east
      [v(x0, y0, z0), v(x0, y0, z1), v(x0, y1, z1), v(x0, y1, z0)], // west
    ];
    for (const [a, b, c, d] of faces) this.positions.push(...a, ...b, ...c, ...a, ...c, ...d);
  }

  get empty() {
    return this.positions.length === 0;
  }

  mesh(mat, { cast = false, receive = true } = {}) {
    const geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.Float32BufferAttribute(this.positions, 3));
    if (this.colors) geo.setAttribute("color", new T.Float32BufferAttribute(this.colors, 3));
    geo.computeVertexNormals();
    const mesh = new T.Mesh(geo, mat);
    mesh.castShadow = cast;
    mesh.receiveShadow = receive;
    return mesh;
  }
}
```

- [ ] **Step 4: 寫 `terrain.js`**

```js
// Ground and seabed: one height-field mesh. Land is flat at the road's level (the simulation is
// flat); below the shoreline the ground shelves down under the sea surface.
import { PALETTE, T, Batch, material } from "./kit.js";

const CELL = 10;
const MARGIN = 300; // ground beyond the drivable bounds, so the horizon is not an edge
const SHELF = 0.12; // seabed drop per metre from the shoreline
const SEABED = -6;

// The sea is the polygon closed by the shoreline and the map's south-east corner beyond it.
export function seaPolygon(shoreline, bounds) {
  const far = 4000;
  const first = shoreline[0], last = shoreline.at(-1);
  return [...shoreline, { x: last.x + far, z: last.z }, { x: last.x + far, z: bounds.maxZ + far }, { x: first.x - far, z: bounds.maxZ + far }, { x: first.x - far, z: first.z }];
}

export function inside(poly, p) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) hit = !hit;
  }
  return hit;
}

export function distanceToLine(line, p) {
  let best = Infinity;
  for (let i = 0; i < line.length - 1; i++) {
    const a = line[i], b = line[i + 1], dx = b.x - a.x, dz = b.z - a.z, len2 = dx * dx + dz * dz;
    const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.z - a.z) * dz) / len2));
    best = Math.min(best, Math.hypot(p.x - a.x - t * dx, p.z - a.z - t * dz));
  }
  return best;
}

// Height of the ground at p: 0 on land, shelving to SEABED under the sea.
export function groundHeight(world, p, sea = seaPolygon(world.visual.shoreline, world.bounds)) {
  if (!inside(sea, p)) return -0.05;
  return Math.max(SEABED, -0.05 - distanceToLine(world.visual.shoreline, p) * SHELF);
}

// Linear RGB for a vertex colour; three.js converts the sRGB hex when it builds the Color.
function linear(hex) {
  const c = new T.Color(hex);
  return [c.r, c.g, c.b];
}

export function buildTerrain(world) {
  const { bounds } = world;
  const sea = seaPolygon(world.visual.shoreline, bounds);
  const x0 = bounds.minX - MARGIN, x1 = bounds.maxX + MARGIN, z0 = bounds.minZ - MARGIN, z1 = bounds.maxZ + MARGIN;
  const nx = Math.round((x1 - x0) / CELL), nz = Math.round((z1 - z0) / CELL);
  const grass = PALETTE.grass.map(linear), sand = linear(PALETTE.sand), seabed = linear(PALETTE.seabed);
  const vertex = [];
  for (let j = 0; j <= nz; j++) {
    const row = [];
    for (let i = 0; i <= nx; i++) {
      const p = { x: x0 + i * CELL, z: z0 + j * CELL };
      const wet = inside(sea, p);
      const shore = distanceToLine(world.visual.shoreline, p);
      const y = wet ? Math.max(SEABED, -0.05 - shore * SHELF) : -0.05;
      const colour = wet ? (shore < 12 ? sand : seabed) : shore < 25 ? sand : grass[(i * 7 + j * 13) % grass.length];
      row.push({ x: p.x, y, z: p.z, colour });
    }
    vertex.push(row);
  }
  const batch = new Batch();
  batch.colors = [];
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const a = vertex[j][i], b = vertex[j][i + 1], c = vertex[j + 1][i + 1], d = vertex[j + 1][i];
      for (const [p, q, r] of [[a, d, c], [a, c, b]]) {
        for (const v of [p, q, r]) {
          batch.positions.push(v.x, v.y, v.z);
          batch.colors.push(...v.colour);
        }
      }
    }
  }
  const mesh = batch.mesh(material("#ffffff", { vertexColors: true }));
  mesh.name = "semif-terrain";
  return mesh;
}
```

- [ ] **Step 5: 寫 `water.js`**

```js
// The sea surface: one flat sheet just below the road level, reaching past the far plane.
import { PALETTE, Batch, material } from "./kit.js";

export const SEA_LEVEL = -0.6;
const REACH = 6000;

export function buildSea() {
  const batch = new Batch();
  const y = SEA_LEVEL;
  batch.quad({ x: -REACH, y, z: -REACH }, { x: REACH, y, z: -REACH }, { x: REACH, y, z: REACH }, { x: -REACH, y, z: REACH });
  const mesh = batch.mesh(material(PALETTE.sea, { roughness: 0.25, metalness: 0.1 }), { receive: false });
  mesh.name = "semif-sea";
  return mesh;
}
```

- [ ] **Step 6: 寫 `roads.js`**

```js
// Roads: asphalt, pavements or shoulders and markings along every road's centre line, and a pad
// with crosswalks and stop bars at every junction. Any heading works; junction legs are straight
// and axis-aligned for their last 25 m (semif-worldgen.js), which is where crosswalks sit.
import { PALETTE, T, Batch, material, along, headingOf } from "./kit.js";

const PAVEMENT = 3.6; // harbour and festival streets have raised pavements
const SHOULDER = 2;
const DASH = 3;
const DASH_GAP = 6;
const LINE = 0.15;
const KERB_HEIGHT = 0.14;
const CLEAR = 13; // markings stop this far from a junction centre
const CROSSWALK_AT = 7.5; // as the bundle: pedestrians cross 7-8 m out from the junction
const STOP_BAR_AT = 10.5; // as the bundle's crossing stop line

const URBAN = new Set(["harbour", "festival"]);

// Index ranges of `points` that are at least `clear` metres from every junction.
function openRuns(points, junctions, clear) {
  const runs = [];
  let start = -1;
  for (let i = 0; i < points.length; i++) {
    const open = junctions.every((n) => Math.hypot(points[i].x - n.x, points[i].z - n.z) >= clear);
    if (open && start < 0) start = i;
    if (!open && start >= 0) {
      if (i - 1 > start) runs.push([start, i - 1]);
      start = -1;
    }
  }
  if (start >= 0 && points.length - 1 > start) runs.push([start, points.length - 1]);
  return runs;
}

function dashes(batch, points, offset, runs, y) {
  for (const [from, to] of runs) {
    for (let i = from; i < to; i++) {
      if (points[i].s % (DASH + DASH_GAP) < DASH) batch.ribbon(points, offset - LINE / 2, offset + LINE / 2, y, i, i + 1);
    }
  }
}

function solid(batch, points, offset, runs, y) {
  for (const [from, to] of runs) batch.ribbon(points, offset - LINE / 2, offset + LINE / 2, y, from, to);
}

export function buildRoads(world) {
  const asphalt = new Batch(), pavement = new Batch(), shoulder = new Batch(), median = new Batch(), marking = new Batch();
  const junctions = world.nodes.filter((n) => n.townJunction);

  for (const road of world.connectorRoads) {
    const pts = road.points, half = road.width / 2;
    asphalt.ribbon(pts, -half, half, 0.03);
    if (URBAN.has(road.kind)) {
      pavement.ribbon(pts, half, half + PAVEMENT, KERB_HEIGHT);
      pavement.ribbon(pts, -half - PAVEMENT, -half, KERB_HEIGHT);
    } else {
      shoulder.ribbon(pts, half, half + SHOULDER, 0.02);
      shoulder.ribbon(pts, -half - SHOULDER, -half, 0.02);
    }
    const runs = openRuns(pts, junctions, CLEAR);
    if (road.kind === "expressway") {
      median.ribbon(pts, -1, 1, 0.12);
      for (const side of [-1, 1]) {
        dashes(marking, pts, side * 5, runs, 0.045);
        solid(marking, pts, side * (half - 2.4), runs, 0.045);
      }
    } else {
      dashes(marking, pts, 0, runs, 0.045);
      if (!URBAN.has(road.kind)) for (const side of [-1, 1]) solid(marking, pts, side * (half - 0.35), runs, 0.045);
    }
  }

  for (const node of junctions) {
    const legs = world.edges.filter((e) => e.a === node.id || e.b === node.id);
    const half = Math.max(...legs.map((e) => e.width / 2)) + 1;
    asphalt.rect(node, 0, half * 2, half * 2, 0.035);
    for (const e of legs) {
      const c = e.a === node.id ? e.centerline : [...e.centerline].reverse();
      const out = headingOf(c[0], c[1]); // leaving the junction along this leg
      const w = e.width / 2;
      if (node.control === "signal") {
        const centre = along(node, out, CROSSWALK_AT);
        for (let t = -w + 0.6; t <= w - 0.6; t += 1.2) marking.rect(along(centre, out + Math.PI / 2, t), out, 3, 0.6, 0.05);
      }
      // The stop bar spans the arriving car's lane: right of the arriving heading.
      const arrive = out + Math.PI;
      const bar = along(node, out, STOP_BAR_AT);
      marking.rect(along(bar, arrive + Math.PI / 2, w / 2), out, 0.4, w, 0.05);
    }
  }

  const group = new T.Group();
  group.name = "semif-roads";
  group.add(asphalt.mesh(material(PALETTE.asphalt)));
  if (!pavement.empty) group.add(pavement.mesh(material(PALETTE.pavement)));
  if (!shoulder.empty) group.add(shoulder.mesh(material(PALETTE.shoulder)));
  if (!median.empty) group.add(median.mesh(material(PALETTE.median)));
  group.add(marking.mesh(material(PALETTE.marking, { roughness: 0.7 })));
  return group;
}
```

- [ ] **Step 7: 寫 `buildings.js`**

```js
// Buildings, first pass: stucco blocks with a tiled roof slab, one merged mesh per colour.
// Footprints come from semif-worldgen.js, where they are also the simulation's collision boxes.
import { PALETTE, T, Batch, material } from "./kit.js";

export function buildBuildings(world) {
  const walls = PALETTE.stucco.map(() => new Batch());
  const roofs = PALETTE.roof.map(() => new Batch());
  let i = 0;
  for (const o of world.objects) {
    if (o.type !== "building") continue;
    walls[i % walls.length].box(o.x, o.z, o.width, o.depth, o.height);
    roofs[(i * 7) % roofs.length].box(o.x, o.z, o.width + 0.6, o.depth + 0.6, 0.5, o.height);
    i++;
  }
  const group = new T.Group();
  group.name = "semif-buildings";
  walls.forEach((b, k) => b.empty || group.add(b.mesh(material(PALETTE.stucco[k]), { cast: true })));
  roofs.forEach((b, k) => b.empty || group.add(b.mesh(material(PALETTE.roof[k]), { cast: true })));
  return group;
}
```

- [ ] **Step 8: 寫 `index.js`**

```js
// Solmare Coast renderer (docs/superpowers/specs/2026-10-01-solmare-coast-design.md).
//
// The bundle calls the scenery hooks (BUNDLE_PATCHES.md). This module wraps the old-map layer
// (semif-scenery.js): on the coast map it draws the world itself, on every other map it hands each
// hook to the old layer unchanged.
import { PALETTE, T, setKit, resetCaches } from "./kit.js";
import { buildTerrain, seaPolygon } from "./terrain.js";
import { buildSea } from "./water.js";
import { buildRoads } from "./roads.js";
import { buildBuildings } from "./buildings.js";

const legacy = window.SEMIF_SCENERY || {};
const onCoast = () => window.SEMIF_SIM?.world?.type === "coast";

function buildCoast(view) {
  resetCaches();
  // Stop the old layer's per-frame work and any upgrade it still has pending from an old map.
  view._sceneryBuild = {};
  view._sceneryHooks = [];
  const world = view.sim.world;
  const root = new T.Group();
  root.name = "semif-world";
  root.add(buildTerrain(world), buildSea(world), buildRoads(world), buildBuildings(world));
  view.scene.add(root);
  return root;
}

function drawMinimap(ctx, world, project, scale) {
  ctx.fillStyle = PALETTE.minimap.sea;
  ctx.beginPath();
  seaPolygon(world.visual.shoreline, world.bounds).forEach((p, i) => (i ? ctx.lineTo(...project(p)) : ctx.moveTo(...project(p))));
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = PALETTE.minimap.building;
  for (const o of world.objects) {
    if (o.type !== "building") continue;
    const [x, y] = project(o);
    ctx.fillRect(x - (o.width * scale) / 2, y - (o.depth * scale) / 2, o.width * scale, o.depth * scale);
  }
}

window.SEMIF_SCENERY = {
  palette: legacy.palette,
  kit(kit) {
    setKit(kit);
    legacy.kit?.(kit);
  },
  object(group, obj, view) {
    if (!onCoast()) return legacy.object?.(group, obj, view) ?? false;
    return obj?.type === "building"; // drawn by buildBuildings
  },
  built(view) {
    if (!onCoast()) return legacy.built?.(view);
    try {
      buildCoast(view);
    } catch (err) {
      console.error("semif-world: build", err);
    }
  },
  minimap(ctx, world, project, scale) {
    if (world?.type !== "coast") return legacy.minimap?.(ctx, world, project, scale);
    drawMinimap(ctx, world, project, scale);
  },
};
```

- [ ] **Step 9: 執行，確認通過**

Run: `python -m pytest -q tests/test_world_render.py`
Expected: `7 passed`

- [ ] **Step 10: Commit**

```bash
git add jevpilot_vision/web/semif-world tests/test_world_render.py
git commit -m "feat(web): Solmare Coast renderer: ground, sea, roads, junctions, buildings"
```

---

### Task 4: 頁面接線（`index.html`）

**Files:**
- Modify: `jevpilot_vision/web/index.html`
- Test: `tests/test_world_render.py`（加入頁面測試）

**Interfaces:**
- Consumes: Task 1 的 `STARTS` 鍵名；Task 2 讀取的 `window.SEMIF_DEFAULT_WORLD`；Task 3 的 `semif-world/index.js`。
- Produces: 自由駕駛預設 `coast:<start>`（`?start=` 可選，未知值退回 `festival`）；`lap=1` 時 `SEMIF_DEFAULT_WORLD = null`。生成器（一般 `<script>`）與渲染器（`type="module"`）都排在打包檔的 module 之前。

- [ ] **Step 1: 寫失敗的測試**

在 `tests/test_world_render.py` 檔尾加入：

```python


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
```

- [ ] **Step 2: 執行，確認失敗**

Run: `python -m pytest -q tests/test_world_render.py -k "page or free_driving"`
Expected: 3 FAIL（`world` 是 `None`；找不到 `var starts`；找不到 `semif-worldgen.js` 的 `<script>`）。

- [ ] **Step 3: 修改 `index.html`**

在 `window.SEMIF_MAP = …;` 那一行之後加入：

```js
        // Free driving opens on the Solmare coast; a benchmark lap keeps its published map.
        var start = q.get("start");
        var starts = ["festival", "harbour", "coast", "pass", "highway"];
        window.SEMIF_DEFAULT_WORLD = q.get("lap") === "1" ? null : "coast:" + (starts.indexOf(start) >= 0 ? start : "festival");
```

在 `<link rel="stylesheet" href="/jevpilot/semif-layer.css" />` 之後、打包檔的 `<script type="module" crossorigin src="/jevpilot/assets/index-DC8fTtby.js…">` 之前加入：

```html
    <script src="/jevpilot/semif-worldgen.js?v=20261001a"></script>
    <script type="module" src="/jevpilot/semif-world/index.js?v=20261001a"></script>
```

`semif-scenery.js` 的 `<script>` 留在原位（一般 script 在任何 module 之前就執行完）。把載入訊息 `Preparing Cedar Town, Millbrook & Interstate 08…` 改成 `Preparing the map…`。

- [ ] **Step 4: 執行，確認通過**

Run: `python -m pytest -q tests/test_world_render.py tests/test_scenery.py`
Expected: 全部 PASS（`test_world_render.py` 10 個）。

- [ ] **Step 5: Commit**

```bash
git add jevpilot_vision/web/index.html tests/test_world_render.py
git commit -m "feat(web): free driving opens on the Solmare Coast; laps keep the city"
```

---

### Task 5: 實機驗證、截圖與文件

**Files:**
- Create: `docs/visual/solmare-coast/festival.jpg`、`harbour.jpg`、`coast.jpg`、`pass.jpg`、`minimap.jpg`
- Modify: `README.md`（「畫面與地圖」一節）

**Interfaces:**
- Consumes: Task 1–4 的全部成果。
- Produces: 實機證據（自駕跑過目的地鏈、`lap=1` 不變、主控台沒有例外）與文件。

- [ ] **Step 1: 完整測試**

Run: `python -m pytest -q`
Expected: 全部 PASS（235 個既有 + 39 個新增 = 274 個）。

- [ ] **Step 2: 啟動 mock 伺服器**

Run（背景執行）: `python demo/server.py --mock --port 8000`
Expected: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/jevpilot/` 回 `200`。

- [ ] **Step 3: 載入與切換（Playwright，1280×720）**

開 `http://localhost:8000/jevpilot/?seed=42`，等 5 秒後在頁面上執行：

```js
async () => {
  const s = document.getElementById("world-select");
  const before = { type: SEMIF_SIM.world.type, start: SEMIF_SIM.world.start, label: document.querySelector("label[for=world-select]").textContent, options: [...s.options].map((o) => o.value) };
  s.value = "coast:pass";
  s.dispatchEvent(new Event("change"));
  await new Promise((r) => setTimeout(r, 6000));
  return { before, after: { start: SEMIF_SIM.world.start, select: s.value, route: SEMIF_SIM.world.route.ids, drawn: !!SEMIF_WORLD.scene.getObjectByName("semif-world"), traffic: SEMIF_SIM.traffic.length, peds: SEMIF_SIM.pedestrians.length } };
}
```

Expected: `before = { type: "coast", start: "festival", label: "Start from", options: ["coast:festival","coast:harbour","coast:coast","coast:pass","coast:highway"] }`；`after.start == "pass"`、`after.select == "coast:pass"`、`after.route[0] == "pass-belvedere"`、`drawn == true`、`traffic >= 30`、`peds == 28`。按「New layout」後 `SEMIF_SIM.world.start` 仍是 `"pass"`。主控台除了 `favicon` 404 之外沒有 error。

- [ ] **Step 4: 自駕跑目的地鏈**

開 `http://localhost:8000/jevpilot/?seed=42`，等 5 秒，點 `#autopilot`，然後每秒記錄 `SEMIF_SIM.time`、`player.x/z/speed`、`world.destination`、`collisions`、`events[0].text`，持續 10 分鐘（分次 `browser_evaluate`，每次等待 ≤ 100 秒）。

Expected:
- `collisions == 0`，沒有 `crash`。
- `world.destination` 依序經過 `harbour-quay → coast-bay → pass-belvedere`（至少三站），每次抵達都出現 `Next destination` 事件。
- 沒有任何一段超過 60 秒速度 < 0.5 m/s（排隊等紅燈除外：期間 `SEMIF_SIM.rule(SEMIF_SIM.player).color` 是 `red`）。
- 記下 `redLightViolations`，並在 `?world=city&seed=42` 用同樣方式跑 3 分鐘取得對照值；若 coast 每公里的次數明顯高於 city，停下來回報，不要自行修改決策邏輯。

- [ ] **Step 5: `lap=1` 不變**

開 `http://localhost:8000/jevpilot/?seed=42&lap=1`，等 5 秒後執行：

```js
() => ({ type: SEMIF_SIM.world.type, nodes: SEMIF_SIM.world.nodes.length, label: document.querySelector("label[for=world-select]").textContent, options: [...document.getElementById("world-select").options].map((o) => o.value), coast: !!SEMIF_WORLD.scene.getObjectByName("semif-world") })
```

Expected: `{ type: "city", nodes: 25, label: "Change map", options: ["city","town","highway"], coast: false }`。

- [ ] **Step 6: 截圖**

依序開 `?seed=42&start=festival`、`harbour`、`coast`、`pass`，等 6 秒，截圖（css 比例，1280×720，jpeg）存到 `docs/visual/solmare-coast/<start>.jpg`；再按 `C`（或 HUD 的相機鈕）直到相機名稱顯示 `Bird’s eye`，存 `minimap.jpg`。Playwright 的輸出目錄 `.playwright-mcp/` 不要 commit。

- [ ] **Step 7: 更新 `README.md` 的「畫面與地圖」**

在該節第一條之前加入：

```markdown
- **Solmare Coast：** 自由駕駛預設開這張地中海海岸的開放世界（約 2.4 × 1.6 km、11 km 道路）：港口小鎮 Porto Solmare、海岸公路、葡萄園山谷、Passo del Falco 山口與 SS-1 快速道路。左上角「Start from」選出發地點，網址也可以用 `?start=festival|harbour|coast|pass|highway`。地圖由 `jevpilot_vision/web/semif-worldgen.js` 生成（道路固定，seed 只改變號誌相位、建築、交通與行人），畫面由 `jevpilot_vision/web/semif-world/` 繪製。舊的 Skyline City、Small town、Interstate 08 只在 `lap=1` 或 `?world=city|town|highway` 時出現。截圖在 [`docs/visual/solmare-coast/`](docs/visual/solmare-coast/)。
```

並把「地圖尺寸」那一條的開頭改成「**舊地圖尺寸：**」。

- [ ] **Step 8: Commit**

```bash
git add docs/visual/solmare-coast README.md
git commit -m "docs: Solmare Coast screenshots and README"
```

---

## 之後的分期

第 2–5 期（地景、聚落、車與人、收尾）各自另寫計畫，等這一期合併後依實機結果寫。它們會沿用本期的介面：`SEMIF_WORLDGEN.generate` 的 `visual` 區塊會擴充（地形參數、植被與裝飾擺放），`semif-world/` 增加模組並在 `index.js` 組裝，`PALETTE` 擴充後仍受同一組色塊測試約束。
