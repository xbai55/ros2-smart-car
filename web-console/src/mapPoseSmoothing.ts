export type DisplayPoseCell = {
  x: number;
  y: number;
  yawDeg: number;
  motionYawDeg?: number;
};

export type ManualCommand = "forward" | "backward" | "left" | "right" | string;

export type MapFrame = {
  width: number;
  height: number;
  resolution: number;
  originX: number;
  originY: number;
};

export type MapPoseLike = {
  x: number;
  y: number;
  yaw: number;
};

export type VelocityLike = {
  linear_x: number;
  linear_y: number;
  angular_z: number;
};

export type VelocityStatusLike = VelocityLike & {
  ok?: boolean;
};

type SmoothOptions = {
  positionAlpha?: number;
  yawAlpha?: number;
  positionDeadbandCells?: number;
  yawDeadbandDeg?: number;
  teleportDistanceCells?: number;
};

function shortestAngleDiffDeg(from: number, to: number) {
  return ((((to - from) % 360) + 540) % 360) - 180;
}

function normalizeDeg(deg: number) {
  return ((deg % 360) + 360) % 360;
}

function cleanDegZero(deg: number) {
  return Object.is(deg, -0) ? 0 : deg;
}

function degToRad(deg: number) {
  return (deg * Math.PI) / 180;
}

function commandVector(command: ManualCommand, yawDeg: number) {
  const yaw = degToRad(yawDeg);
  const forward = { x: Math.cos(yaw), y: Math.sin(yaw) };
  const left = { x: Math.sin(yaw), y: -Math.cos(yaw) };
  if (command === "forward") return { x: -forward.x, y: -forward.y };
  if (command === "backward") return forward;
  if (command === "left") return { x: -left.x, y: -left.y };
  if (command === "right") return left;
  return null;
}

export function isDriveCommand(command: ManualCommand) {
  return command === "forward"
    || command === "backward"
    || command === "left"
    || command === "right"
    || command === "turn_l"
    || command === "turn_r"
    || command === "turn_left"
    || command === "turn_right";
}

export function mapPoseToScreenCell(frame: MapFrame, pose: MapPoseLike): DisplayPoseCell {
  const mapX = (pose.x - frame.originX) / frame.resolution;
  const mapY = (pose.y - frame.originY) / frame.resolution;
  const yawDeg = 180 - (pose.yaw * 180) / Math.PI;
  const motionYawDeg = -(pose.yaw * 180) / Math.PI;
  return {
    x: mapX,
    y: frame.height - mapY,
    yawDeg: cleanDegZero(yawDeg),
    motionYawDeg: cleanDegZero(motionYawDeg),
  };
}

export function projectPoseByCommand(
  pose: DisplayPoseCell,
  command: ManualCommand,
  deltaSeconds: number,
  speedCellsPerSecond: number,
  turnDegreesPerSecond = 14,
) {
  if (deltaSeconds <= 0) return pose;

  if (command === "turn_l" || command === "turn_left" || command === "turn_r" || command === "turn_right") {
    const sign = command === "turn_l" || command === "turn_left" ? -1 : 1;
    const motionYawDeg = (pose.motionYawDeg ?? pose.yawDeg) + sign * turnDegreesPerSecond * deltaSeconds;
    return {
      ...pose,
      yawDeg: normalizeDeg(motionYawDeg + 180),
      motionYawDeg,
    };
  }

  const expected = commandVector(command, pose.motionYawDeg ?? pose.yawDeg);
  if (!expected || speedCellsPerSecond <= 0) return pose;

  const distance = deltaSeconds * speedCellsPerSecond;
  return {
    ...pose,
    x: pose.x + expected.x * distance,
    y: pose.y + expected.y * distance,
  };
}

export function hasActiveVelocity(velocity: VelocityLike, epsilon = 0.0001) {
  return Math.abs(velocity.linear_x) > epsilon
    || Math.abs(velocity.linear_y) > epsilon
    || Math.abs(velocity.angular_z) > epsilon;
}

export function shouldApplySlamCorrection(
  slamCorrectionEnabled: boolean,
  slamPoseChanged: boolean,
  lastCommand: ManualCommand,
  cmdVel: VelocityStatusLike,
) {
  return slamCorrectionEnabled
    && slamPoseChanged
    && lastCommand === "stop"
    && !hasActiveVelocity(cmdVel);
}

export function projectPoseByVelocity(
  pose: DisplayPoseCell,
  velocity: VelocityLike,
  deltaSeconds: number,
  resolution: number,
) {
  if (deltaSeconds <= 0 || resolution <= 0) return pose;

  const motionYawDeg = pose.motionYawDeg ?? pose.yawDeg;
  const yaw = degToRad(motionYawDeg);
  const forward = { x: Math.cos(yaw), y: Math.sin(yaw) };
  const left = { x: Math.sin(yaw), y: -Math.cos(yaw) };
  const dxMeters = (-velocity.linear_x * forward.x - velocity.linear_y * left.x) * deltaSeconds;
  const dyMeters = (-velocity.linear_x * forward.y - velocity.linear_y * left.y) * deltaSeconds;
  const nextMotionYawDeg = motionYawDeg - (velocity.angular_z * 180 * deltaSeconds) / Math.PI;

  return {
    x: pose.x + dxMeters / resolution,
    y: pose.y + dyMeters / resolution,
    yawDeg: normalizeDeg(nextMotionYawDeg + 180),
    motionYawDeg: nextMotionYawDeg,
  };
}

export function applySlamCorrection(
  display: DisplayPoseCell,
  slam: DisplayPoseCell,
  enabled: boolean,
  options: { attractDistanceCells?: number; snapDistanceCells?: number; alpha?: number } = {},
): { pose: DisplayPoseCell; status: "off" | "hold" | "attract" | "snap" } {
  if (!enabled) return { pose: display, status: "off" };

  const attractDistanceCells = options.attractDistanceCells ?? 8;
  const snapDistanceCells = options.snapDistanceCells ?? 18;
  const alpha = options.alpha ?? 0.08;
  const dx = slam.x - display.x;
  const dy = slam.y - display.y;
  const distance = Math.hypot(dx, dy);

  if (distance >= snapDistanceCells) return { pose: slam, status: "snap" };
  if (distance <= attractDistanceCells) {
    return {
      pose: {
        x: display.x + dx * alpha,
        y: display.y + dy * alpha,
        yawDeg: slam.yawDeg,
        motionYawDeg: slam.motionYawDeg,
      },
      status: "attract",
    };
  }
  return { pose: display, status: "hold" };
}

export function smoothMapPoseCell(
  previous: DisplayPoseCell | null,
  target: DisplayPoseCell,
  options: SmoothOptions = {},
) {
  if (!previous) return target;

  const positionAlpha = options.positionAlpha ?? 0.55;
  const yawAlpha = options.yawAlpha ?? 0.65;
  const positionDeadbandCells = options.positionDeadbandCells ?? 0.12;
  const yawDeadbandDeg = options.yawDeadbandDeg ?? 1.2;
  const teleportDistanceCells = options.teleportDistanceCells ?? 18;

  const dx = target.x - previous.x;
  const dy = target.y - previous.y;
  const distance = Math.hypot(dx, dy);

  if (distance > teleportDistanceCells) return target;

  const yawDiff = shortestAngleDiffDeg(previous.yawDeg, target.yawDeg);

  const smoothed: DisplayPoseCell = {
    x: distance < positionDeadbandCells ? previous.x : previous.x + dx * positionAlpha,
    y: distance < positionDeadbandCells ? previous.y : previous.y + dy * positionAlpha,
    yawDeg: Math.abs(yawDiff) < yawDeadbandDeg
      ? previous.yawDeg
      : normalizeDeg(previous.yawDeg + yawDiff * yawAlpha),
  };
  const motionYawDeg = target.motionYawDeg ?? previous.motionYawDeg;
  if (motionYawDeg !== undefined) smoothed.motionYawDeg = motionYawDeg;
  return smoothed;
}
