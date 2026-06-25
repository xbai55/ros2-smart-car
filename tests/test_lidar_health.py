from types import SimpleNamespace

import pytest

from smart_car_decision.lidar_health import (
    ScanRateWindow,
    evaluate_lidar_health,
    scan_quality,
)


def make_scan(ranges):
    return SimpleNamespace(ranges=ranges, range_min=0.05, range_max=12.0)


def test_scan_quality_counts_only_finite_in_range_values():
    quality = scan_quality(
        make_scan([1.0, 2.0, float("inf"), float("nan"), 0.01, 13.0])
    )

    assert quality.total_count == 6
    assert quality.valid_count == 2
    assert quality.valid_ratio == pytest.approx(1 / 3)


def test_scan_rate_window_uses_elapsed_time_between_samples():
    window = ScanRateWindow(max_samples=4)

    for timestamp in [1.0, 1.1, 1.2, 1.3]:
        window.add(timestamp)

    assert window.rate_hz == pytest.approx(10.0)


def test_lidar_health_reports_missing_stale_invalid_and_healthy_data():
    missing = evaluate_lidar_health(
        last_scan_time=None,
        now=10.0,
        timeout_sec=0.6,
        rate_hz=0.0,
        valid_count=0,
        valid_ratio=0.0,
        min_valid_ratio=0.05,
        frame_id="",
    )
    stale = evaluate_lidar_health(
        last_scan_time=9.0,
        now=10.0,
        timeout_sec=0.6,
        rate_hz=9.5,
        valid_count=500,
        valid_ratio=0.8,
        min_valid_ratio=0.05,
        frame_id="laser",
    )
    invalid = evaluate_lidar_health(
        last_scan_time=9.8,
        now=10.0,
        timeout_sec=0.6,
        rate_hz=9.5,
        valid_count=2,
        valid_ratio=0.01,
        min_valid_ratio=0.05,
        frame_id="laser",
    )
    healthy = evaluate_lidar_health(
        last_scan_time=9.8,
        now=10.0,
        timeout_sec=0.6,
        rate_hz=9.5,
        valid_count=500,
        valid_ratio=0.8,
        min_valid_ratio=0.05,
        frame_id="laser",
    )

    assert missing["message"] == "no_data"
    assert stale["message"] == "stale"
    assert invalid["message"] == "insufficient_valid_points"
    assert healthy == {
        "ok": True,
        "message": "ok",
        "scan_age_sec": 0.2,
        "scan_rate_hz": 9.5,
        "valid_count": 500,
        "valid_ratio": 0.8,
        "frame_id": "laser",
    }

