// The sea surface: one flat sheet just below the road level, reaching past the far plane.
import { PALETTE, Batch, material } from "./kit.js";

export const SEA_LEVEL = -0.6;
const REACH = 6000;

export function buildSea() {
  const batch = new Batch();
  const y = SEA_LEVEL;
  batch.quad({ x: -REACH, y, z: -REACH }, { x: REACH, y, z: -REACH }, { x: REACH, y, z: REACH }, { x: -REACH, y, z: REACH });
  const mesh = batch.mesh(material(PALETTE.sea, { roughness: 0.25, metalness: 0.1 }), { receive: false });
  mesh.name = "semif-sea";
  return mesh;
}
