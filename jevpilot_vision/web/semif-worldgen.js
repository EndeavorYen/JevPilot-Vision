// Solmare Coast: the open-world map (docs/superpowers/specs/2026-10-01-solmare-coast-design.md).
//
// One hand-laid road network. The seed changes signal offsets, buildings, traffic and people, not
// the roads. The world has the shape of the bundle's own Interstate 08 world (every edge carries a
// path, a centreline and a lane offset; junctions are townJunction nodes), so the bundle's physics,
// signals, traffic and planner drive it unchanged. It runs in the page and in the planner worker:
// no window, no DOM, and the same seed gives the same world in both.
(function (root) {
  "use strict";

  const STEP = 1.5; // path sample spacing, as in the bundle
  const LANE_OFFSET = 3; // every edge is driven 3 m right of its centreline
  const JUNCTION_STRAIGHT = 25; // straight, axis-aligned run every road keeps at a junction
  const MAX_LATERAL = 3; // m/s^2 at the speed limit on the tightest corner of an edge
  // No corner is tighter than this. The bundle's traffic finds the car ahead along its own heading
  // (within 2.35 m sideways), so on a tighter bend it loses a slowing car ahead and runs into it.
  const MIN_RADIUS = 60;
  const KMH = 1 / 3.6;

  const THEME = { name: "Solmare Coast", subtitle: "Sun, sea and the open road.", size: 0, traffic: 36, buildings: 0, limit: 100 * KMH };
  const BOUNDS = { minX: -1250, maxX: 1250, minZ: -800, maxZ: 800 };

  // Road kinds: nominal limit (the tightest corner may lower an edge's own), width, lane half width.
  const KINDS = {
    harbour: { limit: 50 * KMH, width: 12, laneHalfWidth: 3 },
    festival: { limit: 50 * KMH, width: 12, laneHalfWidth: 3 },
    coastal: { limit: 80 * KMH, width: 11, laneHalfWidth: 3 },
    valley: { limit: 70 * KMH, width: 10, laneHalfWidth: 3 },
    pass: { limit: 35 * KMH, width: 10, laneHalfWidth: 3 },
    expressway: { limit: 100 * KMH, width: 22, laneHalfWidth: 2 },
  };
  const CROSSING_KINDS = Object.keys(KINDS);

  // Porto Solmare: a 4 x 3 grid of junctions.
  const HX = [-1100, -1000, -900, -800];
  const HZ = [100, 200, 300];
  const hb = (c, r) => `harbour-${c}-${r}`;

  const NODES = [
    ...HZ.flatMap((z, r) => HX.map((x, c) => ({ id: hb(c, r), x, z }))),
    { id: "harbour-quay", x: -950, z: 300 },
    { id: "festival", x: 0, z: 250 },
    { id: "festival-gate", x: 0, z: 330 },
    { id: "coast-junction", x: 0, z: 520 },
    { id: "coast-bay", x: 555, z: 610 },
    { id: "pass-foot", x: 900, z: 250 },
    { id: "pass-belvedere", x: 1010, z: -10 },
    { id: "pass-top", x: 1120, z: -420 },
    { id: "ss1-west", x: -1100, z: -300 },
    { id: "ss1-w400", x: -400, z: -600 },
    { id: "ss1-junction", x: 0, z: -600 },
    { id: "ss1-e400", x: 400, z: -600 },
    { id: "ss1-e700", x: 700, z: -600 },
  ];
  // Junctions get signals or stop signs, crossings and turn smoothing; the rest are waypoints that
  // only split a road (same heading on both sides, so the lane path stays continuous).
  const JUNCTIONS = new Set([...HZ.flatMap((z, r) => HX.map((x, c) => hb(c, r))), "festival", "coast-junction", "ss1-junction", "pass-foot"]);
  const STOP_JUNCTIONS = new Set(["pass-foot"]);

  const ROW_NAMES = ["Via Garibaldi", "Via Roma", "Lungomare del Porto"];
  const COLUMN_NAMES = ["Via del Faro", "Via dei Pescatori", "Via delle Reti", "Via della Dogana"];

  // [from, to, kind, name, corners as [x, z, radius]]
  const ROADS = [
    ...HZ.flatMap((z, r) => [0, 1, 2].flatMap((c) =>
      r === 2 && c === 1
        ? [[hb(1, 2), "harbour-quay", "harbour", ROW_NAMES[r], []], ["harbour-quay", hb(2, 2), "harbour", ROW_NAMES[r], []]]
        : [[hb(c, r), hb(c + 1, r), "harbour", ROW_NAMES[r], []]])),
    ...[0, 1, 2, 3].flatMap((c) => [0, 1].map((r) => [hb(c, r), hb(c, r + 1), "harbour", COLUMN_NAMES[c], []])),
    [hb(3, 0), "festival", "valley", "Via delle Vigne", [[-620, 100, 90], [-480, -10, 90], [-330, -10, 90], [-200, 250, 90]]],
    ["festival", "pass-foot", "valley", "Strada dei Vigneti", [[180, 250, 100], [330, 120, 100], [520, 120, 100], [680, 250, 100]]],
    [hb(3, 2), "coast-junction", "coastal", "Lungomare Solmare", [[-640, 300, 150], [-420, 450, 150], [-240, 520, 150]]],
    ["coast-junction", "coast-bay", "coastal", "Lungomare Solmare", [[220, 520, 150], [450, 610, 150]]],
    ["coast-bay", "pass-foot", "coastal", "Lungomare Solmare", [[660, 610, 150], [900, 450, 120]]],
    ["festival", "festival-gate", "festival", "Viale del Festival", []],
    ["festival-gate", "coast-junction", "festival", "Viale del Festival", []],
    ["festival", "ss1-junction", "valley", "Strada del Colle", [[0, 120, 120], [-90, -60, 120], [-90, -200, 120], [0, -380, 120]]],
    [hb(0, 0), "ss1-west", "expressway", "SS-1 Costiera", []],
    ["ss1-west", "ss1-w400", "expressway", "SS-1 Costiera", [[-1100, -600, 300]]],
    ["ss1-w400", "ss1-junction", "expressway", "SS-1 Costiera", []],
    ["ss1-junction", "ss1-e400", "expressway", "SS-1 Costiera", []],
    ["ss1-e400", "ss1-e700", "expressway", "SS-1 Costiera", []],
    ["ss1-e700", "pass-top", "expressway", "SS-1 Costiera", [[1120, -600, 160]]],
    // Switchbacks: each bend turns 90 degrees, and two bends that turn the same way have 50 m of
    // straight between them, so the planner never faces a 180-degree turn within its horizon.
    ["pass-top", "pass-belvedere", "pass", "Passo del Falco", [[1120, -180, 60], [900, -180, 60], [900, -10, 60]]],
    ["pass-belvedere", "pass-foot", "pass", "Passo del Falco", [[1120, -10, 60], [1120, 160, 60], [900, 160, 60]]],
  ];
  // The SS-1 slows to 70 km/h on the harbour hill and 80 km/h either side of its junction.
  const EDGE_LIMITS = { [`${hb(0, 0)}>ss1-west`]: 70 * KMH, "ss1-w400>ss1-junction": 80 * KMH, "ss1-junction>ss1-e400": 80 * KMH };

  // Start points: [start node, first node to drive to]. Free driving goes round the destinations.
  const STARTS = {
    festival: ["festival-gate", "festival"],
    harbour: ["harbour-quay", hb(2, 2)],
    coast: ["coast-bay", "pass-foot"],
    pass: ["pass-belvedere", "pass-top"],
    highway: ["ss1-e400", "ss1-junction"],
  };
  const DESTINATIONS = ["festival-gate", "harbour-quay", "coast-bay", "pass-belvedere", "ss1-e400"];
  const START_LABELS = { festival: "Solmare Festival", harbour: "Porto Solmare", coast: "Lungomare", pass: "Passo del Falco", highway: "SS-1 Costiera" };

  // The sea lies south and east of this line.
  const SHORELINE = [[-1300, 345], [-760, 345], [-600, 380], [-430, 500], [-240, 560], [220, 560], [450, 650], [660, 650], [800, 600], [960, 470], [980, 330], [1170, 250], [1180, -200], [1300, -300]];

  // --- geometry, in the bundle's conventions: x east, z south, heading 0 north and pi/2 east
  const dist = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);
  const headingOf = (a, b) => Math.atan2(b.x - a.x, a.z - b.z);
  const along = (p, h, d) => ({ x: p.x + Math.sin(h) * d, z: p.z - Math.cos(h) * d });
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));

  // Same as the bundle's resampler: points every `step` metres, each with its arc length s.
  function resample(points, step) {
    const out = [{ x: points[0].x, z: points[0].z, s: 0 }];
    let s = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i], len = dist(a, b), n = Math.max(1, Math.ceil(len / step));
      for (let k = 1; k <= n; k++) {
        s += len / n;
        out.push({ x: a.x + (b.x - a.x) * k / n, z: a.z + (b.z - a.z) * k / n, s });
      }
    }
    return out;
  }

  // Same as the bundle's lane shift: each point moved `d` to the right of the local heading.
  function shift(points, d) {
    return points.map((p, i) => along(p, headingOf(points[Math.max(0, i - 1)], points[Math.min(points.length - 1, i + 1)]) + Math.PI / 2, d));
  }

  // Same generator as the bundle's seeded RNG.
  function rng(seed) {
    let t = Number(seed) >>> 0;
    return () => {
      t += 1831565813;
      let e = t;
      e = Math.imul(e ^ (e >>> 15), e | 1);
      e ^= e + Math.imul(e ^ (e >>> 7), e | 61);
      return ((e ^ (e >>> 14)) >>> 0) / 4294967296;
    };
  }
  const pick = (r, list) => list[Math.floor(r() * list.length)];

  // A polyline with each corner rounded to its own radius. Throws when two roundings overlap.
  function fillet(points, label) {
    const out = [{ x: points[0].x, z: points[0].z }];
    const tangent = points.map((p, i) => {
      if (i === 0 || i === points.length - 1 || !p.r) return 0;
      const turn = wrap(headingOf(p, points[i + 1]) - headingOf(points[i - 1], p));
      return p.r * Math.tan(Math.abs(turn) / 2);
    });
    for (let i = 1; i < points.length; i++) {
      if (tangent[i - 1] + tangent[i] > dist(points[i - 1], points[i]) + 1e-6) throw Error(`${label}: corners ${i - 1} and ${i} overlap`);
      if (points[i].r && points[i].r < MIN_RADIUS) throw Error(`${label}: corner ${i} is tighter than ${MIN_RADIUS} m`);
    }
    for (let i = 1; i < points.length - 1; i++) {
      const p = points[i];
      const h1 = headingOf(points[i - 1], p);
      const turn = wrap(headingOf(p, points[i + 1]) - h1);
      if (!tangent[i] || Math.abs(turn) < 1e-9) {
        out.push({ x: p.x, z: p.z });
        continue;
      }
      const side = Math.sign(turn); // +1 turns right
      const centre = along(along(p, h1, -tangent[i]), h1 + side * Math.PI / 2, p.r);
      const n = Math.max(2, Math.ceil((Math.abs(turn) * p.r) / 0.75));
      for (let k = 0; k <= n; k++) out.push(along(centre, h1 + (turn * k) / n - side * Math.PI / 2, p.r));
    }
    out.push({ x: points.at(-1).x, z: points.at(-1).z });
    return out;
  }

  function buildRoads(byId, seed) {
    const edges = [];
    const connectorRoads = [];
    for (const [a, b, kind, name, corners] of ROADS) {
      const A = byId[a], B = byId[b], spec = KINDS[kind];
      const control = [A, ...corners.map(([x, z, r]) => ({ x, z, r })), B];
      const centerline = resample(fillet(control, `${a}>${b}`), STEP);
      const path = resample(shift(centerline, LANE_OFFSET), STEP);
      const minRadius = Math.min(Infinity, ...corners.map((c) => c[2]));
      const cornerLimit = Math.sqrt(MAX_LATERAL * minRadius);
      const speedLimit = Math.floor(Math.min(EDGE_LIMITS[`${a}>${b}`] ?? spec.limit, cornerLimit) * 10) / 10;
      A.neighbors.push(b);
      B.neighbors.push(a);
      const id = `${a}-${b}`;
      edges.push({ id, a, b, oneWay: false, width: spec.width, speedLimit, kind, name, length: path.at(-1).s, path, centerline, laneOffset: LANE_OFFSET, laneHalfWidth: spec.laneHalfWidth, minRadius });
      const h0 = headingOf(centerline[0], centerline[1]);
      const h1 = headingOf(centerline.at(-2), centerline.at(-1));
      connectorRoads.push({ id, points: resample([along(centerline[0], h0, -0.25), ...centerline, along(centerline.at(-1), h1, 0.25)], STEP), width: spec.width, kind, twoWay: true });
    }
    return { edges, connectorRoads };
  }

  // Heading of each road where it reaches `node`, keyed by the neighbour it comes from.
  function approaches(node, edges) {
    const out = [];
    for (const e of edges) {
      if (e.a !== node.id && e.b !== node.id) continue;
      const c = e.centerline;
      const from = e.b === node.id ? e.a : e.b;
      const heading = e.b === node.id ? headingOf(c.at(-2), c.at(-1)) : headingOf(c[1], c[0]);
      out.push({ from, heading });
    }
    return out;
  }

  function controls(nodes, edges) {
    const objects = [];
    for (const n of nodes) {
      if (!n.townJunction) continue;
      for (const { from, heading } of approaches(n, edges)) {
        const p = along(along(n, heading, -9), heading + Math.PI / 2, 6.9);
        objects.push({ id: `${n.control}-${n.id}-${from}`, type: n.control === "stop" ? "stop_sign" : "traffic_light", x: p.x, z: p.z, nodeId: n.id, approach: heading, height: n.control === "stop" ? 2.8 : 4.8 });
      }
    }
    return objects;
  }

  // Harbour blocks: a ring of houses round each block, 17 m back from the street centre lines.
  // Buildings are the bundle's only collision objects, so they stay axis-aligned and off the roads.
  function harbourBuildings(r) {
    const out = [];
    const seen = new Set();
    for (let c = 0; c < HX.length - 1; c++) {
      for (let row = 0; row < HZ.length - 1; row++) {
        const x0 = HX[c] + 17, x1 = HX[c + 1] - 17, z0 = HZ[row] + 17, z1 = HZ[row + 1] - 17;
        const spots = [];
        for (let x = x0; x <= x1 + 1e-6; x += (x1 - x0) / 3) spots.push([x, z0], [x, z1]);
        for (let z = z0; z <= z1 + 1e-6; z += (z1 - z0) / 3) spots.push([x0, z], [x1, z]);
        for (const [x, z] of spots) {
          const key = `${Math.round(x)}:${Math.round(z)}`;
          if (seen.has(key)) continue;
          seen.add(key);
          out.push({ id: `building-${out.length}`, type: "building", style: pick(r, ["townhouse", "townhouse", "villa", "shop"]), x, z, width: 12 + Math.floor(r() * 3), depth: 12 + Math.floor(r() * 3), height: 8 + Math.floor(r() * 3) * 3, rotation: 0 });
        }
      }
    }
    return out;
  }

  // Pedestrians in the bundle's own format. Walkers pace a straight pavement 7.05 m off a street's
  // centre line; crossers use the bundle's crosswalk over the north leg of a signal junction. No one
  // jaywalks: a jaywalker re-crosses whenever the player is 8-35 m away, so a player queued at the
  // junction would hold every approach on "Yield to pedestrian" for ever.
  function pedestrians(world, r) {
    const streets = world.edges.filter((e) => e.kind === "harbour" || e.kind === "festival");
    const crossable = world.nodes.filter((n) => n.control === "signal" && n.legs.includes("north") && (n.id.startsWith("harbour") || n.id.startsWith("festival") || n.id === "coast-junction"));
    const out = [];
    for (let i = 0; i < 28; i++) {
      const e = pick(r, streets);
      const reverse = r() < 0.5;
      const from = world.byId[reverse ? e.b : e.a], to = world.byId[reverse ? e.a : e.b];
      const heading = headingOf(from, to);
      const side = r() < 0.5 ? -1 : 1;
      const start = along(along(from, heading, 14), heading + Math.PI / 2, 7.05 * side);
      const length = e.length - 28;
      const crossing = i % 2 === 0;
      const node = crossing ? pick(r, crossable) : from;
      const progress = crossing ? 0 : r() * length;
      const at = crossing ? { x: node.x - 8, z: node.z - 7.8 } : along(start, heading, progress);
      out.push({
        id: `pedestrian-${i}`, type: "pedestrian", nodeId: node.id, x: at.x, z: at.z, progress,
        walkPath: { start, heading, length }, direction: r() > 0.5 ? 1 : -1, crossing, jaywalker: false,
        walking: false, speed: 0, width: 0.6, depth: 0.6, height: 1.7,
      });
    }
    return out;
  }

  const LEG_NAMES = ["north", "east", "south", "west"];

  function generate(seed, type) {
    const startName = String(type ?? "").split(":")[1];
    const start = STARTS[startName] ? startName : "festival";
    const r = rng(Number(seed) + 7331);
    const nodes = NODES.map((n) => ({
      id: n.id, x: n.x, z: n.z, neighbors: [],
      control: JUNCTIONS.has(n.id) ? (STOP_JUNCTIONS.has(n.id) ? "stop" : "signal") : "none",
      offset: Math.floor(r() * 14),
      ...(JUNCTIONS.has(n.id) ? { townJunction: true } : {}),
    }));
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const { edges, connectorRoads } = buildRoads(byId, seed);
    for (const n of nodes) {
      // Legs are named by the direction a car leaves the junction in.
      n.legs = approaches(n, edges).map(({ heading }) => LEG_NAMES[((Math.round(wrap(heading + Math.PI) / (Math.PI / 2)) % 4) + 4) % 4]);
      if (n.control === "signal" && n.legs.length === 2) n.control = "stop";
    }
    const [startNode, nextNode] = STARTS[start];
    let destinationIndex = (DESTINATIONS.indexOf(startNode) + 1) % DESTINATIONS.length;
    const world = {
      seed, type: "coast", start, selectValue: `coast:${start}`, theme: THEME,
      nodes, byId, edges, connectorRoads,
      objects: [...controls(nodes, edges), ...harbourBuildings(r)],
      xs: [BOUNDS.minX, BOUNDS.maxX], zs: [BOUNDS.minZ, BOUNDS.maxZ], bounds: { ...BOUNDS },
      startNode, nextNode, destination: DESTINATIONS[destinationIndex], destinations: DESTINATIONS.slice(),
      visual: { shoreline: SHORELINE.map(([x, z]) => ({ x, z })) },
    };
    world.pedestrians = (sim) => pedestrians(world, sim);
    // Free driving: after an arrival the bundle asks for the next stop round the coast every tick
    // until a route to it builds, and commits it only then, so a failed reroute never skips a stop.
    world.peekDestination = () => byId[DESTINATIONS[(destinationIndex + 1) % DESTINATIONS.length]];
    world.commitDestination = (id) => {
      destinationIndex = DESTINATIONS.indexOf(id);
      world.destination = id;
    };
    return world;
  }

  // Extra rows for the bundle's navigation table, keyed by road kind; `turn` is the next crossing's.
  function navigation(turn) {
    const turning = turn === "left" || turn === "right";
    return {
      harbour: [turning ? `Turn ${turn} in Porto Solmare` : "Continue through Porto Solmare", turn],
      festival: [turning ? `Turn ${turn} at the festival` : "Follow Viale del Festival", turn],
      coastal: [turning ? `Turn ${turn} off the Lungomare` : "Follow the Lungomare", turn],
      valley: [turning ? `Turn ${turn} at the vineyards` : "Follow the valley road", turn],
      pass: [turning ? `Turn ${turn} at the foot of the pass` : "Take the Passo del Falco", turn],
      expressway: [turning ? `Turn ${turn} off the SS-1` : "Follow the SS-1 Costiera", turn],
    };
  }

  // <option>s for the world picker: the start points on the coast, the old maps elsewhere.
  function options(type) {
    if (!String(type).startsWith("coast")) {
      return '<option value="city">Skyline City</option><option value="town">Small town</option><option value="highway">Interstate 08</option>';
    }
    return Object.entries(START_LABELS).map(([k, label]) => `<option value="coast:${k}">${label}</option>`).join("");
  }

  const pickerLabel = (type) => (String(type).startsWith("coast") ? "Start from" : "Change map");

  root.SEMIF_WORLDGEN = { THEME, KINDS, CROSSING_KINDS, STARTS, DESTINATIONS, JUNCTION_STRAIGHT, MAX_LATERAL, MIN_RADIUS, generate, navigation, options, pickerLabel };
})(globalThis);
