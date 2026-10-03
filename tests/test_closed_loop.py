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
            "broke": False, "unreadable": False, "fmt": cl.ROW_FORMAT}
    base.update(kw)
    return base


def test_the_summary_reports_counts_and_rates_per_mode_never_clean():
    rows = [_row("vision", s, r) for s in (1, 2, 3) for r in ("festival", "harbour")]
    rows[0].update(red_light=2, violations=2)
    rows[3].update(crash=True, collisions=1, vehicle_collisions=1, distance_m=900.0)
    rows += [_row("privileged", s, r) for s in (1, 2, 3) for r in ("festival", "harbour")]
    summary = cl.summarize(rows)
    v = summary[("held_out", "vision", 150, 0, "medium")]
    assert v["runs"] == 6
    assert v["runs_with_red_light"] == 1 and v["red_light_events"] == 2
    assert v["runs_with_collision"] == 1
    assert v["distance_km"] == pytest.approx((5 * 1.5) + 0.9)
    assert v["red_light_per_km"] == pytest.approx(2 / 8.4)
    text = cl.report(summary)
    assert "red light 1/6 runs" in text and "collision 1/6 runs" in text
    assert "95%" in text
    assert "clean" not in text.lower()
    assert summary[("held_out", "privileged", 150, 0, "medium")]["runs_with_red_light"] == 0


def test_runs_that_could_not_be_driven_are_counted_apart_and_retried():
    """A setup failure (the tab, the page, the browser) says nothing about driving: it is listed,
    left out of the rates, and a later run of the same seed replaces it."""
    rows = [_row("vision", 1, "festival"), _row("vision", 2, "festival", ok=False, error="tab crashed")]
    v = cl.summarize(rows)[("held_out", "vision", 150, 0, "medium")]
    assert v["runs"] == 1 and v["failed_runs"] == 1
    assert v["failures"] == {"tab crashed": 1}
    retried = rows + [_row("vision", 2, "festival")]
    v = cl.summarize(retried)[("held_out", "vision", 150, 0, "medium")]
    assert v["runs"] == 2 and v["failed_runs"] == 0


def test_review2_a_disengagement_or_a_stall_is_a_result_never_retried_away():
    """Review #28: the autopilot giving up (three failed or expired decisions) or a car that never
    moves is what the drive did. It counts in its own k/n, and resuming does not drive it again."""
    gave_up = _row("vision", 2, "festival", disengaged=True, distance_m=300.0)
    parked = _row("vision", 3, "festival", stalled=True, distance_m=12.0)
    rows = [_row("vision", 1, "festival"), gave_up, parked]
    v = cl.summarize(rows)[("held_out", "vision", 150, 0, "medium")]
    assert v["runs"] == 3 and v["runs_disengaged"] == 1 and v["runs_stalled"] == 1
    text = cl.report(cl.summarize(rows))
    assert "autopilot gave up 1/3 runs" in text and "car did not move 1/3 runs" in text
    plan = cl.plan_runs([1, 2, 3], ["festival"], ["vision"], seconds=150, lag_ms=0)
    assert cl.pending(plan, [dict(r, set="held_out") for r in rows]) == []
    # A later lucky run of the same seed does not replace the disengagement.
    v = cl.summarize(rows + [_row("vision", 2, "festival")])[("held_out", "vision", 150, 0, "medium")]
    assert v["runs_disengaged"] == 1


def test_a_results_file_is_resumed_not_rerun(tmp_path):
    out = tmp_path / "runs.jsonl"
    out.write_text(json.dumps(_row("vision", 1, "festival")) + "\n" + "{not json\n", encoding="utf-8")
    plan = cl.plan_runs([1, 2], ["festival"], ["vision"], seconds=150, lag_ms=0)
    todo = cl.pending(plan, cl.read_rows(out))
    assert [(r["seed"], r["route"], r["mode"]) for r in todo] == [(2, "festival", "vision")]


def test_the_page_url_carries_seed_route_mode_and_lag():
    url = cl.page_url("http://localhost:8768", {"seed": 7, "route": "harbour", "mode": "vision", "lag_ms": 300})
    assert url == "http://localhost:8768/jevpilot/?minimal=0&candidates=selected&traffic=low&people=low&seed=7&world=coast:harbour&mode=vision&lag_ms=300&gfx=medium"
    assert "lag_ms" not in cl.page_url("http://localhost:8768", {"seed": 7, "route": "pass", "mode": "privileged", "lag_ms": 0})


def test_the_report_names_where_the_mocks_constants_come_from():
    text = cl.report(cl.summarize([_row("vision", 1, "festival")]))
    assert "DECISION_GAP_S" in text and "STOP_DECEL_MPS2" in text


def test_review_runs_are_pooled_only_with_their_own_set_mode_duration_and_lag():
    rows = [_row("vision", 1, "festival"), _row("vision", 1, "festival", lag_ms=400),
            _row("vision", 895794, "festival", set="tuning")]
    summary = cl.summarize(rows)
    assert set(summary) == {("held_out", "vision", 150, 0, "medium"), ("held_out", "vision", 150, 400, "medium"), ("tuning", "vision", 150, 0, "medium")}
    text = cl.report(summary)
    assert "held_out · vision · 150 s · lag 400 ms" in text


def test_review_a_drive_that_was_not_set_up_as_asked_is_not_a_run():
    """The tab was hidden (the sim does not step), the sim ran too little, or the page drove another
    mode, route or lag than asked: a setup failure, not a result."""
    run = {"seed": 7, "route": "harbour", "mode": "vision", "seconds": 150, "lag_ms": 400}
    good = {"mode_seen": "vision", "world_seen": "coast:harbour", "lag_seen": 400, "gfx_seen": "medium", "autopilot": True, "crash": False,
            "sim_time_s": 150, "hidden": False, "distance_m": 1800}
    assert cl.validate(run, good) is None
    assert cl.validate(run, dict(good, crash=True, autopilot=False, sim_time_s=80)) is None, "a crash is a result"
    assert cl.validate(run, dict(good, autopilot=False)) is None, "giving up is a result too"
    for change, words in [({"hidden": True}, "hidden"), ({"mode_seen": "privileged"}, "mode"),
                          ({"world_seen": "coast:festival"}, "route"), ({"lag_seen": 0}, "lag"),
                          ({"engaged": False}, "never engaged"),
                          ({"server_ok": False, "distance_m": 20}, "decision server"),
                          ({"outage_errors": 3, "autopilot": False, "distance_m": 20}, "decision server unreachable")]:
        reason = cl.validate(run, dict(good, **change))
        assert reason and words in reason, (change, reason)
    none = {"disengaged": False, "stalled": False, "broke": False, "unreadable": False}
    assert cl.outcome(run, good) == none
    assert cl.outcome(run, dict(good, autopilot=False)) == dict(none, disengaged=True)
    assert cl.outcome(run, dict(good, distance_m=40)) == dict(none, stalled=True)
    assert cl.outcome(run, dict(good, crash=True, autopilot=False, distance_m=40)) == none
    # Review #28 (5): once the car moved, an outage seen at the end does not erase the drive: it is
    # kept as a result, flagged.
    assert cl.validate(run, dict(good, server_ok=False)) is None
    assert cl.validate(run, dict(good, outage_errors=3, autopilot=False)) is None
    # Review #28 (8): a 500 or a timeout from a healthy server is the system under test failing: a result.
    assert cl.validate(run, dict(good, system_errors=3, autopilot=False, distance_m=0)) is None
    # Review #28 (6): expired decisions are the model's own latency: a stall from them is a result.
    assert cl.validate(run, dict(good, expired_decisions=3, autopilot=False, distance_m=20)) is None
    # Review #28 (7): but a request that failed while the car never got going is an outage, even if
    # a slow first decision expired too.
    assert "decision server unreachable" in cl.validate(run, dict(good, expired_decisions=1, outage_errors=2,
                                                                   autopilot=False, distance_m=0))
    assert cl.outcome(run, dict(good, expired_decisions=3, autopilot=False, distance_m=20))["stalled"] is True
    # A red light run before the car covered 150 m is not erased by an outage that followed.
    assert cl.validate(run, dict(good, server_ok=False, distance_m=120, red_light=1)) is None
    # Review #28 (3): once the car drove, a page that stopped stepping is what the drive did.
    assert cl.validate(run, dict(good, sim_time_s=60)) is None
    assert cl.outcome(run, dict(good, sim_time_s=60))["broke"] is True



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
    v = cl.summarize(rows)[("held_out", "vision", 150, 0, "medium")]
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

    def boom(base):
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
    # Review #28 (6): rows written under earlier rules (no format version) too, even with outcomes.
    older = dict(old_ok, stalled=False, broke=True, error="drive broke: x")
    assert cl.pending(plan, [older]) == plan
    assert cl.current_rows([older], cl.load_seeds())[0] == []


def test_review3_a_run_shared_with_another_tab_is_not_kept(monkeypatch, tmp_path):
    out = tmp_path / "runs.jsonl"
    tabs = iter([[], ["OTHER"]])  # none before the run, one appeared during it
    monkeypatch.setattr(cl, "_jevpilot_tabs", lambda base: ["MINE"] + next(tabs))
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


def test_review5_a_drive_whose_result_could_not_be_read_is_unknown_not_clean():
    rows = [_row("vision", 1, "festival"), _row("vision", 2, "festival", broke=True, unreadable=True, distance_m=0.0),
            _row("vision", 3, "festival", red_light=1)]
    v = cl.summarize(rows)[("held_out", "vision", 150, 0, "medium")]
    assert v["drove"] == 2 and v["runs_unreadable"] == 1
    text = cl.report(cl.summarize(rows))
    assert "result unreadable 1/3 runs" in text and "red light 1/2 runs that moved" in text


def test_review5_a_run_whose_shared_tab_check_failed_is_counted():
    rows = [_row("vision", 1, "festival", tab_check="failed"), _row("vision", 2, "festival", tab_check="ok")]
    text = cl.report(cl.summarize(rows))
    assert "tab check could not be made for 1" in text


def _fake_http(monkeypatch, replies, seen):
    """http.client with scripted replies: an exception to raise, or a status."""
    import http.client

    class Conn:
        def __init__(self, host, port=None, timeout=None):
            self.host, self.port = host, port

        def request(self, method, url, headers=None):
            seen.append({"url": url, "host": self.host, "headers": dict(headers or {})})
            nxt = replies.pop(0) if replies else 200
            if isinstance(nxt, Exception):
                raise nxt
            self.status = nxt

        def getresponse(self):
            class Res:
                status = self.status

                def read(self):
                    return b"{}"
            return Res()

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", Conn)


def test_review5_a_busy_server_is_not_an_outage(monkeypatch):
    """During a Vision drive the server is busy with the detector; one slow /health is not an
    outage. It is asked again after the drive stopped, a few times."""
    seen = []
    _fake_http(monkeypatch, [TimeoutError("busy"), TimeoutError("busy"), 200], seen)
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    assert cl.server_ok("http://localhost:8768") is True and len(seen) == 3
    seen.clear()
    _fake_http(monkeypatch, [TimeoutError("down")] * 3, seen)
    assert cl.server_ok("http://localhost:8768") is False


def test_the_health_check_keeps_the_connection_alive_and_asks_ipv4(monkeypatch):
    """Root cause (2026-10-03): Python's urllib sends 'Connection: close', and the server's Windows
    event loop reset 57% of such requests (23/40) while keep-alive requests all passed (40/40); so a
    healthy server read as unreachable after 10 of 60 held-out runs. 'localhost' also resolved to
    ::1 first while the server listens on IPv4 only."""
    seen = []
    _fake_http(monkeypatch, [200], seen)
    assert cl.server_ok("http://localhost:8768") is True
    assert seen[0]["url"] == "/health" and seen[0]["host"] == "127.0.0.1"
    assert "close" not in {str(v).lower() for v in seen[0]["headers"].values()}


def test_review6_a_read_result_survives_a_failed_park_and_unreadable_is_not_broke(monkeypatch):
    run = {"seed": 7, "route": "harbour", "mode": "vision", "seconds": 150, "lag_ms": 0}
    good = {"mode_seen": "vision", "world_seen": "coast:harbour", "lag_seen": 0, "gfx_seen": "medium", "autopilot": True, "crash": False,
            "sim_time_s": 150, "hidden": False, "distance_m": 1800, "red_light": 1, "events": [], "engaged": True}
    calls = []

    def fake_cdp(*args, **kw):
        calls.append(args)
        if args[0] == "nav" and args[2].endswith("/openapi.json"):
            raise RuntimeError("cdp hiccup")
        return ""

    monkeypatch.setattr(cl, "_cdp", fake_cdp)
    monkeypatch.setattr(cl, "_js", lambda target, code, timeout=120: dict(good) if "JSON.stringify" in code else 1)
    monkeypatch.setattr(cl, "server_ok", lambda base: True)
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    row = cl.drive("T", "http://x", run)
    assert row["ok"] is True and row["red_light"] == 1 and row.get("unreadable") is False
    # A read that fails is unknown, not a page that stopped.
    monkeypatch.setattr(cl, "_js", lambda target, code, timeout=120: (_ for _ in ()).throw(RuntimeError("timeout"))
                        if "JSON.stringify" in code else 1)
    row = cl.drive("T", "http://x", run)
    assert row["unreadable"] is True and row["broke"] is False


def test_review7_request_failures_come_from_the_pages_counters_expiry_from_the_events():
    got = {"events": ["40 Jev decision expired before it arrived. Replanning.", "42 Unexpected token 'I'",
                      "43 Jev decision expired before it arrived. Replanning."],
           "classifier": {"ok": 5, "http_errors": 2, "network_errors": 1, "bad_replies": 1, "gateway_errors": 1, "timeouts": 3}}
    assert cl.decision_trouble(got) == {"expired_decisions": 2, "outage_errors": 2, "system_errors": 6}


def test_review7_failed_rows_from_earlier_rules_are_not_reported():
    old_failed = {"set": "held_out", "mode": "vision", "seed": 104729, "ok": False,
                  "error": "decision service failed (the bundle paused after three failed requests)"}
    kept, dropped = cl.current_rows([old_failed], cl.load_seeds())
    assert kept == [] and dropped == [old_failed]


def test_review8_the_report_names_failures_of_the_system_under_test():
    rows = [_row("vision", 1, "festival", system_errors=4, stalled=True, distance_m=0.0), _row("vision", 2, "festival")]
    text = cl.report(cl.summarize(rows))
    assert "decision path errors (500s, timeouts, unreadable replies) during 1" in text
    assert cl.ROW_FORMAT == 7


class _FakeChrome:
    """Chrome as the DevTools HTTP endpoint and chrome-cdp-ex see it: pages with ids; `open` adds a
    page, /json/close removes one; closing the last page would quit Chrome (#39)."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.next = 1
        self.closed = []
        self.quit = False

    def cdp(self, *args, **kw):
        if args[0] == "open":
            pid = f"NEW{self.next:05d}" + "X" * 24
            self.next += 1
            self.pages.append({"id": pid, "url": args[1]})
            return ""
        if args[0] == "list":
            return "\n".join(f"{p['id'][:8]}  title  {p['url']}" for p in self.pages)
        if args[0] == "nav":
            for p in self.pages:
                if p["id"].startswith(args[1]):
                    p["url"] = args[2]
            return ""
        return ""

    def close(self, full_id):
        self.closed.append(full_id)
        self.pages = [p for p in self.pages if p["id"] != full_id]
        if not self.pages:
            self.quit = True


def _with_chrome(monkeypatch, chrome, rows):
    monkeypatch.setattr(cl, "_cdp", chrome.cdp)
    monkeypatch.setattr(cl, "_devtools_pages", lambda: list(chrome.pages))
    monkeypatch.setattr(cl, "_devtools_close", chrome.close)
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    seen = []

    def drive(target, base, run):
        seen.append(target)
        return dict(rows.pop(0) if rows else dict(ok=True, fmt=cl.ROW_FORMAT, stalled=False), **run)

    monkeypatch.setattr(cl, "drive", drive)
    return seen


def test_issue39_the_evaluation_closes_its_tab_and_keeps_an_anchor(monkeypatch, tmp_path):
    chrome = _FakeChrome([])  # a freshly launched debug Chrome with no page
    seen = _with_chrome(monkeypatch, chrome, [])
    cl.main(["--set", "tuning", "--seeds", "7", "--routes", "festival", "--modes", "vision", "--seconds", "30",
             "--out", str(tmp_path / "runs.jsonl")])
    assert not chrome.quit, "Chrome kept running: an anchor page stayed"
    assert [p["url"] for p in chrome.pages] == ["http://localhost:8768/openapi.json"], chrome.pages
    assert len(chrome.closed) == 1 and seen and all(t == seen[0] for t in seen)


def test_issue39_a_tab_whose_drive_never_started_is_replaced(monkeypatch, tmp_path):
    chrome = _FakeChrome([{"id": "ANCHOR" + "Y" * 26, "url": "http://localhost:8768/openapi.json"}])
    seen = _with_chrome(monkeypatch, chrome, [dict(ok=False, fmt=cl.ROW_FORMAT, error="setup: Error: Timeout: Page.enable")])
    cl.main(["--set", "tuning", "--seeds", "7", "31337", "--routes", "festival", "--modes", "vision", "--seconds", "30",
             "--out", str(tmp_path / "runs.jsonl")])
    assert seen[0] != seen[1], "the second run drove in a fresh tab"
    assert len(chrome.closed) == 2 and [p["id"][:6] for p in chrome.pages] == ["ANCHOR"]


def test_issue39_a_simulation_tab_of_another_server_does_not_block(monkeypatch, tmp_path):
    """Only a tab on the same server shares its vision slot; another session's server is not ours to refuse."""
    chrome = _FakeChrome([{"id": "OTHERSIM" + "Z" * 24, "url": "http://localhost:8790/jevpilot/?seed=1"},
                          {"id": "ANCHOR" + "Y" * 26, "url": "http://localhost:8790/openapi.json"}])
    seen = _with_chrome(monkeypatch, chrome, [])
    cl.main(["--set", "tuning", "--seeds", "7", "--routes", "festival", "--modes", "vision", "--seconds", "30",
             "--out", str(tmp_path / "runs.jsonl")])
    assert seen and cl.read_rows(tmp_path / "runs.jsonl")[0]["ok"] is True
    assert [p["id"][:8] for p in chrome.pages] == ["OTHERSIM", "ANCHORYY"]


def test_issue39_a_simulation_tab_of_the_same_server_still_blocks(monkeypatch, tmp_path):
    chrome = _FakeChrome([{"id": "OTHERSIM" + "Z" * 24, "url": "http://127.0.0.1:8768/jevpilot/?seed=1"}])
    _with_chrome(monkeypatch, chrome, [])
    with pytest.raises(SystemExit):
        cl.main(["--set", "tuning", "--seeds", "7", "--routes", "festival", "--modes", "vision", "--seconds", "30",
                 "--out", str(tmp_path / "runs.jsonl")])

def test_issue39_a_hidden_tab_is_replaced(monkeypatch, tmp_path):
    """A hidden tab does not step the simulation (another window took the foreground): it is a tab
    problem like a stalled load, so the next run gets a fresh tab."""
    chrome = _FakeChrome([{"id": "ANCHOR" + "Y" * 26, "url": "http://localhost:8768/openapi.json"}])
    seen = _with_chrome(monkeypatch, chrome, [dict(ok=False, fmt=cl.ROW_FORMAT, error="tab hidden (the simulation does not step)")])
    cl.main(["--set", "tuning", "--seeds", "7", "31337", "--routes", "festival", "--modes", "vision", "--seconds", "30",
             "--out", str(tmp_path / "runs.jsonl")])
    assert seen[0] != seen[1], "the second run drove in a fresh tab"
    assert len(chrome.closed) == 2


def test_issue39_review_m1_a_tab_still_closing_is_not_mistaken_for_someone_elses(monkeypatch, tmp_path):
    """/json/close returns before Chrome drops the target: the replacement waits for it to go, and the
    failed run's row is saved before any of that."""
    chrome = _FakeChrome([{"id": "ANCHOR" + "Y" * 26, "url": "http://localhost:8768/openapi.json"}])
    closing = []
    real_close, real_cdp = chrome.close, chrome.cdp

    def slow_close(full_id):
        closing.append([p for p in chrome.pages if p["id"] == full_id][0])
        real_close(full_id)

    def cdp(*args, **kw):
        if args[0] == "list" and closing:
            return real_cdp(*args) + "".join(f"\n{p['id'][:8]}  title  {p['url']}" for p in closing[-1:])
        return real_cdp(*args, **kw)

    def pages():
        out = list(chrome.pages) + list(closing)
        closing.clear()  # gone by the next look
        return out

    seen = _with_chrome(monkeypatch, chrome, [dict(ok=False, fmt=cl.ROW_FORMAT, error="setup: Error: Timeout: Page.enable")])
    monkeypatch.setattr(cl, "_cdp", cdp)
    monkeypatch.setattr(cl, "_devtools_close", slow_close)
    monkeypatch.setattr(cl, "_devtools_pages", pages)
    cl.main(["--set", "tuning", "--seeds", "7", "31337", "--routes", "festival", "--modes", "vision", "--seconds", "30",
             "--out", str(tmp_path / "runs.jsonl")])
    rows = cl.read_rows(tmp_path / "runs.jsonl")
    assert [r["ok"] for r in rows] == [False, True] and seen[0] != seen[1]


def test_issue39_review_m2_a_tab_someone_else_opens_meanwhile_is_not_claimed(monkeypatch, tmp_path):
    chrome = _FakeChrome([{"id": "ANCHOR" + "Y" * 26, "url": "http://localhost:8768/openapi.json"}])
    real_cdp = chrome.cdp

    def cdp(*args, **kw):
        if args[0] == "open" and "/jevpilot" in args[1]:
            chrome.pages.append({"id": "AAAFOREIGN" + "Q" * 22, "url": "https://example.com/"})  # listed first
        return real_cdp(*args, **kw)

    seen = _with_chrome(monkeypatch, chrome, [])
    monkeypatch.setattr(cl, "_cdp", cdp)
    cl.main(["--set", "tuning", "--seeds", "7", "--routes", "festival", "--modes", "vision", "--seconds", "30",
             "--out", str(tmp_path / "runs.jsonl")])
    assert seen[0].startswith("NEW") and any(p["id"].startswith("AAAFOREIGN") for p in chrome.pages)


def test_issue39_review_l2_an_anchor_closed_mid_evaluation_is_restored_before_a_replacement(monkeypatch, tmp_path):
    chrome = _FakeChrome([{"id": "ANCHOR" + "Y" * 26, "url": "http://localhost:8768/openapi.json"}])
    seen = _with_chrome(monkeypatch, chrome, [])

    def drive(target, base, run):
        seen.append(target)
        chrome.pages = [p for p in chrome.pages if not p["id"].startswith("ANCHOR")]  # the user closed it
        return dict(ok=False, fmt=cl.ROW_FORMAT, error="tab hidden (the simulation does not step)", **run)

    monkeypatch.setattr(cl, "drive", drive)
    cl.main(["--set", "tuning", "--seeds", "7", "--routes", "festival", "--modes", "vision", "--seconds", "30",
             "--out", str(tmp_path / "runs.jsonl")])
    assert not chrome.quit


# ---- Graphics quality (docs/superpowers/specs/2026-10-03-visual-quality-design.md §4.3) ---------

def test_runs_carry_the_graphics_quality_and_old_rows_count_as_medium():
    plan = cl.plan_runs([1], ["festival"], ["vision"], seconds=150, lag_ms=0, gfx="high")
    assert plan[0]["gfx"] == "high"
    assert "gfx=high" in cl.page_url("http://localhost:8768", plan[0])
    assert cl.plan_runs([1], ["festival"], ["vision"], seconds=150, lag_ms=0)[0]["gfx"] == "medium"
    old = {"seed": 1, "route": "festival", "mode": "vision", "seconds": 150, "lag_ms": 0}
    assert cl._key(old) == cl._key(dict(old, gfx="medium"))
    assert cl._key(old) != cl._key(dict(old, gfx="high"))


def test_the_report_keeps_medium_and_high_apart():
    rows = [_row("vision", 1, "festival"), _row("vision", 1, "festival", gfx="high", red_light=1, violations=1)]
    summary = cl.summarize(rows)
    assert set(summary) == {("held_out", "vision", 150, 0, "medium"), ("held_out", "vision", 150, 0, "high")}
    text = cl.report(summary)
    assert "gfx medium" in text and "gfx high" in text


def test_a_page_on_the_wrong_quality_is_a_setup_failure():
    run = cl.plan_runs([1], ["festival"], ["vision"], seconds=150, lag_ms=0, gfx="high")[0]
    got = {"mode_seen": "vision", "world_seen": "coast:festival", "lag_seen": 0, "engaged": True, "distance_m": 1500}
    assert cl.validate(run, dict(got, gfx_seen="medium")) == "drove graphics 'medium'"
    assert cl.validate(run, dict(got, gfx_seen="high")) is None
    assert cl.validate(run, got) == "drove graphics None", "a coast page always reports its quality"


def test_issue19_review_the_evaluation_never_draws_the_candidate_fan():
    """A fan remembered in the evaluation's Chrome profile would keep the planner worker busy before
    the drive and draw a dozen extra lines: the page always shows the chosen path only."""
    assert "candidates=selected" in cl.page_url("http://localhost:8768", {"seed": 7, "route": "harbour", "mode": "vision"})


def test_issue22_evaluations_drive_todays_density_and_a_page_on_another_is_a_setup_failure():
    """Low is the coast every earlier result drove; the default (medium) would make them incomparable."""
    url = cl.page_url("http://localhost:8768", {"seed": 7, "route": "harbour", "mode": "vision"})
    assert "traffic=low&people=low" in url
    run = cl.plan_runs([1], ["festival"], ["vision"], seconds=150, lag_ms=0)[0]
    got = {"mode_seen": "vision", "world_seen": "coast:festival", "lag_seen": 0, "engaged": True, "distance_m": 1500, "gfx_seen": "medium"}
    assert cl.validate(run, dict(got, density_seen={"traffic": "med", "people": "low"})) == "drove density {'traffic': 'med', 'people': 'low'}"
    assert cl.validate(run, dict(got, density_seen={"traffic": "low", "people": "low"})) is None
    assert cl.validate(run, got) is None, "a page from before #22 drove today's counts"
