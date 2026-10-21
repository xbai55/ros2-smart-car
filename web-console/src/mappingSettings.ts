export const MAPPING_RANGE_PRESETS = [0.5, 1, 3, 6] as const;
export const TURN_SPEED_PRESETS = [0.1, 0.15, 0.25, 0.35, 0.5] as const;
export const validTurnSpeed = (value: number) => Number.isFinite(value) && value >= 0.05 && value <= 0.6;
export const validMappingRange = (value: number) => (MAPPING_RANGE_PRESETS as readonly number[]).includes(value);
