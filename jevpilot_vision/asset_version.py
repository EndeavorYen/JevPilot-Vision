"""Asset versions from content (#63).

The page and the bundle chain (index -> main -> planner worker -> generator) write every cache-busting
version as the one token `?v=HASH`. The server fills each with the referenced file's hash, taken
after that file's own tokens are filled, so a change anywhere down a chain changes every URL above
it, and nobody bumps a version by hand. A reference that resolves to no file keeps the token.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

TOKEN = "?v=HASH"
_REF = re.compile(rb"([A-Za-z0-9_./-]+?\.(?:js|css))\?v=HASH")


class AssetVersions:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        # path -> (mtime_ns, the digests it was filled with, served bytes, digest)
        self._memo: Dict[Path, Tuple[int, Tuple[Tuple[str, str], ...], bytes, str]] = {}

    def _resolve(self, ref: str, base: Path) -> Optional[Path]:
        if ref.startswith("/jevpilot/"):
            candidates = [self.root / ref[len("/jevpilot/"):]]
        elif ref.startswith("./") or ref.startswith("../"):
            candidates = [base.parent / ref]
        else:  # "assets/x.js" in the bundle's preload list is relative to the page, not the bundle
            candidates = [base.parent / ref, self.root / ref]
        for path in candidates:
            path = path.resolve()
            if path.is_file() and self.root in path.parents:
                return path
        return None

    def served(self, path: Path, _stack: Tuple[Path, ...] = ()) -> bytes:
        return self._fill(Path(path).resolve(), _stack)[0]

    def digest(self, path: Path) -> str:
        return self._fill(Path(path).resolve(), ())[1]

    def _fill(self, path: Path, stack: Tuple[Path, ...]) -> Tuple[bytes, str]:
        raw = path.read_bytes()
        refs = sorted({m.group(1).decode() for m in _REF.finditer(raw)})
        deps = []
        for ref in refs:
            target = self._resolve(ref, path)
            if target is None or target in stack or target == path:
                continue  # unresolved or a cycle: the token stays
            deps.append((ref, self._fill(target, stack + (path,))[1]))
        key = (path.stat().st_mtime_ns, tuple(deps))
        memo = self._memo.get(path)
        if memo and memo[:2] == key:
            return memo[2], memo[3]
        filled = dict(deps)
        out = _REF.sub(lambda m: m.group(1) + b"?v=" + filled[m.group(1).decode()].encode()
                       if m.group(1).decode() in filled else m.group(0), raw)
        digest = hashlib.sha1(out).hexdigest()[:10]
        self._memo[path] = (key[0], key[1], out, digest)
        return out, digest


def versioned_static(directory: Path):
    """StaticFiles that serves .html/.js/.css with their version tokens filled."""
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse, Response

    versions = AssetVersions(directory)

    class VersionedStaticFiles(StaticFiles):
        async def get_response(self, path, scope):  # type: ignore[override]
            response = await super().get_response(path, scope)
            file = getattr(response, "path", None)
            if isinstance(response, FileResponse) and file and str(file).endswith((".html", ".js", ".css")):
                body = versions.served(Path(file))
                if body != Path(file).read_bytes() or TOKEN.encode() in body:
                    return Response(content=body, status_code=response.status_code, media_type=response.media_type)
            return response

    return VersionedStaticFiles(directory=str(directory), html=True)
