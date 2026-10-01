// Buildings, first pass: stucco blocks with a tiled roof slab, one merged mesh per colour.
// Footprints come from semif-worldgen.js, where they are also the simulation's collision boxes.
import { PALETTE, T, Batch, material } from "./kit.js";

export function buildBuildings(world) {
  const walls = PALETTE.stucco.map(() => new Batch());
  const roofs = PALETTE.roof.map(() => new Batch());
  let i = 0;
  for (const o of world.objects) {
    if (o.type !== "building") continue;
    walls[i % walls.length].box(o.x, o.z, o.width, o.depth, o.height);
    roofs[(i * 7) % roofs.length].box(o.x, o.z, o.width + 0.6, o.depth + 0.6, 0.5, o.height);
    i++;
  }
  const group = new T.Group();
  group.name = "semif-buildings";
  walls.forEach((b, k) => b.empty || group.add(b.mesh(material(PALETTE.stucco[k]), { cast: true })));
  roofs.forEach((b, k) => b.empty || group.add(b.mesh(material(PALETTE.roof[k]), { cast: true })));
  return group;
}
