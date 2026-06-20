import math
from types import SimpleNamespace

from smart_car_decision.common import front_range_statistic
from smart_car_decision.scan_visualization import simplify_scan_points
from smart_car_decision.web_state import MIN_SPEED_SCALE, RobotStateStore


def test_simplify_scan_points_limits_and_projects_valid_ranges():
    scan = SimpleNamespace(
        ranges=[1.0, float("inf"), 2.0, 99.0],
        angle_min=0.0,
        angle_increment=math.pi / 2.0,
        range_min=0.1,
        range_max=5.0,
    )

    points = simplify_scan_points(scan, max_points=8)

    assert points == [
        {"x": 1.0, "y": 0.0, "distance": 1.0},
        {"x": -2.0, "y": 0.0, "distance": 2.0},
    ]


def test_speed_scale_has_nonzero_floor_for_manual_control():
    store = RobotStateStore()

    assert store.set_speed_scale(0.0) == MIN_SPEED_SCALE


def test_front_range_uses_configured_180_degree_sector_across_wraparound():
    scan = SimpleNamespace(ranges=[1.2, 4.0, 4.0, 4.0, 1.0], angle_min=-math.pi, angle_increment=math.pi / 2.0, range_min=0.05, range_max=12.0)
    distance = front_range_statistic(scan, center_angle_rad=math.pi, half_width_rad=math.radians(10.0), percentile=0.0)
    assert distance == 1.0


def test_front_range_percentile_rejects_single_near_noise_point():
    scan = SimpleNamespace(ranges=[0.08, 1.0, 1.1, 1.2, 1.3], angle_min=math.radians(160.0), angle_increment=math.radians(10.0), range_min=0.05, range_max=12.0)
    distance = front_range_statistic(scan, center_angle_rad=math.pi, half_width_rad=math.radians(25.0), percentile=20.0)
    assert distance == 1.0


def test_front_range_returns_infinity_when_sector_has_no_valid_measurements():
    scan = SimpleNamespace(ranges=[float("inf"), float("nan")], angle_min=math.pi - 0.1, angle_increment=0.1, range_min=0.05, range_max=12.0)
    assert math.isinf(front_range_statistic(scan, center_angle_rad=math.pi, half_width_rad=0.2, percentile=20.0))


def test_scan_points_rotate_lidar_frame_so_vehicle_front_faces_up():
    scan = SimpleNamespace(
        ranges=[2.0],
        angle_min=math.pi,
        angle_increment=0.1,
        range_min=0.05,
        range_max=12.0,
    )

    assert simplify_scan_points(scan, max_points=8, rotation_rad=math.pi) == [
        {"x": 2.0, "y": 0.0, "distance": 2.0}
    ]
