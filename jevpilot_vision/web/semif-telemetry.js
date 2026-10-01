(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.SEMIF_TELEMETRY_CORE = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const LATENCY_WINDOW = 120;
  // The charts read the last minutes by time, apart from the 120-sample ring buffer above.
  const TIMELINE_MS = 15 * 60 * 1000;
  const TIMELINE_CAP = 20000;
  const SERIES_KEYS = ["grab_frame_ms", "vision_encode_ms", "classifier_ms", "e2e_loop_ms"];

  function percentileMs(samples, pct) {
    if (!samples || !samples.length) return null;
    const ordered = samples.map(Number).filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
    if (!ordered.length) return null;
    if (ordered.length === 1) return ordered[0];
    const rank = (Number(pct) / 100) * (ordered.length - 1);
    const lo = Math.floor(rank);
    const hi = Math.ceil(rank);
    if (lo === hi) return ordered[lo];
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo);
  }

  function summarizeLatency(samples) {
    const values = (samples || []).map(Number).filter((x) => Number.isFinite(x));
    const n = values.length;
    if (!n) {
      return {
        n: 0,
        min: null,
        max: null,
        mean: null,
        p50: null,
        p90: null,
        p95: null,
        p99: null,
        stddev: null,
      };
    }
    let sum = 0;
    let min = values[0];
    let max = values[0];
    for (const x of values) {
      sum += x;
      if (x < min) min = x;
      if (x > max) max = x;
    }
    const mean = sum / n;
    let varSum = 0;
    for (const x of values) varSum += (x - mean) * (x - mean);
    return {
      n,
      min,
      max,
      mean,
      p50: percentileMs(values, 50),
      p90: percentileMs(values, 90),
      p95: percentileMs(values, 95),
      p99: percentileMs(values, 99),
      stddev: Math.sqrt(varSum / n),
    };
  }

  function fmt(ms) {
    if (ms == null || !Number.isFinite(ms)) return "—";
    return ms.toFixed(ms >= 100 ? 0 : 1);
  }

  function createLatencyTelemetry(opts) {
    const windowSize = (opts && opts.window) || LATENCY_WINDOW;
    const now = (opts && opts.now) || function () {
      return typeof performance !== "undefined" ? performance.now() : Date.now();
    };
    const series = {};
    const timeline = {};
    for (const key of SERIES_KEYS) {
      series[key] = [];
      timeline[key] = [];
    }
    function push(name, ms) {
      const value = Number(ms);
      if (!Number.isFinite(value) || value < 0) return;
      const t = now();
      const buf = series[name];
      buf.push({ t, ms: value });
      if (buf.length > windowSize) buf.splice(0, buf.length - windowSize);
      const line = timeline[name];
      line.push({ t, ms: value });
      let drop = 0;
      while (drop < line.length && t - line[drop].t > TIMELINE_MS) drop++;
      drop = Math.max(drop, line.length - TIMELINE_CAP);
      if (drop > 0) line.splice(0, drop);
    }

    // Samples of one series from the last `windowMs`, oldest first.
    function getTimeline(name, windowMs) {
      const line = timeline[name] || [];
      const since = now() - Math.min(windowMs, TIMELINE_MS);
      let i = line.length;
      while (i > 0 && line[i - 1].t >= since) i--;
      return line.slice(i).map((row) => ({ t: row.t, ms: row.ms }));
    }

    function summarizeWindow(name, windowMs) {
      return summarizeLatency(getTimeline(name, windowMs).map((row) => row.ms));
    }

    function getHistory() {
      const out = {};
      for (const key of SERIES_KEYS) out[key] = series[key].map((row) => ({ t: row.t, ms: row.ms }));
      return out;
    }

    function getMetrics() {
      const out = {};
      for (const key of SERIES_KEYS) out[key] = summarizeLatency(series[key].map((row) => row.ms));
      return out;
    }

    function hudText() {
      const m = getMetrics();
      const e2e = m.e2e_loop_ms;
      const vis = m.vision_encode_ms;
      const cls = m.classifier_ms;
      const lastE2e = series.e2e_loop_ms.length ? series.e2e_loop_ms[series.e2e_loop_ms.length - 1].ms : null;
      const lastVis = series.vision_encode_ms.length
        ? series.vision_encode_ms[series.vision_encode_ms.length - 1].ms
        : null;
      const lastCls = series.classifier_ms.length
        ? series.classifier_ms[series.classifier_ms.length - 1].ms
        : null;
      return [
        "e2e " + fmt(lastE2e) + "ms",
        "P50 " + fmt(e2e.p50),
        "P95 " + fmt(e2e.p95),
        "vis " + fmt(lastVis) + "/P50 " + fmt(vis.p50),
        "cls " + fmt(lastCls) + "/P50 " + fmt(cls.p50),
      ].join("  ");
    }

    return {
      recordVision: function (sample) {
        const grab = sample && sample.grab_ms;
        if (grab != null) push("grab_frame_ms", grab);
        push("vision_encode_ms", sample && sample.encode_ms);
      },
      recordClassifier: function (sample) {
        push("classifier_ms", sample && sample.classifier_ms);
        push("e2e_loop_ms", sample && sample.rtt_ms);
      },
      getMetrics: getMetrics,
      getHistory: getHistory,
      getTimeline: getTimeline,
      summarizeWindow: summarizeWindow,
      exportJSON: function () {
        return {
          schema: "semif.web_latency.v1",
          window: windowSize,
          generated_at_ms: now(),
          metrics: getMetrics(),
          history: getHistory(),
        };
      },
      hudText: hudText,
    };
  }

  return {
    LATENCY_WINDOW: LATENCY_WINDOW,
    TIMELINE_MS: TIMELINE_MS,
    SERIES_KEYS: SERIES_KEYS,
    percentileMs: percentileMs,
    summarizeLatency: summarizeLatency,
    createLatencyTelemetry: createLatencyTelemetry,
  };
});
