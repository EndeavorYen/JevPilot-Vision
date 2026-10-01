// Solmare Coast renderer (docs/superpowers/specs/2026-10-01-solmare-coast-design.md).
//
// The bundle calls the scenery hooks (BUNDLE_PATCHES.md). This module wraps the old-map layer
// (semif-scenery.js): on the coast map it draws the world itself, on every other map it hands each
// hook to the old layer unchanged.
import { PALETTE, T, setKit, resetCaches } from "./kit.js";
import { buildTerrain, seaPolygon } from "./terrain.js";
import { buildSea } from "./water.js";
import { buildRoads } from "./roads.js";
import { buildBuildings } from "./buildings.js";

const legacy = window.SEMIF_SCENERY || {};
const onCoast = () => window.SEMIF_SIM?.world?.type === "coast";

function buildCoast(view) {
  resetCaches();
  // Stop the old layer's per-frame work and any upgrade it still has pending from an old map.
  view._sceneryBuild = {};
  view._sceneryHooks = [];
  const world = view.sim.world;
  const root = new T.Group();
  root.name = "semif-world";
  root.add(buildTerrain(world), buildSea(world), buildRoads(world), buildBuildings(world));
  view.scene.add(root);
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
    if (!onCoast()) return legacy.built?.(view);
    try {
      buildCoast(view);
    } catch (err) {
      console.error("semif-world: build", err);
    }
  },
  minimap(ctx, world, project, scale) {
    if (world?.type !== "coast") return legacy.minimap?.(ctx, world, project, scale);
    drawMinimap(ctx, world, project, scale);
  },
};
