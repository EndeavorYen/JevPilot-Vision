"""benchmarks/perf_baseline.py: what it asks the page for and what it writes."""

from __future__ import annotations

import pytest

from benchmarks import perf_baseline as pb


def test_the_url_pins_seed_route_quality_and_a_fixed_hour():
    url = pb.page_url("http://localhost:8768", "high")
    assert "gfx=high" in url and "world=coast:festival" in url and f"seed={pb.SEED}" in url
    assert "time=16:30" in url and "daycycle=0" in url, "a fixed hour, so shadows cost the same every run"


def test_main_refuses_a_relative_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as err:
        pb.main(["--out", "perf.json"])
    assert err.value.code == 2


def test_measure_reads_the_snapshot_and_names_the_canvas(monkeypatch):
    calls = []
    snapshot = {"frames": 3000, "fps_p50": 60, "gpu_timer": True, "gpu_ms_p50": {"main": 2.1, "onboard": 0.8}}
    page = {"snapshot": snapshot, "canvas": [1920, 1080], "dpr": 1, "gpu": "RTX", "quality": "medium"}
    monkeypatch.setattr(pb, "_cdp", lambda *a, **k: calls.append(a) or "")
    monkeypatch.setattr(pb, "_js", lambda target, code, timeout=120: page if "snapshot" in code else 1)
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)
    got = pb.measure("T", "http://localhost:8768", "medium", seconds=60)
    assert got["fps_p50"] == 60 and got["canvas"] == [1920, 1080] and got["quality_seen"] == "medium"
    assert any(a[0] == "nav" for a in calls)


def test_a_page_on_the_wrong_quality_is_refused(monkeypatch):
    page = {"snapshot": {"frames": 10}, "canvas": [1, 1], "dpr": 1, "gpu": "RTX", "quality": "medium"}
    monkeypatch.setattr(pb, "_cdp", lambda *a, **k: "")
    monkeypatch.setattr(pb, "_js", lambda target, code, timeout=120: page if "snapshot" in code else 1)
    monkeypatch.setattr(pb.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="medium"):
        pb.measure("T", "http://localhost:8768", "high", seconds=60)


def test_main_drives_the_tab_open_tab_hands_back_and_closes_it(tmp_path, monkeypatch):
    """closed_loop.open_tab returns {target, id} (#41): measure gets the target, close_tab the tab."""
    tab = {"target": "ABCD1234", "id": "ABCD1234FFFF"}
    seen, closed = [], []
    monkeypatch.setattr(pb, "open_tab", lambda base: tab)
    monkeypatch.setattr(pb, "close_tab", lambda t, wait=False: closed.append(t))
    monkeypatch.setattr(pb, "measure", lambda target, base, gfx, seconds: seen.append(target) or {"fps_p50": 1})
    assert pb.main(["--gfx", "medium", "--out", str(tmp_path / "perf.json")]) == 0
    assert seen == ["ABCD1234"] and closed == [tab]


def test_issue19_review_the_perf_baseline_never_draws_the_candidate_fan():
    """A fan remembered in the measuring Chrome profile would add its lines and worker load."""
    assert "candidates=selected" in pb.page_url("http://localhost:8768", "medium")
