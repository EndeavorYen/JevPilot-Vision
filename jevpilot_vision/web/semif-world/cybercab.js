// The Cybercab-style hero (#90), rebuilt from photos of the 2024 show car (Wikimedia Commons, see
// docs/visual/cybercab/README.md) with the img2threejs workflow: analysis, spec, passes reviewed
// against the references. No Tesla emblems or lettering.
//
// One lofted shell carries the whole body: every section is a custom outline (sill, near-vertical
// side, shoulder, then either the hood -- raised fenders, a valley between -- or a narrower glass
// house with tumblehome), so the canopy, the hood valley and the shoulder line are one surface.
// Quads take their material from where they sit: paint, canopy glass, the dark rear-quarter
// window, dark cladding along the sills, chin and rear bumper.
//
// Host contract (vehicles.js): outer box 4.75 x 1.9 m, nose toward -z, wheel pivots
// wheel_fl/fr/rl/rr with userData.radius/front and a spinning children[0], the canopy in the
// material named `Glass`, and new geometry on every call (the bundle dents it in place).
import { PALETTE, T, material, physical } from "./kit.js";
import { lathe, box, Parts } from "./shapes.js";

// A monotone cubic through keys [[t, value], ...] (Fritsch-Carlson): smooth, with no flat spot at
// each key (unlike shapes.curve's cosine easing, which ripples a lofted surface) and no overshoot.
function spline(keys) {
  const n = keys.length, t = keys.map((k) => k[0]), v = keys.map((k) => k[1]);
  const d = [], m = new Array(n).fill(0);
  for (let i = 0; i < n - 1; i++) d.push((v[i + 1] - v[i]) / (t[i + 1] - t[i]));
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (d[i - 1] * d[i] <= 0) continue; // a local extremum stays flat: no overshoot
    const h0 = t[i] - t[i - 1], h1 = t[i + 1] - t[i], w1 = 2 * h1 + h0, w2 = h1 + 2 * h0;
    m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i]);
  }
  return (x) => {
    if (x <= t[0]) return v[0];
    if (x >= t[n - 1]) return v[n - 1];
    let i = 0;
    while (x > t[i + 1]) i++;
    const h = t[i + 1] - t[i], u = (x - t[i]) / h, u2 = u * u, u3 = u2 * u;
    return (2 * u3 - 3 * u2 + 1) * v[i] + (u3 - 2 * u2 + u) * h * m[i] + (-2 * u3 + 3 * u2) * v[i + 1] + (u3 - u2) * h * m[i + 1];
  };
}

const C = PALETTE.car;
export const CYBERCAB = {
  L: 4.75,
  r: 0.42, // wheel radius: big wheels pushed out to the corners (overhangs 0.74 and 0.85 wheel diameters)
  w: 0.26,
  front: -1.7,
  rear: 1.62,
  eye: [1.1, 0.2],
};
const L2 = CYBERCAB.L / 2;

// Profiles along z (metres). Measured on the side photo and scaled into the host's 4.75 m box.
// Round in plan at the nose (the face wraps into the fenders), squarer at the tail.
const half = spline([[-L2, 0.46], [-2.36, 0.62], [-2.33, 0.72], [-2.28, 0.8], [-2.2, 0.868], [-2.08, 0.915], [-1.95, 0.936], [-1.7, 0.946], [1.8, 0.946], [2.15, 0.945], [2.3, 0.938], [L2, 0.925]]); // 3 mm under 0.95 leaves room for the door lines // the rear haunches are as wide as the car
const sill = spline([[-L2, 0.31], [-2.35, 0.25], [-2.29, 0.215], [-2.15, 0.19], [-1.9, 0.18], [1.9, 0.18], [2.2, 0.2], [L2, 0.27]]);
// The fenders stand high over the big front wheels; the hood's centre stays low between them.
// The nose stands tall and the hood rises in one sweep into the windscreen (no flat deck).
const shoulder = spline([[-L2, 0.67], [-2.33, 0.735], [-2.22, 0.8], [-2.05, 0.855], [-1.82, 0.905], [-1.55, 0.945], [-1.3, 0.972], [-0.9, 0.988], [0.5, 0.99], [1.5, 1.0], [1.9, 1.0], [2.25, 0.975], [L2, 0.94]]);
// The hood's centre sits in a shallow valley between the fenders: none at the nose (the fenders
// must not end in points), 5 cm at the windscreen base.
const valley = spline([[-L2, 0.0], [-2.2, 0.015], [-1.8, 0.035], [-1.35, 0.045]]);
const hood = (z) => shoulder(z) - valley(z);
const roof = spline([[-1.35, 0.972], [-0.95, 1.13], [-0.45, 1.3], [0.05, 1.42], [0.5, 1.47], [0.95, 1.45], [1.5, 1.32], [2.0, 1.13], [L2, 0.97]]);
const house = spline([[-1.45, 0.8], [-0.6, 0.8], [0.6, 0.8], [1.4, 0.775], [2.0, 0.72], [L2, 0.68]]); // glass-house half width at the belt
const CANOPY_FROM = -1.35;
const GLASS_TO = 0.95; // the side glass ends here; behind it a painted fastback, no rear window
const ROOF_FROM = -0.45; // the windscreen runs up to here; from here back the roof is painted
const QUARTER = [0.95, 1.62]; // the dark rear-quarter window
const NOSE0 = -L2 + 0.045; // the shell starts here; its domed nose cap reaches -L2
const TAIL = L2 - 0.06; // the tail face, set back under the duckbill lip that reaches L2

// The right half of a section, from the bottom centre up to the top centre: [x, y] pairs.
function halfOutline(z, bottom) {
  const hb = half(z), yb = bottom, ys = shoulder(z);
  // Over a wheel the side runs straight down to the arch's edge (a clean cut through a vertical
  // side); elsewhere the sill rolls under. The blend keeps the arch's ends smooth.
  const arch = Math.min(1, Math.max(0, (bottom - sill(z)) / 0.08));
  const roll = 1 - arch;
  // Widest at mid height, drawn in toward the shoulder (tumblehome) with a generous radius, so
  // the section reads round and streamlined rather than slab-sided.
  const y3 = yb + 0.02 + 0.13 * roll;
  const y5 = Math.max(y3 + 0.01, ys - 0.12), y6 = Math.max(y5 + 0.008, ys - 0.035), y7 = Math.max(y6 + 0.006, ys);
  const side = [
    [0, yb], [hb - 0.02 - 0.1 * roll, yb], [hb - 0.012 - 0.02 * roll, yb + 0.006 + 0.044 * roll], [hb - 0.004, y3],
    [hb, (y3 + y5) / 2], [hb - 0.022, y5], [hb - 0.06, y6], [hb - 0.12, y7],
  ];
  // The hood: raised fenders, a shallow valley in the middle.
  const yc = z < CANOPY_FROM ? hood(z) : hood(CANOPY_FROM);
  // Round fenders: the crest sits inboard (about 0.6 m out) and rolls down to the side; the hood's
  // centre lies in a valley between the two crests.
  const crest = Math.min(0.62, hb - 0.2);
  const top = [[hb - 0.17, ys - 0.012], [crest, ys + 0.012], [crest * 0.62, (ys + yc) / 2], [crest * 0.28, yc + 0.003], [0, yc]];
  if (z >= CANOPY_FROM) {
    // The glass house, blended in from the windscreen base so the surface stays continuous.
    const yr = roof(z), hg = Math.min(house(z), hb - 0.1);
    const g = Math.min(1, Math.max(0, (yr - ys) / 0.12));
    const cab = [[hg, ys + 0.015], [hg - 0.04, ys + 0.27 * (yr - ys)], [hg - 0.13, ys + 0.62 * (yr - ys)], [hg * 0.6, yr - 0.03], [0, yr]];
    for (let i = 0; i < top.length; i++) top[i] = [top[i][0] + (cab[i][0] - top[i][0]) * g, top[i][1] + (cab[i][1] - top[i][1]) * g];
  }
  return side.concat(top);
}
const GH = 8; // index of the first point above the shoulder

// Catmull-Rom through a closed ring of [x, y] points, `sub` points per span.
function smoothRing(ring, sub) {
  const out = [], n = ring.length;
  for (let i = 0; i < n; i++) {
    const p0 = ring[(i - 1 + n) % n], p1 = ring[i], p2 = ring[(i + 1) % n], p3 = ring[(i + 2) % n];
    for (let s = 0; s < sub; s++) {
      const t = s / sub, t2 = t * t, t3 = t2 * t;
      const f = (a, b, c, d) => 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      out.push([f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1]), i + t]);
    }
  }
  return out; // [x, y, position along the coarse ring]
}

// Where a quad of the shell belongs. `u` is its place on the coarse ring (0 = bottom centre,
// GH..GH+4 = the house or hood, mirrored on the other side).
function classify(z, u, n, y, axles, R) {
  const v = u > n / 2 ? n - u : u; // fold the left side onto the right
  const inArch = axles.some((az) => Math.abs(z - az) < R + 0.02);
  if (v >= GH - 0.15 && z >= CANOPY_FROM + 0.03) {
    if (z < ROOF_FROM) return "glass"; // the windscreen
    if (z < GLASS_TO && v < GH + 2.75) return "glass"; // the side windows, up to the roof rail
    const qTop = 1.33 - (0.31 * (z - QUARTER[0])) / (QUARTER[1] - QUARTER[0]);
    return "paint";
  }
  if (y < 0.38 && !inArch && z > -1.95 && z < 1.95) return "clad"; // rockers
  if (y < 0.37 && z <= -1.95) return "clad"; // chin
  if (y < 0.5 && z >= 1.95) return "clad"; // rear bumper
  return "paint";
}

function shell(m) {
  const { r, front, rear } = CYBERCAB;
  const R = r + 0.055, axles = [front, rear];
  const bottom = (z) => {
    let b = sill(z);
    for (const az of axles) {
      const dz = z - az;
      if (Math.abs(dz) < R) b = Math.max(b, r + Math.sqrt(R * R - dz * dz));
    }
    return b;
  };
  const zs = [];
  for (let z = NOSE0; z < TAIL - 1e-6; z += 0.045) zs.push(z);
  zs.push(TAIL);
  for (const az of axles) for (let k = 0; k <= 16; k++) zs.push(az - R + (k * 2 * R) / 16);
  for (const z of [CANOPY_FROM, GLASS_TO, ...QUARTER, -1.95, 1.95]) zs.push(z);
  zs.sort((a, b) => a - b);
  const SUB = 3;
  const rings = zs.map((z) => {
    const right = halfOutline(z, bottom(z));
    const ring = right.concat(right.slice(1, -1).reverse().map(([x, y]) => [-x, y]));
    const hb = half(z); // the spline must not bulge past the section's own width
    return smoothRing(ring, SUB).map(([x, y, u]) => [Math.sign(x) * Math.min(Math.abs(x), hb), y, u]);
  });
  const coarse = halfOutline(0, 0.2).length * 2 - 2;
  const around = rings[0].length;
  const positions = [];
  rings.forEach((ring, i) => ring.forEach(([x, y]) => positions.push(x, y, zs[i])));
  const lists = { paint: [], glass: [], clad: [] };
  for (let i = 0; i < zs.length - 1; i++) {
    for (let k = 0; k < around; k++) {
      const a0 = i * around + k, a1 = i * around + ((k + 1) % around), b0 = a0 + around, b1 = a1 + around;
      const y = (positions[a0 * 3 + 1] + positions[a1 * 3 + 1] + positions[b0 * 3 + 1] + positions[b1 * 3 + 1]) / 4;
      const u = rings[i][k][2] + 0.5 / SUB;
      lists[classify((zs[i] + zs[i + 1]) / 2, u, coarse, y, axles, R)].push(a0, a1, b0, a1, b1, b0);
    }
  }
  // Caps: a nose domed forward to -L2 (a full front face under the light bar) and a tail face
  // dished inward under the lip. Each is the end ring, a ring shrunk toward its centre, and the
  // centre; their low parts are cladding (chin, rear bumper).
  const caps = { paint: { positions: [], index: [] }, clad: { positions: [], index: [] } };
  for (const [i, sign, dz, cladBelow] of [[0, -1, -(L2 + NOSE0), 0.37], [zs.length - 1, 1, -0.03, 0.5]]) {
    const ring = rings[i], z0 = zs[i];
    let cy = 0;
    for (const [, y] of ring) cy += y / around;
    const rows = [ring.map(([x, y]) => [x, y, z0]), ring.map(([x, y]) => [x * 0.62, cy + (y - cy) * 0.62, z0 + sign * dz * 0.0 + (sign < 0 ? dz * 0.7 : dz * 0.6)])];
    const centre = [0, cy, z0 + (sign < 0 ? dz : dz)];
    const tri = (a, b, c) => {
      const key = (a[1] + b[1] + c[1]) / 3 < cladBelow ? "clad" : "paint";
      const p = caps[key], base = p.positions.length / 3;
      p.positions.push(...a, ...b, ...c);
      if (sign < 0) p.index.push(base, base + 2, base + 1);
      else p.index.push(base, base + 1, base + 2);
    };
    for (let k = 0; k < around; k++) {
      const k1 = (k + 1) % around;
      tri(rows[0][k], rows[0][k1], rows[1][k]);
      tri(rows[0][k1], rows[1][k1], rows[1][k]);
      tri(rows[1][k], rows[1][k1], centre);
    }
  }
  const parts = new Parts();
  for (const [key, mat] of [["paint", m.paint], ["glass", m.glass], ["clad", m.clad]]) {
    if (lists[key].length) parts.add(mat, { positions: positions.slice(), index: lists[key] });
  }
  parts.add(m.paint, caps.paint);
  parts.add(m.clad, caps.clad);
  parts.add(m.quarter, quarterWindow(rings, zs, positions));
  parts.add(m.well, doorLines(rings, zs));
  return parts;
}

// The dark rear-quarter window: a patch laid 4 mm off the house's side between the shoulder and a
// top edge that falls toward the tail, on both sides. Its edges follow lines, not quad steps.
// The door shut lines: a 6 mm dark band on each side, at the door's front edge (leaning back at
// its foot) and rear edge, from the rocker to the belt.
function doorLines(rings, zs) {
  const positions = [], index = [];
  const outer = (i, y) => {
    let best = null;
    const ring = rings[i];
    for (let k = 0; k < ring.length - 1; k++) {
      const [x0, y0] = ring[k], [x1, y1] = ring[k + 1];
      if (x0 < 0 || x1 < 0 || (y0 - y) * (y1 - y) > 0 || y0 === y1) continue;
      const x = x0 + ((x1 - x0) * (y - y0)) / (y1 - y0);
      if (best === null || x > best) best = x;
    }
    return best;
  };
  const xAt = (z, y) => {
    let i = 0;
    while (i < zs.length - 2 && zs[i + 1] < z) i++;
    const a = outer(i, y), b = outer(i + 1, y), t = (z - zs[i]) / (zs[i + 1] - zs[i] || 1);
    return a === null || b === null ? null : a + (b - a) * Math.min(1, Math.max(0, t));
  };
  const lines = [
    (t) => [-1.2 - 0.1 * t, 0.39 + 0.56 * t], // front edge
    (t) => [0.99 - 0.04 * t * t, 0.39 + 0.58 * t], // rear edge
  ];
  for (const side of [1, -1]) {
    for (const line of lines) {
      const base = positions.length / 3;
      let n = 0;
      for (let s = 0; s <= 24; s++) {
        const t = s / 24, [z, y] = line(t), [z2, y2] = line(Math.min(1, t + 0.01));
        const x = xAt(z, y);
        if (x === null) continue;
        let dz = z2 - z, dy = y2 - y;
        const l = Math.hypot(dz, dy) || 1;
        dz /= l;
        dy /= l;
        const w = 0.003; // half width, across the line in the side plane
        positions.push(side * (x + 0.0025), y + dz * w, z - dy * w, side * (x + 0.0025), y - dz * w, z + dy * w);
        n++;
      }
      for (let r = 0; r < n - 1; r++) {
        const a = base + r * 2, b = a + 2;
        index.push(a, b, a + 1, b, b + 1, a + 1);
      }
    }
  }
  return { positions, index };
}

function quarterWindow(rings, zs) {
  const positions = [], index = [];
  const [q0, q1] = QUARTER;
  const top = (z) => 1.34 - (0.33 * (z - q0)) / (q1 - q0);
  const sideAt = (ring, y, limit) => {
    // The outermost point of the right half at height y, from the house's side polyline.
    let best = null;
    for (let k = 0; k < ring.length - 1; k++) {
      const [x0, y0] = ring[k], [x1, y1] = ring[k + 1];
      if (x0 < 0 || x1 < 0 || x0 > limit || x1 > limit) continue; // the house's side, not the body below it
      if ((y0 - y) * (y1 - y) <= 0 && y0 !== y1) {
        const x = x0 + ((x1 - x0) * (y - y0)) / (y1 - y0);
        if (!best || x > best) best = x;
      }
    }
    return best;
  };
  for (const side of [1, -1]) {
    const base = positions.length / 3;
    let rows = 0;
    for (let i = 0; i < zs.length; i++) {
      const z = zs[i];
      if (z < q0 || z > q1) continue;
      const lo = shoulder(z) + 0.04, hi = Math.max(lo, top(z));
      const ring = rings[i];
      const limit = house(z) + 0.02;
      const xl = sideAt(ring, lo, limit), xh = sideAt(ring, hi, limit);
      if (xl === null || xh === null) continue;
      positions.push(side * (xl + 0.012), lo, z, side * (xh + 0.012), hi, z);
      rows++;
    }
    for (let r = 0; r < rows - 1; r++) {
      const a = base + r * 2, b = a + 2;
      if (side > 0) index.push(a, b, a + 1, b, b + 1, a + 1);
      else index.push(a, a + 1, b, b, a + 1, b + 1);
    }
  }
  return { positions, index };
}

// A thin strip of quads through points [x, y, z], `h` tall and pushed `out` along `n(p)`.
function strip(points, h, normal) {
  const positions = [], index = [];
  points.forEach(([x, y, z], i) => {
    const [nx, nz] = normal([x, y, z]);
    positions.push(x + nx * 0.006, y - h / 2, z + nz * 0.006, x + nx * 0.006, y + h / 2, z + nz * 0.006);
    if (i) {
      const a = (i - 1) * 2, b = i * 2;
      index.push(a, b, a + 1, b, b + 1, a + 1);
    }
  });
  return { positions, index };
}

// The front light bar follows the hood's leading edge across the nose and rises up both fenders.
function frontLightBar() {
  const pts = [];
  for (let s = -1; s <= 1.0001; s += 0.025) {
    const x = s * 0.88;
    // Walk back from the nose until the plan outline reaches |x|.
    let z = -L2;
    while (z < -1.9 && half(z) < Math.abs(x)) z += 0.004;
    pts.push([x, shoulder(z) - 0.022, z]);
  }
  return strip(pts, 0.03, ([x, , z]) => {
    const d = Math.hypot(x, z + 1.9) || 1;
    return [x / d, (z + 1.9) / d];
  });
}

function well(side, az) {
  const { r } = CYBERCAB;
  const R = r + 0.05, hb = half(az), x0 = hb - 0.36, x1 = hb - 0.006, segs = 18;
  const positions = [], index = [];
  for (let k = 0; k <= segs; k++) {
    const a = (k / segs) * Math.PI, y = r + Math.sin(a) * R, z = az - Math.cos(a) * R;
    positions.push(side * x0, y, z, side * x1, y, z);
    if (k) {
      const p = (k - 1) * 2, q = k * 2;
      index.push(p, q, p + 1, q, q + 1, p + 1);
    }
  }
  return { positions, index };
}

function wheel(name, x, z, front, m) {
  const { r, w } = CYBERCAB;
  const pivot = new T.Group();
  pivot.name = name;
  pivot.position.set(x, r, z);
  pivot.userData.front = front;
  pivot.userData.radius = r;
  const out = x < 0 ? -1 : 1;
  const rotor = new T.Group();
  rotor.name = `${name}_spin`;
  const spin = new Parts();
  // A low-profile tyre: the cover hides almost all of the sidewall.
  spin.add(m.tyre, lathe([[r * 0.85, -w / 2], [r * 0.965, -w / 2], [r, -w * 0.4], [r, w * 0.4], [r * 0.965, w / 2], [r * 0.85, w / 2]], { segments: 48 }));
  // The flat disc cover: a rolled outer lip, a flat face with a shallow concentric step at 0.62 of
  // its radius, and a small domed centre cap.
  const f = out * (w / 2 + 0.002), o = (d) => f + out * d; // proud of the tyre's sidewall, so only a thin tyre band shows
  spin.add(m.cover, lathe([
    [r * 0.945, o(-0.03)], [r * 0.945, o(-0.006)], [r * 0.925, o(0.002)], [r * 0.64, o(0.003)], [r * 0.61, o(-0.006)],
    [r * 0.6, o(-0.012)], [0.07, o(-0.012)], [0.055, o(-0.004)], [0.035, o(0.002)], [0.001, o(0.004)],
  ], { segments: 44 }));
  spin.add(m.cover, lathe([[r * 0.9, -out * (w / 2)], [0.001, -out * (w / 2)]], { segments: 30 })); // the inner face
  rotor.add(...spin.meshes());
  pivot.add(rotor);
  return pivot;
}

function mats() {
  return {
    paint: physical(C.champagne, { metalness: 0.55, roughness: 0.4, clearcoat: 0.2, clearcoatRoughness: 0.35 }),
    cover: physical(C.champagne, { metalness: 0.5, roughness: 0.46, clearcoat: 0.1, clearcoatRoughness: 0.4, side: 2 }),
    glass: physical(C.glass, { name: "Glass", metalness: 0.3, roughness: 0.05, clearcoat: 1 }),
    quarter: physical(C.glass, { metalness: 0.35, roughness: 0.08, clearcoat: 1, side: 2 }),
    clad: material(C.trim, { roughness: 0.62, metalness: 0.1 }),
    well: material(C.trim, { roughness: 0.95, side: 2 }),
    tyre: material(C.tyre, { roughness: 0.92, side: 2 }),
    lens: material(C.lens, { emissive: C.lens, emissiveIntensity: 1.6, roughness: 0.2, side: 2 }),
    tail: material(C.taillight, { emissive: C.taillight, emissiveIntensity: 0.9, roughness: 0.3, side: 2 }),
  };
}

export function buildCybercab() {
  const m = mats();
  const { r, front, rear } = CYBERCAB;
  const group = new T.Group();
  const body = new T.Group();
  body.name = "body";
  body.add(...shell(m).meshes());
  group.add(body);

  const details = new Parts();
  details.add(m.lens, frontLightBar());
  // The tail: a duckbill lip over the vertical tail plane, a full-width red bar under it, two lower
  // lamps at the bumper corners and the dark bumper itself.
  const lipY = Math.max(shoulder(TAIL), roof(TAIL)) - 0.012;
  details.add(m.paint, box(1.72, 0.03, 0.13, 0, lipY, L2 - 0.065)); // overhangs the tail face by 6 cm; its edge is the car's end
  details.add(m.tail, box(1.6, 0.04, 0.008, 0, lipY - 0.055, TAIL + 0.004));
  for (const side of [-1, 1]) details.add(m.tail, box(0.4, 0.03, 0.008, side * 0.56, 0.535, TAIL + 0.03));
  details.add(m.clad, box(1.66, 0.25, 0.05, 0, 0.385, TAIL + 0.005));
  // Wheel wells: a dark half-tube inside each arch, so the gap round the tyre is shadow, not the
  // far side of the car. It stays under the fender (shoulder > arch top over both axles).
  for (const az of [front, rear]) {
    for (const side of [-1, 1]) details.add(m.well, well(side, az));
  }
  const extra = new T.Group();
  extra.name = "details";
  extra.add(...details.meshes());
  group.add(extra);

  const track = (az) => half(az) - CYBERCAB.w / 2 - 0.04; // covers flush with the fender lip
  for (const [name, az, isFront] of [["wheel_fl", front, true], ["wheel_fr", front, true], ["wheel_rl", rear, false], ["wheel_rr", rear, false]]) {
    group.add(wheel(name, (name.endsWith("l") ? -1 : 1) * track(az), az, isFront, m));
  }
  group.userData.wheelbase = Math.abs(front - rear);
  return group;
}
