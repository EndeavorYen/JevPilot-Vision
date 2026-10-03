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
