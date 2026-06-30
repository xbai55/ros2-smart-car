from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_recovers_hardware_before_compose_up():
    source = (ROOT / "scripts/deploy_docker_jetson.sh").read_text(encoding="utf-8")

    assert "sudo modprobe cp210x || true" in source
    assert "sudo modprobe uvcvideo || true" in source
    assert "sudo udevadm control --reload-rules || true" in source
    assert "sudo udevadm trigger || true" in source
    assert "stop_device_conflicts" in source
    assert "recover_hardware" in source
    assert source.index("check_hardware") < source.index("build smart-car-runtime")


def test_deploy_script_fails_strict_lidar_and_camera_missing():
    source = (ROOT / "scripts/deploy_docker_jetson.sh").read_text(encoding="utf-8")

    assert 'SMART_CAR_REQUIRE_LIDAR="${SMART_CAR_REQUIRE_LIDAR:-1}"' in source
    assert 'SMART_CAR_REQUIRE_CAMERA="${SMART_CAR_REQUIRE_CAMERA:-1}"' in source
    assert "expected /dev/rplidar or a CP210x /dev/ttyUSB* device" in source
    assert "expected /dev/video0 or another /dev/video* device" in source
    assert "print_device_diagnostics >&2" in source
    assert "lsusb || true" in source
    assert "dmesg | tail" in source


def test_runtime_entrypoint_checks_devices_and_passes_launch_args():
    source = (ROOT / "docker/launch_runtime.sh").read_text(encoding="utf-8")

    assert "print_runtime_diagnostics" in source
    assert "/dev/myserial" in source
    assert "detect_lidar_port" in source
    assert "detect_camera_source" in source
    assert "lidar_serial_port:=" in source
    assert "start_yolo_camera:=" in source
    assert "start_color_tracker:=" in source
    assert "start_web_camera:=" in source


def test_healthcheck_reports_specific_stack_failures():
    source = (ROOT / "scripts/healthcheck_docker.sh").read_text(encoding="utf-8")

    assert "web port 8080 is not listening" in source
    assert "TCP command bridge port 9999 is not listening" in source
    assert "required ROS2 node is missing" in source
    assert "required lidar topic /scan is missing or has no data" in source
    assert "camera topic /vision/annotated_frame is missing" in source
