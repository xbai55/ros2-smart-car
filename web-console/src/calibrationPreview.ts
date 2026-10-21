import type { CalibrationPair, DrawingDescriptor } from "./labNavigation";

// Read-only feedback; the vehicle remains responsible for accepting registration.
export function calibrationPreview(pairs: CalibrationPair[], drawing: DrawingDescriptor) {
  if (pairs.length !== 4) return null;
  const points = pairs.map(p => [p.drawing.x / drawing.width, p.drawing.y / drawing.height]);
  const coverageX = Math.max(...points.map(p => p[0])) - Math.min(...points.map(p => p[0]));
  const coverageY = Math.max(...points.map(p => p[1])) - Math.min(...points.map(p => p[1]));
  const concentrated = coverageX < .3 || coverageY < .3;
  const design = points.map(([x, y]) => [x, y, 1]);
  const normal = [0, 1, 2].map(i => [0, 1, 2].map(j => design.reduce((sum, row) => sum + row[i] * row[j], 0)));
  const solve = (axis: "x" | "y") => {
    const rows = normal.map((row, i) => [...row, design.reduce((sum, p, k) => sum + p[i] * pairs[k].world[axis], 0)]);
    for (let col = 0; col < 3; col++) {
      let pivot = col;
      for (let r = col + 1; r < 3; r++) if (Math.abs(rows[r][col]) > Math.abs(rows[pivot][col])) pivot = r;
      if (Math.abs(rows[pivot][col]) < 1e-9) return null;
      [rows[col], rows[pivot]] = [rows[pivot], rows[col]];
      const value = rows[col][col]; rows[col] = rows[col].map(v => v / value);
      for (let r = 0; r < 3; r++) if (r !== col) {
        const factor = rows[r][col]; rows[r] = rows[r].map((v, j) => v - factor * rows[col][j]);
      }
    }
    return rows.map(row => row[3]);
  };
  const x = solve("x"), y = solve("y");
  if (!x || !y) return { coverageX, coverageY, concentrated: true, errors: null, maxError: null };
  const errors = design.map((p, i) => Math.hypot(
    p.reduce((sum, v, j) => sum + v * x[j], 0) - pairs[i].world.x,
    p.reduce((sum, v, j) => sum + v * y[j], 0) - pairs[i].world.y));
  return { coverageX, coverageY, concentrated, errors, maxError: Math.max(...errors) };
}
