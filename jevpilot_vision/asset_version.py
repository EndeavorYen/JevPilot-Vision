"""Asset versions from content (#63).

The page and the bundle chain (index -> main -> planner worker -> generator) write every cache-busting
version as the one token `?v=HASH`. The server fills each with the referenced file's hash, taken
after that file's own tokens are filled, so a change down a chain of `?v=HASH` references changes
every URL above it, and nobody bumps a version by hand. Only such references carry it: a module's
own plain imports (semif-world/index.js -> ./kit.js) do not, and rely on the server's no-cache
revalidation. A reference that resolves to no file keeps the token.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, NamedTuple, Optional, Tuple

TOKEN = "?v=HASH"
_REF = re.compile(rb"([A-Za-z0-9_./-]+?\.(?:js|css))\?v=HASH")


class _Entry(NamedTuple):
    stamp: Tuple[int, int]  # mtime_ns, size, taken before the bytes were read
    refs: Tuple[str, ...]  # the `?v=HASH` references in the file
    deps: Tuple[Tuple[str, str], ...]  # (reference, digest) it was filled with
    served: bytes
    digest: str


class AssetVersions:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._memo: Dict[Path, _Entry] = {}

    def _resolve(self, ref: str, base: Path) -> Optional[Path]:
        if ref.startswith("/jevpilot/"):
            candidates = [self.root / ref[len("/jevpilot/"):]]
        elif ref.startswith("./") or ref.startswith("../"):
            candidates = [base.parent / ref]
        else:  # "assets/x.js" in the bundle's preload list is relative to the page, not the bundle
            candidates = [base.parent / ref, self.root / ref]
        for path in candidates:
            path = path.resolve()
            if self.root in path.parents and path.is_file():
                return path
        return None

    def served(self, path: Path) -> bytes:
        return self._fill(Path(path).resolve(), ()).served

    def digest(self, path: Path) -> str:
        return self._fill(Path(path).resolve(), ()).digest

    def has_refs(self, path: Path) -> bool:
        return bool(self._fill(Path(path).resolve(), ()).refs)

    def _fill(self, path: Path, stack: Tuple[Path, ...]) -> _Entry:
        st = path.stat()  # before reading: a write after it shows as a new stamp next time
        stamp = (st.st_mtime_ns, st.st_size)
        memo = self._memo.get(path)
        if memo is not None and memo.stamp == stamp:
            refs, raw = memo.refs, None
        else:
            raw = path.read_bytes()
            refs = tuple(sorted({m.group(1).decode() for m in _REF.finditer(raw)}))
        deps = []
        for ref in refs:
            target = self._resolve(ref, path)
            if target is None or target in stack or target == path:
                continue  # unresolved or a cycle: the token stays
            deps.append((ref, self._fill(target, stack + (path,)).digest))
        deps_t = tuple(deps)
        if memo is not None and memo.stamp == stamp and memo.deps == deps_t:
            return memo
        if raw is None:
            raw = path.read_bytes()
        filled = dict(deps_t)
        out = _REF.sub(lambda m: m.group(1) + b"?v=" + filled[m.group(1).decode()].encode()
                       if m.group(1).decode() in filled else m.group(0), raw) if refs else raw
        entry = _Entry(stamp, refs, deps_t, out, hashlib.sha1(out).hexdigest()[:10])
        self._memo[path] = entry
        return entry


def versioned_static(directory: Path):
    """StaticFiles that serves files with `?v=HASH` references filled in, their digest as ETag (a
    matching If-None-Match gets 304). Files without such references are served as before."""
    import anyio
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse, Response

    versions = AssetVersions(directory)

    class VersionedStaticFiles(StaticFiles):
        async def get_response(self, path, scope):  # type: ignore[override]
            response = await super().get_response(path, scope)
            file = getattr(response, "path", None)
            if not (isinstance(response, FileResponse) and file and str(file).endswith((".html", ".js", ".css"))):
                return response
            entry = await anyio.to_thread.run_sync(versions._fill, Path(file).resolve(), ())
            if not entry.refs:
                return response
            etag = f'"{entry.digest}"'
            headers = {"ETag": etag}
            match = dict((k.decode().lower(), v.decode()) for k, v in scope.get("headers", [])).get("if-none-match")
            if match and etag in [m.strip() for m in match.split(",")]:
                return Response(status_code=304, headers=headers)
            return Response(content=entry.served, status_code=response.status_code, media_type=response.media_type, headers=headers)

    return VersionedStaticFiles(directory=str(directory), html=True)
