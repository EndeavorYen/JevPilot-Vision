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
