from math import atan2, cos, isfinite, sin


def clamp(value, low, high):
    return max(low, min(high, value))


def normalize_command(text):
    return text.strip().lower().replace("-", "_").replace(" ", "_")


def min_front_range(scan, front_angle_rad):
    return front_range_statistic(
        scan,
        center_angle_rad=0.0,
        half_width_rad=front_angle_rad,
        percentile=0.0,
    )


def front_range_statistic(scan, center_angle_rad, half_width_rad, percentile=20.0):
    """Return a robust low percentile for valid ranges in an angular sector."""
    if not scan.ranges:
        return float("inf")

    distances = []
    angle = scan.angle_min
    for distance in scan.ranges:
        delta = atan2(sin(angle - center_angle_rad), cos(angle - center_angle_rad))
        if abs(delta) <= half_width_rad:
            if isfinite(distance) and scan.range_min <= distance <= scan.range_max:
                distances.append(float(distance))
        angle += scan.angle_increment
    if not distances:
        return float("inf")
    distances.sort()
    percentile = max(0.0, min(100.0, float(percentile)))
    index = min(len(distances) - 1, int(len(distances) * percentile / 100.0))
    return distances[index]
