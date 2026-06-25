from pathlib import Path


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "ros2_ws" / "src" / "smart_car_decision"
YOLO_NODE = PACKAGE / "smart_car_decision" / "yolo11_camera_node.py"
SETUP = PACKAGE / "setup.py"
CONFIG = PACKAGE / "config" / "bytetrack.yaml"
STATUS_NODE = PACKAGE / "smart_car_decision" / "system_status_node.py"


def test_object_follow_uses_persistent_ultralytics_bytetrack():
    source = YOLO_NODE.read_text(encoding="utf-8-sig")

    assert "self.model.track(" in source
    assert "persist=True" in source
    assert "tracker=self.tracker_config" in source
    assert '"track_id"' in source


def test_bytetrack_config_is_packaged_with_ros_share_data():
    setup = SETUP.read_text(encoding="utf-8-sig")
    config = CONFIG.read_text(encoding="utf-8-sig")

    assert 'glob("config/*.yaml")' in setup
    assert "tracker_type: bytetrack" in config
    assert "track_high_thresh: 0.5" in config
    assert "track_low_thresh: 0.1" in config
    assert "track_buffer: 8" in config


def test_tracking_selection_and_status_topics_are_wired():
    source = YOLO_NODE.read_text(encoding="utf-8-sig")

    assert '"/vision/tracking_target/set"' in source
    assert '"/vision/tracking_target"' in source
    assert "self.person_selector.select_point" in source
    assert "self.person_selector.select_auto" in source
    assert 'previous_mode == "object_follow"' in source
    assert "self.person_selector.reset()" in source
    assert "tracking_reset = True" in source
    assert "self._publish_tracking_status(time.monotonic())" in source
    assert "tracker.reset()" in source


def test_system_status_forwards_tracking_target_state():
    source = STATUS_NODE.read_text(encoding="utf-8-sig")

    assert '"tracking_target":' in source
    assert '"tracking_target_topic"' in source
    assert "self.on_tracking_target" in source

