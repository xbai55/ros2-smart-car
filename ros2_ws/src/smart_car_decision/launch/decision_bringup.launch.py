from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from pathlib import Path


def generate_launch_description():
    pkg_share = Path(get_package_share_directory("smart_car_decision"))
    params = str(pkg_share / "config" / "decision.yaml")

    return LaunchDescription(
        [
            Node(
                package="smart_car_decision",
                executable="laser_obstacle_monitor",
                name="laser_obstacle_monitor",
                output="screen",
                parameters=[params],
            ),
            Node(
                package="smart_car_decision",
                executable="decision_controller",
                name="decision_controller",
                output="screen",
                parameters=[params],
            ),
            Node(
                package="smart_car_decision",
                executable="tcp_command_bridge",
                name="tcp_command_bridge",
                output="screen",
                parameters=[params],
            ),
        ]
    )
