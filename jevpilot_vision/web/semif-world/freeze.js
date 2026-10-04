// Matrices set once (#58). three.js recomputes every node's matrix on every render, and a frame
// renders the scene several times (main view, post passes, onboard cameras). Most of the coast never
// moves after it is built, so its nodes stop updating. A node marked `userData.moves` (its own
// transform changes: the sky that follows the camera, a bobbing boat, the Ferris wheel's rim and
// gondolas, wheel pivots and their spinning rotors) keeps updating; its children that keep their
// place in it are still frozen, and follow it through their world matrices.
//
// Their matrices are computed here, once. Whoever moves a node after it is built must mark it
// `moves` when building it. The bundle's own cars (the Model Y) carry no marks, so its convention
// is honoured here: it steers each `wheel_fl/fr/rl/rr` pivot and spins the pivot's first child.
const WHEEL = /^wheel_[fr][lr]$/;

export function freezeStatic(node) {
  if (!node) return;
  if (WHEEL.test(node.name || "")) {
    node.userData.moves = true;
    if (node.children?.[0]) node.children[0].userData.moves = true;
  }
  if (!node.userData?.moves) {
    node.matrixAutoUpdate = false;
    node.updateMatrix?.();
  }
  for (const child of node.children || []) freezeStatic(child);
}
