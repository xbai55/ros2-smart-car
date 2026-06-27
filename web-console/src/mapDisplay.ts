export const UNKNOWN_VALUE = -1;
export const FREE_VALUE = 0;
export const LOW_CONFIDENCE_VALUE = 50;
export const OBSTACLE_VALUE = 100;

export const UNKNOWN_COLOR = "#0b2237";
export const FREE_COLOR = "#12384f";
export const LOW_CONFIDENCE_COLOR = "#23556a";
export const OBSTACLE_COLOR = "#19dfff";
export const GRID_STROKE_COLOR = "#08263d";

export function cellColor(value: number) {
  if (value < 0) return UNKNOWN_COLOR;
  if (value < 25) return FREE_COLOR;
  if (value < 65) return LOW_CONFIDENCE_COLOR;
  return OBSTACLE_COLOR;
}

export function cellAt(cells: number[], width: number, height: number, x: number, y: number) {
  if (x < 0 || y < 0 || x >= width || y >= height) return UNKNOWN_VALUE;
  return cells[y * width + x] ?? UNKNOWN_VALUE;
}

function neighborValues(cells: number[], width: number, height: number, x: number, y: number, radius = 1) {
  const values: number[] = [];
  for (let dy = -radius; dy <= radius; dy += 1) {
    for (let dx = -radius; dx <= radius; dx += 1) {
      if (dx === 0 && dy === 0) continue;
      values.push(cellAt(cells, width, height, x + dx, y + dy));
    }
  }
  return values;
}

export function occupiedNeighborCount(cells: number[], width: number, height: number, x: number, y: number, radius = 1) {
  return neighborValues(cells, width, height, x, y, radius).filter((value) => value >= 65).length;
}

function localContextReplacement(cells: number[], width: number, height: number, x: number, y: number) {
  const counts = { unknown: 0, free: 0, low: 0 };
  neighborValues(cells, width, height, x, y, 2).forEach((value) => {
    if (value >= 65) return;
    if (value < 0) counts.unknown += 1;
    else if (value < 25) counts.free += 1;
    else counts.low += 1;
  });

  if (counts.free >= 4 && counts.free >= counts.low && counts.free >= counts.unknown) return FREE_VALUE;
  if (counts.low >= 4 && counts.low >= counts.unknown) return LOW_CONFIDENCE_VALUE;
  if (counts.unknown > 0) return UNKNOWN_VALUE;
  return FREE_VALUE;
}

export function shouldRemoveObstacleNoise(cells: number[], width: number, height: number, x: number, y: number) {
  if (cellAt(cells, width, height, x, y) < 65) return false;
  const nearOccupied = occupiedNeighborCount(cells, width, height, x, y, 1);
  const widerOccupied = occupiedNeighborCount(cells, width, height, x, y, 2);
  return nearOccupied <= 1 && widerOccupied <= 3;
}

function shouldFillSmallInteriorHole(cells: number[], width: number, height: number, x: number, y: number) {
  const value = cellAt(cells, width, height, x, y);
  if (value >= 65 || value < 0) return false;
  const neighbors = neighborValues(cells, width, height, x, y, 1);
  const freeLike = neighbors.filter((neighbor) => neighbor >= 0 && neighbor < 65).length;
  const unknown = neighbors.filter((neighbor) => neighbor < 0).length;
  return freeLike >= 6 && unknown <= 1;
}

function hasOccupiedLineGap(cells: number[], width: number, height: number, x: number, y: number) {
  const directions = [
    [1, 0],
    [0, 1],
    [1, 1],
    [1, -1],
  ];

  return directions.some(([dx, dy]) => {
    const nearA = cellAt(cells, width, height, x - dx, y - dy) >= 65;
    const nearB = cellAt(cells, width, height, x + dx, y + dy) >= 65;
    const farA = cellAt(cells, width, height, x - dx * 2, y - dy * 2) >= 65;
    const farB = cellAt(cells, width, height, x + dx * 2, y + dy * 2) >= 65;
    return (nearA && nearB) || (nearA && farB) || (farA && nearB);
  });
}

function shouldBridgeSmallGap(cells: number[], width: number, height: number, x: number, y: number) {
  if (cellAt(cells, width, height, x, y) >= 65) return false;
  return hasOccupiedLineGap(cells, width, height, x, y) || occupiedNeighborCount(cells, width, height, x, y, 1) >= 5;
}

export function enhancedDisplayValue(cells: number[], width: number, height: number, x: number, y: number) {
  const value = cellAt(cells, width, height, x, y);
  if (shouldRemoveObstacleNoise(cells, width, height, x, y)) {
    return localContextReplacement(cells, width, height, x, y);
  }
  if (shouldBridgeSmallGap(cells, width, height, x, y)) {
    return OBSTACLE_VALUE;
  }
  if (shouldFillSmallInteriorHole(cells, width, height, x, y)) {
    return localContextReplacement(cells, width, height, x, y);
  }
  return value;
}
