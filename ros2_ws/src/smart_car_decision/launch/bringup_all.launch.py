from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = Path(get_package_share_directory("smart_car_decision"))
    yahboom_description_share = Path(get_package_share_directory("yahboomcar_description"))
    params = str(pkg_share / "config" / "decision.yaml")
    x3_urdf = str(yahboom_description_share / "urdf" / "yahboomcar_X3.urdf")

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
            DeclareLaunchArgument(
                "start_base_odom",
                default_value="true",
                description="Start Yahboom base odometry node and remap odom_raw to /odom.",
            ),
            DeclareLaunchArgument(
                "start_robot_description",
                default_value="true",
                description="Start robot_state_publisher for base_footprint to base_link TF.",
            ),
            DeclareLaunchArgument(
                "publish_scan_laser_tf",
                default_value="true",
                description="Publish base_link to laser alias TF matching /scan frame_id.",
            ),
            ExecuteProcess(
                cmd=["ros2", "run", "yahboomcar_bringup", "Mcnamu_driver_X3"],
                name="yahboom_base_driver",
                output="screen",
                emulate_tty=True,
                condition=IfCondition(LaunchConfiguration("start_base_driver")),
            ),
            ExecuteProcess(
                cmd=[
                    "ros2",
                    "launch",
                    "sllidar_ros2",
                    "sllidar_launch.py",
                    "serial_port:=/dev/rplidar",
                    "serial_baudrate:=115200",
                    "frame_id:=laser",
                ],
                name="sllidar_driver",
                output="screen",
                emulate_tty=True,
                condition=IfCondition(LaunchConfiguration("start_lidar_driver")),
            ),
            Node(
                package="yahboomcar_base_node",
                executable="base_node_X3",
                name="base_node",
                output="screen",
                parameters=[
                    {
                        "pub_odom_tf": True,
                        "linear_scale_x": 1.0,
                        "linear_scale_y": 1.0,
                        "angular_scale": 1.0,
                    }
                ],
                remappings=[("odom_raw", "odom")],
                condition=IfCondition(LaunchConfiguration("start_base_odom")),
            ),
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                name="robot_state_publisher",
                output="screen",
                arguments=[x3_urdf],
                condition=IfCondition(LaunchConfiguration("start_robot_description")),
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_to_scan_laser_static_tf",
                output="screen",
                arguments=[
                    "--x", "0.0435",
                    "--y", "0.0",
                    "--z", "0.11",
                    "--roll", "0.0",
                    "--pitch", "0.0",
                    "--yaw", "0.0",
                    "--frame-id", "base_link",
                    "--child-frame-id", "laser",
                ],
                condition=IfCondition(LaunchConfiguration("publish_scan_laser_tf")),
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
