// Solmare Coast renderer (docs/superpowers/specs/2026-10-01-solmare-coast-design.md).
//
// The bundle calls the scenery hooks (BUNDLE_PATCHES.md). This module wraps the old-map layer
// (semif-scenery.js): on the coast map it draws the world itself, on every other map it hands each
// hook to the old layer unchanged.
import { PALETTE, T, setKit, resetCaches } from "./kit.js";
import { buildTerrain } from "./terrain.js";
import { createHeightField, seaPolygon } from "./heights.js";
import { buildSea, updateSea } from "./water.js";
import { buildRoads } from "./roads.js";
import { buildBuildings } from "./buildings.js";
import { buildSky, widenShadows, placeSun, applyLight } from "./sky.js";
import { sunDirection, gradeAt } from "./daylight.js";
import { createPost } from "./post.js";
import { clock, mountClock, showClock, tick } from "./clock.js";

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
    if (onCoast()) {
      for (const hook of frameHooks) {
        try {
          hook(view, dt);
        } catch (err) {
          console.warn("semif-world: frame", err);
        }
      }
    }
    return render(dt, draw);
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
  const light = applyLight(view, sky, clock.hours, dt);
  updateSea(sea, light, sunDirection(clock.hours), dt);
});

function buildCoast(view) {
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
  const ground = buildTerrain(world, field);
  sea = buildSea(ground.userData.grid);
  root.add(sky, ground, sea, buildRoads(world), buildBuildings(world));
  view.scene.add(root);
  widenShadows(view.sun);
  mountClock();
  showClock(true);
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
    if (!POST) return false;
    post ??= createPost();
    post.render(view, gradeAt(clock.hours));
    return true;
  },
  minimap(ctx, world, project, scale) {
    if (world?.type !== "coast") return legacy.minimap?.(ctx, world, project, scale);
    drawMinimap(ctx, world, project, scale);
  },
};
