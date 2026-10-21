// Marker sizes are CSS pixels in every map view, independent of grid resolution.
export const MAP_MARKERS = { robot: 12, halo: 19, goal: 11, goalDot: 4, anchor: 12, label: 12 };

export function svgScreenScale(view: { width: number; height: number }, screen: { width: number; height: number }) {
  // SVG's default xMidYMid meet also fits the height on wide, shallow maps.
  return Math.min(Math.max(1, screen.width) / Math.max(.001, view.width), Math.max(1, screen.height) / Math.max(.001, view.height));
}
