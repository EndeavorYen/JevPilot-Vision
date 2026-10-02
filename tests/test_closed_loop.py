"""#28: the closed-loop evaluation: tuning and held-out seeds kept apart, rates with intervals.

The browser part (benchmarks/closed_loop.py drive()) needs Chrome; what it reports is computed by
plain functions tested here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks import closed_loop as cl

REPO = Path(__file__).resolve().parents[1]


def test_tuning_and_held_out_seeds_never_overlap_and_held_out_was_never_debugged():
    seeds = cl.load_seeds()
    tuning, held = set(seeds["tuning"]), set(seeds["held_out"])
    assert len(seeds["tuning"]) == 3 and len(seeds["held_out"]) == 10
    assert not tuning & held
    assert not held & set(seeds["debugged"]), "a seed looked at while debugging is no longer held out"
    assert set(seeds["debugged"]) >= {895794, 31337}
    assert "rule" in seeds and "held_out" in seeds["rule"]


def test_wilson_interval_is_honest_about_small_samples():
    lo, hi = cl.wilson(0, 30)
    assert lo == 0.0 and 0.10 < hi < 0.12, "0 of 30 still allows about 11%"
    lo, hi = cl.wilson(2, 30)
    assert 0.01 < lo < 0.03 and 0.20 < hi < 0.23
    assert cl.wilson(0, 0) == (0.0, 1.0)


def _row(mode, seed, route, **kw):
    base = {"mode": mode, "seed": seed, "route": route, "lag_ms": 0, "seconds": 150, "distance_m": 1500.0,
            "crash": False, "collisions": 0, "vehicle_collisions": 0, "pedestrian_casualties": 0, "red_light": 0,
            "violations": 0, "min_gap_m": 4.0, "events": [], "ok": True}
    base.update(kw)
    return base


def test_the_summary_reports_counts_and_rates_per_mode_never_clean():
    rows = [_row("vision", s, r) for s in (1, 2, 3) for r in ("festival", "harbour")]
    rows[0].update(red_light=2, violations=2)
    rows[3].update(crash=True, collisions=1, vehicle_collisions=1, distance_m=900.0)
    rows += [_row("privileged", s, r) for s in (1, 2, 3) for r in ("festival", "harbour")]
    summary = cl.summarize(rows)
    v = summary["vision"]
    assert v["runs"] == 6
    assert v["runs_with_red_light"] == 1 and v["red_light_events"] == 2
    assert v["runs_with_collision"] == 1
    assert v["distance_km"] == pytest.approx((5 * 1.5) + 0.9)
    assert v["red_light_per_km"] == pytest.approx(2 / 8.4)
    text = cl.report(summary)
    assert "red light 1/6 runs" in text and "collision 1/6 runs" in text
    assert "95%" in text
    assert "clean" not in text.lower()
    assert summary["privileged"]["runs_with_red_light"] == 0


def test_failed_runs_are_counted_apart_not_as_good_drives():
    rows = [_row("vision", 1, "festival"), _row("vision", 2, "festival", ok=False, error="tab crashed")]
    v = cl.summarize(rows)["vision"]
    assert v["runs"] == 1 and v["failed_runs"] == 1


def test_a_results_file_is_resumed_not_rerun(tmp_path):
    out = tmp_path / "runs.jsonl"
    out.write_text(json.dumps(_row("vision", 1, "festival")) + "\n" + "{not json\n", encoding="utf-8")
    plan = cl.plan_runs([1, 2], ["festival"], ["vision"], seconds=150, lag_ms=0)
    todo = cl.pending(plan, cl.read_rows(out))
    assert [(r["seed"], r["route"], r["mode"]) for r in todo] == [(2, "festival", "vision")]


def test_the_page_url_carries_seed_route_mode_and_lag():
    url = cl.page_url("http://localhost:8768", {"seed": 7, "route": "harbour", "mode": "vision", "lag_ms": 300})
    assert url == "http://localhost:8768/jevpilot/?minimal=0&seed=7&world=coast:harbour&mode=vision&lag_ms=300"
    assert "lag_ms" not in cl.page_url("http://localhost:8768", {"seed": 7, "route": "pass", "mode": "privileged", "lag_ms": 0})


def test_the_report_names_where_the_mocks_constants_come_from():
    text = cl.report(cl.summarize([_row("vision", 1, "festival")]))
    assert "DECISION_GAP_S" in text and "STOP_DECEL_MPS2" in text
