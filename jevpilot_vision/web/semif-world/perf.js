// Frame time, GPU time and draw calls of the main view and the onboard cameras, apart
// (docs/superpowers/specs/2026-10-03-visual-quality-design.md §4.4). window.SEMIF_PERF.
// GPU time needs EXT_disjoint_timer_query_webgl2; without it the GPU fields stay null.
const VIEWS = ["main", "onboard"];
// A gap longer than this is a hidden tab or a trip to an old map, not a frame.
const MAX_FRAME_MS = 1000;

export function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const i = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
  return Math.round(sorted[i] * 100) / 100;
}

export function createPerf({ now = () => performance.now(), keep = 600, maxPending = 32 } = {}) {
  let gl = null;
  let ext = null;
  let last = null;
  let active = false;
  let nested = 0;
  let pending = [];
  const frames = [];
  const per = () => Object.fromEntries(VIEWS.map((v) => [v, []]));
  let gpu = per();
  let calls = per();
  let triangles = per();

  const push = (list, v) => {
    list.push(v);
    if (list.length > keep) list.shift();
  };

  function attach(context) {
    gl = context || null;
    ext = gl?.getExtension?.("EXT_disjoint_timer_query_webgl2") || null;
    pending = [];
  }

  function poll() {
    if (!ext || !pending.length) return;
    const disjoint = gl.getParameter(ext.GPU_DISJOINT_EXT);
    pending = pending.filter(([view, q]) => {
      if (!gl.getQueryParameter(q, gl.QUERY_RESULT_AVAILABLE)) return true;
      if (!disjoint) push(gpu[view], gl.getQueryParameter(q, gl.QUERY_RESULT) / 1e6);
      gl.deleteQuery(q);
      return false;
    });
    // A tab in the background or a lost context never answers: keep only the newest few.
    while (pending.length > maxPending) gl.deleteQuery(pending.shift()[1]);
  }

  function frame() {
    const t = now();
    if (last !== null && t - last <= MAX_FRAME_MS) push(frames, t - last);
    last = t;
    poll();
  }

  function span(view, renderer, fn) {
    // WebGL2 allows one TIME_ELAPSED query at a time: a span inside a span runs unmeasured.
    // Draw calls are summed over every render() inside the span (scene and post passes), so
    // autoReset is off for its length and put back after.
    if (active) {
      nested++;
      return fn();
    }
    active = true;
    const info = renderer?.info;
    const autoReset = info?.autoReset;
    if (info) {
      info.autoReset = false;
      info.reset();
    }
    const q = ext ? gl.createQuery() : null;
    if (q) gl.beginQuery(ext.TIME_ELAPSED_EXT, q);
    try {
      return fn();
    } finally {
      if (q) {
        gl.endQuery(ext.TIME_ELAPSED_EXT);
        pending.push([view, q]);
      }
      if (info) {
        push(calls[view], info.render.calls);
        push(triangles[view], info.render.triangles);
        info.autoReset = autoReset;
      }
      active = false;
    }
  }

  const p50 = (lists) => Object.fromEntries(VIEWS.map((v) => [v, percentile(lists[v], 50)]));

  function snapshot() {
    const fps = frames.map((ms) => 1000 / ms);
    return {
      frames: frames.length,
      fps_p50: percentile(fps, 50),
      fps_p5: percentile(fps, 5),
      frame_ms_p50: percentile(frames, 50),
      gpu_timer: !!ext,
      gpu_ms_p50: p50(gpu),
      calls_p50: p50(calls),
      triangles_p50: p50(triangles),
      nested,
    };
  }

  function reset() {
    frames.length = 0;
    last = null;
    nested = 0;
    gpu = per();
    calls = per();
    triangles = per();
  }

  return { attach, frame, span, snapshot, reset };
}

if (globalThis.window) globalThis.window.SEMIF_PERF ??= createPerf();
