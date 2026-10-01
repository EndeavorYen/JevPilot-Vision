// The Solmare Festival on the grounds south of the festival junction: a banner arch over the
// avenue, the main stage with its screen, a village of tents, flags along the avenue, display
// podiums and a Ferris wheel that turns slowly over it all. Everything but the arch's pillars
// stands at least 6 m from a road's edge; colours are PALETTE's (no signal reds or greens).
import { PALETTE, T, Batch, material } from "./kit.js";

const ARCH_Z = 425;
const STAGE = { x: -80, z: 400, w: 34, d: 18 };
const WHEEL = { x: 95, z: 452, radius: 20, hub: 24, cars: 16 };
const PODIUMS = [{ x: 30, z: 472 }, { x: -36, z: 472 }];

function canvasTexture(w, h, draw) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new T.CanvasTexture(c);
  t.colorSpace = T.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

// The festival's mark: a sun over three waves, and the name.
function banner(text) {
  const F = PALETTE.festival;
  return canvasTexture(1024, 192, (g, w, h) => {
    g.fillStyle = F.ink;
    g.fillRect(0, 0, w, h);
    g.fillStyle = F.sand;
    g.beginPath();
    g.arc(110, 120, 52, Math.PI, 0);
    g.fill();
    g.strokeStyle = F.teal;
    g.lineWidth = 10;
    for (let i = 0; i < 3; i++) {
      g.beginPath();
      for (let x = 40; x <= 180; x += 4) g.lineTo(x, 132 + i * 18 + Math.sin(x / 14) * 6);
      g.stroke();
    }
    g.fillStyle = F.white;
    g.font = "bold 92px system-ui, sans-serif";
    g.textBaseline = "middle";
    g.fillText(text, 220, h / 2 + 4);
  });
}

function screenTexture() {
  const F = PALETTE.festival;
  return canvasTexture(512, 256, (g, w, h) => {
    const grad = g.createLinearGradient(0, 0, w, h);
    grad.addColorStop(0, F.purple);
    grad.addColorStop(0.55, F.blue);
    grad.addColorStop(1, F.teal);
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
    g.fillStyle = F.white;
    g.font = "bold 64px system-ui, sans-serif";
    g.textAlign = "center";
    g.fillText("SOLMARE", w / 2, h / 2 - 10);
    g.font = "600 34px system-ui, sans-serif";
    g.fillText("FESTIVAL", w / 2, h / 2 + 44);
  });
}

function mesh(geometry, mat, x, y, z, cast = true) {
  const m = new T.Mesh(geometry, mat);
  m.position.set(x, y, z);
  m.castShadow = cast;
  m.receiveShadow = true;
  return m;
}

function buildArch(y0) {
  const F = PALETTE.festival;
  const group = new T.Group();
  group.name = "semif-festival-arch";
  const frame = material(F.ink, { roughness: 0.6 });
  for (const x of [-8.6, 8.6]) group.add(mesh(new T.BoxGeometry(0.9, 9.4, 0.9), frame, x, y0 + 4.7, ARCH_Z));
  group.add(mesh(new T.BoxGeometry(18.4, 1.2, 1.0), frame, 0, y0 + 9.0, ARCH_Z));
  // Two banners back to back, so the name reads the right way round from either side.
  const face = material("#ffffff", { map: banner("SOLMARE FESTIVAL"), roughness: 0.7 });
  for (const turn of [0, Math.PI]) {
    const sign = new T.Mesh(new T.PlaneGeometry(15, 2.8), face);
    sign.position.set(0, y0 + 7.4, ARCH_Z + (turn ? -0.06 : 0.06));
    sign.rotation.y = turn;
    group.add(sign);
  }
  return group;
}

function buildStage(y0) {
  const F = PALETTE.festival;
  const group = new T.Group();
  group.name = "semif-festival-stage";
  const { x, z, w, d } = STAGE;
  group.add(mesh(new T.BoxGeometry(w, 1.6, d), material(F.ink, { roughness: 0.8 }), x, y0 + 0.8, z));
  const truss = material(PALETTE.guardrail, { metalness: 0.5, roughness: 0.4 });
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) group.add(mesh(new T.BoxGeometry(0.8, 13, 0.8), truss, x + (sx * (w - 2)) / 2, y0 + 6.5, z + (sz * (d - 2)) / 2));
  group.add(mesh(new T.BoxGeometry(w + 1, 0.9, d + 1), truss, x, y0 + 13.2, z));
  group.add(mesh(new T.BoxGeometry(w - 2, 0.4, d - 2), material(F.white, { roughness: 0.9 }), x, y0 + 13.8, z));
  // The screen faces the crowd to the east, towards the avenue.
  const screen = new T.Mesh(new T.PlaneGeometry(14, 7), material("#ffffff", { map: screenTexture(), emissive: "#ffffff", emissiveMap: screenTexture(), emissiveIntensity: 0.35, roughness: 0.4 }));
  screen.position.set(x + w / 2 - 1.2, y0 + 7, z);
  screen.rotation.y = Math.PI / 2;
  group.add(screen);
  return group;
}

function buildTents(y0) {
  const F = PALETTE.festival;
  const walls = new Batch();
  const cones = [];
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 3; j++) {
      const x = 28 + i * 13, z = 288 + j * 22;
      walls.box(x, z, 8, 8, 2.6, y0);
      cones.push([x, z, (i + j) % 2]);
    }
  }
  const group = new T.Group();
  group.name = "semif-festival-tents";
  group.add(walls.mesh(material(F.white, { roughness: 0.9 }), { cast: true }));
  const roofMats = [material(F.white, { roughness: 0.85 }), material(F.teal, { roughness: 0.85 })];
  for (const [x, z, k] of cones) {
    const roof = mesh(new T.ConeGeometry(6.4, 3.4, 4), roofMats[k], x, y0 + 2.6 + 1.7, z);
    roof.rotation.y = Math.PI / 4;
    group.add(roof);
  }
  return group;
}

const wave = { value: 0 };

function flagMaterial(colour) {
  const mat = material(colour, { roughness: 0.8, side: 2 });
  if (mat.userData.wave) return mat;
  mat.userData.wave = true;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uWave = wave;
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nuniform float uWave;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\ntransformed.z += sin(uWave * 3.0 + position.x * 2.4 + position.y) * 0.18 * (position.x + 0.9);");
  };
  return mat;
}

function buildFlags(y0) {
  const F = PALETTE.festival;
  const colours = [F.teal, F.blue, F.purple, F.sand, F.white];
  const group = new T.Group();
  group.name = "semif-festival-flags";
  const pole = material(PALETTE.guardrail, { metalness: 0.4, roughness: 0.5 });
  let k = 0;
  for (let z = 276; z <= 500; z += 18) {
    for (const side of [-1, 1]) {
      const x = side * 13;
      group.add(mesh(new T.CylinderGeometry(0.07, 0.09, 7, 6), pole, x, y0 + 3.5, z, false));
      const cloth = new T.Mesh(new T.PlaneGeometry(1.8, 1.1, 8, 3).translate(0.9, 0, 0), flagMaterial(colours[k++ % colours.length]));
      cloth.position.set(x, y0 + 6.2, z);
      cloth.rotation.y = side > 0 ? 0 : Math.PI;
      group.add(cloth);
    }
  }
  return group;
}

function buildPodiums(y0) {
  const group = new T.Group();
  group.name = "semif-festival-podiums";
  for (const p of PODIUMS) {
    group.add(mesh(new T.CylinderGeometry(5.5, 6, 0.7, 40), material(PALETTE.festival.ink, { roughness: 0.5, metalness: 0.2 }), p.x, y0 + 0.35, p.z));
    group.add(mesh(new T.CylinderGeometry(5.6, 5.6, 0.08, 40), material(PALETTE.festival.white, { roughness: 0.4 }), p.x, y0 + 0.74, p.z, false));
  }
  return group;
}

let wheel = null;

function buildWheel(y0) {
  const F = PALETTE.festival;
  const group = new T.Group();
  group.name = "semif-festival-wheel";
  group.position.set(WHEEL.x, y0, WHEEL.z);
  const steel = material(F.white, { metalness: 0.5, roughness: 0.35 });
  // A-frame legs either side of the wheel's plane.
  for (const side of [-1, 1]) {
    for (const lean of [-1, 1]) {
      const leg = mesh(new T.BoxGeometry(0.7, WHEEL.hub + 1, 0.7), steel, lean * 5.5, WHEEL.hub / 2, side * 2.4);
      leg.rotation.z = lean * -0.22;
      group.add(leg);
    }
  }
  const rim = new T.Group();
  rim.position.set(0, WHEEL.hub, 0);
  const segments = 32;
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    const len = 2 * Math.PI * WHEEL.radius / segments + 0.2;
    for (const side of [-1, 1]) {
      const seg = mesh(new T.BoxGeometry(len, 0.45, 0.45), steel, Math.cos(a) * WHEEL.radius, Math.sin(a) * WHEEL.radius, side * 1.4, false);
      seg.rotation.z = a + Math.PI / 2;
      rim.add(seg);
    }
  }
  for (let i = 0; i < WHEEL.cars; i++) {
    const a = (i / WHEEL.cars) * Math.PI * 2;
    const spoke = mesh(new T.BoxGeometry(WHEEL.radius, 0.22, 0.22), steel, (Math.cos(a) * WHEEL.radius) / 2, (Math.sin(a) * WHEEL.radius) / 2, 0, false);
    spoke.rotation.z = a;
    rim.add(spoke);
  }
  rim.add(mesh(new T.CylinderGeometry(1.2, 1.2, 3.6, 16).rotateX(Math.PI / 2), steel, 0, 0, 0, false));
  const cars = [];
  const carColours = [F.teal, F.blue, F.purple, F.sand];
  for (let i = 0; i < WHEEL.cars; i++) {
    const car = mesh(new T.BoxGeometry(2.2, 2.0, 2.0), material(carColours[i % carColours.length], { roughness: 0.6 }), 0, 0, 0);
    car.userData.angle = (i / WHEEL.cars) * Math.PI * 2;
    cars.push(car);
    group.add(car);
  }
  group.add(rim);
  group.userData.rim = rim;
  group.userData.cars = cars;
  wheel = group;
  placeCars(group);
  return group;
}

// Gondolas hang from the rim and stay upright as it turns.
function placeCars(group) {
  const turn = group.userData.rim.rotation.z;
  for (const car of group.userData.cars) {
    const a = car.userData.angle + turn;
    car.position.set(Math.cos(a) * WHEEL.radius, WHEEL.hub + Math.sin(a) * WHEEL.radius - 1.4, 0);
  }
}

export function buildFestival(world, field, grid) {
  const y0 = grid.heightAt(0, 400);
  const group = new T.Group();
  group.name = "semif-festival";
  group.add(buildArch(grid.heightAt(0, ARCH_Z)), buildStage(y0), buildTents(y0), buildFlags(y0), buildPodiums(y0), buildWheel(grid.heightAt(WHEEL.x, WHEEL.z)));
  return group;
}

export function updateFestival(dt) {
  wave.value += dt || 0;
  if (!wheel) return;
  wheel.userData.rim.rotation.z += (dt || 0) * 0.04; // a turn every two and a half minutes
  placeCars(wheel);
}
