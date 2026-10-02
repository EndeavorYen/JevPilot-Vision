// Geometry for the cars and people: plain vertex arrays, merged per material and turned into
// BufferGeometry. Every call builds new arrays, so each car has its own geometry (the bundle's
// crash code dents it in place), and node tests can measure what is drawn.
import { T } from "./kit.js";

// A smooth curve through keyframes [[t, value], ...] (cosine easing between keys).
export function curve(keys) {
  return (t) => {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      const [t1, v1] = keys[i];
      if (t <= t1) {
        const [t0, v0] = keys[i - 1];
        const u = (1 - Math.cos(((t - t0) / (t1 - t0)) * Math.PI)) / 2;
        return v0 + (v1 - v0) * u;
      }
    }
    return keys[keys.length - 1][1];
  };
}

// A body lofted along z: at each z a superellipse section (exponent n, 2 = ellipse, larger =
// squarer) spanning ±half(z) in x and [bottom(z), top(z)] in y. Ends are capped. `stops` adds
// sections at given z, so details such as wheel arches are sampled exactly.
//
// With `classify(z, angle)` (angle 0 = +x side, pi/2 = top) the result is {key: part}: every quad
// of the surface goes to the part its centre is classified as, so material borders run along the
// loft's own lines (sections and around-lines) instead of zig-zagging across triangles.
export function loft({ z0, z1, half, bottom, top, n = 4, step = 0.06, around = 28, stops = [], classify = null }) {
  const zs = [];
  for (let z = z0; z < z1 - 1e-6; z += step) zs.push(z);
  zs.push(z1);
  for (const z of stops) if (z > z0 && z < z1) zs.push(z);
  zs.sort((a, b) => a - b);
  const positions = [], index = [];
  const e = 2 / n;
  for (const z of zs) {
    const hw = half(z), lo = bottom(z), hi = Math.max(lo, top(z));
    const yc = (lo + hi) / 2, hh = (hi - lo) / 2;
    for (let k = 0; k < around; k++) {
      const a = (k / around) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
      positions.push(hw * Math.sign(c) * Math.abs(c) ** e, yc + hh * Math.sign(s) * Math.abs(s) ** e, z);
    }
  }
  const indexOf = classify ? new Map() : null;
  for (let r = 0; r < zs.length - 1; r++) {
    for (let k = 0; k < around; k++) {
      const a0 = r * around + k, a1 = r * around + ((k + 1) % around), b0 = a0 + around, b1 = a1 + around;
      let list = index;
      if (classify) {
        const key = classify((zs[r] + zs[r + 1]) / 2, ((k + 0.5) / around) * Math.PI * 2);
        if (!indexOf.has(key)) indexOf.set(key, []);
        list = indexOf.get(key);
      }
      list.push(a0, a1, b0, a1, b1, b0);
    }
  }
  // End caps: the front one faces -z, the rear one +z. Classified lofts leave them open.
  if (classify) {
    const out = {};
    for (const [key, list] of indexOf) out[key] = { positions: positions.slice(), index: list };
    return out;
  }
  // Each cap has its own copy of its ring, so its flat normals do not bend the sides.
  for (const [r, sign] of [[0, -1], [zs.length - 1, 1]]) {
    const first = positions.length / 3;
    let y = 0;
    for (let k = 0; k < around; k++) {
      const i = (r * around + k) * 3;
      positions.push(positions[i], positions[i + 1], positions[i + 2]);
      y += positions[i + 1] / around;
    }
    const c = positions.length / 3;
    positions.push(0, y, zs[r]);
    for (let k = 0; k < around; k++) {
      const a = first + k, b = first + ((k + 1) % around);
      if (sign < 0) index.push(c, b, a);
      else index.push(c, a, b);
    }
  }
  return { positions, index };
}

// A solid of revolution: profile points [radius, along] turned around the x, y or z axis.
export function lathe(profile, { axis = "x", segments = 20, phase = 0 } = {}) {
  const positions = [], index = [];
  for (const [r, t] of profile) {
    for (let k = 0; k < segments; k++) {
      const a = phase + (k / segments) * Math.PI * 2, c = Math.cos(a) * r, s = Math.sin(a) * r;
      if (axis === "x") positions.push(t, c, s);
      else if (axis === "z") positions.push(c, s, t);
      else positions.push(c, t, s);
    }
  }
  // Around x or z the axes are a mirror image of the y case, so the winding flips with them.
  const flip = axis !== "y";
  for (let p = 0; p < profile.length - 1; p++) {
    for (let k = 0; k < segments; k++) {
      const a0 = p * segments + k, a1 = p * segments + ((k + 1) % segments), b0 = a0 + segments, b1 = a1 + segments;
      if (flip) index.push(a0, a1, b0, a1, b1, b0);
      else index.push(a0, b0, a1, a1, b0, b1);
    }
  }
  return { positions, index };
}

// An axis-aligned box centred on (x, y, z); faces have their own vertices, so edges stay crisp.
export function box(w, h, d, x = 0, y = 0, z = 0) {
  const positions = [], index = [];
  const faces = [
    [[1, -1, -1], [1, 1, -1], [1, 1, 1], [1, -1, 1]],
    [[-1, -1, 1], [-1, 1, 1], [-1, 1, -1], [-1, -1, -1]],
    [[-1, 1, -1], [-1, 1, 1], [1, 1, 1], [1, 1, -1]],
    [[-1, -1, 1], [-1, -1, -1], [1, -1, -1], [1, -1, 1]],
    [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]],
    [[1, -1, -1], [-1, -1, -1], [-1, 1, -1], [1, 1, -1]],
  ];
  for (const face of faces) {
    const base = positions.length / 3;
    for (const [sx, sy, sz] of face) positions.push(x + (sx * w) / 2, y + (sy * h) / 2, z + (sz * d) / 2);
    index.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  return { positions, index };
}

// Rigid moves, baked into the vertices.
export function rotateX(part, a) {
  const c = Math.cos(a), s = Math.sin(a), p = part.positions;
  for (let i = 0; i < p.length; i += 3) {
    const y = p[i + 1], z = p[i + 2];
    p[i + 1] = y * c - z * s;
    p[i + 2] = y * s + z * c;
  }
  return part;
}

export function rotateY(part, a) {
  const c = Math.cos(a), s = Math.sin(a), p = part.positions;
  for (let i = 0; i < p.length; i += 3) {
    const x = p[i], z = p[i + 2];
    p[i] = x * c + z * s;
    p[i + 2] = -x * s + z * c;
  }
  return part;
}

export function move(part, x = 0, y = 0, z = 0) {
  const p = part.positions;
  for (let i = 0; i < p.length; i += 3) {
    p[i] += x;
    p[i + 1] += y;
    p[i + 2] += z;
  }
  return part;
}

export function mirrorX(part) {
  const p = part.positions;
  for (let i = 0; i < p.length; i += 3) p[i] = -p[i];
  for (let i = 0; i < part.index.length; i += 3) [part.index[i + 1], part.index[i + 2]] = [part.index[i + 2], part.index[i + 1]];
  return part;
}

export function scale(part, sx, sy = sx, sz = sx) {
  const p = part.positions;
  for (let i = 0; i < p.length; i += 3) {
    p[i] *= sx;
    p[i + 1] *= sy;
    p[i + 2] *= sz;
  }
  return part;
}

// Parts collected per material and drawn as one mesh each.
export class Parts {
  constructor() {
    this.byMaterial = new Map();
  }

  add(mat, part) {
    const list = this.byMaterial.get(mat) || [];
    list.push(part);
    this.byMaterial.set(mat, list);
    return this;
  }

  meshes({ cast = true } = {}) {
    const out = [];
    for (const [mat, list] of this.byMaterial) {
      const positions = [], index = [];
      for (const part of list) {
        const base = positions.length / 3;
        for (const v of part.positions) positions.push(v);
        for (const i of part.index) index.push(base + i);
      }
      const geo = new T.BufferGeometry();
      geo.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
      geo.setIndex(index);
      geo.computeVertexNormals();
      const mesh = new T.Mesh(geo, mat);
      mesh.castShadow = cast;
      mesh.receiveShadow = true;
      out.push(mesh);
    }
    return out;
  }
}
