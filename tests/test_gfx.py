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
        "].map(M.classifyGpu));")
    assert got == ["medium"] * 7 + ["high"] * 3


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
