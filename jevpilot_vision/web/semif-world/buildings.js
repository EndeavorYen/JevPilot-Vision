// Buildings: the harbour's town houses on the simulation's collision boxes (worldgen), white villas
// on the hills, the harbour's quay wall and a lighthouse on its breakwater. Facades are canvas
// textures of window bays (shutters, sills, railings, doors, shop windows) in PALETTE colours.
import { PALETTE, T, Batch, material } from "./kit.js";
import { SEA_LEVEL } from "./heights.js";

const BAY = 3; // metres of facade per texture repeat, across and up
const GROUND_FLOOR = 3.6;
const PX = 256;

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619) >>> 0;
  return h;
}

function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.max(0, Math.min(255, Math.round(v * f))));
  return `rgb(${c.join(",")})`;
}

// --- facades -------------------------------------------------------------------------------

const textures = new Map();

// One bay, 3 m by 3 m: `kind` is upper (window with shutters), balcony (the same with a railing),
// door (arched door on a stone plinth) or shop (a wide shop window).
function facade(wall, shutter, kind) {
  const key = `${wall}|${shutter}|${kind}`;
  if (textures.has(key)) return textures.get(key);
  const c = document.createElement("canvas");
  c.width = c.height = PX;
  const g = c.getContext("2d");
  const m = PX / 3; // pixels per metre
  g.fillStyle = wall;
  g.fillRect(0, 0, PX, PX);
  // Plaster: faint blotches of lighter and darker wall.
  let seed = hash(key);
  const rnd = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296);
  for (let i = 0; i < 70; i++) {
    g.fillStyle = shade(wall, 0.94 + rnd() * 0.1);
    g.globalAlpha = 0.35;
    g.beginPath();
    g.arc(rnd() * PX, rnd() * PX, 6 + rnd() * 22, 0, Math.PI * 2);
    g.fill();
  }
  g.globalAlpha = 1;
  if (kind === "upper" || kind === "balcony") {
    const x0 = 1.0 * m, x1 = 2.0 * m, y0 = 0.7 * m, y1 = 2.2 * m;
    g.fillStyle = PALETTE.trim;
    g.fillRect(x0 - 6, y0 - 6, x1 - x0 + 12, y1 - y0 + 12);
    g.fillStyle = PALETTE.glass;
    g.fillRect(x0, y0, x1 - x0, y1 - y0);
    g.fillStyle = PALETTE.trim;
    g.fillRect((x0 + x1) / 2 - 2, y0, 4, y1 - y0);
    for (const sx of [x0 - 0.5 * m - 4, x1 + 4]) {
      g.fillStyle = shutter;
      g.fillRect(sx, y0, 0.5 * m, y1 - y0);
      g.fillStyle = shade(shutter, 0.78);
      for (let y = y0 + 6; y < y1; y += 9) g.fillRect(sx + 4, y, 0.5 * m - 8, 3);
    }
    g.fillStyle = PALETTE.stone;
    g.fillRect(x0 - 12, y1 + 4, x1 - x0 + 24, 10);
    if (kind === "balcony") {
      g.fillStyle = PALETTE.railing;
      g.fillRect(0.6 * m, 1.75 * m, 1.8 * m, 5);
      for (let x = 0.6 * m; x <= 2.4 * m; x += 10) g.fillRect(x, 1.75 * m, 3, 0.45 * m);
      g.fillRect(0.6 * m, 2.2 * m, 1.8 * m, 4);
    }
  } else if (kind === "door") {
    g.fillStyle = PALETTE.stone;
    g.fillRect(0, 2.55 * m, PX, 0.45 * m);
    g.fillStyle = PALETTE.door;
    g.fillRect(1.05 * m, 0.95 * m, 0.9 * m, 1.6 * m);
    g.beginPath();
    g.arc(1.5 * m, 0.95 * m, 0.45 * m, Math.PI, 0);
    g.fill();
    g.fillStyle = shade(PALETTE.door, 0.75);
    g.fillRect(1.48 * m, 0.95 * m, 4, 1.6 * m);
  } else {
    g.fillStyle = PALETTE.stone;
    g.fillRect(0, 2.6 * m, PX, 0.4 * m);
    g.fillStyle = PALETTE.shopFrame;
    g.fillRect(0.2 * m, 0.55 * m, 2.6 * m, 2.05 * m);
    g.fillStyle = PALETTE.glass;
    g.fillRect(0.3 * m, 0.65 * m, 2.4 * m, 1.85 * m);
    g.fillStyle = PALETTE.shopFrame;
    g.fillRect(1.48 * m, 0.65 * m, 4, 1.85 * m);
  }
  const t = new T.CanvasTexture(c);
  t.wrapS = t.wrapT = T.RepeatWrapping;
  t.colorSpace = T.SRGBColorSpace;
  t.anisotropy = 8;
  textures.set(key, t);
  return t;
}

// Walls with facade UVs: one texture repeat per BAY metres, across and up.
class Shell {
  constructor() {
    this.positions = [];
    this.uvs = [];
  }
  wall(ax, az, bx, bz, y0, y1) {
    const len = Math.hypot(bx - ax, bz - az) / BAY;
    const v0 = y0 / BAY, v1 = y1 / BAY;
    this.positions.push(ax, y0, az, bx, y0, bz, bx, y1, bz, ax, y0, az, bx, y1, bz, ax, y1, az);
    this.uvs.push(0, v0, len, v0, len, v1, 0, v0, len, v1, 0, v1);
  }
  ring(x, z, w, d, y0, y1) {
    const x0 = x - w / 2, x1 = x + w / 2, z0 = z - d / 2, z1 = z + d / 2;
    this.wall(x0, z1, x1, z1, y0, y1);
    this.wall(x1, z1, x1, z0, y0, y1);
    this.wall(x1, z0, x0, z0, y0, y1);
    this.wall(x0, z0, x0, z1, y0, y1);
  }
  mesh(mat) {
    const geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.Float32BufferAttribute(this.positions, 3));
    geo.setAttribute("uv", new T.Float32BufferAttribute(this.uvs, 2));
    geo.computeVertexNormals();
    const mesh = new T.Mesh(geo, mat);
    mesh.castShadow = mesh.receiveShadow = true;
    return mesh;
  }
}

function facadeMaterial(wall, shutter, kind) {
  return material(`#ffffff`, { map: facade(wall, shutter, kind), roughness: 0.92, side: 2 });
}

// A hip roof over a w x d footprint at height y, with eaves overhanging by `eave`.
function hipRoof(batch, x, z, w, d, y, rise, eave = 0.4) {
  const W = w / 2 + eave, D = d / 2 + eave;
  const along = w >= d;
  const r = Math.abs(W - D);
  const a = along ? { x: x - r, y: y + rise, z } : { x, y: y + rise, z: z - r };
  const b = along ? { x: x + r, y: y + rise, z } : { x, y: y + rise, z: z + r };
  const c = [
    { x: x - W, y, z: z - D },
    { x: x + W, y, z: z - D },
    { x: x + W, y, z: z + D },
    { x: x - W, y, z: z + D },
  ];
  const tri = (p, q, s) => batch.positions.push(p.x, p.y, p.z, q.x, q.y, q.z, s.x, s.y, s.z);
  if (along) {
    tri(c[0], c[1], b), tri(c[0], b, a); // north slope
    tri(c[2], c[3], a), tri(c[2], a, b); // south slope
    tri(c[1], c[2], b), tri(c[3], c[0], a); // hips
  } else {
    tri(c[1], c[2], b), tri(c[1], b, a);
    tri(c[3], c[0], a), tri(c[3], a, b);
    tri(c[0], c[1], a), tri(c[2], c[3], b);
  }
}

// Which side of a footprint faces the nearest road: [dx, dz] unit step.
function frontOf(field, x, z, w, d) {
  const sides = [[0, 1], [0, -1], [1, 0], [-1, 0]];
  return sides.reduce((best, s) => {
    const e = field.roadEdge(x + s[0] * (w / 2 + 4), z + s[1] * (d / 2 + 4));
    return e < best.e ? { s, e } : best;
  }, { s: sides[0], e: Infinity }).s;
}

// --- town houses ------------------------------------------------------------------------------

function buildTown(world, field) {
  const shells = new Map();
  const shell = (wall, shutter, kind) => {
    const key = `${wall}|${shutter}|${kind}`;
    if (!shells.has(key)) shells.set(key, { shell: new Shell(), mat: () => facadeMaterial(wall, shutter, kind) });
    return shells.get(key).shell;
  };
  const roofs = new Batch(), flat = new Batch(), awnings = PALETTE.awning.map(() => new Batch()), slabs = new Batch();
  for (const b of world.objects) {
    if (b.type !== "building") continue;
    const h = hash(b.id);
    const wall = PALETTE.stucco[h % PALETTE.stucco.length];
    const shutter = PALETTE.shutter[(h >>> 4) % PALETTE.shutter.length];
    const shop = b.style === "shop";
    shell(wall, shutter, shop ? "shop" : "door").ring(b.x, b.z, b.width, b.depth, 0, GROUND_FLOOR);
    shell(wall, shutter, (h >>> 8) % 3 === 0 ? "balcony" : "upper").ring(b.x, b.z, b.width, b.depth, GROUND_FLOOR, b.height);
    const [fx, fz] = frontOf(field, b.x, b.z, b.width, b.depth);
    if ((h >>> 12) % 5 < 3) {
      hipRoof(roofs, b.x, b.z, b.width, b.depth, b.height, 2.2);
    } else {
      flat.box(b.x, b.z, b.width, b.depth, 0.2, b.height); // terrace
      for (const [ox, oz, w, d] of [[0, b.depth / 2 - 0.15, b.width, 0.3], [0, -b.depth / 2 + 0.15, b.width, 0.3], [b.width / 2 - 0.15, 0, 0.3, b.depth], [-b.width / 2 + 0.15, 0, 0.3, b.depth]]) {
        flat.box(b.x + ox, b.z + oz, w, d, 0.9, b.height);
      }
    }
    // The front: an awning over a shop, balcony slabs on the floors above.
    const span = fx ? b.depth : b.width;
    if (shop) {
      const ax = b.x + fx * (b.width / 2 + 0.8), az = b.z + fz * (b.depth / 2 + 0.8);
      awnings[(h >>> 16) % awnings.length].box(ax, az, fx ? 1.6 : span * 0.8, fz ? 1.6 : span * 0.8, 0.12, 2.75);
    }
    if ((h >>> 8) % 3 === 0) {
      for (let y = GROUND_FLOOR + 3 * 0.55; y < b.height - 1; y += 3) {
        const sx = b.x + fx * (b.width / 2 + 0.45), sz = b.z + fz * (b.depth / 2 + 0.45);
        slabs.box(sx, sz, fx ? 0.9 : span * 0.6, fz ? 0.9 : span * 0.6, 0.15, y - 1.2);
      }
    }
  }
  const group = new T.Group();
  group.name = "semif-town";
  for (const { shell, mat } of shells.values()) group.add(shell.mesh(mat()));
  group.add(roofs.mesh(material(PALETTE.roof[0], { side: 2, roughness: 0.85 }), { cast: true }));
  if (!flat.empty) group.add(flat.mesh(material(PALETTE.stucco[0], { roughness: 0.9 }), { cast: true }));
  awnings.forEach((a, i) => a.empty || group.add(a.mesh(material(PALETTE.awning[i], { side: 2 }), { cast: true })));
  if (!slabs.empty) group.add(slabs.mesh(material(PALETTE.stone), { cast: true }));
  return group;
}

// --- villas on the hills -----------------------------------------------------------------------

const TOWNS = [
  { x0: -1180, x1: -720, z0: 20, z1: 360 },
  { x0: -180, x1: 180, z0: 130, z1: 540 },
];

export function placeVillas(world, field, grid) {
  const seed = Number(world.seed) >>> 0;
  const villas = [];
  const { minX, maxX, minZ, maxZ } = world.bounds;
  for (let x = minX + 40; x < maxX - 40; x += 70) {
    for (let z = minZ + 40; z < maxZ - 40; z += 70) {
      const h = hash(`${x}:${z}:${seed}`);
      if (h % 7 > 1) continue; // about two in seven candidates
      const vx = x + ((h >>> 3) % 40) - 20, vz = z + ((h >>> 9) % 40) - 20;
      if (TOWNS.some((t) => vx > t.x0 && vx < t.x1 && vz > t.z0 && vz < t.z1)) continue;
      const w = 11 + ((h >>> 14) % 5), d = 9 + ((h >>> 18) % 4);
      const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => grid.heightAt(vx + (a * w) / 2, vz + (b * d) / 2));
      const edge = Math.min(...[[-1, -1], [1, -1], [1, 1], [-1, 1], [0, 0]].map(([a, b]) => field.roadEdge(vx + (a * w) / 2, vz + (b * d) / 2)));
      if (edge < 25 || edge > 260) continue;
      if (Math.min(...corners) < SEA_LEVEL + 6 || field.heightAt(vx, vz) < SEA_LEVEL + 6) continue;
      if (Math.max(...corners) - Math.min(...corners) > 6) continue; // too steep for a house
      villas.push({ x: vx, z: vz, width: w, depth: d, base: Math.min(...corners) - 0.3, floor: Math.max(...corners) + 0.4, height: 6.4, flat: (h >>> 22) % 4 === 0 });
    }
  }
  return villas;
}

function buildVillas(villas) {
  const walls = new Shell(), plinth = new Batch(), roofs = new Batch(), terraces = new Batch();
  for (const v of villas) {
    plinth.box(v.x, v.z, v.width + 0.6, v.depth + 0.6, v.floor - v.base, v.base);
    walls.ring(v.x, v.z, v.width, v.depth, v.floor, v.floor + v.height);
    if (v.flat) terraces.box(v.x, v.z, v.width + 0.3, v.depth + 0.3, 0.6, v.floor + v.height);
    else hipRoof(roofs, v.x, v.z, v.width, v.depth, v.floor + v.height, 2.4, 0.5);
  }
  const group = new T.Group();
  group.name = "semif-villas";
  group.add(walls.mesh(facadeMaterial(PALETTE.villa, PALETTE.shutter[0], "upper")));
  group.add(plinth.mesh(material(PALETTE.stone, { roughness: 0.95 }), { cast: true }));
  if (!roofs.empty) group.add(roofs.mesh(material(PALETTE.roof[1], { side: 2, roughness: 0.85 }), { cast: true }));
  if (!terraces.empty) group.add(terraces.mesh(material(PALETTE.villa), { cast: true }));
  return group;
}

// --- the harbour: quay wall, breakwater, lighthouse ---------------------------------------------

const QUAY_WEST = -1300, QUAY_EAST = -760;
export const BREAKWATER = [{ x: -985, z: 345 }, { x: -960, z: 430 }, { x: -920, z: 520 }];

function buildHarbour(world) {
  const quay = new Batch();
  const shore = world.visual.shoreline.filter((p) => p.x >= QUAY_WEST && p.x <= QUAY_EAST);
  for (let i = 0; i < shore.length - 1; i++) {
    const a = shore[i], b = shore[i + 1];
    quay.positions.push(a.x, SEA_LEVEL - 2, a.z, b.x, SEA_LEVEL - 2, b.z, b.x, 0.25, b.z, a.x, SEA_LEVEL - 2, a.z, b.x, 0.25, b.z, a.x, 0.25, a.z);
  }
  // The mole: a stone causeway out to the lighthouse.
  const mole = new Batch();
  for (let i = 0; i < BREAKWATER.length - 1; i++) {
    const a = BREAKWATER[i], b = BREAKWATER[i + 1];
    const steps = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / 4);
    for (let k = 0; k < steps; k++) {
      const t = k / steps;
      mole.box(a.x + (b.x - a.x) * t, a.z + (b.z - a.z) * t, 9, 9, 1.2 - (SEA_LEVEL - 3), SEA_LEVEL - 3);
    }
  }
  const tip = BREAKWATER.at(-1);
  const tower = new T.Group();
  tower.name = "semif-lighthouse";
  tower.userData.at = { x: tip.x, z: tip.z };
  tower.position.set(tip.x, 1.2, tip.z);
  const white = material(PALETTE.lighthouse.white, { roughness: 0.6 });
  const band = material(PALETTE.lighthouse.band, { roughness: 0.6 });
  const seg = (r0, r1, h, y, mat) => {
    const m = new T.Mesh(new T.CylinderGeometry(r1, r0, h, 20), mat);
    m.position.set(0, y + h / 2, 0);
    m.castShadow = true;
    tower.add(m);
  };
  seg(2.6, 2.4, 4, 0, white);
  seg(2.4, 2.2, 3, 4, band);
  seg(2.2, 2.0, 4, 7, white);
  seg(2.0, 1.85, 3, 11, band);
  seg(1.85, 1.7, 3, 14, white);
  seg(2.4, 2.4, 0.3, 17, band); // gallery
  seg(1.3, 1.3, 2.2, 17.3, material(PALETTE.glass, { roughness: 0.15, metalness: 0.3 }));
  const dome = new T.Mesh(new T.ConeGeometry(1.5, 1.4, 20), band);
  dome.position.set(0, 20.2, 0);
  tower.add(dome);

  const group = new T.Group();
  group.add(Object.assign(quay.mesh(material(PALETTE.stone, { side: 2, roughness: 0.95 })), { name: "semif-quay" }));
  group.add(mole.mesh(material(PALETTE.stone, { roughness: 0.95 }), { cast: true }), tower);
  return group;
}

export function buildBuildings(world, field, grid) {
  textures.clear();
  const group = new T.Group();
  group.name = "semif-buildings";
  group.add(buildTown(world, field), buildVillas(placeVillas(world, field, grid)), buildHarbour(world));
  return group;
}
