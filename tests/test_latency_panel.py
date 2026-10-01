"""Latency panel: line charts over the last minutes, and the minimal (focus) view."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "jevpilot_vision" / "web"
STATS_JS = WEB / "semif-stats.js"


def run_node(body: str) -> dict:
    script = "const s = require(%s);\n%s" % (json.dumps(str(STATS_JS)), body)
    return json.loads(subprocess.check_output(["node", "-e", script], cwd=str(REPO), encoding="utf-8"))


def test_buckets_average_each_slice_and_leave_gaps_empty():
    got = run_node(
        r"""
const rows = [];
for (let t = 0; t < 30000; t += 500) rows.push({ t, ms: t < 10000 ? 100 : 200 });
rows.push({ t: 29900, ms: 900 });
const b = s.bucketize(rows, 0, 60000, 6);
process.stdout.write(JSON.stringify(b));
"""
    )
    assert len(got) == 6
    assert got[0]["mean"] == 100 and got[0]["min"] == 100 and got[0]["max"] == 100 and got[0]["n"] == 20
    assert got[1]["mean"] == 200
    assert got[2]["max"] == 900 and got[2]["n"] == 21
    assert got[2]["t"] == 25000, "a bucket's time is its middle"
    assert got[3] is None and got[5] is None, "no samples, no point: the line breaks there"


def test_nice_scale_rounds_the_axis_up_to_round_ticks():
    got = run_node(
        r"""
process.stdout.write(JSON.stringify([s.niceScale(0), s.niceScale(7.3), s.niceScale(143), s.niceScale(1999)]));
"""
    )
    assert got[0]["max"] > 0, "an empty chart still has an axis"
    assert got[1]["max"] == 8 and got[1]["ticks"] == [0, 2, 4, 6, 8]
    assert got[2]["max"] == 150 and got[2]["ticks"] == [0, 50, 100, 150]
    assert got[3]["max"] == 2000 and got[3]["ticks"][-1] == 2000
    for scale in got:
        assert 3 <= len(scale["ticks"]) <= 6
        assert scale["ticks"][0] == 0


def test_time_ticks_count_back_from_now():
    got = run_node(
        r"""
process.stdout.write(JSON.stringify(s.RANGES.map((r) => ({ key: r.key, ms: r.ms, ticks: s.timeTicks(r.ms) }))));
"""
    )
    assert [r["key"] for r in got] == ["1m", "5m", "15m"]
    assert [r["ms"] for r in got] == [60_000, 300_000, 900_000]
    for r in got:
        assert r["ticks"][-1] == {"ago": 0, "label": "now"}
        assert r["ticks"][0]["ago"] == r["ms"]
    assert [t["label"] for t in got[0]["ticks"]] == ["−60s", "−45s", "−30s", "−15s", "now"]
    assert [t["label"] for t in got[2]["ticks"]] == ["−15m", "−10m", "−5m", "now"]


def test_series_colours_follow_the_validated_palette():
    got = run_node("process.stdout.write(JSON.stringify(s.SERIES));")
    colours = {row["key"]: row["color"] for row in got}
    # Validated on the panel surface #141922 (dataviz validate_palette.js, --pairs all):
    # e2e is alone on its chart; the three stages share one.
    assert colours == {
        "e2e_loop_ms": "#3987e5",
        "classifier_ms": "#d95926",
        "vision_encode_ms": "#199e70",
        "grab_frame_ms": "#9085e9",
    }
    assert [row["chart"] for row in got] == ["e2e", "stages", "stages", "stages"]


def test_page_loads_the_panel_and_wires_it_to_the_telemetry():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "semif-layer.js").read_text(encoding="utf-8")
    css = (WEB / "semif-layer.css").read_text(encoding="utf-8")
    assert html.index("semif-stats.js") < html.index("semif-layer.js")
    assert "SEMIF_STATS" in js and "mountStats" in js
    assert "#fsd-stats" in css and "--viz-surface: #141922" in css


def test_minimal_view_collapses_the_interface_but_keeps_the_drive():
    js = (WEB / "semif-layer.js").read_text(encoding="utf-8")
    css = (WEB / "semif-layer.css").read_text(encoding="utf-8")
    assert '"fsd-minimal"' in js
    assert "KeyH" in js and "semif-minimal" in js and "localStorage" in js
    hidden = re.search(r"body\.semif-minimal :is\(([^)]*)\)\s*\{\s*display: none !important;", css)
    assert hidden, "one rule hides the panels"
    for sel in [".topbar", "#fsd-status", "#fsd-pip", "#minimap", ".semif-clock", "#fsd-boxes", "#fsd-stats",
                "#decision-status", ".dock-tools", "#candidates-toggle", ".dock-divider"]:
        assert sel in hidden.group(1), sel
    # What is left: speed, limit, the autopilot switch and the next turn.
    for kept in ["#speed", "#autopilot", ".navigation-card", ".bottom-hud"]:
        assert kept not in hidden.group(1), kept


def test_window_stats_read_each_series_once_per_redraw():
    """Review: the panel fetched every series twice per tick and sorted it once per percentile."""
    got = run_node(
        r"""
const calls = {};
const rows = Array.from({ length: 50 }, (_, i) => ({ t: i * 1000, ms: 100 + i }));
const tel = { getTimeline(key, w) { calls[key] = (calls[key] || 0) + 1; return rows; },
              summarizeWindow() { throw new Error("re-reads the series"); } };
const st = s.windowStats(tel, 60000);
process.stdout.write(JSON.stringify({ calls, e2e: st.sums.e2e_loop_ms, n: st.lines.classifier_ms.length }));
"""
    )
    assert got["calls"] == {k: 1 for k in ["e2e_loop_ms", "classifier_ms", "vision_encode_ms", "grab_frame_ms"]}
    assert got["e2e"]["n"] == 50 and got["e2e"]["p50"] == 124.5 and got["e2e"]["max"] == 149
    assert got["n"] == 50


def test_the_fifteen_minute_view_redraws_less_often():
    got = run_node("process.stdout.write(JSON.stringify(s.RANGES.map((r) => s.redrawEvery(r.ms))));")
    assert got[0] == 500 and got[1] <= 1000 and got[2] >= 2000


def test_decision_rate_counts_only_the_time_with_samples():
    """Review: two minutes into a session at 5 Hz the 15-minute view said 40/min, not 300/min."""
    got = run_node(
        r"""
process.stdout.write(JSON.stringify([
  s.perMinute(600, 0, 120000, 900000),
  s.perMinute(600, -900000, 0, 60000 * 15),
  s.perMinute(0, null, 1000, 60000),
]));
"""
    )
    assert got[0] == 300
    assert got[1] == 40
    assert got[2] is None


def test_on_narrow_screens_the_panel_clears_the_minimal_button():
    css = (WEB / "semif-layer.css").read_text(encoding="utf-8")
    narrow = css[css.index("@media (max-width: 900px) {\n  #fsd-stats"):]
    top = int(re.search(r"#fsd-stats \{[^}]*?top: (\d+)px", narrow).group(1))
    button = re.search(r"#fsd-minimal \{[^}]*?top: (\d+)px;[^}]*?height: (\d+)px", css)
    assert top >= int(button.group(1)) + int(button.group(2)) + 6, "the panel's close button sits below the corner button"


def test_minimal_view_and_the_panel_stay_in_step_and_the_chip_keeps_the_keyboard():
    js = (WEB / "semif-layer.js").read_text(encoding="utf-8")
    stats = STATS_JS.read_text(encoding="utf-8")
    # Folding the interface closes the panel; opening the panel unfolds it.
    assert re.search(r"function setMinimal\(on\) \{[\s\S]*?stats\.toggle\(false\)", js)
    assert "onOpen: () => setMinimal(false)" in js
    assert "opts.onOpen" in stats
    # Clicking the chip must not take focus, or Space (brake) would press the chip instead.
    assert re.search(r'chip\.addEventListener\("mousedown", \(ev\) => ev\.preventDefault\(\)\)', stats)
