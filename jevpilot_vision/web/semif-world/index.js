// Solmare Coast renderer (docs/superpowers/specs/2026-10-01-solmare-coast-design.md).
//
// The bundle calls the scenery hooks (BUNDLE_PATCHES.md). This module wraps the old-map layer
// (semif-scenery.js): on the coast map it draws the world itself, on every other map it hands each
// hook to the old layer unchanged.
import { PALETTE, T, setKit, resetCaches } from "./kit.js";
import { buildTerrain, groundGrid } from "./terrain.js";
import { placeVegetation, buildVegetation, updateVegetation } from "./vegetation.js";
import { buildFestival, updateFestival } from "./festival.js";
import { placeProps, buildProps, updateProps } from "./props.js";
import { HERO_MODELS, buildHero, buildTrafficFor } from "./vehicles.js";
import { buildPedestrian, placeCrowds, buildCrowds } from "./people.js";
import { createHeightField, seaPolygon } from "./heights.js";
import { buildSea, updateSea } from "./water.js";
import { buildRoads } from "./roads.js";
import { buildBuildings } from "./buildings.js";
import { buildSky, widenShadows, placeSun, applyLight } from "./sky.js";
import { sunDirection, gradeAt } from "./daylight.js";
import { createPost } from "./post.js";
import { clock, mountClock, showClock, tick } from "./clock.js";
import { settleQuality } from "./quality.js";
import "./perf.js";
import { mountGfx, showGfx, gfxTick } from "./gfx-panel.js";

const legacy = window.SEMIF_SCENERY || {};
// ?post=0 draws the main view straight to the screen, without bloom or grade.
const POST = new URLSearchParams(globalThis.location?.search || "").get("post") !== "0";
const onCoast = () => window.SEMIF_SIM?.world?.type === "coast";

// The coast is about 2.5 km across; the bundle's camera stops at 1.2 km.
const COAST_FAR = 3000;
const BUNDLE_FAR = 1200;

// Work done every frame on the coast, as (view, dt), before the bundle draws.
const frameHooks = [];

function installFrame(view) {
  if (view._semifWorldFrame) return;
  view._semifWorldFrame = true;
  const render = view.render.bind(view);
  view.render = function (dt, draw) {
    if (!onCoast()) return render(dt, draw);
    for (const hook of frameHooks) {
      try {
        hook(view, dt);
      } catch (err) {
        console.warn("semif-world: frame", err);
      }
    }
    const perf = window.SEMIF_PERF;
    if (!perf) return render(dt, draw);
    perf.frame();
    return perf.span("main", view.renderer, () => render(dt, draw));
  };
}

function setFar(view, far) {
  if (!view.camera || view.camera.far === far) return;
  view.camera.far = far;
  view.camera.updateProjectionMatrix();
}

let sky = null;
let sea = null;
let post = null;

frameHooks.push((view, dt) => {
  tick(dt);
  gfxTick(dt);
  const light = applyLight(view, sky, clock.hours, dt);
  updateSea(sea, light, sunDirection(clock.hours), dt);
  updateVegetation(dt);
  updateFestival(dt);
  updateProps(dt);
});

// --- vehicles and people (#25) -----------------------------------------------------------------

// The hero car, a Tesla (#47): the one picked with K in this page, else ?car=cybercab|model-y,
// else the last one picked with K, else the Cybercab-style car. A name from the old line-up (gt,
// roadster, rally) falls back to the default.
let picked = null;
let loadModelY = null; // the bundle's own Model Y loader, handed over by the coast-hero patch
function heroModel() {
  if (picked) return picked;
  const asked = new URLSearchParams(globalThis.location?.search || "").get("car");
  if (HERO_MODELS.includes(asked)) return asked;
  try {
    const saved = globalThis.localStorage?.getItem("semif-car");
    if (HERO_MODELS.includes(saved)) return saved;
  } catch (_) {}
  return HERO_MODELS[0];
}

// The Model Y is the bundle's glb (one geometry per call); without its loader, the default car.
function heroFor(model) {
  if (model === "model-y" && loadModelY) return loadModelY();
  return Promise.resolve(buildHero(model));
}

// The bundle asks for its hero car here first (BUNDLE_PATCHES.md `coast-hero`), handing over its
// Model Y loader; off the coast it gets undefined and loads its own Model Y.
window.SEMIF_WORLD_KIT = {
  hero(view, bundleModelY) {
    if (view?.sim?.world?.type !== "coast") return undefined;
    if (bundleModelY) loadModelY = bundleModelY;
    // It runs inside the bundle's build(): a failure must reach its .catch, not abort the build.
    try {
      return heroFor(heroModel());
    } catch (err) {
      return Promise.reject(err);
    }
  },
};

let heroSwap = false;
let swapSeq = 0; // the latest K press; a car loaded for an earlier one is dropped (#47)
globalThis.document?.addEventListener?.("keydown", (e) => {
  if (e.code !== "KeyK" || e.repeat || e.ctrlKey || e.metaKey || e.altKey || !onCoast()) return;
  if (/input|select|textarea/i.test(e.target?.tagName || "")) return;
  const next = HERO_MODELS[(HERO_MODELS.indexOf(heroModel()) + 1) % HERO_MODELS.length];
  picked = next;
  try {
    globalThis.localStorage?.setItem("semif-car", next);
  } catch (_) {}
  heroSwap = true;
});

function dispose(node) {
  node.geometry?.dispose?.();
  (node.children || []).forEach(dispose);
}

// Moves a model's parts into the bundle's own group, which it keeps positioning every frame.
function dress(group, model) {
  for (const child of group.children || []) dispose(child);
  group.clear();
  for (const child of [...model.children]) group.add(child);
  group.name = model.name;
  group.userData.semifDressed = true;
}

function dressAgents(view) {
  if (view.vehicles?.size) {
    let cars = null;
    for (const [id, group] of view.vehicles) {
      if (group.userData.semifDressed) continue;
      cars ??= new Map((view.sim.traffic || []).map((c) => [c.id, c]));
      dress(group, buildTrafficFor(cars.get(id) || { id }));
    }
  }
  if (view.people?.size) {
    for (const [id, group] of view.people) {
      if (group.userData.semifDressed) continue;
      const person = buildPedestrian(id);
      dress(group, person);
      group.userData.limbs = person.userData.limbs;
    }
  }
  if (heroSwap && view.player && view.heroCar && !view.sim.crash) {
    heroSwap = false;
    const player = view.player;
    const seq = ++swapSeq;
    heroFor(heroModel())
      .then((hero) => {
        // A later K press, a new map or a crash while the glb loaded: this car is no longer wanted.
        if (seq !== swapSeq || view.player !== player) return dispose(hero);
        if (view.sim.crash) {
          heroSwap = true; // swap once the crash is over, as asked
          return dispose(hero);
        }
        for (const child of player.children || []) dispose(child);
        player.clear();
        player.add(hero);
        view.heroCar = hero;
        player.userData.eyeHeight = hero.userData.eyeHeight;
        player.userData.eyeForward = hero.userData.eyeForward;
      })
      .catch((err) => console.warn("semif-world: hero", err));
  }
}

frameHooks.push((view) => dressAgents(view));

function buildCoast(view) {
  // Settled before anything is built: the builders read gfx.quality (quality.js).
  settleQuality(view.renderer?.getContext?.());
  window.SEMIF_PERF?.attach(view.renderer?.getContext?.());
  resetCaches();
  // Stop the old layer's per-frame work and any upgrade it still has pending from an old map.
  view._sceneryBuild = {};
  view._sceneryHooks = [];
  installFrame(view);
  setFar(view, COAST_FAR);
  const world = view.sim.world;
  const root = new T.Group();
  root.name = "semif-world";
  sky = buildSky();
  const field = createHeightField(world);
  const grid = groundGrid(world, field);
  const ground = buildTerrain(world, field, grid);
  sea = buildSea(grid);
  const plants = buildVegetation(placeVegetation(world, field, grid));
  root.add(sky, ground, sea, buildRoads(world, field), buildBuildings(world, field, grid), plants, buildFestival(world, field, grid), buildProps(placeProps(world, field, grid)), buildCrowds(placeCrowds(world, field, grid)));
  view.scene.add(root);
  widenShadows(view.sun);
  mountClock();
  showClock(true);
  mountGfx();
  showGfx(true);
  applyLight(view, sky, clock.hours, 0);
  return root;
}

function drawMinimap(ctx, world, project, scale) {
  ctx.fillStyle = PALETTE.minimap.sea;
  ctx.beginPath();
  seaPolygon(world.visual.shoreline, world.bounds).forEach((p, i) => (i ? ctx.lineTo(...project(p)) : ctx.moveTo(...project(p))));
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = PALETTE.minimap.building;
  for (const o of world.objects) {
    if (o.type !== "building") continue;
    const [x, y] = project(o);
    ctx.fillRect(x - (o.width * scale) / 2, y - (o.depth * scale) / 2, o.width * scale, o.depth * scale);
  }
}

window.SEMIF_SCENERY = {
  palette: legacy.palette,
  kit(kit) {
    setKit(kit);
    legacy.kit?.(kit);
  },
  object(group, obj, view) {
    if (!onCoast()) return legacy.object?.(group, obj, view) ?? false;
    return obj?.type === "building"; // drawn by buildBuildings
  },
  built(view) {
    if (!onCoast()) {
      setFar(view, BUNDLE_FAR);
      showClock(false);
      showGfx(false);
      window.SEMIF_PERF?.attach(null); // old maps render exactly as before: no timer queries
      return legacy.built?.(view);
    }
    try {
      buildCoast(view);
    } catch (err) {
      console.error("semif-world: build", err);
    }
  },
  sun(view, player) {
    if (!onCoast()) return false;
    placeSun(view.sun, player, clock.hours);
    return true;
  },
  present(view) {
    if (!onCoast()) return false;
    if (!POST || post === false) return false;
    try {
      post ??= createPost();
      post.render(view, gradeAt(clock.hours));
      return true;
    } catch (err) {
      // No float render targets on this GPU, or the like: the bundle draws the view directly.
      console.warn("semif-world: post-processing off", err);
      post = false;
      view.renderer.setRenderTarget?.(null);
      return false;
    }
  },
  minimap(ctx, world, project, scale) {
    if (world?.type !== "coast") return legacy.minimap?.(ctx, world, project, scale);
    drawMinimap(ctx, world, project, scale);
  },
};
