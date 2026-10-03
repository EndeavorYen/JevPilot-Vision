"""Graphics quality tiers on the coast (docs/superpowers/specs/2026-10-03-visual-quality-design.md §4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RENDER = REPO / "jevpilot_vision" / "web" / "semif-world"


def _node(module: str, body: str):
    code = (
        'import { pathToFileURL } from "url";\n'
        f"const M = await import(pathToFileURL({json.dumps(str(RENDER / module))}));\n"
        "const out = (v) => process.stdout.write(JSON.stringify(v));\n" + body
    )
    proc = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, encoding="utf-8", check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr[-2000:])
    return json.loads(proc.stdout)


def test_integrated_gpus_start_on_medium_and_the_rest_on_high():
    got = _node("quality.js", "out(["
        "'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)',"
        "'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)',"
        "'ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)',"
        "'Apple GPU', 'Mali-G78', 'Adreno (TM) 650', '',"
        "'ANGLE (NVIDIA, NVIDIA GeForce RTX 5080 Direct3D11 vs_5_0 ps_5_0, D3D11)',"
        "'ANGLE (AMD, AMD Radeon RX 7800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)',"
        "'ANGLE (Intel, Intel(R) Arc(TM) A770 Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)',"
        "'ANGLE (Intel, Intel(R) Arc(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)',"
        "].map(M.classifyGpu));")
    assert got == ["medium"] * 7 + ["high"] * 3 + ["medium"], "Meteor Lake's integrated GPU is 'Arc(TM) Graphics'"


def test_the_url_wins_then_the_saved_choice_then_the_gpu():
    got = _node("quality.js", """
const store = (v) => ({ getItem: () => v, setItem() {} });
const broken = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
const rtx = 'NVIDIA GeForce RTX 5080';
out([
  M.resolveQuality({ search: '?seed=7&gfx=medium', storage: store('high'), gpuName: rtx }),
  M.resolveQuality({ search: '?seed=7', storage: store('medium'), gpuName: rtx }),
  M.resolveQuality({ search: '', storage: store('ultra'), gpuName: rtx }),
  M.resolveQuality({ search: '?gfx=ultra', storage: broken, gpuName: 'Intel(R) UHD Graphics' }),
  M.resolveQuality({ search: '', storage: null, gpuName: '' }),
  M.saveQuality(broken, 'high'),
]);""")
    assert got[0] == {"quality": "medium", "source": "url"}
    assert got[1] == {"quality": "medium", "source": "saved"}
    assert got[2] == {"quality": "high", "source": "gpu"}, "an unknown saved value falls back to the GPU"
    assert got[3] == {"quality": "medium", "source": "gpu"}, "a throwing storage falls back to the GPU"
    assert got[4] == {"quality": "medium", "source": "gpu"}, "no GPU name means medium"
    assert got[5] is False


def test_switching_rewrites_gfx_and_keeps_every_other_parameter():
    got = _node("quality.js", "out(["
        "M.switchUrl('http://localhost:8768/jevpilot/?seed=7&world=coast:festival&gfx=medium&mode=vision', 'high'),"
        "M.switchUrl('http://localhost:8768/jevpilot/?seed=7#x', 'medium')]);")
    assert got[0] == "http://localhost:8768/jevpilot/?seed=7&world=coast%3Afestival&gfx=high&mode=vision"
    assert got[1] == "http://localhost:8768/jevpilot/?seed=7&gfx=medium#x"


def test_the_quality_is_settled_once_from_the_renderer():
    got = _node("quality.js", """
globalThis.location = { search: '' };
const gl = (name) => ({ getExtension: () => ({ UNMASKED_RENDERER_WEBGL: 1 }), getParameter: () => name });
const first = { ...M.settleQuality(gl('Intel(R) Iris(R) Xe Graphics')) };
const second = { ...M.settleQuality(gl('NVIDIA GeForce RTX 5080')) };
out({ first, second, name: M.rendererName(gl('X')), none: M.rendererName(null) });""")
    assert got["first"] == {"quality": "medium", "source": "gpu"}
    assert got["second"] == got["first"], "a rebuilt coast keeps the quality it started with"
    assert got["name"] == "X" and got["none"] == ""


def test_slow_frames_raise_one_hint_after_five_seconds_below_27_fps():
    got = _node("quality.js", """
const w = M.createSlowWatch();
const seen = [];
for (let t = 0; t <= 4.5; t += 0.5) seen.push(w.push(20, t));      // 4.5 s slow: not yet
seen.push(w.push(40, 5));                                            // recovers: the run restarts
for (let t = 5.5; t <= 10.5; t += 0.5) seen.push(w.push(20, t));    // 5 s slow again: one hint
for (let t = 11; t <= 20; t += 0.5) seen.push(w.push(10, t));       // never again
out(seen.map((s, i) => s ? i : -1).filter((i) => i >= 0));""")
    assert got == [21], "the hint comes at 10.5 s, five seconds into the second slow run"


# ---- The medium world is the world before the tiers --------------------------------------------

import os  # noqa: E402

from test_world_render import _render  # noqa: E402

SNAPSHOT = REPO / "tests" / "fixtures" / "coast_medium_snapshot.json"

# A structural fingerprint: every mesh's path, geometry class, attribute and index lengths,
# instance count and colours, material scalars and colours, shader sources hashed. Instance
# matrices and canvas textures are not seen by the fake kit; pixel comparisons cover those.
_FINGERPRINT = r"""
const fnv = (s) => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; } return h.toString(16); };
const val = (v) => typeof v === 'string' && v.length > 80 ? 'fnv:' + fnv(v) : v;
const mat = (m) => Object.fromEntries(Object.entries(m || {})
  .filter(([, v]) => v === null || ['number', 'string', 'boolean'].includes(typeof v) || (v && typeof v.hex === 'string'))
  .map(([k, v]) => [k, v && typeof v.hex === 'string' ? v.hex : val(v)]).sort(([a], [b]) => (a < b ? -1 : 1)));
const len = (a) => a == null ? null : (a.array?.length ?? a.length ?? null);
const fp = (o, path) => {
  const here = `${path}/${o.name || o.constructor?.name || '?'}`;
  const rows = [];
  if (o.geometry || o.material) {
    const g = o.geometry || {};
    rows.push({ path: here, geo: g.constructor?.name ?? null,
      attrs: Object.fromEntries(Object.entries(g.attributes || {}).map(([k, a]) => [k, len(a)]).sort()),
      index: len(g.index), count: o.count ?? null, colours: o.colours?.length ? fnv(o.colours.join(',')) : null,
      mats: [].concat(o.material || []).map(mat) });
  }
  (o.children || []).forEach((c, i) => rows.push(...fp(c, `${here}[${i}]`)));
  return rows;
};
"""


def _medium_fingerprint():
    return _render(
        _FINGERPRINT
        + "const view = { sim: { world }, scene: new Obj(), camera: { far: 1200, updateProjectionMatrix() {} }, render() {},"
        "  renderer: { getContext: () => ({ getExtension: () => null, getParameter: () => 'Intel(R) UHD Graphics' }) },"
        "  sun: { position: { set() { return this; } }, target: { position: { set() {} } }, shadow: { camera: { updateProjectionMatrix() {} } }, color: new Color() } };"
        "api.built(view);"
        "const V = await mod('vehicles.js'); const P = await mod('people.js');"
        "const cars = [...V.HERO_MODELS.map((m) => V.buildHero(m)), ...[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((id) => V.buildTrafficFor({ id }))];"
        "out({ quality: window.SEMIF_GFX?.quality ?? null, world: fp(view.scene.children[0], ''),"
        "  cars: cars.flatMap((c, i) => fp(c, `car${i}`)), people: [0, 1, 2, 3, 4, 5].flatMap((i) => fp(P.buildPedestrian(i), `ped${i}`)) });",
        search="?gfx=medium",
    )


def test_the_medium_world_is_the_world_before_the_tiers():
    got = _medium_fingerprint()
    assert got["quality"] == "medium"
    if os.environ.get("UPDATE_COAST_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert got == want, "medium must stay the world it was; refresh the snapshot only with the owner's say-so"


# ---- Frame time, GPU time and draw calls (perf.js) ----------------------------------------------

_FAKE_GL = """
const TIME = 0x88BF, DISJOINT = 0x8FBB;
const makeGl = ({ timer = true, ready = true } = {}) => {
  const gl = { QUERY_RESULT: 1, QUERY_RESULT_AVAILABLE: 2, live: 0, active: 0, errors: 0, deleted: 0,
    getExtension: (n) => timer && n === 'EXT_disjoint_timer_query_webgl2' ? { TIME_ELAPSED_EXT: TIME, GPU_DISJOINT_EXT: DISJOINT } : null,
    createQuery() { gl.live++; return { ns: 2e6 }; },
    beginQuery() { if (gl.active) gl.errors++; gl.active++; },
    endQuery() { gl.active--; },
    deleteQuery() { gl.live--; gl.deleted++; },
    getParameter: (p) => p === DISJOINT ? false : null,
    getQueryParameter: (q, p) => p === 2 ? ready : q.ns };
  return gl;
};
const renderer = (calls) => ({ info: { autoReset: true, render: { calls: 0, triangles: 0 }, reset() { this.render.calls = 0; this.render.triangles = 0; } },
  draw() { this.info.render.calls += calls; this.info.render.triangles += calls * 100; } });
"""


def test_frames_gpu_time_and_draw_calls_are_kept_per_view():
    got = _node("perf.js", _FAKE_GL + """
let t = 0; const perf = M.createPerf({ now: () => t });
const gl = makeGl(); perf.attach(gl);
const main = renderer(40), onboard = renderer(25);
for (let i = 0; i < 10; i++) {
  t += 20; perf.frame();
  perf.span('main', main, () => main.draw());
  perf.span('onboard', onboard, () => onboard.draw());
}
t += 20; perf.frame();
out({ s: perf.snapshot(), autoReset: main.info.autoReset, errors: gl.errors });""")
    s = got["s"]
    assert s["frames"] == 10 and s["fps_p50"] == 50 and s["frame_ms_p50"] == 20
    assert s["gpu_timer"] is True and s["gpu_ms_p50"] == {"main": 2, "onboard": 2}
    assert s["calls_p50"] == {"main": 40, "onboard": 25} and s["triangles_p50"] == {"main": 4000, "onboard": 2500}
    assert got["autoReset"] is True, "the renderer's own bookkeeping is put back"
    assert got["errors"] == 0


def test_without_the_timer_extension_frames_are_still_measured():
    got = _node("perf.js", _FAKE_GL + """
let t = 0; const perf = M.createPerf({ now: () => t }); perf.attach(makeGl({ timer: false }));
const r = renderer(3);
for (let i = 0; i < 5; i++) { t += 40; perf.frame(); perf.span('main', r, () => r.draw()); }
perf.attach(null); perf.span('main', null, () => 1);
out(perf.snapshot());""")
    assert got["gpu_timer"] is False and got["gpu_ms_p50"] == {"main": None, "onboard": None}
    assert got["fps_p50"] == 25 and got["calls_p50"]["main"] == 3


def test_a_span_inside_a_span_runs_unmeasured_and_is_counted():
    got = _node("perf.js", _FAKE_GL + """
const perf = M.createPerf({ now: () => 0 }); const gl = makeGl(); perf.attach(gl);
const value = perf.span('main', null, () => perf.span('onboard', null, () => 7));
perf.frame();
out({ value, errors: gl.errors, s: perf.snapshot() });""")
    assert got["value"] == 7 and got["errors"] == 0
    assert got["s"]["nested"] == 1 and got["s"]["gpu_ms_p50"]["onboard"] is None


def test_queries_that_never_finish_are_dropped_not_hoarded():
    got = _node("perf.js", _FAKE_GL + """
const perf = M.createPerf({ now: () => 0, maxPending: 8 }); const gl = makeGl({ ready: false }); perf.attach(gl);
for (let i = 0; i < 100; i++) { perf.span('main', null, () => 0); perf.frame(); }
out({ live: gl.live });""")
    assert got["live"] <= 8


def test_a_throwing_render_still_ends_its_query():
    got = _node("perf.js", _FAKE_GL + """
const perf = M.createPerf({ now: () => 0 }); const gl = makeGl(); perf.attach(gl);
let caught = false; try { perf.span('main', null, () => { throw new Error('boom'); }); } catch (_) { caught = true; }
perf.span('main', null, () => 0);
out({ caught, errors: gl.errors, active: gl.active });""")
    assert got == {"caught": True, "errors": 0, "active": 0}


def test_the_coast_frame_is_measured_and_old_maps_are_not():
    got = _render(
        "const view = { sim: { world }, scene: new Obj(), camera: { far: 1200, updateProjectionMatrix() {} },"
        "  renderer: { getContext: () => null, info: { autoReset: true, render: { calls: 0, triangles: 0 }, reset() {} } },"
        "  sun: { position: { set() { return this; } }, target: { position: { set() {} } }, shadow: { camera: { updateProjectionMatrix() {} } }, color: new Color() },"
        "  render(dt, draw) { view.renderer.info.render.calls = 12; return 'base'; } };"
        "api.built(view); for (let i = 0; i < 3; i++) view.render(0.016, true);"
        "const coast = window.SEMIF_PERF.snapshot();"
        "window.SEMIF_PERF.reset(); window.SEMIF_SIM = { world: { type: 'city' } }; view.render(0.016, true);"
        "out({ coast, city: window.SEMIF_PERF.snapshot() });"
    )
    assert got["coast"]["frames"] == 2 and got["coast"]["calls_p50"]["main"] == 12
    assert got["city"]["frames"] == 0 and got["city"]["calls_p50"]["main"] is None


def test_the_onboard_render_is_measured_in_the_layer():
    src = (REPO / "jevpilot_vision" / "web" / "semif-layer.js").read_text(encoding="utf-8")
    assert 'SEMIF_PERF.span("onboard", renderer, () => renderer.render(scene, cam))' in src
    assert 'onCoastMap(world) && window.SEMIF_PERF' in src, "old maps render exactly as before"


# ---- The graphics button (gfx-panel.js) ---------------------------------------------------------

def test_the_panel_offers_two_qualities_and_says_what_switching_does():
    got = _render(
        "const P = await mod('gfx-panel.js');"
        "out({ medium: P.describe('medium'), high: P.describe('high') });"
    )
    assert "Integrated" in got["medium"] and "Discrete" in got["high"]


def test_the_button_sits_in_the_chip_bar_on_the_coast_only():
    got = _render(
        "const view = { sim: { world }, scene: new Obj(), camera: { far: 1200, updateProjectionMatrix() {} }, render() {},"
        "  renderer: { getContext: () => null },"
        "  sun: { position: { set() { return this; } }, target: { position: { set() {} } }, shadow: { camera: { updateProjectionMatrix() {} } }, color: new Color() } };"
        "api.built(view);"
        "const bar = globalThis.__clock.parent; const coast = { bar: bar.className, kids: bar.children.map((c) => c.className), label: bar.children[0].textContent, shown: bar.children[0].style.display };"
        "window.SEMIF_SIM = { world: { type: 'city' } }; api.built({ scene: new Obj() });"
        "out({ coast, city: bar.children[0].style.display });"
    )
    assert got["coast"]["bar"] == "semif-hud-chips"
    assert got["coast"]["kids"] == ["semif-gfx", "semif-clock", "semif-gfx-panel"], "the button sits left of the clock; its panel opens under the bar"
    assert "Medium" in got["coast"]["label"] and got["coast"]["shown"] == ""
    assert got["city"] == "none"


def test_the_chip_bar_carries_the_clock_position_in_every_layout():
    css = (REPO / "jevpilot_vision" / "web" / "semif-layer.css").read_text(encoding="utf-8")
    bar = css.split(".semif-hud-chips {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in bar
    clock = css.split(".semif-clock,", 1)[1].split("}", 1)[0]
    assert "position: fixed" not in clock, "the bar is placed, not the clock"
    assert "body.fsd-theme .semif-hud-chips {" in css, "the desktop layout moves the bar"
    minimal = css.split("body.semif-minimal :is(", 1)[1].split(")", 1)[0]
    assert ".semif-hud-chips" in minimal and ".semif-gfx-panel" in minimal


_PANEL = (
    "const walk = (o) => [o, ...(o.children || []).flatMap(walk)];"
    "const view = { sim: { world }, scene: new Obj(), camera: { far: 1200, updateProjectionMatrix() {} }, render() {},"
    "  renderer: { getContext: () => null },"
    "  sun: { position: { set() { return this; } }, target: { position: { set() {} } }, shadow: { camera: { updateProjectionMatrix() {} } }, color: new Color() } };"
    "const went = []; globalThis.location.href = 'http://localhost:8768/jevpilot/?seed=7&gfx=medium'; globalThis.location.assign = (u) => went.push(u);"
    "api.built(view);"
    "const button = globalThis.__clock.parent.children[0]; const panel = globalThis.__panel;"
    "const radios = walk(panel).filter((e) => e.type === 'radio'); const apply = walk(panel).find((e) => e.className === 'semif-gfx-apply');"
)


def test_moving_between_options_never_reloads_only_apply_does():
    got = _render(
        _PANEL
        + "button.fire('click'); const open = !panel.hidden;"
        "const high = radios.find((r) => r.value === 'high'); radios.forEach((r) => { r.checked = r === high; });"
        "high.fire('click'); high.fire('change'); high.fire('keydown', { key: 'ArrowDown' });"
        "const before = went.length; const enabledAfterPick = !apply.disabled;"
        "apply.fire('click');"
        "out({ open, before, enabledAfterPick, went, values: radios.map((r) => r.value) });",
        search="?gfx=medium",
    )
    assert got["open"] and got["values"] == ["medium", "high"]
    assert got["before"] == 0, "arrow keys fire click on radios: picking must not reload"
    assert got["enabledAfterPick"]
    assert got["went"] == ["http://localhost:8768/jevpilot/?seed=7&gfx=high"]


def test_apply_on_the_current_quality_just_closes():
    got = _render(
        _PANEL + "button.fire('click'); const before = apply.disabled; apply.fire('click'); out({ before, went, hidden: panel.hidden });",
        search="?gfx=medium",
    )
    assert got == {"before": True, "went": [], "hidden": True}


def test_old_maps_detach_the_meter():
    got = _render(
        "const gl = { getExtension: (n) => n === 'EXT_disjoint_timer_query_webgl2' ? { TIME_ELAPSED_EXT: 1, GPU_DISJOINT_EXT: 2 } : null, getParameter: () => '' };"
        "const view = { sim: { world }, scene: new Obj(), camera: { far: 1200, updateProjectionMatrix() {} }, render() {},"
        "  renderer: { getContext: () => gl },"
        "  sun: { position: { set() { return this; } }, target: { position: { set() {} } }, shadow: { camera: { updateProjectionMatrix() {} } }, color: new Color() } };"
        "api.built(view); const coast = window.SEMIF_PERF.snapshot().gpu_timer;"
        "window.SEMIF_SIM = { world: { type: 'city' } }; api.built({ scene: new Obj() });"
        "out({ coast, city: window.SEMIF_PERF.snapshot().gpu_timer });"
    )
    assert got == {"coast": True, "city": False}


def test_a_long_pause_is_not_a_frame():
    got = _node("perf.js", """
let t = 0; const perf = M.createPerf({ now: () => t });
for (let i = 0; i < 5; i++) { t += 16; perf.frame(); }
t += 90000; perf.frame();   // a hidden tab, or a trip to an old map and back
t += 16; perf.frame();
out(perf.snapshot());""")
    assert got["frames"] == 5 and got["fps_p5"] > 60


def test_narrow_screens_hide_the_whole_bar_where_the_mode_switch_sits():
    css = (REPO / "jevpilot_vision" / "web" / "semif-layer.css").read_text(encoding="utf-8")
    hidden = [block for block in css.split("}") if "display: none" in block and ".semif-hud-chips" in block and "fsd-theme" in block]
    assert hidden, "on narrow screens the bar overlaps the mode switch; ?gfx= still picks the quality there"


# ---- Density (#22): vehicles and people, in the same panel ----------------------------------------

_DENSITY = (
    _PANEL
    + "const selects = walk(panel).filter((e) => e.className === 'semif-density-select');"
    "const dApply = walk(panel).find((e) => e.className === 'semif-density-apply');"
    "const kept = {}; globalThis.localStorage = { getItem: (k) => kept[k] ?? null, setItem: (k, v) => { kept[k] = String(v); } };"
)


def test_issue22_the_panel_offers_vehicle_and_people_density_showing_the_current_ones():
    got = _render(
        _DENSITY
        + "out({ names: selects.map((s) => s.name), values: selects.map((s) => s.value),"
        "  options: selects.map((s) => s.children.map((o) => o.value)), apply: dApply.textContent, disabled: dApply.disabled });",
        search="?gfx=medium&traffic=high&people=low",
    )
    assert got["names"] == ["traffic", "people"]
    assert got["values"] == ["high", "low"], "the levels this world was built with"
    assert got["options"] == [["low", "med", "high"], ["low", "med", "high"]]
    assert got["disabled"] is True


def test_issue22_picking_a_level_never_reloads_and_apply_saves_and_rebuilds():
    got = _render(
        _DENSITY
        + "selects[0].value = 'low'; selects[0].fire('change'); selects[1].value = 'high'; selects[1].fire('change');"
        "const before = went.length; const enabled = !dApply.disabled;"
        "dApply.fire('click');"
        "out({ before, enabled, went, kept });",
        search="?gfx=medium",
    )
    assert got["before"] == 0 and got["enabled"]
    assert got["went"] == ["http://localhost:8768/jevpilot/?seed=7&gfx=medium&traffic=low&people=high"]
    assert got["kept"] == {"semif.density.traffic": "low", "semif.density.people": "high"}
