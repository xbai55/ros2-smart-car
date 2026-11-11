type Point = {x: number; y: number};
type Viewport = {left: number; top: number; width: number; height: number};

export const launcherSize = 64;
const margin = 8;
const gap = 12;
const fit = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

export function placeAssistant(point: Point, viewport: Viewport, workspaceTop: number, expanded: boolean) {
  const left = viewport.left + margin;
  const right = viewport.left + viewport.width - margin;
  const bottom = viewport.top + viewport.height - margin;
  const top = fit(workspaceTop, viewport.top + margin, bottom - 252);
  const launcher = {
    x: fit(point.x, left, right - launcherSize),
    y: fit(point.y, top, bottom - launcherSize),
  };
  const width = Math.min(expanded ? 760 : 400, right - left);
  const height = Math.min(expanded ? 760 : 560, bottom - top);
  const above = launcher.y - gap - top;
  const below = bottom - launcher.y - launcherSize - gap;
  const before = launcher.x - gap - left;
  const after = right - launcher.x - launcherSize - gap;
  const vertical = Math.max(above, below);
  const horizontal = Math.max(before, after);

  // Dock on the side if it preserves more space and leaves room for the controls.
  if (horizontal >= Math.min(width, 220) && Math.min(1, horizontal / width) > vertical / height) {
    const panelWidth = Math.min(width, horizontal);
    return {launcher, panel: {
      left: before >= after ? launcher.x - gap - panelWidth : launcher.x + launcherSize + gap,
      top: fit(launcher.y + launcherSize - height, top, bottom - height),
      width: panelWidth, height,
    }};
  }

  const panelHeight = Math.max(0, Math.min(height, vertical));
  return {launcher, panel: {
    left: fit(launcher.x + launcherSize - width, left, right - width),
    top: above >= below ? launcher.y - gap - panelHeight : launcher.y + launcherSize + gap,
    width, height: panelHeight,
  }};
}
