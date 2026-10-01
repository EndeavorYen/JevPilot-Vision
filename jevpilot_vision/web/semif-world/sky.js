// Sky dome and the day's light on the scene: sun, sky light, fog and exposure, from daylight.js.
import { T } from "./kit.js";
import { lightAt, sunDirection } from "./daylight.js";

const DOME_RADIUS = 2400;
const SUN_DISTANCE = 300;
const SHADOW_HALF = 130; // long low-sun shadows need a wider shadow camera than the bundle's 65 m
const BACK_SIDE = 1;

const VERTEX = /* glsl */ `
varying vec3 vDir;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vDir = world.xyz - cameraPosition;
  gl_Position = projectionMatrix * viewMatrix * world;
  gl_Position.z = gl_Position.w; // on the far plane, behind everything
}`;

// Gradient from horizon to zenith, sun disc and halo, and drifting fair-weather clouds.
const FRAGMENT = /* glsl */ `
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uGlow;
uniform vec3 uSun;
uniform vec3 uSunDir;
uniform float uTime;
varying vec3 vDir;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= 0.5; }
  return v;
}

void main() {
  vec3 d = normalize(vDir);
  float up = clamp(d.y, 0.0, 1.0);
  vec3 col = mix(uHorizon, uZenith, pow(up, 0.55));
  col = mix(col, uHorizon * 0.9, smoothstep(0.0, -0.1, d.y));
  float c = max(dot(d, normalize(uSunDir)), 0.0);
  col += uGlow * (pow(c, 6.0) * 0.28 + pow(c, 48.0) * 0.55) * (1.0 - 0.5 * up);
  col += uSun * smoothstep(0.99935, 0.99965, c) * 8.0;
  if (d.y > 0.0) {
    vec2 uv = d.xz / (d.y + 0.16) * 1.4 + vec2(uTime * 0.006, uTime * 0.002);
    float n = fbm(uv);
    float cover = smoothstep(0.55, 0.8, n) * smoothstep(0.0, 0.14, d.y);
    vec3 lit = mix(uHorizon * 1.15 + 0.08, uGlow * 1.2, pow(c, 4.0) * 0.8);
    vec3 cloud = mix(lit, lit * 0.68, smoothstep(0.62, 0.95, n));
    col = mix(col, cloud, cover * 0.9);
  }
  gl_FragColor = vec4(col, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

export function buildSky() {
  const uniforms = {
    uZenith: { value: new T.Color("#ffffff") },
    uHorizon: { value: new T.Color("#ffffff") },
    uGlow: { value: new T.Color("#ffffff") },
    uSun: { value: new T.Color("#ffffff") },
    uSunDir: { value: new T.Vector3(0, 1, 0) },
    uTime: { value: 0 },
  };
  const material = new T.ShaderMaterial({ uniforms, vertexShader: VERTEX, fragmentShader: FRAGMENT, side: BACK_SIDE, depthWrite: false, fog: false });
  const mesh = new T.Mesh(new T.SphereGeometry(DOME_RADIUS, 48, 24), material);
  mesh.name = "semif-sky";
  mesh.frustumCulled = false;
  mesh.renderOrder = -1;
  return mesh;
}

export function widenShadows(sun) {
  Object.assign(sun.shadow.camera, { left: -SHADOW_HALF, right: SHADOW_HALF, top: SHADOW_HALF, bottom: -SHADOW_HALF, near: 1, far: 700 });
  sun.shadow.camera.updateProjectionMatrix();
}

export function placeSun(sun, player, hours) {
  const d = sunDirection(hours);
  sun.position.set(player.x + d.x * SUN_DISTANCE, d.y * SUN_DISTANCE, player.z + d.z * SUN_DISTANCE);
  sun.target.position.set(player.x, 0, player.z);
}

let elapsed = 0;

export function applyLight(view, sky, hours, dt) {
  const L = lightAt(hours);
  const scene = view.scene;
  view.renderer.toneMappingExposure = L.exposure;
  view.sun.color.set(L.sun);
  view.sun.intensity = L.sunIntensity;
  const hemi = scene.children.find((c) => c.isHemisphereLight);
  if (hemi) {
    hemi.color.set(L.hemiSky);
    hemi.groundColor.set(L.hemiGround);
    hemi.intensity = L.hemiIntensity;
  }
  if (scene.fog) {
    scene.fog.color.set(L.fog);
    scene.fog.near = 350;
    scene.fog.far = 2600;
  }
  // The dome is the background; the bundle's daylight HDR stays only as the reflection map.
  scene.background = null;
  scene.environmentIntensity = L.envIntensity;
  if (sky) {
    elapsed += dt || 0;
    const u = sky.material.uniforms;
    u.uZenith.value.set(L.zenith);
    u.uHorizon.value.set(L.horizon);
    u.uGlow.value.set(L.glow);
    u.uSun.value.set(L.sun);
    const d = sunDirection(hours);
    u.uSunDir.value.set(d.x, d.y, d.z);
    u.uTime.value = elapsed;
    if (view.camera?.position) sky.position.copy(view.camera.position);
  }
  return L;
}
