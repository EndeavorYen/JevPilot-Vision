// The onboard cameras are grabbed only when the vision server can take the frames (#42).
// The server keeps the latest frame and hands back old evidence while it is busy
// (jevpilot_vision/http.py _vision_slot), so grabbing while a request is out costs four renders,
// four pixel reads and four JPEG encodes on the main thread for nothing. One request at a time;
// a request that never answers is given up after STALE_MS so a stuck fetch cannot stop Vision.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.SEMIF_VISION_PACE = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  // Well past any answer seen so far: evidence age p95 was 1.3 s even with frames queued behind
  // each other before this pacing (#42 measurement, RTX 5080), and the first RT-DETR call warms up.
  const STALE_MS = 5000;

  function createVisionPacer(opts) {
    const now = (opts && opts.now) || (() => performance.now());
    let current = 0; // the ticket of the request that is out, 0 when none
    let since = 0;
    let controller = null; // aborts the request when it is given up, so connections do not pile up
    let issued = 0;
    const counts = { grabs: 0, skipped: 0, stale: 0 };

    return {
      // True when a grab may start now; the caller then owes one end(ticket()).
      tryBegin() {
        const t = now();
        if (current && t - since <= STALE_MS) {
          counts.skipped++;
          return false;
        }
        if (current) {
          counts.stale++;
          if (controller) controller.abort();
        }
        controller = typeof AbortController === "function" ? new AbortController() : null;
        current = ++issued;
        since = t;
        counts.grabs++;
        return true;
      },
      ticket() {
        return current;
      },
      // For the request's fetch: aborted if the request is given up.
      signal() {
        return controller ? controller.signal : undefined;
      },
      // An answer or a failure frees the slot; one from a request already given up does not.
      end(ticket) {
        if (ticket === undefined || ticket === current) current = 0;
      },
      stats() {
        return { grabs: counts.grabs, skipped: counts.skipped, stale: counts.stale };
      },
    };
  }

  return { STALE_MS: STALE_MS, createVisionPacer: createVisionPacer };
});
