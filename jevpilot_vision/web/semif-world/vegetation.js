// Trees, shrubs and vineyards. placeVegetation() decides what grows where (a plain function, tested
// in node); buildVegetation() draws it as instanced meshes in 512 m chunks, so the camera's frustum
// skips the chunks out of view, with crowns that sway a little in the breeze.
import { PALETTE, T, material } from "./kit.js";
import { SEA_LEVEL, fbm, distanceToLine } from "./heights.js";
import { placeVillas } from "./buildings.js";

export const SPECIES = ["cypress", "pine", "olive", "palm", "shrub", "vine"];

const CELL = 12; // one candidate plant per 12 m cell
const MARGIN = 220; // plants reach this far past the drivable map
const CLEAR = 6; // metres from a road's edge to any plant but a street palm
const STREET_PALM_EDGE = 3.3; // street palms stand on the pavement, off the asphalt
const STREET_PALM_EVERY = 24;
const CHUNK = 512;

const smooth = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

function hash(a, b, c) {
  let h = Math.imul(a, 374761393) ^ Math.imul(b, 668265263) ^ Math.imul(c, 2246822519);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

// The festival grounds are dressed by festival.js.
const FESTIVAL = { x0: -150, x1: 150, z0: 150, z1: 510 };

export function placeVegetation(world, field, grid) {
  const seed = Number(world.seed) >>> 0;
  const rand = (ix, iz, k) => hash(ix * 31 + k, iz * 17 - k, seed + k * 101);
  const shoreline = world.visual.shoreline;
  // The town's houses and the hillside villas (placed by buildings.js, which draws them).
  const buildings = [...world.objects.filter((o) => o.type === "building"), ...placeVillas(world, field, grid)];
  const inBuilding = (x, z, pad) => buildings.some((b) => Math.abs(x - b.x) < b.width / 2 + pad && Math.abs(z - b.z) < b.depth / 2 + pad);
  const inFestival = (x, z) => x > FESTIVAL.x0 && x < FESTIVAL.x1 && z > FESTIVAL.z0 && z < FESTIVAL.z1;
  const slopeAt = (x, z) => Math.hypot(grid.heightAt(x + 2, z) - grid.heightAt(x - 2, z), grid.heightAt(x, z + 2) - grid.heightAt(x, z - 2)) / 4;
  const ground = (x, z) => grid.heightAt(x, z);
  const vineyard = (x, z) => z > -450 && z < 250 && x > -720 && x < 820 && fbm(x / 230 + 7.7, z / 230 - 3.3, 3) > 0.6;
  const plants = [];
  const add = (species, x, z, scale, k) => plants.push({ species, x, z, y: ground(x, z), scale, rotation: k * Math.PI * 2 });

  const { minX, maxX, minZ, maxZ } = world.bounds;
  for (let gx = minX - MARGIN, ix = 0; gx < maxX + MARGIN; gx += CELL, ix++) {
    for (let gz = minZ - MARGIN, iz = 0; gz < maxZ + MARGIN; gz += CELL, iz++) {
      const x = gx + rand(ix, iz, 1) * CELL, z = gz + rand(ix, iz, 2) * CELL;
      if (inFestival(x, z) || vineyard(x, z)) continue;
      const h = ground(x, z);
      if (h < SEA_LEVEL + 1.5) continue;
      const edge = field.roadEdge(x, z);
      if (edge < CLEAR || inBuilding(x, z, 2)) continue;
      if (slopeAt(x, z) > 0.8) continue;
      // The drawn ground interpolates the field; near the water check the field itself as well.
      if (h < SEA_LEVEL + 4 && field.heightAt(x, z) < SEA_LEVEL + 1.5) continue;
      const north = smooth(-480, -900, z);
      const coast = 1 - smooth(40, 180, distanceToLine(shoreline, { x, z }));
      const roadside = edge < 22 ? 1 : 0;
      const odds = {
        pine: 0.03 + 0.22 * north + 0.1 * coast,
        cypress: 0.025 + 0.2 * roadside * (1 - north),
        olive: 0.09 * (1 - north) * (1 - coast),
        palm: 0.035 * coast * (1 - north),
        shrub: 0.1,
      };
      let roll = rand(ix, iz, 3);
      for (const [species, p] of Object.entries(odds)) {
        if (roll < p) {
          add(species, x, z, 0.75 + 0.5 * rand(ix, iz, 4), rand(ix, iz, 5));
          break;
        }
        roll -= p;
      }
    }
  }

  // Street palms on both pavements of the harbour and festival streets, clear of junctions.
  const junctions = world.nodes.filter((n) => n.townJunction);
  for (const road of world.connectorRoads) {
    if (road.kind !== "harbour" && road.kind !== "festival") continue;
    const pts = road.points;
    for (let i = 1; i < pts.length - 1; i++) {
      if (Math.floor(pts[i].s / STREET_PALM_EVERY) === Math.floor(pts[i - 1].s / STREET_PALM_EVERY)) continue;
      if (junctions.some((n) => Math.hypot(pts[i].x - n.x, pts[i].z - n.z) < 16)) continue;
      const h = Math.atan2(pts[i + 1].x - pts[i - 1].x, pts[i - 1].z - pts[i + 1].z);
      for (const side of [-1, 1]) {
        const d = road.width / 2 + STREET_PALM_EDGE;
        const x = pts[i].x + Math.sin(h + (side * Math.PI) / 2) * d, z = pts[i].z - Math.cos(h + (side * Math.PI) / 2) * d;
        if (inBuilding(x, z, 1.5) || field.roadEdge(x, z) < 2.5 || ground(x, z) < SEA_LEVEL + 1.5) continue;
        add("palm", x, z, 0.9 + 0.2 * hash(i, side, seed), hash(side, i, seed + 3));
      }
    }
  }

  // Vineyards: rows 2.6 m apart in 48 m patches on gentle valley ground, one plant per 2.5 m.
  for (let px = -720; px < 820; px += 48) {
    for (let pz = -450; pz < 250; pz += 48) {
      const cx = px + 24, cz = pz + 24;
      if (!vineyard(cx, cz)) continue;
      const corners = [[px, pz], [px + 48, pz], [px, pz + 48], [px + 48, pz + 48]];
      if (corners.some(([x, z]) => field.roadEdge(x, z) < 10 || slopeAt(x, z) > 0.28 || ground(x, z) < SEA_LEVEL + 2)) continue;
      const angle = hash(px, pz, seed) < 0.5 ? 0 : Math.PI / 2;
      for (let a = -22; a <= 22; a += 2.6) {
        for (let b = -22; b <= 22; b += 2.5) {
          const x = cx + (angle ? b : a), z = cz + (angle ? a : b);
          if (field.roadEdge(x, z) < CLEAR || inBuilding(x, z, 1.5)) continue;
          plants.push({ species: "vine", x, z, y: ground(x, z), scale: 1, rotation: angle });
        }
      }
    }
  }
  return plants;
}

// --- drawing -------------------------------------------------------------------------------

// A palm frond: a strip of quads arching out and drooping, built along +x.
function frondGeometry() {
  const pos = [];
  const segments = 6, length = 3.4, width = 0.55;
  const at = (t) => ({ x: t * length, y: 0.9 * t - 1.6 * t * t });
  for (let i = 0; i < segments; i++) {
    const a = at(i / segments), b = at((i + 1) / segments);
    const wa = width * (1 - i / segments), wb = width * (1 - (i + 1) / segments);
    pos.push(a.x, a.y, -wa, b.x, b.y, -wb, b.x, b.y, wb, a.x, a.y, -wa, b.x, b.y, wb, a.x, a.y, wa);
  }
  const geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
  geo.computeVertexNormals();
  return geo;
}

function crown(count, make) {
  const parts = [];
  for (let i = 0; i < count; i++) parts.push(make(i));
  return T.mergeGeometries(parts);
}

// Each species is a few parts: [geometry, colour, sways?].
function speciesParts() {
  const trunk = (r0, r1, h) => new T.CylinderGeometry(r0, r1, h, 7).translate(0, h / 2, 0);
  const blob = (sx, sy, sz, x, y, z) => new T.SphereGeometry(1, 8, 6).scale(sx, sy, sz).translate(x, y, z);
  const F = PALETTE.foliage, B = PALETTE.bark;
  return {
    cypress: [[trunk(0.14, 0.22, 1.4), B.dark, false], [blob(1.15, 4.6, 1.15, 0, 5.2, 0), F.cypress, true]],
    pine: [
      [trunk(0.18, 0.32, 7.2), B.light, false],
      [crown(4, (i) => blob(2.6, 1.0, 2.6, Math.cos(i * 1.7) * 1.6, 7.6 + (i % 2) * 0.5, Math.sin(i * 1.7) * 1.6)), F.pine, true],
    ],
    olive: [
      [trunk(0.2, 0.34, 1.7), B.light, false],
      [crown(3, (i) => blob(1.5, 1.1, 1.5, Math.cos(i * 2.1) * 0.9, 2.4 + i * 0.25, Math.sin(i * 2.1) * 0.9)), F.olive, true],
    ],
    palm: [
      [trunk(0.16, 0.28, 8.5), B.palm, false],
      [crown(9, (i) => frondGeometry().rotateZ(0.1).rotateY((i / 9) * Math.PI * 2 + (i % 2) * 0.2).translate(0, 8.4, 0)), F.palm, true],
    ],
    shrub: [[blob(1.2, 0.8, 1.2, 0, 0.6, 0), F.shrub, false]],
    vine: [[new T.BoxGeometry(0.55, 1.15, 2.5).translate(0, 0.58, 0), F.vine, false]],
  };
}

const sway = { value: 0 };

function swayingMaterial(colour) {
  const mat = material(colour, { roughness: 0.92, side: 2 });
  if (mat.userData.sway) return mat;
  mat.userData.sway = true;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uSway = sway;
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nuniform float uSway;")
      .replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
        #ifdef USE_INSTANCING
          vec3 root = instanceMatrix[3].xyz;
          float lift = max(position.y - 1.0, 0.0);
          transformed.x += sin(uSway * 1.3 + root.x * 0.07 + root.z * 0.05) * 0.035 * lift;
          transformed.z += cos(uSway * 1.1 + root.x * 0.05) * 0.025 * lift;
        #endif`,
      );
  };
  return mat;
}

export function buildVegetation(plants) {
  const parts = speciesParts();
  const group = new T.Group();
  group.name = "semif-vegetation";
  const m = new T.Matrix4(), q = new T.Quaternion(), p = new T.Vector3(), s = new T.Vector3(), up = new T.Vector3(0, 1, 0);
  const tint = new T.Color("#ffffff");
  // Group plants by species and 512 m chunk.
  const chunks = new Map();
  for (const plant of plants) {
    const key = `${plant.species}:${Math.floor(plant.x / CHUNK)}:${Math.floor(plant.z / CHUNK)}`;
    if (!chunks.has(key)) chunks.set(key, []);
    chunks.get(key).push(plant);
  }
  for (const [key, list] of chunks) {
    const species = key.split(":")[0];
    for (const [geometry, colour, sways] of parts[species]) {
      const mesh = new T.InstancedMesh(geometry, sways ? swayingMaterial(colour) : material(colour, { roughness: 0.9 }), list.length);
      list.forEach((plant, i) => {
        q.setFromAxisAngle(up, plant.rotation);
        p.set(plant.x, plant.y - 0.05, plant.z);
        s.set(plant.scale, plant.scale, plant.scale);
        mesh.setMatrixAt(i, m.compose(p, q, s));
        const v = 0.88 + 0.24 * ((Math.sin(plant.x * 12.9898 + plant.z * 78.233) * 43758.5453) % 1 + 1) % 1;
        mesh.setColorAt(i, tint.setRGB(v, v, v));
      });
      mesh.castShadow = species !== "vine";
      mesh.receiveShadow = true;
      mesh.computeBoundingSphere();
      mesh.name = `semif-${species}`;
      group.add(mesh);
    }
  }
  return group;
}

export function updateVegetation(dt) {
  sway.value += dt || 0;
}
