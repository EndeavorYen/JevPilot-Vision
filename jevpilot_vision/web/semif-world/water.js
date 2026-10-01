// The sea: a surface over every part of the ground grid that dips below sea level, shaded by its
// depth (turquoise shallows, deep blue offshore), with moving wave normals, the sky reflected at
// grazing angles, the sun's glitter and surf at the shore; and one deep sheet out to the horizon.
import { PALETTE, T } from "./kit.js";
import { SEA_LEVEL } from "./heights.js";

export { SEA_LEVEL };

const HORIZON = 8000;

const VERTEX = /* glsl */ `
attribute float aDepth;
varying vec3 vWorld;
varying float vDepth;
#include <fog_pars_vertex>
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorld = world.xyz;
  vDepth = aDepth;
  vec4 mvPosition = viewMatrix * world;
  gl_Position = projectionMatrix * mvPosition;
  #include <fog_vertex>
}`;

const FRAGMENT = /* glsl */ `
uniform float uTime;
uniform vec3 uSunDir;
uniform vec3 uSun;
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uDeep;
uniform vec3 uShallow;
uniform vec3 uFoam;
varying vec3 vWorld;
varying float vDepth;
#include <fog_pars_fragment>

// Height of the swell: a few travelling waves of different lengths and directions.
float swell(vec2 p) {
  float t = uTime;
  return 0.22 * sin(dot(p, vec2(0.040, 0.021)) + t * 0.9)
       + 0.15 * sin(dot(p, vec2(-0.027, 0.052)) + t * 1.15)
       + 0.08 * sin(dot(p, vec2(0.11, -0.07)) + t * 1.9)
       + 0.05 * sin(dot(p, vec2(-0.19, -0.13)) + t * 2.6)
       + 0.03 * sin(dot(p, vec2(0.37, 0.29)) + t * 3.7);
}

void main() {
  vec2 p = vWorld.xz;
  float e = 0.35;
  vec3 n = normalize(vec3(swell(p - vec2(e, 0.0)) - swell(p + vec2(e, 0.0)), 2.0 * e, swell(p - vec2(0.0, e)) - swell(p + vec2(0.0, e))));
  vec3 v = normalize(cameraPosition - vWorld);
  float fresnel = 0.03 + 0.85 * pow(1.0 - max(dot(n, v), 0.0), 5.0);
  vec3 r = reflect(-v, n);
  vec3 sky = mix(uHorizon, uZenith, pow(clamp(r.y, 0.0, 1.0), 0.5));
  float shallow = 1.0 - smoothstep(0.0, 7.0, vDepth);
  vec3 body = mix(uDeep, uShallow, shallow) * (0.55 + 0.45 * clamp(uSunDir.y * 1.6, 0.0, 1.0));
  vec3 col = mix(body, sky, fresnel);
  vec3 h = normalize(normalize(uSunDir) + v);
  col += uSun * pow(max(dot(n, h), 0.0), 260.0) * 2.5;
  float surf = (1.0 - smoothstep(0.0, 1.1, vDepth)) * (0.55 + 0.45 * sin(uTime * 1.4 + p.x * 0.17 + p.y * 0.13));
  col = mix(col, uFoam, clamp(surf, 0.0, 1.0) * 0.75);
  gl_FragColor = vec4(col, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
  #include <fog_fragment>
}`;

function seaMaterial() {
  const uniforms = {
    uTime: { value: 0 },
    uSunDir: { value: new T.Vector3(0, 1, 0) },
    uSun: { value: new T.Color("#ffffff") },
    uZenith: { value: new T.Color("#ffffff") },
    uHorizon: { value: new T.Color("#ffffff") },
    uDeep: { value: new T.Color(PALETTE.sea.deep) },
    uShallow: { value: new T.Color(PALETTE.sea.shallow) },
    uFoam: { value: new T.Color(PALETTE.sea.foam) },
    fogColor: { value: new T.Color("#ffffff") },
    fogNear: { value: 1 },
    fogFar: { value: 2000 },
    fogDensity: { value: 0 },
  };
  return new T.ShaderMaterial({ uniforms, vertexShader: VERTEX, fragmentShader: FRAGMENT, fog: true });
}

// The sea over the ground grid (terrain.js hands over its axes and heights), plus a deep sheet
// out to the horizon just below it.
export function buildSea(grid) {
  const { xs, zs, heights } = grid;
  const nx = xs.length, nz = zs.length;
  const wet = (k) => heights[k] < SEA_LEVEL + 0.5;
  const positions = [], depth = [], index = [], slot = new Int32Array(nx * nz).fill(-1);
  const vertex = (k) => {
    if (slot[k] < 0) {
      slot[k] = positions.length / 3;
      positions.push(xs[k % nx], SEA_LEVEL, zs[Math.floor(k / nx)]);
      depth.push(Math.max(0, SEA_LEVEL - heights[k]));
    }
    return slot[k];
  };
  for (let j = 0; j < nz - 1; j++) {
    for (let i = 0; i < nx - 1; i++) {
      const a = j * nx + i, b = a + 1, c = a + nx + 1, d = a + nx;
      if (!(wet(a) || wet(b) || wet(c) || wet(d))) continue;
      index.push(vertex(a), vertex(d), vertex(c), vertex(a), vertex(c), vertex(b));
    }
  }
  const material = seaMaterial();
  const geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
  geo.setAttribute("aDepth", new T.Float32BufferAttribute(depth, 1));
  geo.setIndex(index);
  const near = new T.Mesh(geo, material);
  near.name = "semif-sea-near";

  const far = new T.BufferGeometry();
  const y = SEA_LEVEL - 0.08;
  far.setAttribute("position", new T.Float32BufferAttribute([-HORIZON, y, -HORIZON, -HORIZON, y, HORIZON, HORIZON, y, HORIZON, HORIZON, y, -HORIZON], 3));
  far.setAttribute("aDepth", new T.Float32BufferAttribute([40, 40, 40, 40], 1));
  far.setIndex([0, 1, 2, 0, 2, 3]);
  const sheet = new T.Mesh(far, material);
  sheet.name = "semif-sea-far";

  const group = new T.Group();
  group.name = "semif-sea";
  group.add(near, sheet);
  group.userData.material = material;
  return group;
}

let elapsed = 0;

export function updateSea(sea, light, sunDir, dt) {
  if (!sea) return;
  elapsed += dt || 0;
  const u = sea.userData.material.uniforms;
  u.uTime.value = elapsed;
  u.uSunDir.value.set(sunDir.x, sunDir.y, sunDir.z);
  u.uSun.value.set(light.sun);
  u.uZenith.value.set(light.zenith);
  u.uHorizon.value.set(light.horizon);
}
