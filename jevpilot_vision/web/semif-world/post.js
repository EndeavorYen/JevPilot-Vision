// Post-processing for the main view only: the scene into an HDR target, bloom from its bright
// parts, then one pass to the screen with tone mapping, the time of day's grade and a vignette.
// The onboard cameras render to their own targets (semif-layer.js) and never come through here,
// so what the vision pipeline sees is unchanged.
import { T } from "./kit.js";

const HALF_FLOAT = 1016;
const LINEAR = 1006;
const LEVELS = 3; // bloom at 1/2, 1/4 and 1/8 size

const QUAD_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

const BRIGHT = /* glsl */ `
uniform sampler2D tInput;
uniform float uThreshold;
varying vec2 vUv;
void main() {
  vec3 c = texture2D(tInput, vUv).rgb;
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  float k = smoothstep(uThreshold, uThreshold * 1.8, l);
  gl_FragColor = vec4(c * k, 1.0);
}`;

const BLUR = /* glsl */ `
uniform sampler2D tInput;
uniform vec2 uStep;
varying vec2 vUv;
void main() {
  vec3 c = texture2D(tInput, vUv).rgb * 0.227027;
  c += (texture2D(tInput, vUv + uStep * 1.384615).rgb + texture2D(tInput, vUv - uStep * 1.384615).rgb) * 0.316216;
  c += (texture2D(tInput, vUv + uStep * 3.230769).rgb + texture2D(tInput, vUv - uStep * 3.230769).rgb) * 0.070270;
  gl_FragColor = vec4(c, 1.0);
}`;

const COMPOSITE = /* glsl */ `
uniform sampler2D tScene;
uniform sampler2D tBloom0;
uniform sampler2D tBloom1;
uniform sampler2D tBloom2;
uniform float uExposure;
uniform float uBloom;
uniform float uWarmth;
uniform float uContrast;
uniform float uSaturation;
uniform float uVignette;
varying vec2 vUv;

vec3 aces(vec3 x) {
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

void main() {
  vec3 hdr = texture2D(tScene, vUv).rgb;
  vec3 bloom = texture2D(tBloom0, vUv).rgb * 0.5 + texture2D(tBloom1, vUv).rgb * 0.3 + texture2D(tBloom2, vUv).rgb * 0.2;
  hdr += bloom * uBloom;
  hdr *= vec3(1.0 + uWarmth, 1.0 + uWarmth * 0.25, 1.0 - uWarmth * 0.6);
  vec3 c = aces(hdr * uExposure * 0.78);
  c = (c - 0.5) * uContrast + 0.5;
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c = mix(vec3(l), c, uSaturation);
  vec2 d = vUv - 0.5;
  c *= 1.0 - uVignette * smoothstep(0.25, 0.75, dot(d, d) * 1.8);
  gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
  #include <colorspace_fragment>
}`;

function pass(fragmentShader, uniforms) {
  return new T.ShaderMaterial({ uniforms, vertexShader: QUAD_VERTEX, fragmentShader, depthTest: false, depthWrite: false, toneMapped: false });
}

const target = (w, h, samples = 0) => new T.WebGLRenderTarget(w, h, { type: HALF_FLOAT, minFilter: LINEAR, magFilter: LINEAR, samples });

export function createPost() {
  const size = new T.Vector2();
  const camera = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const quad = new T.Mesh(new T.PlaneGeometry(2, 2), null);
  quad.frustumCulled = false;
  const bright = pass(BRIGHT, { tInput: { value: null }, uThreshold: { value: 1.1 } });
  const blur = pass(BLUR, { tInput: { value: null }, uStep: { value: new T.Vector2() } });
  const composite = pass(COMPOSITE, {
    tScene: { value: null }, tBloom0: { value: null }, tBloom1: { value: null }, tBloom2: { value: null },
    uExposure: { value: 1 }, uBloom: { value: 0.6 }, uWarmth: { value: 0 }, uContrast: { value: 1 }, uSaturation: { value: 1 }, uVignette: { value: 0.2 },
  });
  let scene = null, levels = [], w = 0, h = 0;

  function resize(renderer) {
    renderer.getDrawingBufferSize(size);
    if (size.x === w && size.y === h) return;
    w = size.x;
    h = size.y;
    scene?.dispose();
    for (const l of levels) l.forEach((t) => t.dispose());
    scene = target(w, h, 4);
    levels = Array.from({ length: LEVELS }, (_, i) => {
      const lw = Math.max(1, Math.round(w / 2 ** (i + 1))), lh = Math.max(1, Math.round(h / 2 ** (i + 1)));
      return [target(lw, lh), target(lw, lh)];
    });
  }

  function draw(renderer, material, out) {
    quad.material = material;
    renderer.setRenderTarget(out);
    renderer.render(quad, camera);
  }

  return {
    // grade: daylight.gradeAt(hours)
    render(view, grade) {
      const renderer = view.renderer;
      resize(renderer);
      renderer.setRenderTarget(scene);
      renderer.render(view.scene, view.camera);
      let input = scene.texture;
      for (const [a, b] of levels) {
        if (input === scene.texture) {
          bright.uniforms.tInput.value = input;
          draw(renderer, bright, a);
        } else {
          blur.uniforms.tInput.value = input;
          blur.uniforms.uStep.value.set(0, 0);
          draw(renderer, blur, a);
        }
        blur.uniforms.tInput.value = a.texture;
        blur.uniforms.uStep.value.set(1 / a.width, 0);
        draw(renderer, blur, b);
        blur.uniforms.tInput.value = b.texture;
        blur.uniforms.uStep.value.set(0, 1 / a.height);
        draw(renderer, blur, a);
        input = a.texture;
      }
      const u = composite.uniforms;
      u.tScene.value = scene.texture;
      levels.forEach(([a], i) => (u[`tBloom${i}`].value = a.texture));
      u.uExposure.value = grade.exposure;
      u.uBloom.value = grade.bloom;
      u.uWarmth.value = grade.warmth;
      u.uContrast.value = grade.contrast;
      u.uSaturation.value = grade.saturation;
      u.uVignette.value = grade.vignette;
      draw(renderer, composite, null);
    },
  };
}
