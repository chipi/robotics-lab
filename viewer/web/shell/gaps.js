// The gaps that matter (RFC-0013 2.1, RFC-0012's first trigger): unknown ground within the drop margin of the plan, the floor the robot
// is about to pass over without knowing it is there. Pure, so a page test can ask it directly.

// RFC-0012: how far beside its way the robot needs floor it has seen (a drop is not a step it can take back); the pivot's
// drift and the sensor's blind sides are why it is wider than the robot
export const GAP_MARGIN_M = 0.45;

const sq = (v) => v * v;
function nearSeg(px, py, ax, ay, bx, by, r2) {
  const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
  const u = L2 > 0 ? Math.min(1, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / L2)) : 0;
  return sq(px - (ax + u * dx)) + sq(py - (ay + u * dy)) <= r2;
}

// A world model's grid ({res, origin, w, h, cells: "?.#..."}, cell k = j * w + i, '?' unknown) and a plan's path ([[x, y], ...]), both in the
// map frame: the unknown cells whose centre is within `margin` of the path (`gap`), and the other unknown cells (`fog`), as cell indexes.
export function gapCells(grid, path, margin = GAP_MARGIN_M) {
  const gap = [], fog = [], r2 = margin * margin, { res, origin, w, cells } = grid;
  const segs = path.length > 1 ? path.slice(1).map((b, k) => [path[k][0], path[k][1], b[0], b[1]]) : path.map((p) => [p[0], p[1], p[0], p[1]]);
  for (let k = 0; k < cells.length; k++) {
    if (cells[k] !== '?') continue;
    const x = origin[0] + ((k % w) + 0.5) * res, y = origin[1] + (((k / w) | 0) + 0.5) * res;
    (segs.some(([ax, ay, bx, by]) => nearSeg(x, y, ax, ay, bx, by, r2)) ? gap : fog).push(k);
  }
  return { gap, fog };
}
