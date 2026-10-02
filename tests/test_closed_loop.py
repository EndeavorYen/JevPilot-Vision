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
    assert len(seeds["tuning"]) >= 3 and len(seeds["held_out"]) >= 10
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
    base = {"set": "held_out", "mode": mode, "seed": seed, "route": route, "lag_ms": 0, "seconds": 150, "distance_m": 1500.0,
            "crash": False, "collisions": 0, "vehicle_collisions": 0, "pedestrian_casualties": 0, "red_light": 0,
            "violations": 0, "min_gap_m": 4.0, "events": [], "ok": True, "disengaged": False, "stalled": False,
            "broke": False}
    base.update(kw)
    return base


def test_the_summary_reports_counts_and_rates_per_mode_never_clean():
    rows = [_row("vision", s, r) for s in (1, 2, 3) for r in ("festival", "harbour")]
    rows[0].update(red_light=2, violations=2)
    rows[3].update(crash=True, collisions=1, vehicle_collisions=1, distance_m=900.0)
    rows += [_row("privileged", s, r) for s in (1, 2, 3) for r in ("festival", "harbour")]
    summary = cl.summarize(rows)
    v = summary[("held_out", "vision", 150, 0)]
    assert v["runs"] == 6
    assert v["runs_with_red_light"] == 1 and v["red_light_events"] == 2
    assert v["runs_with_collision"] == 1
    assert v["distance_km"] == pytest.approx((5 * 1.5) + 0.9)
    assert v["red_light_per_km"] == pytest.approx(2 / 8.4)
    text = cl.report(summary)
    assert "red light 1/6 runs" in text and "collision 1/6 runs" in text
    assert "95%" in text
    assert "clean" not in text.lower()
    assert summary[("held_out", "privileged", 150, 0)]["runs_with_red_light"] == 0


def test_runs_that_could_not_be_driven_are_counted_apart_and_retried():
    """A setup failure (the tab, the page, the browser) says nothing about driving: it is listed,
    left out of the rates, and a later run of the same seed replaces it."""
    rows = [_row("vision", 1, "festival"), _row("vision", 2, "festival", ok=False, error="tab crashed")]
    v = cl.summarize(rows)[("held_out", "vision", 150, 0)]
    assert v["runs"] == 1 and v["failed_runs"] == 1
    assert v["failures"] == {"tab crashed": 1}
    retried = rows + [_row("vision", 2, "festival")]
    v = cl.summarize(retried)[("held_out", "vision", 150, 0)]
    assert v["runs"] == 2 and v["failed_runs"] == 0


def test_review2_a_disengagement_or_a_stall_is_a_result_never_retried_away():
    """Review #28: the autopilot giving up (three failed or expired decisions) or a car that never
    moves is what the drive did. It counts in its own k/n, and resuming does not drive it again."""
    gave_up = _row("vision", 2, "festival", disengaged=True, distance_m=300.0)
    parked = _row("vision", 3, "festival", stalled=True, distance_m=12.0)
    rows = [_row("vision", 1, "festival"), gave_up, parked]
    v = cl.summarize(rows)[("held_out", "vision", 150, 0)]
    assert v["runs"] == 3 and v["runs_disengaged"] == 1 and v["runs_stalled"] == 1
    text = cl.report(cl.summarize(rows))
    assert "autopilot gave up 1/3 runs" in text and "car did not move 1/3 runs" in text
    plan = cl.plan_runs([1, 2, 3], ["festival"], ["vision"], seconds=150, lag_ms=0)
    assert cl.pending(plan, [dict(r, set="held_out") for r in rows]) == []
    # A later lucky run of the same seed does not replace the disengagement.
    v = cl.summarize(rows + [_row("vision", 2, "festival")])[("held_out", "vision", 150, 0)]
    assert v["runs_disengaged"] == 1


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


def test_review_runs_are_pooled_only_with_their_own_set_mode_duration_and_lag():
    rows = [_row("vision", 1, "festival"), _row("vision", 1, "festival", lag_ms=400),
            _row("vision", 895794, "festival", set="tuning")]
    summary = cl.summarize(rows)
    assert set(summary) == {("held_out", "vision", 150, 0), ("held_out", "vision", 150, 400), ("tuning", "vision", 150, 0)}
    text = cl.report(summary)
    assert "held_out · vision · 150 s · lag 400 ms" in text


def test_review_a_drive_that_was_not_set_up_as_asked_is_not_a_run():
    """The tab was hidden (the sim does not step), the sim ran too little, or the page drove another
    mode, route or lag than asked: a setup failure, not a result."""
    run = {"seed": 7, "route": "harbour", "mode": "vision", "seconds": 150, "lag_ms": 400}
    good = {"mode_seen": "vision", "world_seen": "coast:harbour", "lag_seen": 400, "autopilot": True, "crash": False,
            "sim_time_s": 150, "hidden": False, "distance_m": 1800}
    assert cl.validate(run, good) is None
    assert cl.validate(run, dict(good, crash=True, autopilot=False, sim_time_s=80)) is None, "a crash is a result"
    assert cl.validate(run, dict(good, autopilot=False)) is None, "giving up is a result too"
    for change, words in [({"hidden": True}, "hidden"), ({"mode_seen": "privileged"}, "mode"),
                          ({"world_seen": "coast:festival"}, "route"), ({"lag_seen": 0}, "lag"),
                          ({"engaged": False}, "never engaged"), ({"server_ok": False}, "decision server")]:
        reason = cl.validate(run, dict(good, **change))
        assert reason and words in reason, (change, reason)
    none = {"disengaged": False, "stalled": False, "broke": False, "arrived": False}
    assert cl.outcome(run, good) == none
    assert cl.outcome(run, dict(good, autopilot=False)) == dict(none, disengaged=True)
    assert cl.outcome(run, dict(good, distance_m=40)) == dict(none, stalled=True)
    assert cl.outcome(run, dict(good, crash=True, autopilot=False, distance_m=40)) == none
    # Review #28 (4): reaching the destination turns the autopilot off; that is arriving, not giving up.
    assert cl.outcome(run, dict(good, autopilot=False, complete=True)) == dict(none, arrived=True)
    # Review #28 (3): once the car drove, a page that stopped stepping is what the drive did.
    assert cl.validate(run, dict(good, sim_time_s=60)) is None
    assert cl.outcome(run, dict(good, sim_time_s=60))["broke"] is True
    # An arrival that ended the drive early is not a broken page.
    assert cl.outcome(run, dict(good, sim_time_s=60, autopilot=False, complete=True))["broke"] is False


def test_review_a_held_out_seed_moved_to_debugged_no_longer_reports_as_held_out(tmp_path):
    seeds = {"rule": "held_out ...", "tuning": [1, 2, 3], "held_out": [10, 11], "debugged": [1, 11]}
    rows = [_row("vision", 10, "festival"), _row("vision", 11, "festival")]
    kept, dropped = cl.current_rows(rows, seeds)
    assert [r["seed"] for r in kept] == [10] and [r["seed"] for r in dropped] == [11]


def test_review_the_seed_rule_is_checked_where_seeds_are_used(tmp_path):
    bad = tmp_path / "seeds.json"
    bad.write_text(json.dumps({"rule": "held_out", "tuning": [1], "held_out": [1, 2], "debugged": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        cl.load_seeds(bad)


def test_review_the_cli_refuses_routes_modes_lags_and_durations_the_page_would_not_honour(tmp_path, monkeypatch):
    # Never a browser from a unit test: any attempt to drive fails loudly instead.
    monkeypatch.setattr(cl, "_cdp", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tried to drive")))
    for argv in (["--routes", "harbor"], ["--modes", "heuristic2"], ["--lag-ms", "1500"], ["--lag-ms", "-1"],
                 ["--seconds", "0"], ["--seconds", "10"]):
        with pytest.raises(SystemExit):
            cl.main(argv + ["--out", str(tmp_path / "runs.jsonl")])


def test_review2_rows_without_a_seed_set_are_not_reported(tmp_path):
    kept, dropped = cl.current_rows([{"mode": "vision", "seed": 1, "ok": True}], cl.load_seeds())
    assert kept == [] and len(dropped) == 1


def test_review3_retries_are_visible_and_seeds_that_never_drove_are_named():
    rows = [_row("vision", 1, "festival", ok=False, error="tab hidden (the simulation does not step)"),
            _row("vision", 1, "festival"),
            _row("vision", 2, "festival", ok=False, error="sim ran 12 s of 150"),
            _row("vision", 2, "festival", ok=False, error="sim ran 30 s of 150")]
    v = cl.summarize(rows)[("held_out", "vision", 150, 0)]
    assert v["attempts"] == 4 and v["retried"] == 1 and v["never_driven"] == [2]
    text = cl.report(cl.summarize(rows))
    assert "4 attempts" in text and "1 retried after a setup failure" in text and "never driven: seeds [2]" in text


def test_review3_violation_rates_are_over_runs_that_moved_with_all_runs_beside():
    """A run that ran a red light and then gave up still ran the red light: it stays in the rate.
    Only a car that never moved is left out, and the all-runs share has its own interval."""
    rows = [_row("vision", 1, "festival", red_light=1), _row("vision", 2, "festival", stalled=True, distance_m=20.0),
            _row("vision", 3, "festival", disengaged=True, red_light=1), _row("vision", 4, "festival")]
    text = cl.report(cl.summarize(rows))
    assert "red light 2/3 runs that moved" in text
    assert "2/4 of all runs (95%" in text


def test_review4_a_finished_run_is_saved_even_if_the_tab_check_fails(monkeypatch, tmp_path):
    out = tmp_path / "runs.jsonl"

    def boom():
        raise RuntimeError("cdp list timed out")

    monkeypatch.setattr(cl, "_jevpilot_tabs", boom)
    monkeypatch.setattr(cl, "drive", lambda target, base, run: dict(run, ok=True, distance_m=900, events=[], stalled=False))
    import argparse
    args = argparse.Namespace(out=out, base="http://x", set="held_out")
    cl._drive_all(args, cl.plan_runs([10], ["festival"], ["vision"], seconds=150, lag_ms=0), "MINE")
    row = cl.read_rows(out)[0]
    assert row["ok"] is True and row["tab_check"] == "failed"


def test_review4_old_rows_are_driven_again_not_silently_dropped():
    old_ok = {"set": "held_out", "mode": "vision", "seed": 104729, "route": "festival", "seconds": 150, "lag_ms": 0, "ok": True}
    plan = cl.plan_runs([104729], ["festival"], ["vision"], seconds=150, lag_ms=0)
    assert cl.pending(plan, [old_ok]) == plan


def test_review3_a_run_shared_with_another_tab_is_not_kept(monkeypatch, tmp_path):
    out = tmp_path / "runs.jsonl"
    tabs = iter([[], ["OTHER"]])  # none before the run, one appeared during it
    monkeypatch.setattr(cl, "_jevpilot_tabs", lambda: ["MINE"] + next(tabs))
    monkeypatch.setattr(cl, "drive", lambda target, base, run: dict(run, ok=True, distance_m=900, events=[]))
    import argparse
    args = argparse.Namespace(out=out, base="http://x", set="held_out")
    with pytest.raises(SystemExit):
        cl._drive_all(args, cl.plan_runs([10], ["festival"], ["vision"], seconds=150, lag_ms=0), "MINE")
    row = cl.read_rows(out)[0]
    assert row["ok"] is False and "another simulation tab" in row["error"]


def test_review3_rows_from_before_outcomes_were_recorded_are_not_reported():
    old_ok = {"set": "held_out", "mode": "vision", "seed": 104729, "ok": True, "distance_m": 10}
    kept, dropped = cl.current_rows([old_ok], cl.load_seeds())
    assert kept == [] and dropped == [old_ok]
