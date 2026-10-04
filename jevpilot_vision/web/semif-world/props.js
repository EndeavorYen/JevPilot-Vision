// Street furniture and the harbour's boats: wrought-iron lamps along the town streets, café
// umbrellas on the harbour promenade, fishing boats and buoys that rise and roll on the swell.
// placeProps() is plain (tested in node); buildProps() draws it, instanced where it repeats.
import { PALETTE, T, material } from "./kit.js";
import { SEA_LEVEL, inside, seaPolygon, distanceToLine } from "./heights.js";
import { BREAKWATER } from "./buildings.js";

const LAMP_EVERY = 20;
const LAMP_EDGE = 2.4; // on the pavement, off the asphalt
const PALM_EVERY = 24; // vegetation.js's street palms; lamps keep clear of them

function hash(a, b, c) {
  let h = Math.imul(a | 0, 374761393) ^ Math.imul(b | 0, 668265263) ^ Math.imul(c | 0, 2246822519);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export function placeProps(world, field, grid) {
  const seed = Number(world.seed) >>> 0;
  const buildings = world.objects.filter((o) => o.type === "building");
  const inBuilding = (x, z, pad) => buildings.some((b) => Math.abs(x - b.x) < b.width / 2 + pad && Math.abs(z - b.z) < b.depth / 2 + pad);
  const junctions = world.nodes.filter((n) => n.townJunction);
  const lamps = [];
  for (const road of world.connectorRoads) {
    if (road.kind !== "harbour" && road.kind !== "festival") continue;
    const pts = road.points;
    for (let i = 1; i < pts.length - 1; i++) {
      const s = pts[i].s - 8;
      if (Math.floor(s / LAMP_EVERY) === Math.floor((pts[i - 1].s - 8) / LAMP_EVERY)) continue;
      if (Math.abs(pts[i].s - Math.round(pts[i].s / PALM_EVERY) * PALM_EVERY) < 3) continue;
      if (junctions.some((n) => Math.hypot(pts[i].x - n.x, pts[i].z - n.z) < 14)) continue;
      const h = Math.atan2(pts[i + 1].x - pts[i - 1].x, pts[i - 1].z - pts[i + 1].z);
      for (const side of [-1, 1]) {
        const a = h + (side * Math.PI) / 2, d = road.width / 2 + LAMP_EDGE;
        const x = pts[i].x + Math.sin(a) * d, z = pts[i].z - Math.cos(a) * d;
        if (inBuilding(x, z, 0.8) || field.roadEdge(x, z) < 2) continue;
        lamps.push({ x, z, y: grid.heightAt(x, z), facing: a + Math.PI });
      }
    }
  }
  // Cafés on the promenade between the harbour's south street and its quay.
  const cafes = [];
  for (let x = -1085; x <= -815; x += 16) {
    const z = 326 + (hash(x, seed, 1) - 0.5) * 4;
    if (field.roadEdge(x, z) < 3 || field.heightAt(x, z) < -0.5) continue;
    cafes.push({ x, z, y: grid.heightAt(x, z), colour: Math.floor(hash(x, seed, 2) * PALETTE.awning.length) });
  }
  // Boats moored in the harbour basin, clear of the mole.
  const sea = seaPolygon(world.visual.shoreline, world.bounds);
  const boats = [];
  for (let k = 0; boats.length < 14 && k < 400; k++) {
    const x = -1170 + hash(k, seed, 3) * 380, z = 362 + hash(k, seed, 4) * 110;
    if (!inside(sea, { x, z }) || field.heightAt(x, z) > SEA_LEVEL - 2.5) continue;
    if (distanceToLine(BREAKWATER, { x, z }) < 12) continue;
    if (boats.some((b) => Math.hypot(b.x - x, b.z - z) < 14)) continue;
    boats.push({ x, z, heading: hash(k, seed, 5) * Math.PI * 2, size: 0.8 + hash(k, seed, 6) * 0.6, phase: hash(k, seed, 7) * 6.28 });
  }
  return { lamps, cafes, boats };
}

const m4 = () => new T.Matrix4();

function instanced(geometry, mat, items, place) {
  const mesh = new T.InstancedMesh(geometry, mat, items.length);
  const m = m4(), q = new T.Quaternion(), p = new T.Vector3(), s = new T.Vector3(1, 1, 1), up = new T.Vector3(0, 1, 0);
  items.forEach((item, i) => {
    const [x, y, z, turn] = place(item);
    q.setFromAxisAngle(up, turn);
    p.set(x, y, z);
    mesh.setMatrixAt(i, m.compose(p, q, s));
  });
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.computeBoundingSphere();
  return mesh;
}

let boats = [];
let elapsed = 0;

export function buildProps(spots) {
  const group = new T.Group();
  group.name = "semif-props";
  const iron = material(PALETTE.railing, { metalness: 0.4, roughness: 0.5 });
  const lantern = material(PALETTE.trim, { roughness: 0.3, emissive: "#ffffff", emissiveIntensity: 0.05 });
  if (spots.lamps.length) {
    group.add(instanced(new T.CylinderGeometry(0.07, 0.11, 4.4, 8).translate(0, 2.2, 0), iron, spots.lamps, (l) => [l.x, l.y, l.z, 0]));
    group.add(instanced(new T.BoxGeometry(0.08, 0.08, 1.1).translate(0, 4.3, -0.5), iron, spots.lamps, (l) => [l.x, l.y, l.z, -l.facing]));
    group.add(instanced(new T.CylinderGeometry(0.16, 0.24, 0.5, 6).translate(0, 4.0, -1.0), lantern, spots.lamps, (l) => [l.x, l.y, l.z, -l.facing]));
  }
  if (spots.cafes.length) {
    group.add(instanced(new T.CylinderGeometry(0.04, 0.04, 2.4, 6).translate(0, 1.2, 0), iron, spots.cafes, (c) => [c.x, c.y, c.z, 0]));
    group.add(instanced(new T.CylinderGeometry(0.45, 0.45, 0.05, 16).translate(0, 0.75, 0), material(PALETTE.trim), spots.cafes, (c) => [c.x, c.y, c.z, 0]));
    PALETTE.awning.forEach((colour, k) => {
      const mine = spots.cafes.filter((c) => c.colour === k);
      if (mine.length) group.add(instanced(new T.ConeGeometry(1.7, 0.7, 8).translate(0, 2.55, 0), material(colour, { side: 2 }), mine, (c) => [c.x, c.y, c.z, 0]));
    });
  }
  boats = spots.boats.map((b, i) => {
    const boat = new T.Group();
    const hull = new T.Mesh(new T.BoxGeometry(2.4, 1.1, 7).scale(b.size, b.size, b.size), material(i % 3 ? PALETTE.trim : PALETTE.festival.blue, { roughness: 0.5 }));
    const bow = new T.Mesh(new T.ConeGeometry(1.2, 2.2, 4).rotateX(Math.PI / 2).rotateZ(Math.PI / 4).scale(b.size, 0.8 * b.size, b.size).translate(0, 0, -4.6 * b.size), hull.material);
    const cabin = new T.Mesh(new T.BoxGeometry(1.8, 1.3, 2.2).scale(b.size, b.size, b.size).translate(0, 1.1 * b.size, 0.8 * b.size), material(PALETTE.villa, { roughness: 0.6 }));
    for (const part of [hull, bow, cabin]) {
      part.castShadow = true;
      boat.add(part);
    }
    boat.rotation.y = b.heading;
    boat.userData = { base: SEA_LEVEL + 0.2, phase: b.phase, moves: true }; // bobs (updateProps)
    boat.position.set(b.x, boat.userData.base, b.z);
    group.add(boat);
    return boat;
  });
  group.userData.boats = boats;
  return group;
}

export function updateProps(dt) {
  elapsed += dt || 0;
  for (const boat of boats) {
    const t = elapsed * 0.9 + boat.userData.phase;
    boat.position.y = boat.userData.base + Math.sin(t) * 0.18;
    boat.rotation.z = Math.sin(t * 0.8) * 0.04;
    boat.rotation.x = Math.cos(t * 0.7) * 0.025;
  }
}
