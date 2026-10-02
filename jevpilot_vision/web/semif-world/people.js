// Solmare Coast people (spec §5.2).
//
// Sim pedestrians: head, neck, torso, pelvis, arms and legs, with pivots at the shoulders and hips
// that the bundle swings (`userData.limbs = {legs, arms}`). Build, skin, hair, clothes and
// accessories vary per id. The lower body is always PALETTE.people.silhouette: the onboard
// camera's pedestrian mask looks for that dark shape.
//
// Crowds at the festival, the cafés and the beach are decoration, not in the simulation:
// instanced, at least 8 m from the lanes, never in the silhouette colour.
import { PALETTE, T, material } from "./kit.js";
import { lathe, box, move, scale, Parts } from "./shapes.js";
import { SEA_LEVEL, inside, seaPolygon } from "./heights.js";
import { placeProps } from "./props.js";

const P = PALETTE.people;
const STYLES = ["short", "long", "bun", "straw", "cap"];

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619) >>> 0;
  return Math.imul(h ^ (h >>> 15), 2246822519) >>> 0;
}

export function pedestrianLook(id) {
  const h = hash(String(id));
  const pick = (list, shift) => list[(h >>> shift) % list.length];
  return {
    skin: pick(P.skin, 0),
    hair: pick(P.hair, 3),
    style: pick(STYLES, 6),
    top: pick(P.top, 9),
    dress: (h >>> 13) % 5 === 0,
    hat: pick(P.hat, 15),
    bag: (h >>> 18) % 3 === 0 ? pick(P.bag, 20) : null,
    shades: (h >>> 22) % 3 === 0,
    scale: 0.92 + ((h >>> 24) % 15) / 100,
  };
}

// A sphere as a lathe around y: centre height cy, radius r.
function sphere(r, cy, rings = 8, segments = 14) {
  const profile = [];
  for (let i = 0; i <= rings; i++) {
    const a = (i / rings) * Math.PI;
    profile.push([Math.max(0.001, Math.sin(a) * r), cy - Math.cos(a) * r]);
  }
  return lathe(profile, { axis: "y", segments });
}

const mat = (colour) => material(colour, { roughness: 0.85, side: 2 });

// The head and its hair or hat, around a head of radius 0.105 centred at y 1.6.
function head(parts, look) {
  parts.add(mat(look.skin), sphere(0.105, 1.6));
  parts.add(mat(look.skin), lathe([[0.048, 1.43], [0.05, 1.52]], { axis: "y", segments: 10 }));
  const hair = mat(look.hair);
  if (look.style !== "straw" && look.style !== "cap") {
    const cap = sphere(0.112, 1.615, 8, 14);
    // keep the upper part of the sphere as the hair line
    for (let i = 1; i < cap.positions.length; i += 3) cap.positions[i] = Math.max(1.6, cap.positions[i]);
    parts.add(hair, cap);
  }
  if (look.style === "long") parts.add(hair, move(scale(sphere(0.11, 0, 8, 14), 1, 1.9, 0.62), 0, 1.5, 0.05));
  if (look.style === "bun") parts.add(hair, sphere(0.055, 1.7, 6, 10));
  if (look.style === "straw") {
    parts.add(mat(look.hat), lathe([[0.001, 1.69], [0.21, 1.69], [0.21, 1.705], [0.001, 1.71]], { axis: "y", segments: 18 }));
    parts.add(mat(look.hat), lathe([[0.1, 1.69], [0.1, 1.77], [0.001, 1.78]], { axis: "y", segments: 14 }));
  }
  if (look.style === "cap") {
    parts.add(mat(look.hat), sphere(0.115, 1.625, 6, 14));
    parts.add(mat(look.hat), box(0.14, 0.015, 0.1, 0, 1.68, -0.12));
  }
  if (look.shades) parts.add(mat(P.shades), box(0.15, 0.035, 0.02, 0, 1.62, -0.1));
}

export function buildPedestrian(id) {
  const look = pedestrianLook(id);
  const s = look.scale;
  const root = new T.Group();
  root.name = "semif-pedestrian";
  root.userData.id = id;
  const lower = mat(P.silhouette), top = mat(look.top);

  const pelvis = new T.Group();
  pelvis.name = "pelvis";
  pelvis.add(...new Parts().add(lower, scale(lathe([[0.001, 0.84], [0.15, 0.87], [0.165, 0.97], [0.001, 1.0]], { axis: "y", segments: 14 }), s)).meshes());
  root.add(pelvis);

  const body = new Parts();
  body.add(top, scale(lathe([[0.001, 0.95], [0.16, 0.97], [0.18, 1.15], [0.2, 1.33], [0.13, 1.42], [0.001, 1.44]], { axis: "y", segments: 16 }), 1, 1, 0.66));
  if (look.dress) body.add(top, lathe([[0.17, 0.98], [0.26, 0.58]], { axis: "y", segments: 16 }));
  head(body, look);
  if (look.bag) body.add(mat(look.bag), box(0.06, 0.22, 0.28, 0.22, 1.0, 0.02));
  const torso = new T.Group();
  torso.name = "torso";
  for (const part of body.byMaterial.values()) for (const p of part) scale(p, s);
  torso.add(...body.meshes());
  root.add(torso);

  const legs = [], arms = [];
  for (const side of [-1, 1]) {
    const leg = new T.Group();
    leg.name = side < 0 ? "leg_l" : "leg_r";
    leg.position.set(side * 0.09 * s, 0.88 * s, 0);
    const lp = new Parts();
    lp.add(lower, lathe([[0.001, 0.02], [0.075, -0.02], [0.07, -0.4], [0.05, -0.8], [0.001, -0.81]], { axis: "y", segments: 12 }));
    lp.add(mat(P.shades), box(0.1, 0.07, 0.25, 0, -0.845, -0.05));
    for (const part of lp.byMaterial.values()) for (const p of part) scale(p, s);
    leg.add(...lp.meshes());
    root.add(leg);
    legs.push(leg);

    const arm = new T.Group();
    arm.name = side < 0 ? "arm_l" : "arm_r";
    arm.position.set(side * 0.215 * s, 1.38 * s, 0);
    const ap = new Parts();
    ap.add(top, lathe([[0.001, 0.03], [0.052, 0.0], [0.045, -0.3], [0.001, -0.31]], { axis: "y", segments: 10 }));
    ap.add(mat(look.skin), lathe([[0.04, -0.29], [0.035, -0.54], [0.001, -0.6]], { axis: "y", segments: 10 }));
    for (const part of ap.byMaterial.values()) for (const p of part) scale(p, s);
    arm.add(...ap.meshes());
    root.add(arm);
    arms.push(arm);
  }
  root.userData.limbs = { legs, arms };
  return root;
}

// --- crowds ----------------------------------------------------------------------------------

const STAGE = { x: -80, z: 400 }; // festival.js: the screen faces east, the audience stands east of it
const TENTS = Array.from({ length: 12 }, (_, k) => ({ x: 28 + Math.floor(k / 3) * 13, z: 288 + (k % 3) * 22 }));
const PODIUMS = [{ x: 30, z: 472 }, { x: -36, z: 472 }];
const LANE_CLEAR = 6.5; // road edge; lane centre lines are then at least 8 m away

export function placeCrowds(world, field, grid) {
  const seed = Number(world.seed) >>> 0;
  const sea = seaPolygon(world.visual.shoreline, world.bounds);
  const buildings = world.objects.filter((o) => o.type === "building");
  const inBuilding = (x, z) => buildings.some((b) => Math.abs(x - b.x) < b.width / 2 + 1 && Math.abs(z - b.z) < b.depth / 2 + 1);
  const rnd = (k) => hash(`${seed}:${k}`) / 4294967296;
  const spots = [];
  const add = (place, x, z, heading, k) => {
    if (field.roadEdge(x, z) < LANE_CLEAR || inside(sea, { x, z }) || inBuilding(x, z)) return;
    if (field.heightAt(x, z) < SEA_LEVEL + 0.3) return;
    spots.push({ place, x, z, y: grid.heightAt(x, z), heading, look: Math.floor(rnd(`look${k}`) * 1e6) });
  };
  // The audience in front of the stage, facing it (west).
  for (let i = 0; i < 18; i++) {
    for (let j = 0; j < 12; j++) {
      const k = `a${i}:${j}`;
      if (rnd(k) < 0.35) continue;
      add("festival", STAGE.x + 22 + i * 2.1 + (rnd(k + "x") - 0.5), STAGE.z - 12 + j * 2.1 + (rnd(k + "z") - 0.5), -Math.PI / 2 + (rnd(k + "h") - 0.5) * 0.6, k);
    }
  }
  // Browsing at the tents and gathered round the podiums.
  TENTS.forEach((t, n) => {
    for (let q = 0; q < 3; q++) add("festival", t.x - 3 + q * 3, t.z - 6 - rnd(`t${n}:${q}`) * 2, Math.PI * rnd(`t${n}:${q}h`) * 2, `t${n}:${q}`);
  });
  PODIUMS.forEach((p, n) => {
    for (let q = 0; q < 8; q++) {
      const a = (q / 8) * Math.PI * 2;
      add("festival", p.x + Math.sin(a) * 8, p.z - Math.cos(a) * 8, a + Math.PI, `p${n}:${q}`);
    }
  });
  // Two or three at each café table on the harbour promenade.
  placeProps(world, field, grid).cafes.forEach((c, n) => {
    const count = 2 + Math.floor(rnd(`c${n}`) * 2);
    for (let q = 0; q < count; q++) {
      const a = (q / count) * Math.PI * 2 + rnd(`c${n}a`);
      add("cafe", c.x + Math.sin(a) * 1.3, c.z - Math.cos(a) * 1.3, a + Math.PI, `c${n}:${q}`);
    }
  });
  // The festival bay's beach.
  for (let x = -260; x <= 240; x += 7) {
    for (let z = 380; z <= 620; z += 7) {
      const k = `b${x}:${z}`;
      if (rnd(k) < 0.7) continue;
      const px = x + (rnd(k + "x") - 0.5) * 5, pz = z + (rnd(k + "z") - 0.5) * 5;
      const h = field.heightAt(px, pz);
      if (h > SEA_LEVEL + 3.5 || field.roadEdge(px, pz) < 12) continue;
      add("beach", px, pz, rnd(k + "h") * Math.PI * 2, k);
    }
  }
  return spots;
}

// One merged figure per body part, drawn instanced and coloured per person from the palette.
function figurePart(part) {
  const p = new Parts();
  const white = material("#ffffff", { roughness: 0.85, side: 2 });
  if (part === "legs") for (const side of [-1, 1]) p.add(white, move(lathe([[0.07, 0.9], [0.065, 0.45], [0.05, 0.05], [0.001, 0.0]], { axis: "y", segments: 8 }), side * 0.09, 0, 0));
  if (part === "torso") {
    p.add(white, scale(lathe([[0.001, 0.86], [0.16, 0.9], [0.19, 1.2], [0.2, 1.33], [0.13, 1.42], [0.001, 1.44]], { axis: "y", segments: 12 }), 1, 1, 0.66));
    for (const side of [-1, 1]) p.add(white, move(lathe([[0.05, 1.38], [0.04, 0.85]], { axis: "y", segments: 8 }), side * 0.22, 0, 0));
  }
  if (part === "head") p.add(white, sphere(0.105, 1.6, 6, 12));
  if (part === "hair") {
    const cap = sphere(0.112, 1.615, 6, 12);
    for (let i = 1; i < cap.positions.length; i += 3) cap.positions[i] = Math.max(1.6, cap.positions[i]);
    p.add(white, cap);
  }
  return p.meshes()[0];
}

export function buildCrowds(spots) {
  const group = new T.Group();
  group.name = "semif-crowds";
  if (!spots.length) return group;
  const colourOf = { legs: P.bottom, torso: P.top, head: P.skin, hair: P.hair };
  const m4 = new T.Matrix4(), q = new T.Quaternion(), pos = new T.Vector3(), up = new T.Vector3(0, 1, 0);
  for (const part of ["legs", "torso", "head", "hair"]) {
    const template = figurePart(part);
    const mesh = new T.InstancedMesh(template.geometry, template.material, spots.length);
    const colour = new T.Color();
    spots.forEach((s, i) => {
      const size = 0.92 + ((s.look >>> 2) % 15) / 100;
      q.setFromAxisAngle(up, -s.heading);
      pos.set(s.x, s.y, s.z);
      mesh.setMatrixAt(i, m4.compose(pos, q, new T.Vector3(size, size, size)));
      const list = colourOf[part];
      mesh.setColorAt(i, colour.set(list[(s.look >>> (part.length * 3)) % list.length]));
    });
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.computeBoundingSphere();
    mesh.name = `crowd-${part}`;
    group.add(mesh);
  }
  return group;
}
