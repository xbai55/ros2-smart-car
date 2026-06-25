from pathlib import Path

import pytest

from smart_car_decision.web_state import normalize_tracking_target_request


ROOT = Path(__file__).parents[1]
APP_JS = ROOT / "ros2_ws" / "src" / "smart_car_decision" / "web" / "static" / "app.js"
INDEX_HTML = ROOT / "ros2_ws" / "src" / "smart_car_decision" / "web" / "static" / "index.html"
WEB_NODE = ROOT / "ros2_ws" / "src" / "smart_car_decision" / "smart_car_decision" / "web_app_node.py"


def test_tracking_target_request_accepts_auto_and_normalized_point():
    assert normalize_tracking_target_request({"action": "auto"}) == {"action": "auto"}
    assert normalize_tracking_target_request({"action": "select", "x": 0.42, "y": 0.55}) == {
        "action": "select",
        "x": 0.42,
        "y": 0.55,
    }


def test_tracking_target_request_rejects_invalid_coordinates():
    with pytest.raises(ValueError):
        normalize_tracking_target_request({"action": "select", "x": 1.1, "y": 0.5})


def test_web_console_exposes_click_selection_and_auto_reset():
    js = APP_JS.read_text(encoding="utf-8-sig")
    html = INDEX_HTML.read_text(encoding="utf-8-sig")
    node = WEB_NODE.read_text(encoding="utf-8-sig")

    assert 'postJson("/api/tracking-target"' in js
    assert 'videoFeed.addEventListener("click"' in js
    assert 'id="autoTargetBtn"' in html
    assert 'id="trackingTargetState"' in html
    assert '@app.post("/api/tracking-target")' in node
