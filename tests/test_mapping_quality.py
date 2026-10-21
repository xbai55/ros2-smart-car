from smart_car_decision.mapping_quality import evaluate_mapping_quality


def test_supported_fifty_percent_mapping_speed_is_not_reported_as_a_fault():
    healthy = dict(lidar={"ok": True}, map_status={"ok": True}, odom={"ok": True}, tf_status={"ok": True})
    assert evaluate_mapping_quality(speed_scale=.5, **healthy)["ok"] is True
    assert "speed" in evaluate_mapping_quality(speed_scale=.51, **healthy)["issues"]
