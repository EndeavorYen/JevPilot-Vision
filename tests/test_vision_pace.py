"""The onboard cameras are grabbed only when the vision server can take the frames (#42).

The server keeps the latest frame and hands back old evidence while it is busy
(jevpilot_vision/http.py _vision_slot), so a grab while a request is out is wasted work on the
main thread: four renders, four pixel reads and four JPEG encodes.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACE_JS = REPO / "jevpilot_vision" / "web" / "semif-vision-pace.js"
LAYER_JS = REPO / "jevpilot_vision" / "web" / "semif-layer.js"
INDEX = REPO / "jevpilot_vision" / "web" / "index.html"


def _node(body: str):
    script = f"const P = require({json.dumps(str(PACE_JS))});\nconst out = (v) => process.stdout.write(JSON.stringify(v));\n" + body
    return json.loads(subprocess.check_output(["node", "-e", script], cwd=str(REPO)))


def test_one_request_at_a_time_and_the_answer_frees_the_next_grab():
    got = _node("""
let t = 0; const p = P.createVisionPacer({ now: () => t });
const seen = [];
seen.push(p.tryBegin());   // grab: nothing out
t += 16; seen.push(p.tryBegin());   // a frame later, the request is still out: skip
t += 200; seen.push(p.tryBegin());  // still out
p.end();                             // the answer came back
t += 16; seen.push(p.tryBegin());   // next frame: grab
out({ seen, stats: p.stats() });""")
    assert got["seen"] == [True, False, False, True]
    assert got["stats"]["grabs"] == 2 and got["stats"]["skipped"] == 2


def test_a_failed_request_frees_the_next_grab_too():
    got = _node("""
let t = 0; const p = P.createVisionPacer({ now: () => t });
p.tryBegin(); p.end(); t += 16;
out(p.tryBegin());""")
    assert got is True


def test_a_request_that_never_answers_is_given_up_after_five_seconds():
    got = _node("""
let t = 0; const p = P.createVisionPacer({ now: () => t });
p.tryBegin();
t += 4999; const before = p.tryBegin();
t += 2; const after = p.tryBegin();
out({ before, after, stale: p.stats().stale, limit: P.STALE_MS });""")
    assert got == {"before": False, "after": True, "stale": 1, "limit": 5000}


def test_a_late_answer_from_a_given_up_request_does_not_free_the_new_one():
    got = _node("""
let t = 0; const p = P.createVisionPacer({ now: () => t });
const first = p.tryBegin() && p.ticket();
t += 6000; p.tryBegin(); const second = p.ticket();
p.end(first);                         // the stale request finally answers
t += 16; const blocked = !p.tryBegin();   // the new one is still out
p.end(second); t += 16;
out({ blocked, next: p.tryBegin() });""")
    assert got == {"blocked": True, "next": True}


def test_the_layer_asks_the_pacer_before_it_grabs_and_always_releases():
    js = LAYER_JS.read_text(encoding="utf-8")
    body = js.split("async function visionTick(alreadyPainted) {", 1)[1]
    assert "visionPacer.tryBegin()" in body.split("grabSurround(", 1)[0], "ask before the four renders"
    assert "visionPacer.end(ticket)" in body and "finally" in body, "every path releases the slot"


def test_the_page_loads_the_pacer_before_the_layer():
    html = INDEX.read_text(encoding="utf-8")
    assert html.index("semif-vision-pace.js") < html.index("semif-layer.js")


def test_a_given_up_request_is_aborted_so_connections_do_not_pile_up():
    got = _node("""
let t = 0; const p = P.createVisionPacer({ now: () => t });
p.tryBegin(); const first = p.signal();
t += 6000; p.tryBegin(); const second = p.signal();
out({ firstAborted: first.aborted, secondAborted: second.aborted, distinct: first !== second });""")
    assert got == {"firstAborted": True, "secondAborted": False, "distinct": True}


def test_the_layer_hands_the_abort_signal_to_its_vision_post():
    js = LAYER_JS.read_text(encoding="utf-8")
    post = js.split('origFetch("/v1/vision", {', 1)[1].split("});", 1)[0]
    assert "signal: visionPacer.signal()" in post
