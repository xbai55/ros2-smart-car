from smart_car_decision.map_health import evaluate_map_health


def test_map_health_reports_missing_stale_and_healthy_maps():
    missing = evaluate_map_health(
        last_map_time=None, now=10.0, timeout_sec=5.0,
        width=0, height=0, resolution=0.0, frame_id="",
    )
    stale = evaluate_map_health(
        last_map_time=4.0, now=10.0, timeout_sec=5.0,
        width=100, height=80, resolution=0.05, frame_id="map",
    )
    healthy = evaluate_map_health(
        last_map_time=9.0, now=10.0, timeout_sec=5.0,
        width=100, height=80, resolution=0.05, frame_id="map",
    )

    assert missing["message"] == "no_map"
    assert stale["message"] == "stale"
    assert healthy == {
        "ok": True,
        "message": "ok",
        "map_age_sec": 1.0,
        "width": 100,
        "height": 80,
        "resolution": 0.05,
        "frame_id": "map",
    }
