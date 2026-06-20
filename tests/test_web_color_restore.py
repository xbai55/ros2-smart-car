from pathlib import Path


APP_JS = (
    Path(__file__).parents[1]
    / "ros2_ws"
    / "src"
    / "smart_car_decision"
    / "web"
    / "static"
    / "app.js"
)


def test_saved_color_is_reapplied_to_ros_before_status_connection():
    source = APP_JS.read_text(encoding="utf-8-sig")

    assert "async function applySavedColor()" in source
    assert 'await postJson("/api/color-target", config)' in source
    assert "async function initialize()" in source
    startup = source[source.index("async function initialize()") :]
    assert startup.index("await applySavedColor()") < startup.index("connectStatus()")
