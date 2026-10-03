// JPEG encoding of onboard camera frames, off the main thread (#42 item 2).
// canvas.toBlob and a main-thread OffscreenCanvas.convertToBlob wait for the main thread's idle
// time, which the running simulation hardly leaves: about 1 s per frame, measured. Here the
// pixels arrive by transfer, are flipped (WebGL reads bottom-up) and encoded in this thread.
function flipRows(src, w, h) {
  const out = new Uint8ClampedArray(w * h * 4);
  const row = w * 4;
  for (let y = 0; y < h; y++) out.set(src.subarray((h - 1 - y) * row, (h - y) * row), y * row);
  return out;
}

if (typeof module === "object" && module.exports) {
  module.exports = { flipRows: flipRows };
} else {
  self.onmessage = async (e) => {
    const { id, w, h, q, buf } = e.data;
    try {
      const canvas = new OffscreenCanvas(w, h);
      canvas.getContext("2d").putImageData(new ImageData(flipRows(new Uint8Array(buf), w, h), w, h), 0, 0);
      const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: q });
      self.postMessage({ id: id, url: new FileReaderSync().readAsDataURL(blob) });
    } catch (err) {
      self.postMessage({ id: id, error: String((err && err.message) || err) });
    }
  };
}
