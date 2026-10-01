// Latency panel: how long each decision took over the last 1, 5 or 15 minutes, as line charts,
// with a sparkline in the status strip that opens it (L). The numbers come from
// semif-telemetry.js's time-based timeline; this file only draws them.
//
// The chart helpers (bucketize, niceScale, timeTicks) are plain and tested in node
// (tests/test_latency_panel.py); mountStats() builds the panel in the page.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.SEMIF_STATS = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // Categorical slots validated on the panel surface #141922 (dataviz validate_palette.js,
  // --pairs all). End-to-end has a chart to itself; the three stages share the other.
  const SERIES = [
    { key: "e2e_loop_ms", label: "End-to-end", color: "#3987e5", chart: "e2e" },
    { key: "classifier_ms", label: "Classifier", color: "#d95926", chart: "stages" },
    { key: "vision_encode_ms", label: "Vision encode", color: "#199e70", chart: "stages" },
    { key: "grab_frame_ms", label: "Frame grab", color: "#9085e9", chart: "stages" },
  ];
  const RANGES = [
    { key: "1m", ms: 60 * 1000, step: 15 * 1000 },
    { key: "5m", ms: 5 * 60 * 1000, step: 60 * 1000 },
    { key: "15m", ms: 15 * 60 * 1000, step: 5 * 60 * 1000 },
  ];
  const MINUS = "−";

  // Splits [t0, t1) into n slices; each slice with samples gets {t (its middle), mean, min, max, n},
  // an empty one is null so the line breaks there instead of drawing through a gap.
  function bucketize(rows, t0, t1, n) {
    const out = new Array(n).fill(null);
    const width = (t1 - t0) / n;
    for (const row of rows) {
      const i = Math.floor((row.t - t0) / width);
      if (i < 0 || i >= n) continue;
      const b = out[i] || (out[i] = { t: t0 + (i + 0.5) * width, sum: 0, min: Infinity, max: -Infinity, n: 0 });
      b.sum += row.ms;
      b.n += 1;
      if (row.ms < b.min) b.min = row.ms;
      if (row.ms > b.max) b.max = row.ms;
    }
    return out.map((b) => (b ? { t: b.t, mean: b.sum / b.n, min: b.min, max: b.max, n: b.n } : null));
  }

  // A 0-based axis up to a round number at or above `value`, with three to five steps.
  function niceScale(value) {
    const top = value > 0 ? value : 10;
    const raw = top / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw - 1e-9);
    const max = Math.ceil(top / step - 1e-9) * step;
    const ticks = [];
    for (let v = 0; v <= max + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
    return { max, ticks };
  }

  function timeTicks(rangeMs) {
    const range = RANGES.find((r) => r.ms === rangeMs) || RANGES[0];
    const ticks = [];
    for (let ago = range.ms; ago > 0; ago -= range.step) {
      const label = range.step >= 60000 ? ago / 60000 + "m" : ago / 1000 + "s";
      ticks.push({ ago, label: MINUS + label });
    }
    ticks.push({ ago: 0, label: "now" });
    return ticks;
  }

  // Summary of one window: sorted once, percentiles interpolated as semif-telemetry.js does.
  function summarize(values) {
    const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
    const n = v.length;
    if (!n) return { n: 0, min: null, max: null, p50: null, p95: null };
    const pct = (p) => {
      const rank = (p / 100) * (n - 1), lo = Math.floor(rank), hi = Math.ceil(rank);
      return v[lo] + (v[hi] - v[lo]) * (rank - lo);
    };
    return { n, min: v[0], max: v[n - 1], p50: pct(50), p95: pct(95) };
  }

  // Every series of the window, each read from the telemetry once.
  function windowStats(telemetry, range) {
    const lines = {}, sums = {};
    for (const s of SERIES) {
      lines[s.key] = telemetry.getTimeline(s.key, range);
      sums[s.key] = summarize(lines[s.key].map((row) => row.ms));
    }
    return { lines, sums };
  }

  // The long window changes slowly and costs the most to draw.
  function redrawEvery(range) {
    return range >= 15 * 60 * 1000 ? 2000 : range >= 5 * 60 * 1000 ? 1000 : 500;
  }

  // Samples per minute over the part of the window that has samples, not the whole window.
  function perMinute(n, firstT, t1, range) {
    if (!n || firstT == null) return null;
    const span = Math.max(1000, Math.min(range, t1 - firstT));
    return Math.round((n / (span / 60000)) * 10) / 10;
  }

  function fmtMs(v) {
    if (v == null || !Number.isFinite(v)) return "—";
    return v >= 100 ? String(Math.round(v)) : v.toFixed(1);
  }

  function fmtAgo(ms) {
    const s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return MINUS + s + "s";
    return MINUS + Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  // ---- In the page ---------------------------------------------------------------------------

  const INK = "#f4f4f5";
  const INK_2 = "#9aa3b2";
  const GRID = "rgba(255, 255, 255, 0.08)";
  const PAD = { left: 40, right: 54, top: 10, bottom: 22 };

  function seriesOf(chart) {
    return SERIES.filter((s) => s.chart === chart);
  }

  // Sizes the canvas to its box at the screen's pixel ratio; returns the 2D context in CSS pixels.
  function fit(canvas) {
    const dpr = Math.min(2, (typeof devicePixelRatio === "number" && devicePixelRatio) || 1);
    const w = Math.max(1, Math.round(canvas.clientWidth));
    const h = Math.max(1, Math.round(canvas.clientHeight));
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    return { g, w, h };
  }

  function strokeBuckets(g, buckets, x, y, pick) {
    g.beginPath();
    let pen = false;
    buckets.forEach((b, i) => {
      if (!b) {
        pen = false;
        return;
      }
      const px = x(i), py = y(pick(b));
      if (pen) g.lineTo(px, py);
      else g.moveTo(px, py);
      pen = true;
    });
    g.stroke();
  }

  // One chart: grid, axes, lines (and the e2e min–max band), reference lines, and the hover.
  function drawChart(canvas, model, hover) {
    const { g, w, h } = fit(canvas);
    const plotW = w - PAD.left - PAD.right, plotH = h - PAD.top - PAD.bottom;
    const n = model.buckets[0] ? model.buckets[0].length : 0;
    const x = (i) => PAD.left + ((i + 0.5) / n) * plotW;
    const y = (v) => PAD.top + plotH - (Math.min(v, model.scale.max) / model.scale.max) * plotH;
    g.font = "500 10px Inter, system-ui, sans-serif";
    g.textBaseline = "middle";
    g.lineWidth = 1;
    for (const v of model.scale.ticks) {
      g.strokeStyle = GRID;
      g.beginPath();
      g.moveTo(PAD.left, Math.round(y(v)) + 0.5);
      g.lineTo(PAD.left + plotW, Math.round(y(v)) + 0.5);
      g.stroke();
      g.fillStyle = INK_2;
      g.textAlign = "right";
      g.fillText(String(v), PAD.left - 8, y(v));
    }
    g.textAlign = "center";
    g.textBaseline = "top";
    for (const t of model.timeTicks) {
      const px = PAD.left + (1 - t.ago / model.range) * plotW;
      g.fillStyle = INK_2;
      g.textAlign = t.ago === 0 ? "right" : t.ago === model.range ? "left" : "center";
      g.fillText(t.label, px, PAD.top + plotH + 7);
    }
    model.series.forEach((s, k) => {
      const buckets = model.buckets[k];
      if (model.band) {
        g.fillStyle = s.color + "2e";
        let start = -1;
        const flush = (end) => {
          if (start < 0) return;
          g.beginPath();
          for (let i = start; i < end; i++) g.lineTo(x(i), y(buckets[i].max));
          for (let i = end - 1; i >= start; i--) g.lineTo(x(i), y(buckets[i].min));
          g.closePath();
          g.fill();
          start = -1;
        };
        buckets.forEach((b, i) => {
          if (b && start < 0) start = i;
          if (!b) flush(i);
        });
        flush(buckets.length);
      }
      g.strokeStyle = s.color;
      g.lineWidth = 2;
      g.lineJoin = "round";
      g.lineCap = "round";
      strokeBuckets(g, buckets, x, y, (b) => b.mean);
    });
    // P50 / P95 of the window, dashed, labelled in the right margin.
    g.setLineDash([4, 4]);
    g.lineWidth = 1;
    g.textAlign = "left";
    g.textBaseline = "middle";
    let lastLabelY = -Infinity;
    for (const ref of model.refs) {
      if (ref.value == null) continue;
      const py = Math.round(y(ref.value)) + 0.5;
      g.strokeStyle = "rgba(244, 244, 245, 0.55)";
      g.beginPath();
      g.moveTo(PAD.left, py);
      g.lineTo(PAD.left + plotW, py);
      g.stroke();
      const ly = Math.abs(py - lastLabelY) < 12 ? lastLabelY - 12 : py;
      lastLabelY = ly;
      g.fillStyle = INK;
      g.fillText(ref.label + " " + fmtMs(ref.value), PAD.left + plotW + 6, ly);
    }
    g.setLineDash([]);
    if (hover != null && hover >= 0 && hover < n) {
      const px = x(hover);
      g.strokeStyle = "rgba(244, 244, 245, 0.35)";
      g.beginPath();
      g.moveTo(px, PAD.top);
      g.lineTo(px, PAD.top + plotH);
      g.stroke();
      model.series.forEach((s, k) => {
        const b = model.buckets[k][hover];
        if (!b) return;
        g.fillStyle = s.color;
        g.strokeStyle = "#141922";
        g.lineWidth = 2;
        g.beginPath();
        g.arc(px, y(b.mean), 4, 0, Math.PI * 2);
        g.fill();
        g.stroke();
      });
    }
    return { x, plotW, n };
  }

  function drawSpark(canvas, rows, t0, t1) {
    const { g, w, h } = fit(canvas);
    const buckets = bucketize(rows, t0, t1, Math.max(8, Math.floor(w / 2)));
    const top = Math.max(1, ...buckets.filter(Boolean).map((b) => b.mean)) * 1.15;
    g.strokeStyle = SERIES[0].color;
    g.lineWidth = 1.5;
    g.lineJoin = "round";
    strokeBuckets(
      g,
      buckets,
      (i) => ((i + 0.5) / buckets.length) * w,
      (v) => h - 2 - (v / top) * (h - 4),
      (b) => b.mean
    );
  }

  const PANEL_HTML = `
    <header class="fsd-stats-head">
      <div class="fsd-stats-title"><strong>Latency</strong><span class="fsd-stats-live">LIVE</span></div>
      <div class="fsd-stats-range" role="tablist" aria-label="Time window">
        ${RANGES.map((r) => `<button type="button" role="tab" data-range="${r.ms}">${r.key}</button>`).join("")}
      </div>
      <button type="button" id="fsd-latency-export" class="fsd-stats-action">Export JSON</button>
      <button type="button" class="fsd-stats-close" aria-label="Close latency panel" title="Close · L">✕</button>
    </header>
    <div class="fsd-stats-tiles"></div>
    <figure class="fsd-chart" data-chart="e2e">
      <figcaption><strong>End-to-end loop</strong><span>request to decision, ms · band = min–max</span></figcaption>
      <div class="fsd-chart-box"><canvas></canvas><div class="fsd-chart-tip" hidden></div></div>
    </figure>
    <figure class="fsd-chart" data-chart="stages">
      <figcaption><strong>Pipeline stages</strong><span>ms</span>
        <span class="fsd-chart-legend">${seriesOf("stages")
          .map((s) => `<span><i style="background:${s.color}"></i>${s.label}</span>`)
          .join("")}</span>
      </figcaption>
      <div class="fsd-chart-box"><canvas></canvas><div class="fsd-chart-tip" hidden></div></div>
    </figure>
    <table class="fsd-stats-table">
      <thead><tr><th scope="col">Series</th><th>Last</th><th>P50</th><th>P95</th><th>Max</th><th>Samples</th></tr></thead>
      <tbody>${SERIES.map(
        (s) => `<tr data-key="${s.key}"><th scope="row"><i style="background:${s.color}"></i>${s.label}</th><td></td><td></td><td></td><td></td><td></td></tr>`
      ).join("")}</tbody>
    </table>
    <footer class="fsd-stats-foot"></footer>
  `;

  function mountStats(opts) {
    const telemetry = opts.telemetry;
    const now = opts.now || (() => (typeof performance !== "undefined" ? performance.now() : Date.now()));
    const chip = opts.chip;
    const spark = chip && chip.querySelector("canvas");
    const chipText = chip && chip.querySelector(".fsd-latency-text");
    let range = RANGES[1].ms;
    try {
      const saved = Number(localStorage.getItem("semif-latency-range"));
      if (RANGES.some((r) => r.ms === saved)) range = saved;
    } catch (_) {}

    let timer = null;
    const panel = document.createElement("section");
    panel.id = "fsd-stats";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Latency");
    panel.hidden = true;
    panel.innerHTML = PANEL_HTML;
    (opts.parent || document.body).appendChild(panel);

    const tiles = panel.querySelector(".fsd-stats-tiles");
    const foot = panel.querySelector(".fsd-stats-foot");
    const charts = ["e2e", "stages"].map((name) => {
      const fig = panel.querySelector(`[data-chart="${name}"]`);
      return { name, canvas: fig.querySelector("canvas"), tip: fig.querySelector(".fsd-chart-tip"), hover: null, layout: null, model: null };
    });

    function setRange(ms) {
      range = ms;
      try {
        localStorage.setItem("semif-latency-range", String(ms));
      } catch (_) {}
      for (const b of panel.querySelectorAll("[data-range]")) b.setAttribute("aria-selected", String(Number(b.dataset.range) === ms));
      if (!panel.hidden) {
        clearInterval(timer);
        timer = setInterval(draw, redrawEvery(range));
      }
      draw();
    }
    for (const b of panel.querySelectorAll("[data-range]")) b.addEventListener("click", () => setRange(Number(b.dataset.range)));
    panel.querySelector("#fsd-latency-export").addEventListener("click", () => opts.onExport && opts.onExport());
    panel.querySelector(".fsd-stats-close").addEventListener("click", () => toggle(false));

    function tile(label, value, unit, note) {
      return `<div class="fsd-tile"><span>${label}</span><strong>${value}<small>${unit}</small></strong>${note ? `<em>${note}</em>` : ""}</div>`;
    }

    function draw() {
      if (panel.hidden || !telemetry) return;
      const t1 = now(), t0 = t1 - range;
      const { lines, sums } = windowStats(telemetry, range);
      const e2e = sums.e2e_loop_ms, cls = sums.classifier_ms, vis = sums.vision_encode_ms;
      const rate = perMinute(e2e.n, e2e.n ? lines.e2e_loop_ms[0].t : null, t1, range);
      tiles.innerHTML =
        tile("E2E P50", fmtMs(e2e.p50), "ms") +
        tile("E2E P95", fmtMs(e2e.p95), "ms") +
        tile("E2E max", fmtMs(e2e.max), "ms") +
        tile("Decisions", rate == null ? "—" : rate.toFixed(rate >= 10 ? 0 : 1), "/min") +
        tile("Classifier P50", fmtMs(cls.p50), "ms") +
        tile("Vision P50", fmtMs(vis.p50), "ms");
      for (const row of panel.querySelectorAll(".fsd-stats-table tbody tr")) {
        const line = lines[row.dataset.key], sum = sums[row.dataset.key];
        const cells = row.querySelectorAll("td");
        const last = line.length ? line[line.length - 1].ms : null;
        [fmtMs(last), fmtMs(sum.p50), fmtMs(sum.p95), fmtMs(sum.max), String(sum.n)].forEach((v, i) => (cells[i].textContent = v));
      }
      const label = RANGES.find((r) => r.ms === range).key.replace("m", " min");
      foot.textContent = e2e.n || vis.n
        ? `Last ${label} · P50 / P95 over the window · hover a chart for values · L to close`
        : `No samples in the last ${label} yet. Engage Jev (J) to start decisions.`;
      for (const c of charts) {
        const series = seriesOf(c.name);
        const n = Math.max(20, Math.min(240, Math.floor((c.canvas.clientWidth - PAD.left - PAD.right) / 3)));
        const buckets = series.map((s) => bucketize(lines[s.key], t0, t1, n));
        let top = 0;
        buckets.forEach((bs) => bs.forEach((b) => b && (top = Math.max(top, c.name === "e2e" ? b.max : b.mean))));
        if (c.name === "e2e" && e2e.p95 != null) top = Math.max(top, e2e.p95);
        c.model = {
          series,
          buckets,
          range,
          t1,
          band: c.name === "e2e",
          scale: niceScale(top * 1.05),
          timeTicks: timeTicks(range),
          refs: c.name === "e2e" ? [{ label: "P95", value: e2e.p95 }, { label: "P50", value: e2e.p50 }] : [],
        };
        c.layout = drawChart(c.canvas, c.model, c.hover);
        showTip(c);
      }
    }

    function showTip(c) {
      if (c.hover == null || !c.model || !c.layout) {
        c.tip.hidden = true;
        return;
      }
      const rows = c.model.series
        .map((s, k) => {
          const b = c.model.buckets[k][c.hover];
          return b ? `<div><i style="background:${s.color}"></i>${s.label}<b>${fmtMs(b.mean)} ms</b></div>` : "";
        })
        .join("");
      if (!rows) {
        c.tip.hidden = true;
        return;
      }
      const t = c.model.buckets.find((bs) => bs[c.hover])[c.hover].t;
      c.tip.innerHTML = `<span>${fmtAgo(c.model.t1 - t)}</span>${rows}`;
      c.tip.hidden = false;
      const px = c.layout.x(c.hover);
      const left = px + 12 + c.tip.offsetWidth > c.canvas.clientWidth ? px - 12 - c.tip.offsetWidth : px + 12;
      c.tip.style.left = `${Math.round(left)}px`;
    }

    for (const c of charts) {
      c.canvas.addEventListener("pointermove", (ev) => {
        if (!c.layout || !c.layout.n) return;
        const rect = c.canvas.getBoundingClientRect();
        const i = Math.floor(((ev.clientX - rect.left - PAD.left) / c.layout.plotW) * c.layout.n);
        c.hover = i >= 0 && i < c.layout.n ? i : null;
        c.layout = drawChart(c.canvas, c.model, c.hover);
        showTip(c);
      });
      c.canvas.addEventListener("pointerleave", () => {
        c.hover = null;
        if (c.model) c.layout = drawChart(c.canvas, c.model, null);
        showTip(c);
      });
    }

    function toggle(open) {
      const show = open == null ? panel.hidden : open;
      panel.hidden = !show;
      if (chip) chip.setAttribute("aria-expanded", String(show));
      clearInterval(timer);
      timer = null;
      if (show) {
        if (opts.onOpen) opts.onOpen();
        setRange(range);
      }
    }

    if (chip) {
      // The chip never takes focus, so Space and Enter keep braking and driving.
      chip.addEventListener("mousedown", (ev) => ev.preventDefault());
      chip.addEventListener("click", () => toggle());
    }
    document.addEventListener("keydown", (ev) => {
      if (ev.repeat || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (/input|select|textarea/i.test((ev.target && ev.target.tagName) || "")) return;
      if (ev.code === "KeyL") toggle();
      else if (ev.code === "Escape" && !panel.hidden) toggle(false);
    });
    addEventListener("resize", () => draw());

    // The status strip's chip: the last minute of end-to-end latency, redrawn at most once a second.
    let lastSpark = 0;
    function refresh() {
      if (!telemetry || !chip) return;
      const t = now();
      if (chipText) {
        const last = telemetry.getTimeline("e2e_loop_ms", 60000);
        const p95 = telemetry.summarizeWindow("e2e_loop_ms", 60000).p95;
        chipText.textContent = last.length
          ? `e2e ${fmtMs(last[last.length - 1].ms)} ms · P95 ${fmtMs(p95)}`
          : "e2e — · P95 —";
      }
      if (typeof telemetry.hudText === "function") chip.title = telemetry.hudText() + "\nOpen the latency charts · L";
      if (spark && t - lastSpark > 1000) {
        lastSpark = t;
        drawSpark(spark, telemetry.getTimeline("e2e_loop_ms", 60000), t - 60000, t);
      }
    }
    setInterval(refresh, 1000);
    refresh();

    return { panel, toggle, refresh, draw };
  }

  return { SERIES, RANGES, bucketize, niceScale, timeTicks, fmtMs, summarize, windowStats, redrawEvery, perMinute, mountStats };
});
