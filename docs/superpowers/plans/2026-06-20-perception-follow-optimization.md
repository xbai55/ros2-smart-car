# Perception and Person Follow Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist color settings, display reliable front distance, and make YOLO person following stable and radar-safe.

**Architecture:** Pure helpers own scan-sector statistics and person target locking. ROS nodes translate messages into those helpers, while the decision controller keeps lidar safety above vision motion. The web client restores and reapplies the saved color configuration at startup.

**Tech Stack:** ROS2 Humble, Python 3, pytest, vanilla JavaScript, FastAPI, OpenCV/Ultralytics.

---

### Task 1: Front scan sector

**Files:**
- Modify: `ros2_ws/src/smart_car_decision/smart_car_decision/common.py`
- Modify: `ros2_ws/src/smart_car_decision/smart_car_decision/system_status_node.py`
- Modify: `ros2_ws/src/smart_car_decision/smart_car_decision/decision_controller.py`
- Modify: `ros2_ws/src/smart_car_decision/config/decision.yaml`
- Test: `tests/test_scan_visualization.py`

- [ ] Add failing tests for a 180-degree sector, wraparound angles, percentile filtering, and empty sectors.
- [ ] Run `python -m pytest tests/test_scan_visualization.py -q` and confirm the new tests fail.
- [ ] Implement a shared `front_range_statistic` helper and wire both ROS nodes to the same center-angle parameters.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Person-only stable target selection

**Files:**
- Create: `ros2_ws/src/smart_car_decision/smart_car_decision/person_target.py`
- Modify: `ros2_ws/src/smart_car_decision/smart_car_decision/yolo11_camera_node.py`
- Modify: `ros2_ws/src/smart_car_decision/config/decision.yaml`
- Create: `tests/test_person_target.py`

- [ ] Add failing tests showing non-person classes are ignored, the first person is selected deterministically, and the existing person remains locked when detection order changes.
- [ ] Run `python -m pytest tests/test_person_target.py -q` and confirm failure.
- [ ] Implement the target selector and publish offsets only for its locked person.
- [ ] Re-run the focused test and confirm it passes.

### Task 3: Saved color restoration

**Files:**
- Modify: `ros2_ws/src/smart_car_decision/web/static/app.js`
- Create: `tests/test_web_color_restore.py`

- [ ] Add a failing source-level regression test requiring startup restoration to POST the saved HSV configuration.
- [ ] Run `python -m pytest tests/test_web_color_restore.py -q` and confirm failure.
- [ ] Make startup restore inputs and call `/api/color-target` before live status may overwrite the configuration.
- [ ] Re-run the focused test and confirm it passes.

### Task 4: Regression and deployment

**Files:**
- Modify: `README.md`
- Deploy: `/home/jetson/ros2-smart-car`

- [ ] Run `python -m pytest -q` locally and fix only failures caused by this scope.
- [ ] Run the frontend build and static checks.
- [ ] Copy changed files to the Jetson, rebuild the ROS2 workspace, and run its test suite.
- [ ] Start lidar plus status/web nodes without the chassis and verify non-null `front_distance`, radar points, and restored color state.
- [ ] Start the full stack in stop mode, then perform a low-speed person-follow smoke test with obstacle-stop verification.
