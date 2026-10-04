// The nearest point on a route, without scanning the whole route (#42 item 4).
//
// The bundle's nearest-point search (main `p`, worker `l`) walks every segment of a route from the
// start, and its forward simulations call it about three times per 0.1 s step. Routes are resampled
// every metre, so on the coast (routes of 1,300-3,000 points) that walk is most of the planner's time
// in traffic. SEMIF_NEAREST answers the same question from a grid of segment bounding boxes and gives
// the very same object, bit for bit: it widens the search ring by ring and stops only when the best
// distance found is strictly shorter than the way out of the searched square, so no segment outside
// could be as near; candidates are compared as the bundle does (same arithmetic, the first index wins
// a tie). The bundle calls it only on the coast and only for its full-route searches (no start hint).
(function (root) {
  const CELL = 8; // metres: a cell holds about eight 1 m segments
  const indexes = new WeakMap();
  let stamp = 0;

  function build(pts) {
    const cells = new Map();
    let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
    for (let a = 0; a < pts.length - 1; a++) {
      const n = pts[a], o = pts[a + 1];
      const x0 = Math.floor(Math.min(n.x, o.x) / CELL), x1 = Math.floor(Math.max(n.x, o.x) / CELL);
      const z0 = Math.floor(Math.min(n.z, o.z) / CELL), z1 = Math.floor(Math.max(n.z, o.z) / CELL);
      minX = Math.min(minX, x0); maxX = Math.max(maxX, x1); minZ = Math.min(minZ, z0); maxZ = Math.max(maxZ, z1);
      for (let x = x0; x <= x1; x++) {
        for (let z = z0; z <= z1; z++) {
          const key = x * 65536 + z;
          let list = cells.get(key);
          if (!list) cells.set(key, (list = []));
          list.push(a);
        }
      }
    }
    return { cells, minX, minZ, maxX, maxZ, n: pts.length, last: pts[pts.length - 1], seen: new Int32Array(pts.length) };
  }

  function indexOf(pts) {
    let idx = indexes.get(pts);
    // A route grows only while it is built (points.push); a changed length or end rebuilds.
    if (!idx || idx.n !== pts.length || idx.last !== pts[pts.length - 1]) {
      idx = build(pts);
      indexes.set(pts, idx);
    }
    return idx;
  }

  // The bundle's own per-segment arithmetic, in its order.
  function segment(e, n, o, clamp) {
    const s = o.x - n.x, c = o.z - n.z, u = s * s + c * c;
    const d = clamp(((e.x - n.x) * s + (e.z - n.z) * c) / (u || 1), 0, 1);
    const f = n.x + s * d, p = n.z + c * d;
    return { m: Math.hypot(e.x - f, e.z - p), d, f, p, u };
  }

  function nearest(e, pts, clamp, heading) {
    let r = { distance: 1 / 0, index: 0, t: 0, x: 0, z: 0, s: 0 };
    if (!pts || pts.length < 2 || !Number.isFinite(e.x) || !Number.isFinite(e.z)) {
      for (let a = 0; a < (pts ? pts.length - 1 : 0); a++) {
        const g = segment(e, pts[a], pts[a + 1], clamp);
        if (g.m < r.distance) r = { distance: g.m, index: a, t: g.d, x: g.f, z: g.p, s: pts[a].s + Math.sqrt(g.u) * g.d, heading: heading(pts[a], pts[a + 1]) };
      }
      return r;
    }
    const idx = indexOf(pts);
    const cx = Math.floor(e.x / CELL), cz = Math.floor(e.z / CELL);
    const last = Math.max(Math.abs(cx - idx.minX), Math.abs(cx - idx.maxX), Math.abs(cz - idx.minZ), Math.abs(cz - idx.maxZ));
    const mark = ++stamp;
    let bestM = 1 / 0, bestA = -1, best = null;
    const visit = (x, z) => {
      const list = idx.cells.get(x * 65536 + z);
      if (!list) return;
      for (const a of list) {
        if (idx.seen[a] === mark) continue;
        idx.seen[a] = mark;
        const g = segment(e, pts[a], pts[a + 1], clamp);
        if (g.m < bestM || (g.m === bestM && a < bestA)) {
          bestM = g.m;
          bestA = a;
          best = g;
        }
      }
    };
    for (let ring = 0; ring <= last; ring++) {
      if (ring === 0) visit(cx, cz);
      else {
        for (let x = cx - ring; x <= cx + ring; x++) {
          visit(x, cz - ring);
          visit(x, cz + ring);
        }
        for (let z = cz - ring + 1; z <= cz + ring - 1; z++) {
          visit(cx - ring, z);
          visit(cx + ring, z);
        }
      }
      const out = Math.min(e.x - (cx - ring) * CELL, (cx + ring + 1) * CELL - e.x, e.z - (cz - ring) * CELL, (cz + ring + 1) * CELL - e.z);
      if (bestA >= 0 && bestM < out) break;
    }
    if (bestA < 0) return r;
    const n = pts[bestA], o = pts[bestA + 1];
    return { distance: best.m, index: bestA, t: best.d, x: best.f, z: best.p, s: n.s + Math.sqrt(best.u) * best.d, heading: heading(n, o) };
  }

  root.SEMIF_NEAREST = nearest;
  if (typeof module !== "undefined" && module.exports) module.exports = { nearest, CELL };
})(typeof globalThis !== "undefined" ? globalThis : this);
