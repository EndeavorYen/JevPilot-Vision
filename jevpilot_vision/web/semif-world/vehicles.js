// Solmare Coast vehicles (spec §5.1): three hero cars and seven traffic models, procedural.
//
// A body is lofted along the car (side profile x superellipse sections) with its wheel arches cut
// out, a glass house and roof on top, then lights, bumpers and multi-spoke wheels. The bundle
// drives what we return, so the contract is fixed:
// - outer box: hero 4.75 x 1.9 m, traffic 4.2 x 1.9 m, motorcycle 0.8 x 2.3 m; nose toward -z
// - wheel pivots `wheel_fl/fr/rl/rr` (front: z < 0, left: x < 0) with `userData.radius` and
//   `userData.front`, whose children[0] is the part that spins
// - `userData.wheelbase/eyeHeight/eyeForward`; the windows use the material named `Glass`
// - every call builds new geometry: the bundle's crash code dents it in place
import { PALETTE, T, material, physical } from "./kit.js";
import { curve, loft, lathe, box, rotateX, move, Parts } from "./shapes.js";

export const HERO_MODELS = ["gt", "roadster", "rally"];
export const TRAFFIC_KINDS = ["hatch", "sedan", "wagon", "suv", "van", "pickup"];
export const HERO_LENGTH = 4.75;
export const TRAFFIC_LENGTH = 4.2;

const C = PALETTE.car;

function mats() {
  return {
    tyre: material(C.tyre, { roughness: 0.92, side: 2 }),
    rim: material(C.rim, { metalness: 0.85, roughness: 0.3, side: 2 }),
    disc: material(C.disc, { metalness: 0.7, roughness: 0.45, side: 2 }),
    caliper: material(C.caliper, { metalness: 0.4, roughness: 0.5 }),
    trim: material(C.trim, { roughness: 0.55, metalness: 0.2 }),
    glass: physical(C.glass, { name: "Glass", metalness: 0.2, roughness: 0.06, clearcoat: 1 }),
    lens: material(C.lens, { emissive: "#ffffff", emissiveIntensity: 0.5, roughness: 0.15 }),
    tail: material(C.taillight, { roughness: 0.25 }),
    chrome: material(C.chrome, { metalness: 0.95, roughness: 0.12 }),
    interior: material(C.interior, { roughness: 0.85 }),
    leather: material(C.leather, { roughness: 0.7 }),
    plate: material(C.plate, { roughness: 0.6 }),
  };
}

const paintOf = (colour) => physical(colour, { metalness: 0.45, roughness: 0.28, clearcoat: 1, clearcoatRoughness: 0.08 });

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619) >>> 0;
  return h;
}

// --- wheels ----------------------------------------------------------------------------------

// A wheel pivot at (x, r, z): tyre, rim and spokes spin in children[0]; disc and caliper do not.
function wheel(name, { x, z, r, w, spokes, front, chrome }, m) {
  const pivot = new T.Group();
  pivot.name = name;
  pivot.position.set(x, r, z);
  pivot.userData.front = front;
  pivot.userData.radius = r;
  const out = x < 0 ? -1 : 1; // the wheel's outer face points away from the car
  const rotor = new T.Group();
  rotor.name = `${name}_spin`;
  const spin = new Parts();
  spin.add(m.tyre, lathe([[r * 0.66, -w / 2], [r * 0.9, -w / 2], [r, -w * 0.34], [r, w * 0.34], [r * 0.9, w / 2], [r * 0.66, w / 2]], { segments: 30 }));
  const rim = chrome ? m.chrome : m.rim;
  const face = out * (w / 2 - 0.02);
  spin.add(rim, lathe([[r * 0.64, -w / 2 + 0.015], [r * 0.64, w / 2 - 0.015]], { segments: 30 }));
  spin.add(rim, lathe([[r * 0.58, face - out * 0.035], [r * 0.66, face]], { segments: 30 }));
  spin.add(rim, lathe([[0.001, face], [0.075, face], [0.085, face - out * 0.025]], { segments: 14 }));
  for (let k = 0; k < spokes; k++) {
    const spoke = box(0.03, r * 0.52, spokes > 10 ? 0.018 : 0.055, face - out * 0.018, r * 0.33, 0);
    spin.add(rim, rotateX(spoke, (k / spokes) * Math.PI * 2));
  }
  rotor.add(...spin.meshes());
  pivot.add(rotor);
  const fixed = new Parts();
  fixed.add(m.disc, lathe([[r * 0.22, -0.012], [r * 0.52, -0.012], [r * 0.52, 0.012], [r * 0.22, 0.012]], { segments: 22 }));
  fixed.add(m.caliper, box(0.06, 0.12, 0.16, 0, r * 0.38, r * 0.2));
  for (const mesh of fixed.meshes()) {
    mesh.position.set(out * (w / 2 - 0.08), 0, 0);
    pivot.add(mesh);
  }
  return pivot;
}

// --- bodies ----------------------------------------------------------------------------------

// spec: L, r (wheel radius), w (tyre width), front/rear (axle z), sill, half/top keys, n (body
// squareness), house {z0, z1, belt, roof keys, half keys, b (B-pillar z), glass (all glass)}.
function carBody(spec, paintColour) {
  const m = mats();
  const paint = paintOf(paintColour);
  const parts = new Parts();
  const L = spec.L, z0 = -L / 2 + 0.012, z1 = L / 2 - 0.012;
  const half = curve(spec.half), top = curve(spec.top);
  const R = spec.r + 0.06;
  const axles = [spec.front, spec.rear];
  const bottom = (z) => {
    let b = spec.sill;
    for (const az of axles) {
      const dz = z - az;
      if (Math.abs(dz) < R) b = Math.max(b, spec.r + Math.sqrt(R * R - dz * dz));
    }
    // The bumpers rise a little at both ends.
    if (z < z0 + 0.25) b = Math.max(b, spec.sill + (z0 + 0.25 - z) * 0.4);
    if (z > z1 - 0.25) b = Math.max(b, spec.sill + (z - z1 + 0.25) * 0.4);
    return b;
  };
  const stops = axles.flatMap((az) => Array.from({ length: 13 }, (_, k) => az - R + (k * 2 * R) / 12));
  parts.add(paint, loft({ z0, z1, half, bottom, top, n: spec.n || 5, step: 0.05, stops }));
  // Arch liners: a dark band round each opening so the wheel sits in shadow, not in the open.
  for (const az of axles) {
    for (const side of [-1, 1]) {
      const liner = lathe([[R - 0.03, -0.04], [R, -0.04], [R, 0.04], [R - 0.03, 0.04]], { segments: 16, phase: 0 });
      // keep only the upper half: squash the lower half onto the axle line
      for (let i = 0; i < liner.positions.length; i += 3) liner.positions[i + 1] = Math.max(0, liner.positions[i + 1]);
      move(liner, side * (half(az) - 0.07), spec.r, az);
      parts.add(m.trim, liner);
    }
  }

  const house = spec.house;
  if (house) {
    const houseHalf = curve(house.half), houseTop = curve(house.roof);
    const shape = { z0: house.z0, z1: house.z1, half: houseHalf, bottom: () => house.belt - 0.04, top: houseTop, n: house.n || 3.4, step: 0.04, around: 40 };
    if (house.glass) parts.add(m.glass, loft(shape));
    else {
      // Painted roof, waist and pillars; glass for the windscreen, rear and side windows. The
      // borders follow the loft's sections (z) and around-lines (angle), so they run straight.
      const roofY = Math.max(...house.roof.map((k) => k[1]));
      const flat = house.roof.filter((k) => k[1] >= roofY - 0.02).map((k) => k[0]);
      const roofFront = Math.min(...flat), roofRear = Math.max(...flat);
      const sideFrom = roofFront - 0.2, sideTo = roofRear + 0.1;
      const bp = house.b;
      const stops = [roofFront, roofRear, sideFrom, sideTo, ...(bp === undefined ? [] : [bp - 0.06, bp + 0.06])];
      const classify = (z, a) => {
        const c = Math.cos(a), s = Math.sin(a);
        if (s < -0.2) return "paint"; // the waist, below the windows (and the hidden underside)
        if (Math.abs(c) < 0.5) return z >= roofFront && z <= roofRear ? "paint" : "glass"; // roof, or windscreen / rear window
        if (s > 0.86) return "paint"; // the roof rail
        if (z < sideFrom || z > sideTo) return "paint"; // A and C pillars
        if (bp !== undefined && Math.abs(z - bp) < 0.06) return "paint"; // B pillar
        return "glass";
      };
      const pieces = loft({ ...shape, stops, classify });
      if (pieces.paint) parts.add(paint, pieces.paint);
      if (pieces.glass) parts.add(m.glass, pieces.glass);
    }
  }

  // Lights, grille, bumpers and number plates on the two end faces.
  const front = -L / 2 + 0.01, rear = L / 2 - 0.01; // the lamps' faces are the car's ends
  const hf = half(z0), hr = half(z1), tf = top(z0), tr = top(z1);
  for (const side of [-1, 1]) {
    parts.add(m.lens, box(Math.min(0.36, hf * 0.42), 0.085, 0.02, side * hf * 0.62, tf - 0.07, front));
    parts.add(m.tail, box(Math.min(0.34, hr * 0.4), 0.075, 0.02, side * hr * 0.64, tr - 0.07, rear));
  }
  parts.add(m.trim, box(hf * 0.7, 0.1, 0.02, 0, tf - 0.2, front));
  parts.add(m.trim, box(hf * 1.6, 0.09, 0.02, 0, spec.sill + 0.1, front));
  parts.add(m.trim, box(hr * 1.6, 0.09, 0.02, 0, spec.sill + 0.1, rear));
  parts.add(m.plate, box(0.42, 0.1, 0.022, 0, spec.sill + 0.2, front));
  parts.add(m.plate, box(0.42, 0.1, 0.022, 0, spec.sill + 0.24, rear));
  // Door mirrors on short arms from the doors; they also set the car's full width (1.9 m).
  if (house) {
    const mz = house.z0 + 0.18, my = Math.max(top(mz), house.belt) + 0.07;
    for (const side of [-1, 1]) {
      parts.add(paint, box(0.07, 0.1, 0.17, side * (0.95 - 0.035), my, mz));
      parts.add(m.trim, box(0.95 - 0.07 - (half(mz) - 0.06), 0.03, 0.05, side * ((0.95 - 0.07 + half(mz) - 0.06) / 2), my - 0.03, mz));
    }
  }

  const group = new T.Group();
  const shell = new T.Group();
  shell.name = "body";
  shell.add(...parts.meshes());
  group.add(shell);
  const track = (az) => half(az) - spec.w / 2 - 0.03;
  for (const [name, az, front] of [["wheel_fl", spec.front, true], ["wheel_fr", spec.front, true], ["wheel_rl", spec.rear, false], ["wheel_rr", spec.rear, false]]) {
    const x = (name.endsWith("l") ? -1 : 1) * track(az);
    group.add(wheel(name, { x, z: az, r: spec.r, w: spec.w, spokes: spec.spokes || 5, front, chrome: spec.chromeWheels }, m));
  }
  group.userData.wheelbase = Math.abs(spec.front - spec.rear);
  return { group, parts: new Parts(), m, paint, half, top };
}

// Extra parts drawn after the body (spoilers, cockpits, racks, liveries).
function addParts(group, build) {
  const parts = new Parts();
  build(parts);
  const extra = new T.Group();
  extra.name = "details";
  extra.add(...parts.meshes());
  group.add(extra);
}

// --- heroes ----------------------------------------------------------------------------------

const HERO = {
  gt: {
    paint: PALETTE.paint[5],
    eye: [1.05, 0.25],
    spec: {
      L: HERO_LENGTH, r: 0.345, w: 0.26, front: -1.45, rear: 1.36, sill: 0.2, spokes: 10, n: 5,
      half: [[-2.37, 0.78], [-2.15, 0.9], [-1.45, 0.935], [0, 0.9], [1.36, 0.945], [2.1, 0.9], [2.37, 0.8]],
      top: [[-2.37, 0.52], [-2.2, 0.64], [-1.5, 0.74], [-0.9, 0.82], [-0.2, 0.86], [1.0, 0.9], [1.7, 0.92], [2.2, 0.9], [2.37, 0.74]],
      house: { z0: -0.95, z1: 1.85, belt: 0.86, roof: [[-0.95, 0.84], [-0.25, 1.19], [0.45, 1.21], [1.85, 0.9]], half: [[-0.95, 0.76], [0, 0.74], [1.0, 0.72], [1.85, 0.66]] },
    },
    details(p, k) {
      p.add(k.paint, box(1.5, 0.045, 0.28, 0, 1.0, 2.16));
      for (const side of [-1, 1]) p.add(k.m.trim, box(0.04, 0.1, 0.12, side * 0.55, 0.94, 2.16));
      for (const side of [-1, 1]) p.add(k.m.chrome, box(0.11, 0.07, 0.04, side * 0.35, 0.3, 2.34));
      for (const side of [-1, 1]) p.add(k.m.trim, box(0.36, 0.02, 0.42, side * 0.3, k.top(-1.15) + 0.005, -1.15)); // bonnet vents
    },
  },
  roadster: {
    paint: PALETTE.paint[2],
    eye: [1.0, 0.1],
    spec: {
      L: HERO_LENGTH, r: 0.32, w: 0.2, front: -1.5, rear: 1.25, sill: 0.25, spokes: 18, n: 4, chromeWheels: true,
      half: [[-2.37, 0.62], [-2.1, 0.8], [-1.5, 0.9], [-0.9, 0.84], [0, 0.86], [1.25, 0.93], [2.0, 0.86], [2.37, 0.68]],
      top: [[-2.37, 0.55], [-2.0, 0.66], [-1.5, 0.76], [-0.8, 0.8], [-0.35, 0.84], [0.2, 0.82], [1.25, 0.86], [2.0, 0.8], [2.37, 0.62]],
      // A raked windscreen only: the house is a thin wedge of glass.
      house: { z0: -0.44, z1: -0.3, belt: 0.84, roof: [[-0.44, 0.84], [-0.3, 1.12]], half: [[-0.44, 0.66], [-0.3, 0.64]], n: 6, glass: true },
    },
    details(p, k) {
      p.add(k.m.interior, box(1.24, 0.05, 1.05, 0, 0.84, 0.22)); // the open cockpit
      for (const side of [-1, 1]) {
        p.add(k.m.leather, box(0.44, 0.1, 0.5, side * 0.32, 0.86, 0.32));
        p.add(k.m.leather, box(0.44, 0.36, 0.09, side * 0.32, 1.0, 0.6));
      }
      // The steering wheel, in front of the left seat.
      p.add(k.m.trim, move(lathe([[0.17, -0.015], [0.19, -0.015], [0.19, 0.015], [0.17, 0.015]], { axis: "z", segments: 22 }), -0.32, 1.04, -0.05));
      for (const z of [-2.35, 2.35]) p.add(k.m.chrome, box(1.5, 0.07, 0.05, 0, 0.36, z));
    },
  },
  rally: {
    paint: PALETTE.paint[0],
    eye: [1.38, 0.3],
    spec: {
      L: HERO_LENGTH, r: 0.37, w: 0.27, front: -1.4, rear: 1.35, sill: 0.46, spokes: 6, n: 4.5,
      half: [[-2.37, 0.82], [-2.1, 0.9], [-1.4, 0.94], [0, 0.92], [1.35, 0.945], [2.1, 0.9], [2.37, 0.84]],
      top: [[-2.37, 0.82], [-2.2, 0.95], [-1.6, 1.02], [-0.8, 1.08], [0.6, 1.12], [2.0, 1.12], [2.37, 1.0]],
      house: { z0: -0.8, z1: 1.95, belt: 1.1, b: 0.62, roof: [[-0.8, 1.08], [-0.15, 1.53], [1.6, 1.54], [1.95, 1.2]], half: [[-0.8, 0.8], [0, 0.78], [1.95, 0.74]] },
    },
    details(p, k) {
      for (const side of [-1, 1]) {
        p.add(k.m.trim, box(0.05, 0.05, 1.5, side * 0.6, 1.6, 0.7)); // roof rack rails
        for (const z of [0.05, 1.35]) p.add(k.m.trim, box(0.05, 0.08, 0.05, side * 0.6, 1.56, z));
        p.add(k.m.trim, box(0.03, 0.34, 0.3, side * 0.78, 0.32, 1.35 + 0.48)); // mud flaps
        p.add(k.m.trim, box(0.03, 0.34, 0.3, side * 0.78, 0.32, -1.4 + 0.48));
        // Livery: two stripes along each flank, in the palette's teal and navy.
        p.add(paintOf(PALETTE.paint[3]), box(0.012, 0.09, 2.6, side * 0.938, 0.92, 0.0));
        p.add(paintOf(PALETTE.paint[4]), box(0.012, 0.05, 2.6, side * 0.938, 0.83, 0.0));
      }
      for (const z of [0.3, 1.1]) p.add(k.m.trim, box(1.3, 0.04, 0.05, 0, 1.62, z));
      // A light pod on a bar across the grille, and a bonnet scoop sitting on the bonnet.
      for (let i = 0; i < 4; i++) p.add(k.m.lens, box(0.15, 0.15, 0.02, -0.39 + i * 0.26, k.top(-2.36) - 0.02, -2.365));
      p.add(k.m.trim, box(1.2, 0.04, 0.04, 0, k.top(-2.36) - 0.1, -2.355));
      p.add(paintOf(PALETTE.paint[4]), box(0.5, 0.07, 0.34, 0, k.top(-1.15) + 0.03, -1.15));
    },
  },
};

export function buildHero(model = "gt") {
  const def = HERO[model] || HERO.gt;
  const k = carBody(def.spec, def.paint);
  addParts(k.group, (p) => def.details(p, k));
  k.group.name = `semif-hero-${model}`;
  k.group.userData.eyeHeight = def.eye[0];
  k.group.userData.eyeForward = def.eye[1];
  k.group.userData.model = model;
  return k.group;
}

// --- traffic ---------------------------------------------------------------------------------

const TL = TRAFFIC_LENGTH;
const TRAFFIC = {
  hatch: {
    L: TL, r: 0.31, w: 0.2, front: -1.32, rear: 1.24, sill: 0.26,
    half: [[-2.09, 0.78], [-1.8, 0.86], [0, 0.87], [1.8, 0.86], [2.09, 0.8]],
    top: [[-2.09, 0.62], [-1.9, 0.74], [-1.2, 0.86], [-0.6, 0.92], [1.6, 0.98], [2.09, 0.92]],
    house: { z0: -0.7, z1: 1.98, belt: 0.95, b: 0.55, roof: [[-0.7, 0.92], [-0.05, 1.45], [1.6, 1.46], [1.98, 1.0]], half: [[-0.7, 0.74], [0, 0.72], [1.98, 0.68]] },
  },
  sedan: {
    L: TL, r: 0.31, w: 0.2, front: -1.35, rear: 1.3, sill: 0.25,
    half: [[-2.09, 0.78], [-1.8, 0.86], [0, 0.88], [1.8, 0.86], [2.09, 0.8]],
    top: [[-2.09, 0.6], [-1.2, 0.82], [-0.6, 0.88], [1.1, 0.92], [1.8, 0.96], [2.09, 0.86]],
    house: { z0: -0.6, z1: 1.35, belt: 0.9, b: 0.35, roof: [[-0.6, 0.88], [0, 1.42], [0.75, 1.43], [1.35, 0.95]], half: [[-0.6, 0.74], [0, 0.72], [1.35, 0.68]] },
  },
  wagon: {
    L: TL, r: 0.31, w: 0.2, front: -1.35, rear: 1.3, sill: 0.25,
    half: [[-2.09, 0.78], [-1.8, 0.86], [0, 0.88], [1.8, 0.87], [2.09, 0.82]],
    top: [[-2.09, 0.6], [-1.2, 0.82], [-0.6, 0.88], [1.8, 0.95], [2.09, 0.9]],
    house: { z0: -0.6, z1: 2.0, belt: 0.92, b: 0.45, roof: [[-0.6, 0.9], [0, 1.45], [1.75, 1.44], [2.0, 1.05]], half: [[-0.6, 0.74], [0, 0.72], [2.0, 0.7]] },
  },
  suv: {
    L: TL, r: 0.37, w: 0.24, front: -1.32, rear: 1.3, sill: 0.42, n: 5.5,
    half: [[-2.09, 0.82], [-1.8, 0.9], [0, 0.92], [1.8, 0.9], [2.09, 0.84]],
    top: [[-2.09, 0.82], [-1.6, 1.0], [-0.7, 1.08], [2.09, 1.12]],
    house: { z0: -0.75, z1: 2.0, belt: 1.12, b: 0.55, roof: [[-0.75, 1.08], [-0.1, 1.72], [1.75, 1.72], [2.0, 1.2]], half: [[-0.75, 0.8], [0, 0.78], [2.0, 0.76]] },
  },
  van: {
    L: TL, r: 0.32, w: 0.22, front: -1.4, rear: 1.4, sill: 0.3, n: 7,
    half: [[-2.09, 0.84], [-1.8, 0.9], [0, 0.91], [2.09, 0.9]],
    top: [[-2.09, 0.75], [-1.7, 1.0], [-1.25, 1.05], [2.09, 1.05]],
    house: { z0: -1.3, z1: -0.05, belt: 1.05, roof: [[-1.3, 1.05], [-0.6, 1.92], [-0.05, 1.92]], half: [[-1.3, 0.84], [-0.05, 0.84]], n: 6 },
  },
  pickup: {
    L: TL, r: 0.35, w: 0.24, front: -1.4, rear: 1.3, sill: 0.4, n: 6,
    half: [[-2.09, 0.84], [-1.8, 0.9], [0, 0.91], [2.09, 0.9]],
    top: [[-2.09, 0.8], [-1.5, 0.98], [-0.65, 1.0], [0.38, 1.0], [0.48, 0.72], [2.09, 0.72]],
    house: { z0: -0.65, z1: 0.36, belt: 1.02, roof: [[-0.65, 1.0], [-0.1, 1.62], [0.25, 1.62], [0.36, 1.05]], half: [[-0.65, 0.8], [0.36, 0.78]] },
  },
};

export function buildTraffic(kind, paintColour) {
  const spec = TRAFFIC[kind] || TRAFFIC.sedan;
  const k = carBody(spec, paintColour);
  if (kind === "van") {
    // The cargo box: painted, no side glass.
    addParts(k.group, (p) => p.add(k.paint, loft({ z0: -0.05, z1: 2.07, half: () => 0.88, bottom: () => 1.0, top: () => 1.9, n: 8, step: 0.15 })));
  } else if (kind === "pickup") {
    addParts(k.group, (p) => {
      for (const side of [-1, 1]) p.add(k.paint, box(0.06, 0.32, 1.58, side * 0.85, 0.88, 1.27));
      p.add(k.paint, box(1.76, 0.32, 0.06, 0, 0.88, 2.05));
      p.add(k.m.trim, box(1.64, 0.02, 1.55, 0, 0.73, 1.27));
    });
  }
  k.group.name = `semif-traffic-${kind}`;
  k.group.userData.eyeHeight = (spec.house ? spec.house.belt : 1) + 0.3;
  k.group.userData.eyeForward = 0.2;
  return k.group;
}

export function buildMotorcycle(paintColour) {
  const m = mats();
  const paint = paintOf(paintColour);
  const group = new T.Group();
  group.name = "semif-traffic-motorcycle";
  const r = 0.31, w = 0.11;
  for (const [name, z] of [["moto_wheel_f", -0.8], ["moto_wheel_r", 0.82]]) {
    const pivot = wheel(name, { x: 0.001, z, r, w, spokes: 5, front: z < 0 }, m);
    group.add(pivot);
  }
  const p = new Parts();
  p.add(m.trim, box(0.12, 0.12, 1.25, 0, 0.5, 0.0)); // frame
  p.add(m.trim, box(0.26, 0.3, 0.42, 0, 0.42, 0.05)); // engine
  p.add(m.chrome, box(0.08, 0.08, 0.7, 0.16, 0.32, 0.55)); // exhaust
  p.add(paint, loft({ z0: -0.45, z1: 0.05, half: curve([[-0.45, 0.12], [-0.2, 0.17], [0.05, 0.13]]), bottom: () => 0.7, top: curve([[-0.45, 0.88], [-0.25, 0.95], [0.05, 0.86]]), n: 3, step: 0.05 })); // tank
  p.add(m.leather, box(0.26, 0.08, 0.6, 0, 0.84, 0.35)); // seat
  p.add(paint, box(0.22, 0.05, 0.5, 0, 0.73, 0.85)); // rear fender
  p.add(paint, box(0.16, 0.04, 0.42, 0, r * 2 + 0.06, -0.85)); // front fender
  p.add(m.trim, box(0.05, 0.6, 0.05, 0, 0.75, -0.72)); // fork
  p.add(m.trim, box(0.76, 0.035, 0.035, 0, 1.06, -0.58)); // handlebars
  p.add(m.lens, box(0.16, 0.13, 0.02, 0, 0.92, -1.14)); // headlight
  p.add(m.tail, box(0.12, 0.05, 0.02, 0, 0.8, 1.14));
  // The rider: helmet in the bike's paint, a jacket and trousers from the people's palette.
  const P = PALETTE.people;
  const jacket = material(P.top[1], { roughness: 0.8 }), trousers = material(P.bottom[0], { roughness: 0.85 });
  p.add(jacket, box(0.36, 0.5, 0.26, 0, 1.2, 0.25));
  p.add(trousers, box(0.34, 0.16, 0.42, 0, 0.92, 0.32));
  for (const side of [-1, 1]) {
    p.add(trousers, box(0.11, 0.42, 0.12, side * 0.17, 0.66, 0.1));
    p.add(jacket, box(0.09, 0.09, 0.5, side * 0.24, 1.2, -0.1));
  }
  p.add(paint, lathe([[0.001, 1.43], [0.12, 1.47], [0.15, 1.57], [0.12, 1.67], [0.001, 1.7]], { axis: "y", segments: 16 }));
  const body = new T.Group();
  body.name = "body";
  body.add(...p.meshes());
  group.add(body);
  group.userData.wheelbase = 1.62;
  group.userData.eyeHeight = 1.5;
  group.userData.eyeForward = 0;
  return group;
}

// Which model and paint a sim car gets: fixed per car id.
export function trafficLook(car) {
  const h = hash(String(car.id));
  const kind = car.type === "motorcycle" ? "motorcycle" : TRAFFIC_KINDS[h % TRAFFIC_KINDS.length];
  return { kind, paint: PALETTE.paint[(h >>> 4) % PALETTE.paint.length] };
}

export function buildTrafficFor(car) {
  const look = trafficLook(car);
  return look.kind === "motorcycle" ? buildMotorcycle(look.paint) : buildTraffic(look.kind, look.paint);
}
