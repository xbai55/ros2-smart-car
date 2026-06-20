from pathlib import Path

import yaml


def test_web_camera_capture_fps_matches_uvc_mode_and_output_is_separate():
    config_path = Path(__file__).parents[1] / "ros2_ws" / "src" / "smart_car_decision" / "config" / "decision.yaml"
    params = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))["web_app_node"]["ros__parameters"]

    assert params["video_fps"] == 30.0
    assert params["video_target_fps"] == 20.0
