// Solmare Coast renderer: the bundle's three.js classes, the palette and small geometry helpers.
//
// The onboard camera reads lights, construction, warning lights and people by colour
// (jevpilot_vision/vision.py). Every colour the coast renderer uses is in PALETTE, so
// tests/test_world_render.py can keep it out of those masks; no other colour literal is allowed.

export const PALETTE = {
  asphalt: "#4d5257", // the textured asphalt's average tone, kept for the mask tests
  asphaltTint: "#d2d5d9", // multiplies the asphalt texture, as the bundle's own roads do
  kerb: "#c9c3b5",
  guardrail: "#b9bec2",
  post: "#8d9296",
  marking: "#e9e6da",
  pavement: "#cfc6b2",
  shoulder: "#9a9283",
  median: "#a7a59d",
  // Muted olive and grey greens: a saturated leaf green above the horizon is a "green light".
  foliage: { cypress: "#46573b", pine: "#506343", olive: "#7d8864", palm: "#67803f", shrub: "#5e6c46", vine: "#6c7b46" },
  bark: { dark: "#5c4c3e", light: "#706253", palm: "#857d72" },
  sea: { deep: "#1d5a76", shallow: "#3a9ea2", foam: "#e9eee9" },
  stucco: ["#efe6d6", "#e9d8bf", "#f2e2cf", "#dfe3d6", "#e8d2c4"],
  roof: ["#b2857c", "#a6847a", "#9c8a7c"],
  // Facades (canvas bays) and harbour: no colour dark enough, in shade, to read as a pedestrian.
  shutter: ["#5f7d6e", "#5e7389", "#7a6a5a"],
  trim: "#ece6d8",
  glass: "#4a5864",
  stone: "#b8ad98",
  railing: "#5a6066",
  door: "#6e5847",
  shopFrame: "#555c61",
  awning: ["#3f6f73", "#7a5c66", "#4a5d7a", "#8a7f6a"],
  villa: "#f1ece2",
  lighthouse: { white: "#eeeae2", band: "#4c5258" },
  // The festival's colours: sea teal, blue, purple, sand; no signal red, green or cone orange.
  festival: { ink: "#36414f", sand: "#e8d9b5", teal: "#2f8f8f", blue: "#3a5f9a", purple: "#6b5a9a", white: "#f4f1ea" },
  minimap: { sea: "#cfe3ea", building: "#dcdfe4" },
  // Car paints: white, silver, champagne, teal, navy, wine, olive, sand. No cone orange, no
  // signal red or green; the wine and the taillights lean blue so warm light keeps them off red.
  paint: ["#e9e8e3", "#b9bec4", "#d8c7a6", "#3f7f80", "#2e3d5c", "#6a3046", "#6b6f48", "#cdb68f"],
  // Car parts. Tyres and trim are a dark grey, not black: black reads as a pedestrian.
  car: {
    tyre: "#4c4d50",
    rim: "#a9adb2",
    disc: "#7d8085",
    caliper: "#8a8f96",
    trim: "#55595e",
    glass: "#45525e",
    lens: "#e8ecef",
    taillight: "#663046",
    interior: "#5b5751",
    leather: "#7a6458",
    chrome: "#c9cdd2",
    plate: "#e7e4dc",
  },
  // People. `silhouette` is the sim pedestrians' lower body and the only colour allowed in the
  // camera's pedestrian mask; crowds never wear it. Skin, hair and leather lean pink or grey: warm
  // browns turn into the camera's construction orange in the evening light.
  people: {
    silhouette: "#202326",
    skin: ["#e6c2b0", "#d0a690", "#a2827a", "#7a5e58"],
    hair: ["#7d6252", "#a08a78", "#b8a088", "#7a6f68", "#4f4a47"],
    top: ["#e9e4da", "#5f7fa0", "#c4808a", "#7a9a72", "#d9c27a", "#8a6b8f", "#5d8a8c"],
    bottom: ["#5f6f86", "#b7a98c", "#7b7f86", "#e6e1d5"],
    hat: ["#d8c48e", "#3f5f7f", "#e9e4da"],
    bag: ["#7d6252", "#c9b48e"],
    shades: "#4a4f57",
  },
};

// The bundle's three.js classes, handed over by its build() through the kit() hook.
export const T = {};
export function setKit(kit) {
  Object.assign(T, kit);
}

const materials = new Map();
export function resetCaches() {
  materials.clear();
}

export function material(color, opts = {}) {
  const key = `${color}|${JSON.stringify(opts)}`;
  if (!materials.has(key)) materials.set(key, new T.MeshStandardMaterial({ color, roughness: 0.9, metalness: 0, ...opts }));
  return materials.get(key);
}

// Clearcoat paint and glass. `name` survives the cache: the bundle hides the `Glass` material in
// its hood view.
export function physical(color, opts = {}) {
  const key = `physical|${color}|${JSON.stringify(opts)}`;
  if (!materials.has(key)) {
    const { name, ...rest } = opts;
    const mat = new T.MeshPhysicalMaterial({ color, roughness: 0.3, metalness: 0.3, ...rest });
    if (name) mat.name = name;
    materials.set(key, mat);
  }
  return materials.get(key);
}

// Geometry, in the bundle's conventions: x east, z south, heading 0 north and pi/2 east.
export const headingOf = (a, b) => Math.atan2(b.x - a.x, a.z - b.z);
export const along = (p, h, d) => ({ x: p.x + Math.sin(h) * d, z: p.z - Math.cos(h) * d });

// Heading of a polyline at point i, from its neighbours.
export function headingAt(points, i) {
  return headingOf(points[Math.max(0, i - 1)], points[Math.min(points.length - 1, i + 1)]);
}

// Triangles collected per material and drawn as one mesh.
export class Batch {
  constructor() {
    this.positions = [];
    this.colors = null;
  }

  // One upward-facing triangle; the winding is fixed here so callers need not care.
  tri(a, b, c) {
    const ux = b.x - a.x, uz = b.z - a.z, vx = c.x - a.x, vz = c.z - a.z;
    // y of (b - a) x (c - a) for points on the ground plane
    const up = uz * vx - ux * vz > 0;
    for (const p of up ? [a, b, c] : [a, c, b]) this.positions.push(p.x, p.y ?? 0, p.z);
  }

  quad(a, b, c, d) {
    this.tri(a, b, c);
    this.tri(a, c, d);
  }

  // A strip `left`..`right` metres to the right of a polyline (negative is left), at height y.
  ribbon(points, left, right, y, from = 0, to = points.length - 1) {
    for (let i = from; i < to; i++) {
      const h0 = headingAt(points, i), h1 = headingAt(points, i + 1);
      const a = { ...along(points[i], h0 + Math.PI / 2, left), y };
      const b = { ...along(points[i], h0 + Math.PI / 2, right), y };
      const c = { ...along(points[i + 1], h1 + Math.PI / 2, right), y };
      const d = { ...along(points[i + 1], h1 + Math.PI / 2, left), y };
      this.quad(a, b, c, d);
    }
  }

  // A rectangle centred on p, `length` along heading h and `width` across it.
  rect(p, h, length, width, y) {
    const f = along(p, h, length / 2), r = along(p, h, -length / 2);
    const s = h + Math.PI / 2;
    this.quad({ ...along(f, s, -width / 2), y }, { ...along(f, s, width / 2), y }, { ...along(r, s, width / 2), y }, { ...along(r, s, -width / 2), y });
  }

  // An axis-aligned box standing on the ground: four walls and a top.
  box(x, z, w, d, h, y0 = 0) {
    const x0 = x - w / 2, x1 = x + w / 2, z0 = z - d / 2, z1 = z + d / 2, y1 = y0 + h;
    const v = (px, py, pz) => [px, py, pz];
    const faces = [
      [v(x0, y1, z0), v(x0, y1, z1), v(x1, y1, z1), v(x1, y1, z0)], // top
      [v(x0, y0, z1), v(x1, y0, z1), v(x1, y1, z1), v(x0, y1, z1)], // south
      [v(x1, y0, z0), v(x0, y0, z0), v(x0, y1, z0), v(x1, y1, z0)], // north
      [v(x1, y0, z1), v(x1, y0, z0), v(x1, y1, z0), v(x1, y1, z1)], // east
      [v(x0, y0, z0), v(x0, y0, z1), v(x0, y1, z1), v(x0, y1, z0)], // west
    ];
    for (const [a, b, c, d] of faces) this.positions.push(...a, ...b, ...c, ...a, ...c, ...d);
  }

  // A vertical strip `offset` metres right of a polyline, from y0 to y1 (drawn double-sided).
  wall(points, offset, y0, y1, from = 0, to = points.length - 1) {
    for (let i = from; i < to; i++) {
      const a = along(points[i], headingAt(points, i) + Math.PI / 2, offset);
      const b = along(points[i + 1], headingAt(points, i + 1) + Math.PI / 2, offset);
      this.positions.push(a.x, y0, a.z, b.x, y0, b.z, b.x, y1, b.z, a.x, y0, a.z, b.x, y1, b.z, a.x, y1, a.z);
    }
  }

  get empty() {
    return this.positions.length === 0;
  }

  mesh(mat, { cast = false, receive = true } = {}) {
    const geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.Float32BufferAttribute(this.positions, 3));
    if (this.colors) geo.setAttribute("color", new T.Float32BufferAttribute(this.colors, 3));
    if (this.uvScale) {
      const uv = [];
      for (let i = 0; i < this.positions.length; i += 3) uv.push(this.positions[i] / this.uvScale, this.positions[i + 2] / this.uvScale);
      geo.setAttribute("uv", new T.Float32BufferAttribute(uv, 2));
    }
    geo.computeVertexNormals();
    const mesh = new T.Mesh(geo, mat);
    mesh.castShadow = cast;
    mesh.receiveShadow = receive;
    return mesh;
  }
}
