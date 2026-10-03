// Graphics quality on the coast: two tiers (docs/superpowers/specs/2026-10-03-visual-quality-design.md §4).
// Medium is the world as it was before the tiers; high is the refined one. The onboard cameras
// render the same scene, so they see whichever world the driver picked.
export const QUALITIES = ["medium", "high"];
const KEY = "semif-gfx";

// Integrated and mobile GPUs start on medium; so does a browser that hides the GPU's name.
const DISCRETE_INTEL = /intel.*\barc\b/i;
const INTEGRATED = /intel|radeon(\(tm\))? graphics|radeon vega|adreno|mali|powervr|apple (gpu|m\d)|swiftshader|llvmpipe|basic render/i;

export function classifyGpu(name) {
  if (!name) return "medium";
  if (DISCRETE_INTEL.test(name)) return "high";
  return INTEGRATED.test(name) ? "medium" : "high";
}

export function resolveQuality({ search = "", storage = null, gpuName = "" } = {}) {
  const asked = new URLSearchParams(search).get("gfx");
  if (QUALITIES.includes(asked)) return { quality: asked, source: "url" };
  try {
    const saved = storage?.getItem(KEY);
    if (QUALITIES.includes(saved)) return { quality: saved, source: "saved" };
  } catch (_) {}
  return { quality: classifyGpu(gpuName), source: "gpu" };
}

export function saveQuality(storage, quality) {
  try {
    storage?.setItem(KEY, quality);
    return true;
  } catch (_) {
    return false;
  }
}

// The URL outranks the saved choice, so a switch rewrites ?gfx= and keeps everything else.
export function switchUrl(href, quality) {
  const url = new URL(href);
  url.searchParams.set("gfx", quality);
  return url.toString();
}

export function rendererName(gl) {
  try {
    const ext = gl?.getExtension?.("WEBGL_debug_renderer_info");
    return String((ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl?.getParameter?.(gl.RENDERER)) || "");
  } catch (_) {
    return "";
  }
}

export const gfx = { quality: null, source: null };
if (globalThis.window) globalThis.window.SEMIF_GFX = gfx;

// Decided once per page: a rebuilt coast (New layout) keeps the quality the page started with.
export function settleQuality(gl) {
  if (gfx.quality) return gfx;
  let storage = null;
  try {
    storage = globalThis.localStorage ?? null;
  } catch (_) {}
  Object.assign(gfx, resolveQuality({ search: globalThis.location?.search || "", storage, gpuName: rendererName(gl) }));
  return gfx;
}

// One hint, the first time the main view stays below `fps` for `seconds` in a row.
export function createSlowWatch({ fps = 27, seconds = 5 } = {}) {
  let since = null;
  let raised = false;
  return {
    push(current, now) {
      if (raised) return false;
      if (current >= fps) {
        since = null;
        return false;
      }
      since ??= now;
      if (now - since < seconds) return false;
      raised = true;
      return true;
    },
  };
}
