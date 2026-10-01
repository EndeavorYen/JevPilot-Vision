// Ground mesh: one height-field over the map and well beyond it (mountains to the north, sea floor
// to the south), fine near the roads and coarser towards the horizon. Its material blends grass,
// dry grass, rock and sand by the weights heights.js gives each vertex.
import { T, material } from "./kit.js";

const FINE = 6; // metres between vertices over the drivable map
const COARSE = 48; // metres between vertices at the far edge
const CORE = 100; // fine spacing reaches this far past the map's bounds
const REACH = 900; // the ground reaches this far past the bounds

// Vertex positions along one axis: FINE inside [lo, hi], growing to COARSE out to [lo-REACH, hi+REACH].
function axis(lo, hi) {
  const inner = [];
  for (let v = lo - CORE; v <= hi + CORE + 1e-6; v += FINE) inner.push(v);
  const out = (start, dir) => {
    const list = [];
    let v = start, step = FINE;
    while (Math.abs(v - start) < REACH - CORE) {
      step = Math.min(COARSE, step * 1.12);
      v += dir * step;
      list.push(v);
    }
    return list;
  };
  return [...out(inner[0], -1).reverse(), ...inner, ...out(inner.at(-1), 1)];
}

// Texture layers: Poly Haven CC0 maps (textures/LICENSE.md), tinted to Mediterranean tones and
// lifted so shaded ground stays clear of the camera's dark "pedestrian" mask. The grass and rock
// maps have little blue; desaturated and tinted towards olive-grey and limestone, sunlit ground
// cannot turn into the camera's orange "construction" colour.
const LAYERS = [
  { file: "grass-color.jpg", scale: 9, tint: [0.92, 1.0, 1.28], saturation: 0.65 },
  { file: "dry-color.jpg", scale: 4.5, tint: [1.1, 1.12, 1.18], saturation: 0.8 },
  { file: "rock-color.jpg", scale: 9, tint: [1.7, 1.74, 1.9], saturation: 0.45 },
  { file: "sand-color.jpg", scale: 7, tint: [1.42, 1.4, 1.36] },
];

let textures = null;
function layerTextures() {
  if (textures) return textures;
  const loader = new T.TextureLoader();
  textures = LAYERS.map((layer) => {
    const t = loader.load(`/jevpilot/textures/${layer.file}`);
    t.wrapS = t.wrapT = T.RepeatWrapping;
    t.colorSpace = T.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
  });
  return textures;
}

function splatMaterial() {
  const mat = material("#ffffff", { roughness: 0.96 });
  if (mat.userData.splat) return mat;
  mat.userData.splat = true;
  const maps = layerTextures();
  mat.onBeforeCompile = (shader) => {
    LAYERS.forEach((layer, i) => {
      shader.uniforms[`tLayer${i}`] = { value: maps[i] };
    });
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nattribute vec4 aSplat;\nvarying vec4 vSplat;\nvarying vec3 vWorld;\nvarying vec3 vWorldNormal;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvSplat = aSplat;\nvWorld = (modelMatrix * vec4(position, 1.0)).xyz;\nvWorldNormal = normalize(mat3(modelMatrix) * normal);");
    const tone = (l, read) => `tone(${read}, ${(l.saturation ?? 1).toFixed(2)}, vec3(${l.tint.map((v) => v.toFixed(3)).join(", ")}))`;
    const sample = LAYERS.map((l, i) => `vec3 c${i} = ${tone(l, `texture2D(tLayer${i}, vWorld.xz / ${l.scale.toFixed(1)}).rgb`)};`).join("\n");
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>\n${LAYERS.map((_, i) => `uniform sampler2D tLayer${i};`).join("\n")}\nvarying vec4 vSplat;\nvarying vec3 vWorld;\nvarying vec3 vWorldNormal;\nvec3 tone(vec3 c, float saturation, vec3 tint) { return mix(vec3(dot(c, vec3(0.2126, 0.7152, 0.0722))), c, saturation) * tint; }`,
      )
      .replace(
        "#include <map_fragment>",
        `${sample}
        // Rock on steep faces is projected from the side, so cliffs do not smear.
        vec3 n = abs(normalize(vWorldNormal));
        vec3 rockSide = (texture2D(tLayer2, vWorld.xy / 9.0).rgb * n.z + texture2D(tLayer2, vWorld.zy / 9.0).rgb * n.x) / max(n.x + n.z, 0.001);
        c2 = mix(c2, ${tone(LAYERS[2], "rockSide")}, smoothstep(0.35, 0.75, 1.0 - n.y));
        vec3 ground = c0 * vSplat.x + c1 * vSplat.y + c2 * vSplat.z + c3 * vSplat.w;
        // Broad patches break up the tiling.
        float patches = texture2D(tLayer1, vWorld.xz / 173.0).g;
        ground *= 0.86 + 0.28 * patches;
        diffuseColor.rgb *= ground;`,
      );
  };
  return mat;
}

export function buildTerrain(world, field) {
  const xs = axis(world.bounds.minX, world.bounds.maxX);
  const zs = axis(world.bounds.minZ, world.bounds.maxZ);
  const nx = xs.length, nz = zs.length;
  const positions = new Float32Array(nx * nz * 3);
  const splat = new Float32Array(nx * nz * 4);
  const heights = new Float32Array(nx * nz);
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) heights[j * nx + i] = field.heightAt(xs[i], zs[j]);
  }
  for (let j = 0; j < nz; j++) {
    for (let i = 0; i < nx; i++) {
      const k = j * nx + i;
      positions.set([xs[i], heights[k], zs[j]], k * 3);
      // Slope from the neighbouring vertices; near the map the field weighs the surface itself.
      const i0 = Math.max(0, i - 1), i1 = Math.min(nx - 1, i + 1), j0 = Math.max(0, j - 1), j1 = Math.min(nz - 1, j + 1);
      const gx = (heights[j * nx + i1] - heights[j * nx + i0]) / (xs[i1] - xs[i0]);
      const gz = (heights[j1 * nx + i] - heights[j0 * nx + i]) / (zs[j1] - zs[j0]);
      const far = xs[i] < world.bounds.minX - CORE || xs[i] > world.bounds.maxX + CORE || zs[j] < world.bounds.minZ - CORE || zs[j] > world.bounds.maxZ + CORE;
      if (!far) {
        splat.set(field.weights(xs[i], zs[j], heights[k], Math.hypot(gx, gz)), k * 4);
        continue;
      }
      const rock = Math.min(1, Math.max(0, (Math.hypot(gx, gz) - 0.5) / 0.4));
      const sand = heights[k] < -9 ? 1 - rock : 0;
      splat.set([(1 - rock - sand) * 0.45, (1 - rock - sand) * 0.55, rock, sand], k * 4);
    }
  }
  const index = [];
  for (let j = 0; j < nz - 1; j++) {
    for (let i = 0; i < nx - 1; i++) {
      const a = j * nx + i, b = a + 1, c = a + nx + 1, d = a + nx;
      index.push(a, d, c, a, c, b);
    }
  }
  const geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
  geo.setAttribute("aSplat", new T.Float32BufferAttribute(splat, 4));
  geo.setIndex(index);
  geo.computeVertexNormals();
  const mesh = new T.Mesh(geo, splatMaterial());
  mesh.name = "semif-terrain";
  mesh.userData.grid = { xs, zs, heights }; // the sea is laid over the same grid
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  return mesh;
}
