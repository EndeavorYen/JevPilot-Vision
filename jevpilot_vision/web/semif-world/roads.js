// Roads: asphalt, pavements or shoulders and markings along every road's centre line, and a pad
// with crosswalks and stop bars at every junction. Any heading works; junction legs are straight
// and axis-aligned for their last 25 m (semif-worldgen.js), which is where crosswalks sit.
import { PALETTE, T, Batch, material, along, headingOf } from "./kit.js";

const PAVEMENT = 3.6; // harbour and festival streets have raised pavements
const SHOULDER = 2;
const DASH = 3;
const DASH_GAP = 6;
const LINE = 0.15;
const KERB_HEIGHT = 0.14;
const CLEAR = 13; // markings stop this far from a junction centre
const CROSSWALK_AT = 7.5; // as the bundle: pedestrians cross 7-8 m out from the junction
const STOP_BAR_AT = 10.5; // as the bundle's crossing stop line

const URBAN = new Set(["harbour", "festival"]);

// Index ranges of `points` that are at least `clear` metres from every junction.
function openRuns(points, junctions, clear) {
  const runs = [];
  let start = -1;
  for (let i = 0; i < points.length; i++) {
    const open = junctions.every((n) => Math.hypot(points[i].x - n.x, points[i].z - n.z) >= clear);
    if (open && start < 0) start = i;
    if (!open && start >= 0) {
      if (i - 1 > start) runs.push([start, i - 1]);
      start = -1;
    }
  }
  if (start >= 0 && points.length - 1 > start) runs.push([start, points.length - 1]);
  return runs;
}

function dashes(batch, points, offset, runs, y) {
  for (const [from, to] of runs) {
    for (let i = from; i < to; i++) {
      if (points[i].s % (DASH + DASH_GAP) < DASH) batch.ribbon(points, offset - LINE / 2, offset + LINE / 2, y, i, i + 1);
    }
  }
}

function solid(batch, points, offset, runs, y) {
  for (const [from, to] of runs) batch.ribbon(points, offset - LINE / 2, offset + LINE / 2, y, from, to);
}

export function buildRoads(world) {
  const asphalt = new Batch(), pavement = new Batch(), shoulder = new Batch(), median = new Batch(), marking = new Batch();
  const junctions = world.nodes.filter((n) => n.townJunction);

  for (const road of world.connectorRoads) {
    const pts = road.points, half = road.width / 2;
    asphalt.ribbon(pts, -half, half, 0.03);
    if (URBAN.has(road.kind)) {
      pavement.ribbon(pts, half, half + PAVEMENT, KERB_HEIGHT);
      pavement.ribbon(pts, -half - PAVEMENT, -half, KERB_HEIGHT);
    } else {
      shoulder.ribbon(pts, half, half + SHOULDER, 0.02);
      shoulder.ribbon(pts, -half - SHOULDER, -half, 0.02);
    }
    const runs = openRuns(pts, junctions, CLEAR);
    if (road.kind === "expressway") {
      median.ribbon(pts, -1, 1, 0.12);
      for (const side of [-1, 1]) {
        dashes(marking, pts, side * 5, runs, 0.045);
        solid(marking, pts, side * (half - 2.4), runs, 0.045);
      }
    } else {
      dashes(marking, pts, 0, runs, 0.045);
      if (!URBAN.has(road.kind)) for (const side of [-1, 1]) solid(marking, pts, side * (half - 0.35), runs, 0.045);
    }
  }

  for (const node of junctions) {
    const legs = world.edges.filter((e) => e.a === node.id || e.b === node.id);
    const half = Math.max(...legs.map((e) => e.width / 2)) + 1;
    asphalt.rect(node, 0, half * 2, half * 2, 0.035);
    for (const e of legs) {
      const c = e.a === node.id ? e.centerline : [...e.centerline].reverse();
      const out = headingOf(c[0], c[1]); // leaving the junction along this leg
      const w = e.width / 2;
      if (node.control === "signal") {
        const centre = along(node, out, CROSSWALK_AT);
        for (let t = -w + 0.6; t <= w - 0.6; t += 1.2) marking.rect(along(centre, out + Math.PI / 2, t), out, 3, 0.6, 0.05);
      }
      // The stop bar spans the arriving car's lane: right of the arriving heading.
      const arrive = out + Math.PI;
      const bar = along(node, out, STOP_BAR_AT);
      marking.rect(along(bar, arrive + Math.PI / 2, w / 2), out, 0.4, w, 0.05);
    }
  }

  const group = new T.Group();
  group.name = "semif-roads";
  group.add(asphalt.mesh(material(PALETTE.asphalt)));
  if (!pavement.empty) group.add(pavement.mesh(material(PALETTE.pavement)));
  if (!shoulder.empty) group.add(shoulder.mesh(material(PALETTE.shoulder)));
  if (!median.empty) group.add(median.mesh(material(PALETTE.median)));
  group.add(marking.mesh(material(PALETTE.marking, { roughness: 0.7 })));
  return group;
}
