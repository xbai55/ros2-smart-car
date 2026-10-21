from smart_car_decision.web_state import RobotStateStore


def test_mapping_speed_accepts_fifty_percent_and_clamps_higher_requests():
    store = RobotStateStore()
    store.set_mode("mapping")
    assert store.set_speed_scale(.5) == .5
    assert store.set_speed_scale(.9) == .5
    assert store.snapshot()["speed_scale"] == .5
    store.set_mode("manual")
    assert store.set_speed_scale(.9) == .9


def test_state_store_rejects_unknown_modes():
    store = RobotStateStore()
    assert store.set_mode("manual") == "manual"
    assert store.set_mode("not-real") == "stop"
    assert store.snapshot()["mode"] == "stop"


def test_manual_commands_only_allowed_in_manual_mode():
    store = RobotStateStore()
    assert store.set_command("forward") == "stop"


def test_mapping_mode_accepts_commands_for_operator_driven_slam():
    store = RobotStateStore()
    store.set_mode("mapping")

    assert store.set_command("forward") == "forward"
    store.set_mode("manual")
    assert store.set_command("forward") == "forward"
    assert store.snapshot()["last_command"] == "forward"


def test_emergency_stop_updates_snapshot():
    store = RobotStateStore()
    store.set_emergency_stop(True)
    snapshot = store.snapshot()
    assert snapshot["emergency_stop"] is True
    assert snapshot["mode"] == "stop"


def test_mode_change_cannot_release_emergency_stop():
    store = RobotStateStore()
    store.set_emergency_stop(True)
    for mode in ("manual", "auto", "mapping", "object_follow", "navigation"):
        assert store.set_mode(mode) == "stop"
        assert store.set_command("forward") == "stop"
        assert store.snapshot()["emergency_stop"] is True
    store.set_emergency_stop(False)
    assert store.set_mode("manual") == "manual"
    assert store.set_command("forward") == "forward"


def test_state_store_has_safe_lidar_default_before_first_status_message():
    lidar = RobotStateStore().snapshot()["lidar"]

    assert lidar["ok"] is False
    assert lidar["message"] == "no_data"
    assert lidar["scan_age_sec"] is None
