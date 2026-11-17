import asyncio
from types import SimpleNamespace
import pytest

from smart_car_decision import stop_service


def odom(age=.03, linear=0., angular=0.):
    return {"ok": True, "odom_age_sec": age, "linear_speed": linear, "linear_speed_xy": abs(linear), "angular_speed": angular}


def test_stationary_evidence_requires_fresh_post_confirmation_sample():
    assert stop_service.stationary_evidence((10.2, odom()), 10., 10.3)
    assert not stop_service.stationary_evidence((10.2, odom(age=.3)), 10., 10.3)
    assert not stop_service.stationary_evidence((10.2, odom()), 10., 11.)
    assert not stop_service.stationary_evidence((10.2, odom(angular=.1)), 10., 10.3)
    assert not stop_service.stationary_evidence(None, 10., 10.3)


def test_stop_attempts_mode_and_task_cancellation_without_controller_ack():
    calls = []

    def failed_command(command):
        raise RuntimeError("publisher failed")

    node = SimpleNamespace(
        set_command=failed_command, set_mode=calls.append,
        navigation_tasks=SimpleNamespace(interrupt=lambda message: calls.append("interrupt")),
        navigation=SimpleNamespace(cancel=lambda: calls.append("cancel")),
    )
    result = asyncio.run(stop_service.stop_vehicle(node))
    assert calls == ["stop", "interrupt", "cancel"]
    assert result == {
        "request_sent": True, "controller_confirmed": False, "stationary_confirmed": False,
        "errors": ["set_command_failed", "controller_stop_unconfirmed"],
    }


@pytest.mark.parametrize("takeover", [False, True])
def test_stop_waits_for_new_odometry_and_rechecks_control_epoch(monkeypatch, takeover):
    clock = [10.]
    node = SimpleNamespace(set_command=lambda command: None, set_mode=lambda mode: None,
                           stop_odometry_sample=(9.9, odom()))
    state = {"controller_id": "controller", "control_epoch": "stopped", "blocked": True, "fresh": True}

    class Bridge:
        def __init__(self, node):
            pass

        def snapshot(self):
            return state.copy()

        async def request(self, payload):
            assert payload == {"op": "stop", "controller_id": "controller"}
            return {"confirmed": True, "lease": self.snapshot()}

    async def sleep(seconds):
        clock[0] += seconds
        node.stop_odometry_sample = (clock[0], odom(age=.01))
        if takeover:
            state.update(control_epoch="new", blocked=False)

    monkeypatch.setattr(stop_service, "LeaseBridge", Bridge)
    monkeypatch.setattr(stop_service, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(stop_service, "asyncio", SimpleNamespace(sleep=sleep))
    result = asyncio.run(stop_service.stop_vehicle(node))
    assert result["controller_confirmed"] is True
    assert result["stationary_confirmed"] is not takeover
