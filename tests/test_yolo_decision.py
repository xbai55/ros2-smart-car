import numpy as np

from smart_car_decision.yolo_decision import (
    YoloCommandFilter,
    is_frame_obscured,
    normalize_candidate_command,
)


def test_normal_empty_frame_is_clear_but_obscured_frame_stops():
    gradient = np.tile(np.arange(32, dtype=np.uint8) * 4, (32, 1))
    normal_frame = np.dstack([gradient, gradient, gradient])
    covered_frame = np.full((32, 32, 3), 3, dtype=np.uint8)

    assert is_frame_obscured(normal_frame) is False
    assert is_frame_obscured(covered_frame) is True


def test_unknown_candidate_does_not_become_stop():
    assert normalize_candidate_command(None, default_command="no_light") == "no_light"
    assert normalize_candidate_command("chair", default_command="no_light") == "no_light"
    assert normalize_candidate_command("slow", default_command="no_light") == "slow"


def test_safety_command_is_held_through_short_missed_detection():
    command_filter = YoloCommandFilter(default_command="no_light", safety_hold_sec=0.8)

    assert command_filter.update("stop", now=10.0) == "stop"
    assert command_filter.update("no_light", now=10.4) == "stop"
    assert command_filter.update("no_light", now=10.9) == "no_light"
