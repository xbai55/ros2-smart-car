"""Operator-confirmed 25 x 20 cm body in the existing base_link frame."""
import math

FRONT_M = .0935
REAR_M = .1565
HALF_WIDTH_M = .10
BODY_LENGTH_M = FRONT_M + REAR_M
BODY_WIDTH_M = HALF_WIDTH_M * 2
BOUNDING_RADIUS_M = math.hypot(max(FRONT_M, REAR_M), HALF_WIDTH_M)
FOOTPRINT = [[FRONT_M, HALF_WIDTH_M], [FRONT_M, -HALF_WIDTH_M],
             [-REAR_M, -HALF_WIDTH_M], [-REAR_M, HALF_WIDTH_M]]
