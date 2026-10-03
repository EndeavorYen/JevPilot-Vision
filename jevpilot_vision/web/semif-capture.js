// Onboard camera frames, read back and encoded off the main thread's critical path (#42 item 2).
// The renders stay synchronous in semif-layer.js (one instant of the world). The pixel read waits
// on a GPU fence (three.js readRenderTargetPixelsAsync) instead of stalling the pipeline, and the
// JPEG is encoded in a worker (semif-encode-worker.js). Where the async API is missing, the
// synchronous one is used, so a frame is never lost to a missing API.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.SEMIF_CAPTURE = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  async function readPixels(renderer, target, w, h) {
    const pixels = new Uint8Array(w * h * 4);
    if (renderer && renderer.readRenderTargetPixelsAsync) {
      const pending = renderer.readRenderTargetPixelsAsync(target, 0, 0, w, h, pixels);
      // three.js leaves its PIXEL_PACK_BUFFER bound through the fence wait, and WebGL2 refuses a
      // plain readPixels while one is bound: the PIP's synchronous read would come back black.
      // It binds the buffer again itself when the fence signals.
      const gl = renderer.getContext && renderer.getContext();
      if (gl && gl.bindBuffer) gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
      await pending;
    } else if (renderer && renderer.readRenderTargetPixels) {
      renderer.readRenderTargetPixels(target, 0, 0, w, h, pixels);
    }
    return pixels;
  }

  // Pixels as read from WebGL (bottom-up) to a JPEG data URL. A worker does the flip and the
  // encode (semif-encode-worker.js); the pixels are transferred, so the caller must be done with
  // them. Without Worker and OffscreenCanvas, a canvas on this thread does it.
  // A job the worker never answers fails after timeoutMs (well past the 8-50 ms measured), so a
  // grab cannot stay pending; the vision pacer gives up on its request after 5 s anyway.
  function createEncoder(workerUrl, makeCanvas, opts) {
    const timeoutMs = (opts && opts.timeoutMs) || 3000;
    let worker = null;
    let next = 0;
    const waiting = new Map();
    const settle = (id, fn, value) => {
      const job = waiting.get(id);
      if (!job) return;
      waiting.delete(id);
      clearTimeout(job.timer);
      job[fn](value);
    };
    const fail = (e) => {
      if (e && e.preventDefault) e.preventDefault(); // handled here, not a page error
      if (worker) worker.terminate();
      worker = null; // later frames use the canvas; these fail once
      Array.from(waiting.keys()).forEach((id) => settle(id, "reject", new Error("encode worker failed")));
    };
    if (typeof Worker === "function" && typeof OffscreenCanvas !== "undefined") {
      try {
        worker = new Worker(workerUrl);
        worker.onmessage = (e) => {
          if (e.data.error) settle(e.data.id, "reject", new Error(e.data.error));
          else settle(e.data.id, "resolve", e.data.url);
        };
        worker.onerror = fail;
        worker.onmessageerror = fail;
      } catch (_err) {
        worker = null;
      }
    }

    function onCanvas(pixels, w, h, quality) {
      const canvas = makeCanvas ? makeCanvas() : document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      const image = ctx.createImageData(w, h);
      const row = w * 4;
      for (let y = 0; y < h; y++) image.data.set(pixels.subarray((h - 1 - y) * row, (h - y) * row), y * row);
      ctx.putImageData(image, 0, 0);
      return canvas.toDataURL("image/jpeg", quality);
    }

    return {
      encode(pixels, w, h, quality) {
        if (!worker) return Promise.resolve(onCanvas(pixels, w, h, quality));
        const id = ++next;
        return new Promise((resolve, reject) => {
          const timer = setTimeout(() => settle(id, "reject", new Error("encode timed out")), timeoutMs);
          waiting.set(id, { resolve, reject, timer });
          worker.postMessage({ id: id, w: w, h: h, q: quality, buf: pixels.buffer }, [pixels.buffer]);
        });
      },
      waiting() {
        return waiting.size;
      },
    };
  }

  return { readPixels: readPixels, createEncoder: createEncoder };
});
