// Ground heights for the coast: flat roads, hills beyond the shoulders, mountains to the north,
// level towns, and a cliff coast falling to a sea well below the roads. Plain functions of the
// world (tests/test_heights.py runs them in node); fixed noise, so the seed never moves a hill.

export const SEA_LEVEL = -10;

const SHOULDER = 3.5; // the drawn shoulder or pavement beside the asphalt
// Level ground beside the asphalt: the simulation is flat, and the drawn ground (a 6 m grid) must
// not rise through the shoulder, so the level band reaches a full grid cell past it.
const FLAT = 9;
// The ground reaches its full relief this far beyond the shoulder: the SS-1 and the pass open out
// in wide valleys, so they are neither trenches nor shadowed canyons.
const RAMP = { expressway: 110, pass: 90 };
const DEFAULT_RAMP = 45;
const CLIFF = 12; // along most of the coast the land drops to the water over this distance
const BEACH = 45; // ... and over this one in the festival's bay, a sloping beach
const COAST_FLAT = 110; // relief fades out towards the sea over this distance, so the coast road
// looks out over a drop instead of a ridge
const CELL = 64; // road index cell

const smooth = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

// Value noise and its fractal sums, from a fixed integer hash.
function hash(ix, iz) {
  let h = Math.imul(ix, 374761393) ^ Math.imul(iz, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
function noise(x, z) {
  const ix = Math.floor(x), iz = Math.floor(z);
  let fx = x - ix, fz = z - iz;
  fx = fx * fx * (3 - 2 * fx);
  fz = fz * fz * (3 - 2 * fz);
  const a = hash(ix, iz), b = hash(ix + 1, iz), c = hash(ix, iz + 1), d = hash(ix + 1, iz + 1);
  return a + (b - a) * fx + (c - a) * fz + (a - b - c + d) * fx * fz;
}
export function fbm(x, z, octaves = 5) {
  let v = 0, a = 0.5, f = 1, norm = 0;
  for (let i = 0; i < octaves; i++) {
    v += a * noise(x * f + i * 17.3, z * f - i * 9.1);
    norm += a;
    a *= 0.5;
    f *= 2.03;
  }
  return v / norm;
}
function ridged(x, z) {
  let v = 0, a = 0.5, f = 1, norm = 0;
  for (let i = 0; i < 5; i++) {
    const n = 1 - Math.abs(noise(x * f + i * 5.7, z * f + i * 3.1) * 2 - 1);
    v += a * n * n;
    norm += a;
    a *= 0.5;
    f *= 2.1;
  }
  return v / norm;
}

// The sea is the polygon closed by the shoreline and the map's south-east beyond it.
export function seaPolygon(shoreline, bounds) {
  const far = 4000;
  const first = shoreline[0], last = shoreline.at(-1);
  return [...shoreline, { x: last.x + far, z: last.z }, { x: last.x + far, z: bounds.maxZ + far }, { x: first.x - far, z: bounds.maxZ + far }, { x: first.x - far, z: first.z }];
}

export function inside(poly, p) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if (a.z > p.z !== b.z > p.z && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) hit = !hit;
  }
  return hit;
}

export function distanceToLine(line, p) {
  let best = Infinity;
  for (let i = 0; i < line.length - 1; i++) {
    const a = line[i], b = line[i + 1], dx = b.x - a.x, dz = b.z - a.z, len2 = dx * dx + dz * dz;
    const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.z - a.z) * dz) / len2));
    best = Math.min(best, Math.hypot(p.x - a.x - t * dx, p.z - a.z - t * dz));
  }
  return best;
}

// Areas kept nearly level: the harbour town and the festival grounds.
const TOWNS = [
  { x0: -1160, x1: -740, z0: 40, z1: 340 },
  { x0: -170, x1: 170, z0: 140, z1: 530 },
];
function townWeight(x, z) {
  let w = 0;
  for (const t of TOWNS) {
    const dx = Math.max(t.x0 - x, 0, x - t.x1), dz = Math.max(t.z0 - z, 0, z - t.z1);
    w = Math.max(w, 1 - smooth(0, 90, Math.hypot(dx, dz)));
  }
  return w;
}

// Relief before roads and shore: rolling hills, mountains to the north, rugged ground at the pass.
function relief(x, z) {
  const hills = 14 + 55 * fbm(x / 340 + 3.1, z / 340 - 1.7);
  const north = smooth(-480, -980, z);
  const mountains = 70 + 190 * ridged(x / 520 - 2.3, z / 520 + 4.2);
  const pass = smooth(760, 980, x) * smooth(420, 200, z) * (1 - north);
  const rugged = 25 + 60 * ridged(x / 240 + 1.1, z / 240 - 0.6);
  let h = hills;
  h = h + (rugged - h) * pass;
  h = h + (mountains - h) * north;
  return h * (1 - 0.985 * townWeight(x, z));
}

export function createHeightField(world) {
  const shoreline = world.visual.shoreline;
  const sea = seaPolygon(shoreline, world.bounds);

  // Road samples every ~3 m, indexed by 64 m cells: for the distance to the nearest road edge and
  // how far that road's ground ramps up. Wide ramps reach two cells out.
  const cells = new Map();
  for (const road of world.connectorRoads) {
    const half = road.width / 2;
    const ramp = RAMP[road.kind] ?? DEFAULT_RAMP;
    for (let i = 0; i < road.points.length; i += 2) {
      const p = road.points[i];
      const key = `${Math.floor(p.x / CELL)}:${Math.floor(p.z / CELL)}`;
      if (!cells.has(key)) cells.set(key, []);
      cells.get(key).push(p.x, p.z, half, ramp);
    }
  }
  // How much of the relief stands at (x, z): 0 on a road and its shoulder, 1 beyond its ramp.
  function openness(x, z) {
    const cx = Math.floor(x / CELL), cz = Math.floor(z / CELL);
    let best = 1, nearest = Infinity;
    for (let i = cx - 2; i <= cx + 2; i++) {
      for (let j = cz - 2; j <= cz + 2; j++) {
        const list = cells.get(`${i}:${j}`);
        if (!list) continue;
        for (let k = 0; k < list.length; k += 4) {
          const edge = Math.hypot(x - list[k], z - list[k + 1]) - list[k + 2];
          nearest = Math.min(nearest, edge);
          best = Math.min(best, smooth(FLAT, SHOULDER + list[k + 3], edge));
        }
      }
    }
    return { open: nearest < FLAT ? 0 : best, nearest };
  }
  function roadEdge(x, z) {
    const cx = Math.floor(x / CELL), cz = Math.floor(z / CELL);
    let best = Infinity;
    for (let i = cx - 1; i <= cx + 1; i++) {
      for (let j = cz - 1; j <= cz + 1; j++) {
        const list = cells.get(`${i}:${j}`);
        if (!list) continue;
        for (let k = 0; k < list.length; k += 4) best = Math.min(best, Math.hypot(x - list[k], z - list[k + 1]) - list[k + 2]);
      }
    }
    return best;
  }

  function heightAt(x, z) {
    const p = { x, z };
    const toShore = distanceToLine(shoreline, p);
    if (inside(sea, p)) return Math.max(-45, SEA_LEVEL - 0.6 - toShore * 0.3);
    const { open, nearest } = openness(x, z);
    if (nearest < FLAT) return 0;
    const land = relief(x, z) * open * smooth(15, COAST_FLAT, toShore);
    const shore = x > -280 && x < 260 && z > 380 ? BEACH : CLIFF;
    const s = smooth(0, shore, toShore);
    // The drop to the sea fades in beyond the level band too, so the ground has no step at its edge.
    return land * s + smooth(FLAT, FLAT + 10, nearest) * SEA_LEVEL * (1 - s);
  }

  // Blend of [grass, dry grass, rock, sand] at a point whose height and slope are known.
  function weights(x, z, h, slope) {
    const toShore = distanceToLine(shoreline, { x, z });
    const sand = h < SEA_LEVEL + 0.5 ? 1 : (1 - smooth(6, 16, toShore)) * (1 - smooth(0.7, 1.1, slope));
    const rock = smooth(0.55, 0.95, slope) * (1 - sand);
    const rest = Math.max(0, 1 - sand - rock);
    const dryness = Math.min(1, Math.max(0, -0.15 + 0.75 * fbm(x / 90, z / 90, 3) + h / 260));
    return [rest * (1 - dryness), rest * dryness, rock, sand];
  }

  // The same, measuring the slope itself.
  function surface(x, z) {
    const gx = (heightAt(x + 2, z) - heightAt(x - 2, z)) / 4, gz = (heightAt(x, z + 2) - heightAt(x, z - 2)) / 4;
    return weights(x, z, heightAt(x, z), Math.hypot(gx, gz));
  }

  return { heightAt, surface, weights, roadEdge };
}
