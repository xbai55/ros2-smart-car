from smart_car_decision.web_state import RobotStateStore


def test_state_store_rejects_unknown_modes():
    store = RobotStateStore()
    assert store.set_mode("manual") == "manual"
    assert store.set_mode("not-real") == "stop"
    assert store.snapshot()["mode"] == "stop"


def test_manual_commands_only_allowed_in_manual_mode():
    store = RobotStateStore()
    assert store.set_command("forward") == "stop"
    store.set_mode("manual")
    assert store.set_command("forward") == "forward"
    assert store.snapshot()["last_command"] == "forward"


def test_emergency_stop_updates_snapshot():
    store = RobotStateStore()
    store.set_emergency_stop(True)
    snapshot = store.snapshot()
    assert snapshot["emergency_stop"] is True
    assert snapshot["mode"] == "stop"
