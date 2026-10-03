// Onboard camera frames, read back and encoded off the main thread's critical path (#42 item 2).
// The renders stay synchronous in semif-layer.js (one instant of the world). The pixel read waits
// on a GPU fence (three.js readRenderTargetPixelsAsync) instead of stalling the pipeline, and the
// JPEG comes from canvas.toBlob, which Chrome encodes off the main thread. Where the async call is
// missing, the synchronous one is used, so a frame is never lost to a missing API.
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

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }

  async function encodeJpeg(canvas, quality) {
    if (canvas && canvas.toBlob && typeof FileReader !== "undefined") {
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
      if (blob) return blobToDataUrl(blob);
    }
    return canvas.toDataURL("image/jpeg", quality);
  }

  return { readPixels: readPixels, encodeJpeg: encodeJpeg };
});
