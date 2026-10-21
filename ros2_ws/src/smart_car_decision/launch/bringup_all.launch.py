from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


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
                description="Start raw chassis odometry and the IMU/EKF localization chain together. Disable when an external bringup owns this chain.",
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
            DeclareLaunchArgument("base_frame", default_value="base_link"),
            DeclareLaunchArgument("laser_frame", default_value="laser"),
            DeclareLaunchArgument("laser_x", default_value="0.0435"),
            DeclareLaunchArgument("laser_y", default_value="0.00005258"),
            DeclareLaunchArgument("laser_z", default_value="0.11"),
            DeclareLaunchArgument(
                "laser_yaw", default_value="3.141592653589793",
                description="A1 vendor mounting yaw candidate in radians. Confirm front/side obstacles while stationary before movement acceptance.",
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
                    ["frame_id:=", LaunchConfiguration("laser_frame")],
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
                        "pub_odom_tf": False,
                        "linear_scale_x": 1.0,
                        "linear_scale_y": 1.0,
                        "angular_scale": 1.0,
                    }
                ],
                condition=IfCondition(LaunchConfiguration("start_base_odom")),
            ),
            Node(
                package="imu_filter_madgwick",
                executable="imu_filter_madgwick_node",
                name="imu_filter_madgwick",
                output="screen",
                # Reuse the installed vendor calibration, with no joystick or velocity publisher.
                parameters=[PathJoinSubstitution([
                    FindPackageShare("yahboomcar_bringup"), "param", "imu_filter_param.yaml",
                ])],
                condition=IfCondition(LaunchConfiguration("start_base_odom")),
            ),
            Node(
                package="robot_localization",
                executable="ekf_node",
                name="ekf_filter_node",
                output="screen",
                parameters=[str(pkg_share / "config" / "ekf_x1_x3.yaml")],
                remappings=[("odometry/filtered", "odom")],
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
                    "--x", LaunchConfiguration("laser_x"),
                    "--y", LaunchConfiguration("laser_y"),
                    "--z", LaunchConfiguration("laser_z"),
                    "--roll", "0.0",
                    "--pitch", "0.0",
                    "--yaw", LaunchConfiguration("laser_yaw"),
                    "--frame-id", LaunchConfiguration("base_frame"),
                    "--child-frame-id", LaunchConfiguration("laser_frame"),
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
