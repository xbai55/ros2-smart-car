import pytest

from smart_car_decision.control_policy import (
    VALID_MODES,
    normalize_mode,
    decide_motion,
)


def test_normalize_mode_rejects_unknown_values():
    assert normalize_mode("manual") == "manual"
    assert normalize_mode("MANUAL") == "manual"
    assert normalize_mode("bad-mode") == "stop"
    assert "object_follow" in VALID_MODES


def test_stop_mode_always_outputs_zero_motion():
    motion = decide_motion(
        mode="stop",
        emergency_stop=False,
        front_distance=10.0,
        detection="green_light",
        manual_command="forward",
        lane_offset=0.5,
        has_recent_detection=True,
        has_recent_manual=True,
        has_recent_lane=True,
    )
    assert motion == {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}


def test_emergency_stop_overrides_manual_and_auto_inputs():
    motion = decide_motion(
        mode="manual",
        emergency_stop=True,
        front_distance=10.0,
        detection="green_light",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=True,
        has_recent_manual=True,
        has_recent_lane=True,
    )
    assert motion["linear_x"] == 0.0
    assert motion["linear_y"] == 0.0
    assert motion["angular_z"] == 0.0


def test_manual_mode_requires_recent_manual_command():
    stale = decide_motion(
        mode="manual",
        emergency_stop=False,
        front_distance=10.0,
        detection="green_light",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=True,
        has_recent_manual=False,
        has_recent_lane=True,
    )
    fresh = decide_motion(
        mode="manual",
        emergency_stop=False,
        front_distance=10.0,
        detection="",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=False,
        has_recent_manual=True,
        has_recent_lane=False,
    )
    assert stale["linear_x"] == 0.0
    assert fresh["linear_x"] > 0.0


def test_obstacle_stop_distance_overrides_motion():
    motion = decide_motion(
        mode="auto",
        emergency_stop=False,
        front_distance=0.2,
        detection="green_light",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=True,
        has_recent_manual=True,
        has_recent_lane=True,
        obstacle_stop_distance=0.45,
    )
    assert motion == {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}


def test_auto_mode_stops_when_detection_is_stale():
    motion = decide_motion(
        mode="auto",
        emergency_stop=False,
        front_distance=10.0,
        detection="",
        manual_command="",
        lane_offset=0.3,
        has_recent_detection=False,
        has_recent_manual=False,
        has_recent_lane=True,
        cruise_speed=0.18,
        lane_kp=0.9,
    )
    assert motion == {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}


def test_speed_scale_limits_auto_speed():
    motion = decide_motion(
        mode="auto",
        emergency_stop=False,
        front_distance=10.0,
        detection="green_light",
        manual_command="",
        lane_offset=0.0,
        has_recent_detection=True,
        has_recent_manual=False,
        has_recent_lane=False,
        cruise_speed=0.2,
        speed_scale=0.5,
    )
    assert motion["linear_x"] == pytest.approx(0.1)


def test_object_follow_mode_turns_toward_target_offset():
    motion = decide_motion(
        mode="object_follow",
        emergency_stop=False,
        front_distance=10.0,
        detection="person",
        manual_command="",
        lane_offset=-0.4,
        has_recent_detection=True,
        has_recent_manual=False,
        has_recent_lane=True,
        slow_speed=0.08,
        lane_kp=0.9,
    )
    assert motion["linear_x"] == 0.08
    assert motion["angular_z"] == pytest.approx(0.36)


def test_stale_lidar_scan_stops_autonomous_person_follow():
    motion = decide_motion(
        mode="object_follow",
        emergency_stop=False,
        front_distance=10.0,
        detection="slow",
        manual_command="stop",
        lane_offset=0.2,
        has_recent_detection=True,
        has_recent_manual=False,
        has_recent_lane=True,
        has_recent_scan=False,
    )

    assert motion == {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}


def test_mapping_mode_accepts_fresh_manual_commands_through_safety_controller():
    motion = decide_motion(
        mode="mapping",
        emergency_stop=False,
        front_distance=2.0,
        detection="",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=False,
        has_recent_manual=True,
        has_recent_lane=False,
        has_recent_scan=True,
    )

    assert motion["linear_x"] > 0.0


def test_mapping_mode_allows_manual_command_inside_obstacle_stop_distance():
    motion = decide_motion(
        mode="mapping",
        emergency_stop=False,
        front_distance=0.2,
        detection="",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=False,
        has_recent_manual=True,
        has_recent_lane=False,
        has_recent_scan=True,
        obstacle_stop_distance=0.45,
        cruise_speed=0.28,
        speed_scale=0.25,
    )

    assert motion["linear_x"] > 0.0



def test_mode_specific_obstacle_stop_distance_can_stop_mapping():
    motion = decide_motion(
        mode="mapping",
        emergency_stop=False,
        front_distance=0.55,
        detection="",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=False,
        has_recent_manual=True,
        has_recent_lane=False,
        has_recent_scan=True,
        obstacle_stop_distance=0.45,
        mode_obstacle_stop_distances={"mapping": 0.6},
        cruise_speed=0.28,
        speed_scale=0.25,
    )

    assert motion == {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}
def test_mapping_mode_stops_when_scan_or_manual_command_is_stale():
    common = dict(
        mode="mapping",
        emergency_stop=False,
        front_distance=2.0,
        detection="",
        manual_command="forward",
        lane_offset=0.0,
        has_recent_detection=False,
        has_recent_lane=False,
    )

    stale_scan = decide_motion(**common, has_recent_manual=True, has_recent_scan=False)
    stale_command = decide_motion(**common, has_recent_manual=False, has_recent_scan=True)

    assert stale_scan == {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}
    assert stale_command == {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}


@pytest.mark.parametrize("mode", ["manual", "mapping"])
@pytest.mark.parametrize("command", ["forward", "backward", "left", "right", "turn_l", "turn_r"])
def test_operator_speed_does_not_drop_when_front_distance_crosses_slow_zone(mode, command):
    common = dict(mode=mode, emergency_stop=False, detection="", manual_command=command,
                  lane_offset=0, has_recent_detection=False, has_recent_manual=True,
                  has_recent_lane=False, has_recent_scan=True, cruise_speed=.28,
                  turn_speed=1.0, slow_speed=.12, speed_scale=.5,
                  mode_obstacle_stop_distances={"manual": 0, "mapping": 0})
    far = decide_motion(front_distance=2, **common)
    near = decide_motion(front_distance=.2, **common)
    assert near == far
    assert max(abs(near[k]) for k in ("linear_x", "linear_y", "angular_z")) == pytest.approx(.5 if command.startswith("turn") else .14)


def test_mapping_controller_enforces_fifty_percent_even_for_direct_topic_input():
    common = dict(mode="mapping", emergency_stop=False, detection="", manual_command="forward",
                  front_distance=2, lane_offset=0, has_recent_detection=False,
                  has_recent_manual=True, has_recent_lane=False, cruise_speed=.28,
                  turn_speed=1, speed_scale=1)
    assert decide_motion(**common)["linear_x"] == pytest.approx(.14)
    assert decide_motion(**{**common, "manual_command": "turn_l"})["angular_z"] == pytest.approx(.5)


def test_automatic_proximity_slowdown_is_preserved():
    common = dict(mode="auto", emergency_stop=False, detection="", manual_command="",
                  lane_offset=0, has_recent_detection=True, has_recent_manual=False,
                  has_recent_lane=False, cruise_speed=.28, slow_speed=.12, speed_scale=.5)
    assert decide_motion(front_distance=2, **common)["linear_x"] == pytest.approx(.14)
    assert decide_motion(front_distance=.6, **common)["linear_x"] == pytest.approx(.06)
    assert decide_motion(front_distance=.2, **common)["linear_x"] == 0
