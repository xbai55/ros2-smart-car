from math import isfinite


def clamp(value, low, high):
    return max(low, min(high, value))


def normalize_command(text):
    return text.strip().lower().replace("-", "_").replace(" ", "_")


def min_front_range(scan, front_angle_rad):
    if not scan.ranges:
        return float("inf")

    best = float("inf")
    angle = scan.angle_min
    for distance in scan.ranges:
        if -front_angle_rad <= angle <= front_angle_rad:
            if isfinite(distance) and scan.range_min <= distance <= scan.range_max:
                best = min(best, distance)
        angle += scan.angle_increment
    return best
