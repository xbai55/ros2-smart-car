from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = Path(get_package_share_directory("smart_car_decision"))
    params = str(pkg_share / "config" / "decision.yaml")

    return LaunchDescription(
        [
            Node(
                package="smart_car_decision",
                executable="yolo11_camera_node",
                name="yolo11_camera_node",
                output="screen",
                parameters=[params],
            ),
        ]
    )
