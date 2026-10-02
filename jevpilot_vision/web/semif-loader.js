// Loading screen progress (#20). The bundle drives #scene-loader itself: it writes a stage message
// into #loading-message, unhides #loading-retry on failure and hides the loader when the drive is
// ready. Recorded in the browser, a first load shows the page's "Preparing the map…", then
// "Loading car and scenery…" (the downloads), then "Preparing the road…"; a later drive opens with
// "Building your next drive…". This file only watches that, counts the assets the page
// downloads, and turns both into the bar:
// each stage owns a slice of the bar, and downloads move it across the slice, never past the next
// stage's start. It reaches 100% only when the bundle hides the loader.
(function () {
  const STAGES = [
    [/preparing the map/i, 0.02],
    [/building your next drive/i, 0.06],
    [/loading car and scenery/i, 0.12],
    [/preparing the road/i, 0.78],
  ];
  const END = 0.97;
  const PER_DOWNLOAD = 12; // downloads to cover about 63% of a stage's slice

  function stageOf(message) {
    const text = String(message || "");
    return STAGES.findIndex(([pattern]) => pattern.test(text));
  }

  // Fraction of the bar for a stage message, downloads finished since that stage began, and
  // whether the bundle has hidden the loader.
  function progress(message, downloads, done) {
    if (done) return 1;
    const i = stageOf(message);
    const base = i < 0 ? 0.05 : STAGES[i][1];
    const next = i < 0 || i + 1 >= STAGES.length ? END : STAGES[i + 1][1];
    const filled = 1 - Math.exp(-Math.max(0, downloads) / PER_DOWNLOAD);
    return Math.min(END, base + (next - base) * 0.9 * filled);
  }

  window.SEMIF_LOADER = { progress, stageOf };
  if (typeof document === "undefined" || !document) return;

  function start() {
    const loader = document.getElementById("scene-loader");
    const message = document.getElementById("loading-message");
    const retry = document.getElementById("loading-retry");
    const bar = loader && loader.querySelector(".sol-progress");
    const fill = bar && bar.querySelector("span");
    const label = loader && loader.querySelector(".sol-progress-label");
    if (!loader || !message || !bar || !fill) return;

    let downloads = 0;
    let stageStart = 0;
    let stageText = message.textContent;
    let shown = 0;
    let wasHidden = loader.hidden;

    if (typeof PerformanceObserver === "function") {
      try {
        new PerformanceObserver((list) => {
          downloads += list.getEntries().length;
          if (!loader.hidden) render(); // after load, downloads are only counted
        }).observe({ type: "resource", buffered: true });
      } catch (_err) {
        /* no resource timing: the stages alone move the bar */
      }
    }

    function render() {
      if (message.textContent !== stageText) {
        stageText = message.textContent;
        stageStart = downloads;
      }
      if (wasHidden && !loader.hidden) shown = 0; // a new drive is being built
      wasHidden = loader.hidden;
      const failed = !!retry && !retry.hidden;
      loader.dataset.state = failed ? "error" : "loading";
      shown = Math.max(shown, progress(stageText, downloads - stageStart, loader.hidden));
      const pct = Math.round(shown * 100);
      fill.style.transform = `scaleX(${shown})`;
      bar.setAttribute("aria-valuenow", String(pct));
      if (label) label.textContent = failed ? "Couldn't finish" : `${pct}%`;
    }

    const watch = new MutationObserver(render);
    watch.observe(message, { childList: true, characterData: true, subtree: true });
    watch.observe(loader, { attributes: true, attributeFilter: ["hidden"] });
    if (retry) watch.observe(retry, { attributes: true, attributeFilter: ["hidden"] });
    render();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
