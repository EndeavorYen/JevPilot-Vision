// Scenery layer (#11): facades, building massing, traffic cars, signal heads, sky and minimap.
//
// The prebuilt bundle calls four hooks (see BUNDLE_PATCHES.md): kit() hands over its three.js
// classes, object() may take over one world object, built() runs once the scene exists, and
// minimap() draws under the roads. Nothing here changes the simulation, the roads or the signals'
// timing; it only changes what the cameras see. ?scenery=0 turns the layer off.
//
// The onboard camera feeds colour masks (jevpilot_vision/vision.py). Every colour below is in
// PALETTE so tests/test_scenery.py can keep it out of the red / green light, construction and
// emergency-light masks.
(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  if (params.get("scenery") === "0") return;

  const PALETTE = {
    glass: ["#3e4b55", "#46535c", "#505c63", "#3a4650"],
    mullion: "#a3a9ac",
    spandrel: "#2c3339",
    stone: ["#c9c2b4", "#b9b3a6", "#d3cdc0", "#a9a59c"],
    brick: ["#86574d", "#7b5048", "#8f6253", "#6f4a42"],
    stucco: ["#d8cdb9", "#cfc6b4", "#e0d6c3", "#c8bfae"],
    siding: ["#dcd6c8", "#c9d1cc", "#d9cdb3", "#c2c9cf", "#e0d3c1"],
    trim: "#ece6d8",
    windowDark: "#2b343b",
    windowLight: "#6b7880",
    blind: "#cfc9ba",
    interiorWarm: "#b89f78",
    door: "#5b4636",
    roofFlat: "#5e6264",
    roofGable: ["#5d5550", "#4f5559", "#6b5b50", "#58606a"],
    parapet: "#8e9092",
    mechanical: "#9ea3a5",
    awning: ["#3f5f57", "#6a4b44", "#4a5068", "#6b6254"],
    signBand: "#2f3437",
    signText: "#efe8d6",
    balcony: "#a8aaa8",
    carPaint: ["#e7e8ea", "#bfc3c8", "#8e949b", "#5f656c", "#3c4148", "#2e3a52", "#6c2a2c", "#34463d", "#c8bca3", "#f2f2ee"],
    signalHousing: "#23272a",
    signalBackplate: "#16181a",
    fog: "#c3cfd8",
  };

  const SHOP_NAMES = ["CAFE", "BAKERY", "BOOKS", "MARKET", "DELI", "PHARMACY", "FLOWERS", "BISTRO", "HARDWARE", "NOODLES", "OPTICS", "LAUNDRY"];

  let T = null; // three.js classes and bundle helpers, from kit()
  const textureCache = new Map();
  const materialCache = new Map();

  function hash(text) {
    let h = 2166136261;
    const s = String(text);
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h;
  }

  function rng(seed) {
    let a = seed >>> 0 || 1;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function pick(list, r) {
    return list[Math.floor(r() * list.length) % list.length];
  }

  function shade(hex, f) {
    const n = parseInt(hex.slice(1), 16);
    const c = (v) => Math.max(0, Math.min(255, Math.round(v * f)));
    return `rgb(${c((n >> 16) & 255)},${c((n >> 8) & 255)},${c(n & 255)})`;
  }

  // ---- facade textures ------------------------------------------------------------------
  // A tile is 4 bays by 4 floors. Geometry UVs repeat it at BAY_M by FLOOR_M.
  const TILE_PX = 512;
  const BAY_M = 3.0;

  function canvas(w, h) {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    return c;
  }

  function texture(key, draw, w = TILE_PX, h = TILE_PX) {
    if (textureCache.has(key)) return textureCache.get(key);
    const c = canvas(w, h);
    draw(c.getContext("2d"), w, h);
    const tex = new T.CanvasTexture(c);
    tex.wrapS = tex.wrapT = T.RepeatWrapping;
    tex.colorSpace = T.SRGBColorSpace;
    tex.anisotropy = Math.min(8, (T.quality && T.quality.anisotropy) || 4);
    textureCache.set(key, tex);
    return tex;
  }

  function glassPane(ctx, x, y, w, h, base, r) {
    const g = ctx.createLinearGradient(x, y, x + w * 0.3, y + h);
    g.addColorStop(0, shade(base, 1.45 + r() * 0.2));
    g.addColorStop(0.45, shade(base, 1.0));
    g.addColorStop(1, shade(base, 0.72));
    ctx.fillStyle = g;
    ctx.fillRect(x, y, w, h);
    const mode = r();
    if (mode < 0.18) {
      ctx.fillStyle = PALETTE.blind;
      ctx.globalAlpha = 0.55;
      ctx.fillRect(x, y, w, h * (0.25 + r() * 0.5));
      ctx.globalAlpha = 1;
    } else if (mode < 0.3) {
      ctx.fillStyle = PALETTE.interiorWarm;
      ctx.globalAlpha = 0.28;
      ctx.fillRect(x, y + h * 0.35, w, h * 0.65);
      ctx.globalAlpha = 1;
    }
  }

  function punchedTile(ctx, S, wall, variant) {
    const r = rng(hash(`${wall}:${variant}`));
    const cell = S / 4;
    ctx.fillStyle = wall;
    ctx.fillRect(0, 0, S, S);
    // Weathering: faint vertical streaks and mortar-ish noise.
    for (let i = 0; i < 900; i++) {
      ctx.fillStyle = r() < 0.5 ? "rgba(0,0,0,0.035)" : "rgba(255,255,255,0.035)";
      ctx.fillRect(r() * S, r() * S, 2 + r() * 6, 1 + r() * 3);
    }
    for (let f = 0; f < 4; f++) {
      ctx.fillStyle = "rgba(0,0,0,0.08)";
      ctx.fillRect(0, f * cell + cell - 6, S, 3);
      for (let b = 0; b < 4; b++) {
        const x = b * cell + cell * 0.22;
        const y = f * cell + cell * 0.2;
        const w = cell * 0.56;
        const h = cell * 0.58;
        ctx.fillStyle = PALETTE.trim;
        ctx.fillRect(x - 5, y - 5, w + 10, h + 12);
        glassPane(ctx, x, y, w, h, pick(PALETTE.glass, r), r);
        ctx.fillStyle = PALETTE.trim;
        ctx.fillRect(x + w / 2 - 2, y, 4, h);
        ctx.fillRect(x, y + h * 0.42, w, 3);
        ctx.fillStyle = "rgba(0,0,0,0.25)";
        ctx.fillRect(x - 6, y + h + 6, w + 12, 4);
      }
    }
  }

  function brickTile(ctx, S, base, variant) {
    const r = rng(hash(`brick:${base}:${variant}`));
    ctx.fillStyle = shade(base, 0.9);
    ctx.fillRect(0, 0, S, S);
    const bh = 8;
    const bw = 22;
    for (let y = 0; y < S; y += bh) {
      const off = (y / bh) % 2 ? bw / 2 : 0;
      for (let x = -bw; x < S + bw; x += bw) {
        ctx.fillStyle = shade(base, 0.88 + r() * 0.22);
        ctx.fillRect(x + off + 1, y + 1, bw - 2, bh - 2);
      }
    }
    const cell = S / 4;
    for (let f = 0; f < 4; f++) {
      for (let b = 0; b < 4; b++) {
        const x = b * cell + cell * 0.25;
        const y = f * cell + cell * 0.18;
        const w = cell * 0.5;
        const h = cell * 0.6;
        ctx.fillStyle = shade(base, 0.7);
        ctx.fillRect(x - 6, y - 10, w + 12, 10);
        ctx.fillStyle = PALETTE.trim;
        ctx.fillRect(x - 4, y - 4, w + 8, h + 8);
        glassPane(ctx, x, y, w, h, pick(PALETTE.glass, r), r);
        ctx.fillStyle = PALETTE.trim;
        ctx.fillRect(x, y + h / 2 - 2, w, 4);
        ctx.fillRect(x + w / 2 - 2, y, 4, h);
        ctx.fillStyle = "#bdb6a6";
        ctx.fillRect(x - 8, y + h + 4, w + 16, 6);
      }
    }
  }

  function curtainTile(ctx, S, base, variant) {
    const r = rng(hash(`curtain:${base}:${variant}`));
    const cell = S / 4;
    for (let f = 0; f < 4; f++) {
      for (let b = 0; b < 4; b++) {
        glassPane(ctx, b * cell, f * cell, cell, cell * 0.8, base, r);
      }
      ctx.fillStyle = PALETTE.spandrel;
      ctx.fillRect(0, f * cell + cell * 0.8, S, cell * 0.2);
    }
    ctx.fillStyle = PALETTE.mullion;
    for (let b = 0; b <= 4; b++) ctx.fillRect(b * cell - 3, 0, 6, S);
    for (let f = 0; f <= 4; f++) ctx.fillRect(0, f * cell + cell * 0.8 - 2, S, 4);
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    for (let b = 0; b < 4; b++) ctx.fillRect(b * cell + cell / 2 - 1, 0, 2, S);
  }

  function sidingTile(ctx, S, base, variant) {
    const r = rng(hash(`siding:${base}:${variant}`));
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, S, S);
    for (let y = 0; y < S; y += 12) {
      ctx.fillStyle = "rgba(0,0,0,0.10)";
      ctx.fillRect(0, y + 10, S, 2);
      ctx.fillStyle = "rgba(255,255,255,0.10)";
      ctx.fillRect(0, y, S, 1);
    }
    const cell = S / 4;
    for (let f = 0; f < 4; f++) {
      for (let b = 0; b < 4; b++) {
        if (r() < 0.2) continue;
        const x = b * cell + cell * 0.28;
        const y = f * cell + cell * 0.22;
        const w = cell * 0.44;
        const h = cell * 0.52;
        ctx.fillStyle = PALETTE.trim;
        ctx.fillRect(x - 6, y - 6, w + 12, h + 12);
        glassPane(ctx, x, y, w, h, pick(PALETTE.glass, r), r);
        ctx.fillStyle = PALETTE.trim;
        ctx.fillRect(x, y + h / 2 - 2, w, 4);
        ctx.fillRect(x + w / 2 - 2, y, 4, h);
        ctx.fillStyle = shade(pick(PALETTE.awning, r), 1.0);
        ctx.fillRect(x - 16, y - 2, 10, h + 4);
        ctx.fillRect(x + w + 6, y - 2, 10, h + 4);
      }
    }
  }

  function shopfrontTile(ctx, W, H, name, variant) {
    const r = rng(hash(`shop:${name}:${variant}`));
    ctx.fillStyle = PALETTE.signBand;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = PALETTE.signBand;
    ctx.fillRect(0, 0, W, H * 0.22);
    ctx.fillStyle = PALETTE.signText;
    ctx.font = `bold ${Math.round(H * 0.13)}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(name, W / 2, H * 0.11);
    const bay = W / 4;
    for (let b = 0; b < 4; b++) {
      const x = b * bay + 8;
      const y = H * 0.27;
      const w = bay - 16;
      const h = H * 0.7;
      ctx.fillStyle = "#4a5054";
      ctx.fillRect(x - 4, y - 4, w + 8, h + 8);
      if (b === 1) {
        ctx.fillStyle = PALETTE.door;
        ctx.fillRect(x + w * 0.2, y, w * 0.6, h);
        ctx.fillStyle = pick(PALETTE.glass, r);
        ctx.fillRect(x + w * 0.28, y + h * 0.08, w * 0.44, h * 0.55);
        continue;
      }
      glassPane(ctx, x, y, w, h, pick(PALETTE.glass, r), r);
      // Shelves and goods behind the glass.
      ctx.fillStyle = PALETTE.interiorWarm;
      ctx.globalAlpha = 0.45;
      ctx.fillRect(x, y + h * 0.45, w, h * 0.55);
      ctx.globalAlpha = 1;
      for (let k = 0; k < 3; k++) {
        ctx.fillStyle = shade(pick(PALETTE.awning, r), 1.25);
        ctx.fillRect(x + 6 + k * (w / 3), y + h * (0.55 + r() * 0.2), w / 3 - 12, h * 0.12);
      }
    }
  }

  function facadeMaterial(kind, tone, variant) {
    const key = `facade:${kind}:${tone}:${variant}`;
    if (materialCache.has(key)) return materialCache.get(key);
    let tex;
    let opts = { roughness: 0.85, metalness: 0.0 };
    if (kind === "curtain") {
      tex = texture(key, (c, w) => curtainTile(c, w, tone, variant));
      opts = { roughness: 0.28, metalness: 0.55, envMapIntensity: 0.9 };
    } else if (kind === "brick") {
      tex = texture(key, (c, w) => brickTile(c, w, tone, variant));
    } else if (kind === "siding") {
      tex = texture(key, (c, w) => sidingTile(c, w, tone, variant));
      opts = { roughness: 0.9, metalness: 0.0 };
    } else {
      tex = texture(key, (c, w) => punchedTile(c, w, tone, variant));
      opts = { roughness: 0.82, metalness: 0.02 };
    }
    const mat = new T.MeshStandardMaterial(Object.assign({ map: tex }, opts));
    // Merge with the bundle's static batches (it only merges textured materials that say so).
    mat.userData.metersPerTile = BAY_M;
    materialCache.set(key, mat);
    return mat;
  }

  function shopMaterial(name) {
    const key = `shop:${name}`;
    if (materialCache.has(key)) return materialCache.get(key);
    const tex = texture(key, (c, w, h) => shopfrontTile(c, w, h, name, 0), 512, 160);
    const mat = new T.MeshStandardMaterial({ map: tex, roughness: 0.4, metalness: 0.2 });
    mat.userData.metersPerTile = BAY_M;
    materialCache.set(key, mat);
    return mat;
  }

  function plain(color, opts) {
    const key = `plain:${color}:${JSON.stringify(opts || {})}`;
    if (!materialCache.has(key)) {
      materialCache.set(key, new T.MeshStandardMaterial(Object.assign({ color, roughness: 0.8, metalness: 0 }, opts || {})));
    }
    return materialCache.get(key);
  }

  // ---- geometry ---------------------------------------------------------------------------
  // A box whose side faces tile a facade: u runs along the wall, v up it, both in tile units.
  // rows is how many floors one texture tile holds: 4 for facades, 1 for a shopfront.
  function facadeBox(w, h, d, floorM, vOffset = 0, rows = 4) {
    const geo = new T.BoxGeometry(w, h, d);
    const uv = geo.attributes.uv;
    const tileU = 4 * BAY_M;
    const tileV = rows * floorM;
    // BoxGeometry faces: +x, -x, +y, -y, +z, -z; four vertices each.
    const spans = [d, d, w, w, w, w];
    for (let face = 0; face < 6; face++) {
      for (let k = 0; k < 4; k++) {
        const i = face * 4 + k;
        const vertical = face !== 2 && face !== 3;
        uv.setXY(i, (uv.getX(i) * spans[face]) / tileU, vertical ? (uv.getY(i) * h) / tileV + vOffset : 0);
      }
    }
    uv.needsUpdate = true;
    return geo;
  }

  function add(group, geo, mat, x, y, z, cast = true) {
    const mesh = new T.Mesh(geo, mat);
    mesh.position.set(x, y, z);
    mesh.castShadow = cast;
    mesh.receiveShadow = true;
    group.add(mesh);
    return mesh;
  }

  function boxAt(group, w, h, d, x, y, z, mat) {
    return add(group, new T.BoxGeometry(w, h, d), mat, x, y, z);
  }

  // Gable roof as an indexed prism so it batches with other indexed geometry.
  function gableGeometry(w, d, rise) {
    const hw = w / 2;
    const hd = d / 2;
    const pos = [];
    const uv = [];
    const idx = [];
    const quad = (a, b, c, e, u) => {
      const base = pos.length / 3;
      pos.push(...a, ...b, ...c, ...e);
      uv.push(0, 0, u, 0, u, 1, 0, 1);
      idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    };
    const tri = (a, b, c) => {
      const base = pos.length / 3;
      pos.push(...a, ...b, ...c);
      uv.push(0, 0, 1, 0, 0.5, 1);
      idx.push(base, base + 1, base + 2);
    };
    quad([-hw, 0, hd], [hw, 0, hd], [hw, rise, 0], [-hw, rise, 0], w / 3);
    quad([hw, 0, -hd], [-hw, 0, -hd], [-hw, rise, 0], [hw, rise, 0], w / 3);
    tri([hw, 0, hd], [hw, 0, -hd], [hw, rise, 0]);
    tri([-hw, 0, -hd], [-hw, 0, hd], [-hw, rise, 0]);
    const geo = new T.BufferGeometry();
    geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new T.Float32BufferAttribute(uv, 2));
    geo.setIndex(idx);
    geo.computeVertexNormals();
    return geo;
  }

  // ---- buildings ----------------------------------------------------------------------------
  function tower(g, o, r) {
    const { width: w, depth: d, height: h } = o;
    const glassy = r() < 0.6;
    const podiumH = 5.2;
    const ground = shopMaterial(pick(SHOP_NAMES, r));
    add(g, facadeBox(w + 0.4, podiumH, d + 0.4, podiumH, 0, 1), ground, 0, podiumH / 2, 0);
    boxAt(g, w + 1.6, 0.35, d + 1.6, 0, podiumH + 0.1, 0, plain(PALETTE.parapet));
    const floorM = 3.6;
    const mat = glassy
      ? facadeMaterial("curtain", pick(PALETTE.glass, r), Math.floor(r() * 3))
      : facadeMaterial("punched", pick(PALETTE.stone, r), Math.floor(r() * 3));
    const setback = h > 60 && r() < 0.7;
    const lowerH = setback ? (h - podiumH) * (0.62 + r() * 0.1) : h - podiumH;
    add(g, facadeBox(w, lowerH, d, floorM), mat, 0, podiumH + lowerH / 2, 0);
    let top = podiumH + lowerH;
    let tw = w;
    let td = d;
    if (setback) {
      tw = w * 0.78;
      td = d * 0.78;
      const upperH = h - top;
      boxAt(g, w + 0.3, 0.5, d + 0.3, 0, top + 0.25, 0, plain(PALETTE.parapet));
      add(g, facadeBox(tw, upperH, td, floorM, (lowerH / (4 * floorM)) % 1), mat, 0, top + upperH / 2, 0);
      top += upperH;
    }
    boxAt(g, tw + 0.35, 1.1, td + 0.35, 0, top + 0.55, 0, plain(PALETTE.parapet));
    const mech = plain(PALETTE.mechanical, { roughness: 0.6, metalness: 0.3 });
    boxAt(g, tw * 0.45, 3.2, td * 0.4, (r() - 0.5) * tw * 0.2, top + 1.6, (r() - 0.5) * td * 0.2, mech);
    for (let i = 0; i < 3; i++) {
      boxAt(g, 1.6, 1.2, 1.6, (r() - 0.5) * tw * 0.7, top + 0.6, (r() - 0.5) * td * 0.7, mech);
    }
    if (h > 70) add(g, new T.CylinderGeometry(0.12, 0.2, 10, 8), mech, 0, top + 8, 0);
  }

  function apartment(g, o, r, city) {
    const { width: w, depth: d, height: h } = o;
    const brick = r() < 0.55;
    const mat = brick
      ? facadeMaterial("brick", pick(PALETTE.brick, r), Math.floor(r() * 3))
      : facadeMaterial("punched", pick(PALETTE.stucco, r), Math.floor(r() * 3));
    const groundH = city ? 4.4 : 0;
    if (groundH) add(g, facadeBox(w + 0.2, groundH, d + 0.2, groundH, 0, 1), shopMaterial(pick(SHOP_NAMES, r)), 0, groundH / 2, 0);
    const bodyH = h - groundH;
    add(g, facadeBox(w, bodyH, d, 3.1), mat, 0, groundH + bodyH / 2, 0);
    boxAt(g, w + 0.4, 0.9, d + 0.4, 0, h + 0.45, 0, plain(PALETTE.parapet));
    const rail = plain(PALETTE.balcony, { roughness: 0.5, metalness: 0.4 });
    const floors = Math.floor(bodyH / 3.1);
    if (r() < 0.6) {
      for (let f = 1; f < floors; f++) {
        for (const x of [-w * 0.27, w * 0.27]) {
          boxAt(g, 2.4, 0.18, 1.1, x, groundH + f * 3.1, d / 2 + 0.55, rail);
          boxAt(g, 2.4, 0.9, 0.06, x, groundH + f * 3.1 + 0.5, d / 2 + 1.08, rail);
        }
      }
    }
    if (r() < 0.5) {
      const tank = plain("#7d7468", { roughness: 0.9 });
      add(g, new T.CylinderGeometry(1.2, 1.2, 2.2, 10), tank, (r() - 0.5) * w * 0.5, h + 2.2, (r() - 0.5) * d * 0.5);
    }
  }

  function shop(g, o, r) {
    const { width: w, depth: d } = o;
    const h = Math.max(o.height, 7.5);
    add(g, facadeBox(w, 4.2, d, 4.2, 0, 1), shopMaterial(pick(SHOP_NAMES, r)), 0, 2.1, 0);
    const upper = facadeMaterial("brick", pick(PALETTE.brick, r), Math.floor(r() * 3));
    add(g, facadeBox(w, h - 4.2, d, 3.1), upper, 0, 4.2 + (h - 4.2) / 2, 0);
    boxAt(g, w + 0.5, 0.8, d + 0.5, 0, h + 0.4, 0, plain(PALETTE.parapet));
    const awning = plain(pick(PALETTE.awning, r), { roughness: 0.95 });
    const a = boxAt(g, w * 0.92, 0.12, 1.8, 0, 3.55, d / 2 + 0.85, awning);
    a.rotation.x = -0.28;
  }

  function house(g, o, r) {
    const { width: w, depth: d } = o;
    const style = o.style;
    const wallH = style === "townhouse" ? Math.max(o.height, 7.5) : Math.max(o.height + 1.2, 5.6);
    const mat =
      style === "townhouse"
        ? facadeMaterial("brick", pick(PALETTE.brick, r), Math.floor(r() * 3))
        : style === "modern"
          ? facadeMaterial("punched", pick(PALETTE.stucco, r), Math.floor(r() * 3))
          : facadeMaterial("siding", pick(PALETTE.siding, r), Math.floor(r() * 3));
    add(g, facadeBox(w, wallH, d, 2.9, 0.08), mat, 0, wallH / 2, 0);
    boxAt(g, w + 0.25, 0.4, d + 0.25, 0, 0.2, 0, plain("#9a958a"));
    if (style === "modern") {
      boxAt(g, w + 0.6, 0.35, d + 0.6, 0, wallH + 0.18, 0, plain(PALETTE.roofFlat));
      boxAt(g, w * 0.4, 0.08, 2.2, -w * 0.2, 2.8, d / 2 + 1.1, plain("#6e5a48"));
      boxAt(g, 2.6, 2.2, 0.1, w * 0.25, 1.1, d / 2 + 0.06, plain("#8d8f90", { metalness: 0.3, roughness: 0.5 }));
      return;
    }
    const roofMat = plain(pick(PALETTE.roofGable, r), { roughness: 0.92 });
    const rise = Math.min(w, d) * (0.32 + r() * 0.12);
    add(g, gableGeometry(w + 0.8, d + 0.8, rise), roofMat, 0, wallH, 0);
    boxAt(g, 0.9, 2.2, 0.9, w * 0.26, wallH + rise * 0.6, -d * 0.12, plain("#7a5f50"));
    // Porch with a small roof on the street side.
    const porch = plain("#e9e4d8");
    boxAt(g, w * 0.45, 0.2, 1.8, 0, 0.3, d / 2 + 0.9, plain("#b3aa99"));
    boxAt(g, w * 0.5, 0.15, 2.0, 0, 2.7, d / 2 + 1.0, roofMat);
    for (const x of [-w * 0.22, w * 0.22]) boxAt(g, 0.15, 2.4, 0.15, x, 1.5, d / 2 + 1.8, porch);
    boxAt(g, 1.0, 2.1, 0.08, 0, 1.25, d / 2 + 0.04, plain(PALETTE.door));
  }

  function building(group, o, world) {
    const r = rng(hash(`${world && world.sim && world.sim.world ? world.sim.world.seed : 0}:${o.id}`));
    const g = new T.Group();
    g.position.set(o.x, 0, o.z);
    g.rotation.y = o.rotation || 0;
    const city = world && world.sim && world.sim.world && world.sim.world.type === "city";
    if (o.style === "skyscraper") tower(g, o, r);
    else if (o.style === "apartment") apartment(g, o, r, city);
    else if (o.style === "shop") shop(g, o, r);
    else house(g, o, r);
    group.add(g);
    return true;
  }

  // ---- signals ------------------------------------------------------------------------------
  // Housing, backplate and three visors in one geometry: a signal head stays one draw call.
  function signalHeadGeometry() {
    const parts = [];
    const box = (w, h, d, x, y, z) => {
      const g = new T.BoxGeometry(w, h, d);
      g.translate(x, y, z);
      parts.push(g);
    };
    box(0.65, 1.65, 0.38, 0, 4.2, 0);
    box(1.05, 2.05, 0.05, 0, 4.2, -0.21);
    for (let n = 0; n < 3; n++) {
      const hood = new T.CylinderGeometry(0.21, 0.21, 0.28, 12, 1, true, -Math.PI / 2, Math.PI);
      hood.rotateX(Math.PI / 2);
      hood.translate(0, 4.75 - n * 0.5, 0.36);
      parts.push(hood);
    }
    const merged = T.mergeGeometries(parts);
    parts.forEach((g) => g.dispose());
    return merged;
  }

  function restyleSignals(world) {
    if (!T.mergeGeometries) return;
    const housing = plain(PALETTE.signalHousing, { roughness: 0.55, metalness: 0.3, side: 2 });
    const geometry = signalHeadGeometry();
    const seen = new Set();
    for (const light of world.lights || []) {
      const head = light.mesh && light.mesh.parent;
      if (!head || seen.has(head)) continue;
      seen.add(head);
      for (const child of head.children) {
        const p = child.geometry && child.geometry.parameters;
        if (p && Math.abs((p.width || 0) - 0.65) < 1e-3 && Math.abs((p.height || 0) - 1.65) < 1e-3) {
          child.geometry.dispose();
          child.geometry = geometry;
          child.material = housing;
          child.position.set(0, 0, 0);
          child.castShadow = true;
        }
      }
      light.mesh.scale.setScalar(1.15);
    }
  }

  // ---- per-frame work -----------------------------------------------------------------------
  // Far pedestrians and cars are a few pixels; skip drawing them (the bundle draws all of them).
  const PEOPLE_M = 90;
  const CARS_M = 260;

  function installFrame(world) {
    if (world._sceneryFrame) return;
    world._sceneryFrame = true;
    const render = world.render.bind(world);
    world.render = function (dt, draw) {
      for (const hook of world._sceneryHooks || []) {
        try {
          hook();
        } catch (err) {
          console.warn("semif-scenery: frame", err);
        }
      }
      return render(dt, draw);
    };
  }

  function distanceCull(world) {
    return () => {
      const player = world.sim && world.sim.player;
      if (!player) return;
      for (const ped of world.sim.pedestrians || []) {
        const g = world.people && world.people.get(ped.id);
        if (g) g.visible = Math.hypot(ped.x - player.x, ped.z - player.z) < PEOPLE_M;
      }
      for (const car of world.sim.traffic || []) {
        const g = world.vehicles && world.vehicles.get(car.id);
        if (g) g.visible = Math.hypot(car.x - player.x, car.z - player.z) < CARS_M;
      }
    };
  }

  // ---- traffic cars -------------------------------------------------------------------------
  // A Model Y is about 280k triangles, so only the nearest cars get one (level of detail);
  // farther cars keep the bundle's low-poly body. One InstancedMesh per Model Y part.
  const NEAR_CARS = 8;
  const NEAR_M = 90;

  function carPaint(car) {
    return PALETTE.carPaint[hash(car.id) % PALETTE.carPaint.length];
  }

  async function upgradeTraffic(world) {
    if (!T.loadModelY || !world.vehicles || !world.sim) return;
    const cars = (world.sim.traffic || []).filter((car) => car.type !== "motorcycle");
    if (!cars.length) return;
    const model = await T.loadModelY();
    if (world._sceneryBuild !== buildCount) return;
    model.updateMatrixWorld(true);
    const paint = T.materials && T.materials.get("model-y-paint");
    const parts = [];
    model.traverse((mesh) => {
      if (mesh.isMesh) parts.push({ mesh, local: mesh.matrixWorld.clone() });
    });
    const matrix = new T.Object3D();
    const color = new T.Color();
    const batches = parts.map(({ mesh, local }) => {
      const painted = !!paint && mesh.material === paint;
      const material = painted ? paint.clone() : mesh.material;
      if (painted) material.color.set("#ffffff");
      const inst = new T.InstancedMesh(mesh.geometry, material, NEAR_CARS);
      inst.castShadow = true;
      inst.receiveShadow = true;
      inst.frustumCulled = false;
      inst.count = 0;
      inst.name = "traffic-model-y";
      if (painted) {
        for (let i = 0; i < NEAR_CARS; i++) inst.setColorAt(i, color.set("#ffffff"));
      }
      world.scene.add(inst);
      return { inst, local, painted };
    });
    const detailed = new Set();
    const update = () => {
      const player = world.sim.player;
      const near = cars
        .map((car) => ({ car, d: Math.hypot(car.x - player.x, car.z - player.z) }))
        .filter((row) => row.d < NEAR_M)
        .sort((a, b) => a.d - b.d)
        .slice(0, NEAR_CARS)
        .map((row) => row.car);
      const now = new Set(near.map((car) => car.id));
      for (const car of cars) {
        const want = now.has(car.id);
        if (want === detailed.has(car.id)) continue;
        const group = world.vehicles.get(car.id);
        if (group) group.children.forEach((child) => (child.visible = !want));
        if (want) detailed.add(car.id);
        else detailed.delete(car.id);
      }
      near.forEach((car, i) => {
        matrix.position.set(car.x, 0, car.z);
        matrix.rotation.set(0, -car.heading, 0);
        matrix.updateMatrix();
        for (const { inst, local, painted } of batches) {
          inst.matrix.multiplyMatrices(matrix.matrix, local);
          inst.setMatrixAt(i, inst.matrix);
          if (painted) inst.setColorAt(i, color.set(carPaint(car)));
        }
      });
      for (const { inst, painted } of batches) {
        inst.matrix.identity();
        inst.count = near.length;
        inst.instanceMatrix.needsUpdate = true;
        if (painted && inst.instanceColor) inst.instanceColor.needsUpdate = true;
      }
    };
    world._sceneryHooks.push(update);
    update();
  }

  // ---- batching -----------------------------------------------------------------------------
  // The bundle batches static meshes per material in 80 m cells and streetlights / shrubs per
  // 70-80 m cell. On the larger maps that is thousands of draw calls, so after the scene is
  // ready: static batches are merged again in BATCH_M cells, and instanced props with the same
  // geometry and material become one InstancedMesh.
  const BATCH_M = 240;
  const MERGE_PROPS = new Set(["streetlight", "landscape-shrub"]);

  function isIdentity(m) {
    const e = m.elements;
    for (let i = 0; i < 16; i++) if (Math.abs(e[i] - (i % 5 === 0 ? 1 : 0)) > 1e-9) return false;
    return true;
  }

  function signature(geo) {
    const names = Object.keys(geo.attributes).sort().join(",");
    return `${geo.index ? "i" : "n"}:${names}:${Object.keys(geo.morphAttributes).length}`;
  }

  function consolidate(world) {
    const scene = world.scene;
    if (!T.mergeGeometries) return { statics: 0, props: 0 };
    const groups = new Map();
    for (const mesh of scene.children) {
      if (!mesh.isMesh || mesh.isInstancedMesh || mesh.name || mesh.children.length) continue;
      if (mesh === world.sensorCone || Array.isArray(mesh.material)) continue;
      mesh.updateMatrixWorld();
      if (!isIdentity(mesh.matrixWorld)) continue;
      const geo = mesh.geometry;
      if (!geo.boundingSphere) geo.computeBoundingSphere();
      const c = geo.boundingSphere.center;
      const key = `${mesh.material.uuid}:${signature(geo)}:${mesh.castShadow}:${Math.floor(c.x / BATCH_M)}:${Math.floor(c.z / BATCH_M)}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(mesh);
    }
    let statics = 0;
    for (const meshes of groups.values()) {
      if (meshes.length < 2) continue;
      const merged = T.mergeGeometries(meshes.map((m) => m.geometry));
      if (!merged) continue;
      const out = new T.Mesh(merged, meshes[0].material);
      out.castShadow = meshes[0].castShadow;
      out.receiveShadow = meshes[0].receiveShadow;
      out.name = "scenery-batch";
      for (const m of meshes) {
        scene.remove(m);
        m.geometry.dispose();
      }
      scene.add(out);
      statics += meshes.length - 1;
    }
    const props = new Map();
    for (const mesh of scene.children) {
      if (!mesh.isInstancedMesh || !MERGE_PROPS.has(mesh.name)) continue;
      // Each cell clones the part's geometry, so match on material and vertex layout instead.
      const geo = mesh.geometry;
      const key = `${mesh.name}:${mesh.material.uuid}:${geo.attributes.position.count}:${geo.index ? geo.index.count : 0}`;
      if (!props.has(key)) props.set(key, []);
      props.get(key).push(mesh);
    }
    let merges = 0;
    for (const list of props.values()) {
      if (list.length < 2) continue;
      const total = list.reduce((n, m) => n + m.count, 0);
      const out = new T.InstancedMesh(list[0].geometry, list[0].material, total);
      out.name = list[0].name;
      out.castShadow = list[0].castShadow;
      out.receiveShadow = list[0].receiveShadow;
      out.customDepthMaterial = list[0].customDepthMaterial;
      let at = 0;
      const tmp = new list[0].matrix.constructor();
      for (const m of list) {
        for (let i = 0; i < m.count; i++) {
          m.getMatrixAt(i, tmp);
          out.setMatrixAt(at++, tmp);
        }
        scene.remove(m);
      }
      out.instanceMatrix.needsUpdate = true;
      out.computeBoundingSphere();
      scene.add(out);
      merges += list.length - 1;
    }
    return { statics, props: merges };
  }

  // ---- sky, light and the onboard camera ----------------------------------------------------
  function atmosphere(world) {
    const scene = world.scene;
    if (scene.fog) {
      scene.fog.color.set(PALETTE.fog);
      scene.fog.near = 260;
      scene.fog.far = 1400;
    }
    if (world.renderer) world.renderer.toneMappingExposure = 1.0;
    scene.environmentIntensity = 0.75;
    scene.backgroundIntensity = 1.0;
    scene.backgroundBlurriness = 0.0;
    if (world.sun) {
      world.sun.intensity = 3.1;
      world.sun.color.set("#fff1dc");
    }
    // The onboard cameras sit at the windscreen: they see the hood, not the dashboard.
    const leather = T.materials && T.materials.get("model-y-leather");
    if (leather) leather.name = "Interior";
  }

  // ---- hooks --------------------------------------------------------------------------------
  let buildCount = 0;

  const api = {
    palette: PALETTE,
    kit(kit) {
      T = kit;
    },
    object(group, obj, world) {
      if (!T || !obj || obj.type !== "building") return false;
      try {
        return building(group, obj, world);
      } catch (err) {
        console.warn("semif-scenery: building", err);
        return false;
      }
    },
    built(world) {
      if (!T) return;
      buildCount += 1;
      world._sceneryBuild = buildCount;
      world._sceneryHooks = [distanceCull(world)];
      installFrame(world);
      try {
        restyleSignals(world);
      } catch (err) {
        console.warn("semif-scenery: signals", err);
      }
      Promise.resolve(world.ready)
        .then(() => {
          if (world._sceneryBuild !== buildCount) return;
          atmosphere(world);
          world._sceneryBatching = consolidate(world);
          world.renderer.shadowMap.needsUpdate = true;
          return upgradeTraffic(world);
        })
        .catch((err) => console.warn("semif-scenery: traffic", err));
    },
    minimap(ctx, data, project, scale) {
      if (!data || !data.objects) return;
      for (const o of data.objects) {
        if (o.type !== "building" && !(o.type === "parcel" && o.park)) continue;
        const turned = Math.abs(Math.sin(o.rotation || 0)) > 0.5;
        const w = (turned ? o.depth : o.width) * scale;
        const d = (turned ? o.width : o.depth) * scale;
        const [x, y] = project(o);
        ctx.fillStyle = o.type === "parcel" ? "#dbe8d3" : o.style === "skyscraper" ? "#c9ced6" : "#dcdfe4";
        ctx.fillRect(x - w / 2, y - d / 2, w, d);
      }
    },
  };
  window.SEMIF_SCENERY = api;
})();
