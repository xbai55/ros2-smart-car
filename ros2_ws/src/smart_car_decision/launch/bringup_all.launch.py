from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = Path(get_package_share_directory("smart_car_decision"))
    params = str(pkg_share / "config" / "decision.yaml")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "start_base_driver",
                default_value="true",
                description="Start Yahboom ROSMASTER X3 mecanum chassis driver.",
            ),
            DeclareLaunchArgument(
                "start_lidar_driver",
                default_value="true",
                description="Start SLLidar driver so /scan is available for safety and radar visualization.",
            ),
            ExecuteProcess(
                cmd=["ros2", "run", "yahboomcar_bringup", "Mcnamu_driver_X3"],
                name="yahboom_base_driver",
                output="screen",
                emulate_tty=True,
                condition=IfCondition(LaunchConfiguration("start_base_driver")),
            ),
            ExecuteProcess(
                cmd=["ros2", "launch", "sllidar_ros2", "sllidar_a2m8_launch.py"],
                name="sllidar_driver",
                output="screen",
                emulate_tty=True,
                condition=IfCondition(LaunchConfiguration("start_lidar_driver")),
            ),
            Node(package="smart_car_decision", executable="mode_manager", name="mode_manager", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="laser_obstacle_monitor", name="laser_obstacle_monitor", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="decision_controller", name="decision_controller", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="tcp_command_bridge", name="tcp_command_bridge", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="yolo11_camera_node", name="yolo11_camera_node", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="color_tracker_node", name="color_tracker_node", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="object_follow_node", name="object_follow_node", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="system_status_node", name="system_status_node", output="screen", parameters=[params]),
            Node(package="smart_car_decision", executable="web_app_node", name="web_app_node", output="screen", parameters=[params]),
        ]
    )
