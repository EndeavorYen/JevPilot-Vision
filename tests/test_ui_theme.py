"""#20: one token set drives the overlay, and a new loading screen with real progress.

The bundle's DOM and JS are untouched; semif-layer.css restyles its components and ours from the
custom properties in a single :root block, and semif-loader.js turns the bundle's loading stages
and asset downloads into a progress bar.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "jevpilot_vision" / "web"
CSS = (WEB / "semif-layer.css").read_text(encoding="utf-8")
HTML = (WEB / "index.html").read_text(encoding="utf-8")
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(")


def _token_block() -> tuple[int, int]:
    start = CSS.index(":root {")
    return start, CSS.index("\n}\n", start)


def test_colours_live_only_in_the_token_block():
    start, end = _token_block()
    outside = CSS[:start] + CSS[end:]
    stray = [m.group(0) for m in COLOUR.finditer(outside)]
    assert not stray, f"hard-coded colours outside :root: {stray[:8]}"
    assert len(re.findall(r"^:root \{", CSS, re.M)) == 1, "one token block"


def test_the_token_block_defines_the_design_language():
    start, end = _token_block()
    tokens = set(re.findall(r"(--sol-[a-z0-9-]+):", CSS[start:end]))
    for name in ["--sol-panel", "--sol-ink", "--sol-muted", "--sol-line", "--sol-accent", "--sol-ok", "--sol-wait",
                 "--sol-danger", "--sol-radius-lg", "--sol-radius-md", "--sol-font", "--sol-motion",
                 "--sol-viz-1", "--sol-viz-2", "--sol-viz-3", "--sol-viz-4", "--sol-viz-surface"]:
        assert name in tokens, name
    used = set(re.findall(r"var\((--sol-[a-z0-9-]+)", CSS))
    assert used <= tokens, f"undefined tokens: {sorted(used - tokens)}"
    assert "prefers-reduced-motion" in CSS


def test_the_page_keeps_the_loader_contract_the_bundle_drives():
    for ident in ['id="scene-loader"', 'id="loading-message"', 'id="loading-retry"', 'id="app"']:
        assert ident in HTML, ident
    assert not COLOUR.search(HTML.split("<body", 1)[1]), "no inline colours in the page body"
    assert "<style>" not in HTML, "the loader is styled from the token sheet"
    assert 'role="progressbar"' in HTML
    loader = HTML.index("semif-loader.js")
    assert loader < HTML.index("assets/index-DC8fTtby.js"), "the loader listens before the bundle starts"
    assert "JevPilot" not in HTML.split("<body", 1)[1], "a new face, not the JevPilot loader"


def _loader(body: str):
    script = (WEB / "semif-loader.js").read_text(encoding="utf-8")
    code = "globalThis.window = globalThis; globalThis.document = undefined;\n" + script + "\n" + body
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_progress_follows_the_bundles_stages_and_downloads():
    got = _loader(
        "const p = window.SEMIF_LOADER.progress;"
        "process.stdout.write(JSON.stringify({"
        "  start: p('Preparing the map…', 0), road: p('Preparing the road…', 0), roadMore: p('Preparing the road…', 30),"
        "  car: p('Loading car and scenery…', 0), carMore: p('Loading car and scenery…', 400),"
        "  drive: p('Building your next drive…', 0), unknown: p('Something new', 3), done: p(null, 0, true) }));"
    )
    # The order the bundle shows them, recorded in the browser: the page's own "Preparing the map",
    # then "Loading car and scenery" (the downloads), "Preparing the road", hidden. A later drive
    # opens with "Building your next drive".
    order = [got["start"], got["drive"], got["car"], got["road"]]
    assert order == sorted(order) and len(set(order)) == 4, order
    assert got["car"] < got["carMore"] < got["road"], "downloads move the bar within a stage, never past the next"
    assert got["road"] < got["roadMore"] < 1
    assert 0 <= got["unknown"] < 1
    assert got["done"] == 1
    assert all(0 <= v < 1 for k, v in got.items() if k != "done")


def test_the_overlay_scripts_paint_no_inline_colours():
    layer = (WEB / "semif-layer.js").read_text(encoding="utf-8")
    clock = (WEB / "semif-world" / "clock.js").read_text(encoding="utf-8")
    assert "halo.style." not in layer, "the proximity halo is styled by state (data-level)"
    assert "dataset.level" in layer
    assert not re.search(r"background:\s*\"(?:#|rgba)", clock), "the clock chip is styled by the token sheet"


def test_the_latency_charts_read_their_colours_from_the_tokens():
    stats = (WEB / "semif-stats.js").read_text(encoding="utf-8")
    assert "getComputedStyle" in stats
    for name in ["--sol-viz-1", "--sol-viz-2", "--sol-viz-3", "--sol-viz-4", "--sol-viz-surface"]:
        assert name in stats, name


def _rule(selector: str, within: str = CSS) -> str:
    i = within.index(selector + " {")
    return within[i:within.index("}", i)]


def test_review_h1_the_route_map_keeps_a_fixed_width_when_dragged_out():
    """The bundle's drag gives #minimap inline position: fixed; a percentage width would then
    resolve against the window and stretch the map across it."""
    rule = _rule("  body.fsd-theme .navigation-hud .minimap")
    width = re.search(r"width:\s*([^;]+);", rule).group(1)
    assert "%" not in width and "px" in width, width


def test_review_m2_the_latency_panel_opens_beside_the_column_only_where_both_columns_stay_clear():
    """Beside the command column it needs room between the column (392 px) and the navigation
    stack (306 px): from 1318 px wide it gets at least 600 px; narrower windows keep the original
    placement over the command column, never over the map."""
    beside = CSS[CSS.index("@media (min-width: 1318px) {"):]
    rule = beside[:beside.index("}")]
    assert "#fsd-stats" in rule and "left: 392px" in rule
    assert re.search(r"width: min\(620px, calc\(100vw - 714px\)\)", rule), rule
    desktop = CSS[CSS.index("@media (min-width: 901px) {"):CSS.index("@media (min-width: 1318px) {")]
    assert "#fsd-stats" not in desktop


def test_review_m3_legend_swatches_and_bands_follow_the_tokens():
    stats = (WEB / "semif-stats.js").read_text(encoding="utf-8")
    assert '+ "2e"' not in stats, "the band's alpha does not assume a 6-digit hex colour"
    assert "globalAlpha" in stats
    assert "background:var(${s.token}" in stats, "swatches use the token itself"


def test_review_m4_the_percentage_is_not_announced_every_step():
    label = re.search(r'<span class="sol-progress-label"[^>]*>', HTML).group(0)
    assert 'aria-hidden="true"' in label


def test_review_m5_the_two_halo_levels_stay_apart():
    watch, near = _rule('#fsd-halo[data-level="watch"]'), _rule('#fsd-halo[data-level="near"]')
    assert "--sol-wait" in watch and "--sol-danger" in near


def test_review_l9_the_surround_picture_labels_use_the_tokens():
    layer = (WEB / "semif-layer.js").read_text(encoding="utf-8")
    assert '"rgba(8, 10, 14, 0.6)"' not in layer and '"#e8edf3"' not in layer
    assert "--sol-scrim" in layer and "--sol-font" in layer


def test_the_mode_indicator_stays_in_the_minimal_view():
    """#21: the driving mode is always on screen; the minimal view folds everything else away."""
    hidden = re.search(r"body\.semif-minimal :is\(([^)]*)\)\s*\{\s*display: none !important;", CSS).group(1)
    assert "#sol-mode" not in hidden and ".sol-mode" not in hidden
    assert "#sol-mode {" in CSS and "z-index: 46;" in _rule("#sol-mode")
