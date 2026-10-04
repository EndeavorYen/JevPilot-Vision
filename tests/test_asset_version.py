"""Asset versions come from content, written in one place: the server (#63).

Every `?v=HASH` in the page and the bundle chain is served as the referenced file's content hash,
taken after its own references are filled in, so a change anywhere down the chain (the generator
the planner worker imports) reaches every URL above it. Nobody bumps a version by hand.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from jevpilot_vision.asset_version import TOKEN, AssetVersions

WEB = Path(__file__).resolve().parents[1] / "jevpilot_vision" / "web"
CHAIN = ["index.html", "assets/index-DC8fTtby.js", "assets/main-CvLEeHjW.js", "assets/planner.worker-DFdG3q6n.js",
         "semif-worldgen.js", "semif-layer.js", "semif-encode-worker.js"]


def _versions(text: str) -> dict[str, str]:
    return {name: v for name, v in re.findall(r"([\w.-]+\.(?:js|css))\?v=(\w+)", text)}


def test_issue63_every_version_in_the_repo_is_the_one_token():
    for rel in CHAIN[:4] + ["semif-layer.js"]:  # the files that load others
        text = (WEB / rel).read_text(encoding="utf-8")
        found = re.findall(r"\?v=(\w+)", text)
        assert found and set(found) == {"HASH"}, (rel, found)


def test_issue63_the_server_fills_each_version_with_the_referenced_files_hash():
    from demo.server import app

    client = TestClient(app)
    page = client.get("/jevpilot/").text
    assert TOKEN not in page
    versions = _versions(page)
    assert re.fullmatch(r"[0-9a-f]{10}", versions["semif-layer.js"])
    layer = client.get("/jevpilot/semif-layer.js?v=" + versions["semif-layer.js"]).text
    assert TOKEN not in layer
    stack = AssetVersions(WEB)
    assert versions["semif-layer.js"] == stack.digest(WEB / "semif-layer.js")
    assert versions["semif-layer.css"] == stack.digest(WEB / "semif-layer.css")
    # down the bundle chain: index -> main -> worker -> generator
    index = client.get("/jevpilot/assets/index-DC8fTtby.js").text
    main = client.get("/jevpilot/assets/main-CvLEeHjW.js").text
    worker = client.get("/jevpilot/assets/planner.worker-DFdG3q6n.js").text
    assert TOKEN not in index + main + worker
    assert _versions(index)["main-CvLEeHjW.js"] == stack.digest(WEB / "assets" / "main-CvLEeHjW.js")
    assert _versions(main)["planner.worker-DFdG3q6n.js"] == stack.digest(WEB / "assets" / "planner.worker-DFdG3q6n.js")
    assert _versions(worker)["semif-worldgen.js"] == versions["semif-worldgen.js"], "the page and the worker load one generator"


def test_issue63_a_change_at_the_bottom_of_the_chain_reaches_every_url_above_it(tmp_path):
    root = tmp_path / "web"
    for rel in CHAIN:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WEB / rel, root / rel)
    stack = AssetVersions(root)
    before = {rel: stack.digest(root / rel) for rel in CHAIN}
    gen = root / "semif-worldgen.js"
    gen.write_text(gen.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    after = {rel: stack.digest(root / rel) for rel in CHAIN}
    for rel in ("semif-worldgen.js", "assets/planner.worker-DFdG3q6n.js", "assets/main-CvLEeHjW.js",
                "assets/index-DC8fTtby.js", "index.html"):
        assert after[rel] != before[rel], rel
    assert after["semif-layer.js"] == before["semif-layer.js"], "a file that does not load it keeps its version"
    # filled where the target exists; a missing target leaves the token and nothing breaks
    assert b"semif-worldgen.js" + TOKEN.encode() not in stack.served(root / "index.html")
    assert b"semif-stats.js" + TOKEN.encode() in stack.served(root / "index.html"), "not copied here"
    (root / "semif-encode-worker.js").unlink()
    assert TOKEN.encode() in stack.served(root / "semif-layer.js")
