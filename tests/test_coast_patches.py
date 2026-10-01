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

# three.js classes the bundle hands the renderer on top of the ones semif-scenery.js already gets,
# as name: minified identifier. test_kit_classes_are_the_classes_they_claim_to_be checks each one.
KIT = {
    "ShaderMaterial": ("Tc", "isShaderMaterial"),
    "WebGLRenderTarget": ("Gi", "isWebGLRenderTarget"),
    "OrthographicCamera": ("Dl", "isOrthographicCamera"),
    "Vector2": ("B", "isVector2"),
    "Vector4": ("Ui", "isVector4"),
    "Matrix4": ("W", "isMatrix4"),
    "Quaternion": ("Ei", "isQuaternion"),
    "Euler": ("ra", "isEuler"),
    "DataTexture": ("hs", "isDataTexture"),
    "DepthTexture": ("ac", "isDepthTexture"),
    "TextureLoader": ("cl", "new Hi,a=new ol(this.manager)"),
    "Fog": ("ka", "isFog"),
    "HemisphereLight": ("ul", "isHemisphereLight"),
    "InstancedBufferAttribute": ("ys", "isInstancedBufferAttribute"),
}
KIT_CLASSES = "".join(f"{name}:{ident}," for name, (ident, _) in KIT.items())

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
     "let t=this.world.peekDestination?.()??e[Math.floor(this.planRandom()*e.length)];"),
    ("coast-commit-destination", MAIN,
     "if(n&&n.route){r.route=this.world.route=n.route;",
     "if(n&&n.route){this.world.commitDestination?.(t.id);r.route=this.world.route=n.route;"),
    # --- phase 2: more three.js classes for the renderer, the sun and the main view's output
    ("coast-kit-classes", MAIN,
     "build(){window.SEMIF_SCENERY?.kit?.({Mesh:K,",
     "build(){window.SEMIF_SCENERY?.kit?.({Mesh:K," + KIT_CLASSES),
    ("coast-sun", MAIN,
     "this.sun.position.set(i.x-55,85,i.z+50),this.sun.target.position.set(i.x,0,i.z)",
     "window.SEMIF_SCENERY?.sun?.(this,i)||(this.sun.position.set(i.x-55,85,i.z+50),this.sun.target.position.set(i.x,0,i.z))"),
    ("coast-present", MAIN,
     "t&&this.renderer.render(this.scene,this.camera)",
     "t&&(window.SEMIF_SCENERY?.present?.(this)||this.renderer.render(this.scene,this.camera))"),
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


def test_kit_classes_are_the_classes_they_claim_to_be():
    """Minified names are only stable for this exact bundle: each must be defined as a class whose
    body sets the matching three.js flag soon after its name."""
    text = (ASSETS / MAIN).read_text(encoding="utf-8")
    for name, (ident, flag) in KIT.items():
        starts = [i for i in range(len(text)) if text.startswith(f"{ident}=class", i) and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_$"))]
        assert len(starts) == 1, (name, ident, len(starts))
        assert flag in text[starts[0]:starts[0] + 400], (name, ident, flag)


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
