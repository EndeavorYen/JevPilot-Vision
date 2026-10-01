// Ground and seabed: one height-field mesh. Land is flat at the road's level (the simulation is
// flat); below the shoreline the ground shelves down under the sea surface.
import { PALETTE, T, Batch, material } from "./kit.js";

const CELL = 10;
const MARGIN = 300; // ground beyond the drivable bounds, so the horizon is not an edge
const SHELF = 0.12; // seabed drop per metre from the shoreline
const SEABED = -6;

// The sea is the polygon closed by the shoreline and the map's south-east corner beyond it.
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

// Height of the ground at p: 0 on land, shelving to SEABED under the sea.
export function groundHeight(world, p, sea = seaPolygon(world.visual.shoreline, world.bounds)) {
  if (!inside(sea, p)) return -0.05;
  return Math.max(SEABED, -0.05 - distanceToLine(world.visual.shoreline, p) * SHELF);
}

// Linear RGB for a vertex colour; three.js converts the sRGB hex when it builds the Color.
function linear(hex) {
  const c = new T.Color(hex);
  return [c.r, c.g, c.b];
}

export function buildTerrain(world) {
  const { bounds } = world;
  const sea = seaPolygon(world.visual.shoreline, bounds);
  const x0 = bounds.minX - MARGIN, x1 = bounds.maxX + MARGIN, z0 = bounds.minZ - MARGIN, z1 = bounds.maxZ + MARGIN;
  const nx = Math.round((x1 - x0) / CELL), nz = Math.round((z1 - z0) / CELL);
  const grass = PALETTE.grass.map(linear), sand = linear(PALETTE.sand), seabed = linear(PALETTE.seabed);
  const vertex = [];
  for (let j = 0; j <= nz; j++) {
    const row = [];
    for (let i = 0; i <= nx; i++) {
      const p = { x: x0 + i * CELL, z: z0 + j * CELL };
      const wet = inside(sea, p);
      const shore = distanceToLine(world.visual.shoreline, p);
      const y = wet ? Math.max(SEABED, -0.05 - shore * SHELF) : -0.05;
      const colour = wet ? (shore < 12 ? sand : seabed) : shore < 25 ? sand : grass[(i * 7 + j * 13) % grass.length];
      row.push({ x: p.x, y, z: p.z, colour });
    }
    vertex.push(row);
  }
  const batch = new Batch();
  batch.colors = [];
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const a = vertex[j][i], b = vertex[j][i + 1], c = vertex[j + 1][i + 1], d = vertex[j + 1][i];
      for (const [p, q, r] of [[a, d, c], [a, c, b]]) {
        for (const v of [p, q, r]) {
          batch.positions.push(v.x, v.y, v.z);
          batch.colors.push(...v.colour);
        }
      }
    }
  }
  const mesh = batch.mesh(material("#ffffff", { vertexColors: true }));
  mesh.name = "semif-terrain";
  return mesh;
}
