from smart_car_decision.mapping_quality import evaluate_mapping_quality
from smart_car_decision.odom_health import evaluate_odom_health
from smart_car_decision.tf_health import evaluate_tf_health


def test_odom_health_reports_missing_stale_and_healthy_odom():
    missing = evaluate_odom_health(
        last_odom_time=None,
        now=10.0,
        timeout_sec=1.0,
        frame_id="",
        child_frame_id="",
        linear_speed=0.0,
        angular_speed=0.0,
    )
    stale = evaluate_odom_health(
        last_odom_time=8.0,
        now=10.0,
        timeout_sec=1.0,
        frame_id="odom",
        child_frame_id="base_link",
        linear_speed=0.1,
        angular_speed=0.0,
    )
    healthy = evaluate_odom_health(
        last_odom_time=9.8,
        now=10.0,
        timeout_sec=1.0,
        frame_id="odom",
        child_frame_id="base_link",
        linear_speed=0.1,
        angular_speed=0.02,
    )

    assert missing["message"] == "no_odom"
    assert stale["message"] == "stale"
    assert healthy == {
        "ok": True,
        "message": "ok",
        "odom_age_sec": 0.2,
        "frame_id": "odom",
        "child_frame_id": "base_link",
        "linear_speed": 0.1,
        "angular_speed": 0.02,
    }


def test_tf_health_uses_stable_status_shape():
    tf_status = evaluate_tf_health(
        ok=True,
        message="ok",
        checked_at=12.5,
        parent_frame="odom",
        child_frame="base_link",
    )

    assert tf_status == {
        "ok": True,
        "message": "ok",
        "checked_at": 12.5,
        "parent_frame": "odom",
        "child_frame": "base_link",
    }


def test_mapping_quality_flags_required_mapping_inputs():
    good = {"ok": True}
    bad = {"ok": False}

    assert evaluate_mapping_quality(
        lidar=good,
        map_status=good,
        odom=good,
        tf_status=good,
        speed_scale=0.2,
    )["level"] == "good"

    quality = evaluate_mapping_quality(
        lidar=good,
        map_status=good,
        odom=bad,
        tf_status=good,
        speed_scale=0.2,
    )

    assert quality["level"] == "bad"
    assert quality["issues"] == ["odom"]
