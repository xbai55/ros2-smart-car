import math


def simplify_scan_points(scan, max_points=96, rotation_rad=0.0):
    ranges = list(scan.ranges or [])
    if not ranges:
        return []
    stride = max(1, math.ceil(len(ranges) / int(max_points)))
    points = []
    for index in range(0, len(ranges), stride):
        distance = float(ranges[index])
        if not math.isfinite(distance) or distance < scan.range_min or distance > scan.range_max:
            continue
        angle = scan.angle_min + index * scan.angle_increment - float(rotation_rad)
        points.append(
            {
                "x": round(math.cos(angle) * distance, 3),
                "y": round(math.sin(angle) * distance, 3),
                "distance": round(distance, 3),
            }
        )
    return points
