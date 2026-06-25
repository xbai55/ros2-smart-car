from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    package_share = Path(get_package_share_directory("smart_car_decision"))
    slam_share = Path(get_package_share_directory("slam_toolbox"))

    start_base = LaunchConfiguration("start_base_driver")
    start_lidar = LaunchConfiguration("start_lidar_driver")
    publish_laser_tf = LaunchConfiguration("publish_laser_tf")
    use_sim_time = LaunchConfiguration("use_sim_time")

    bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(package_share / "launch" / "bringup_all.launch.py")),
        launch_arguments={
            "start_base_driver": start_base,
            "start_lidar_driver": start_lidar,
        }.items(),
    )

    laser_tf = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="base_to_laser_static_tf",
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
        condition=IfCondition(publish_laser_tf),
    )

    slam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(slam_share / "launch" / "online_async_launch.py")),
        launch_arguments={
            "slam_params_file": str(package_share / "config" / "slam_toolbox.yaml"),
            "use_sim_time": use_sim_time,
        }.items(),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("start_base_driver", default_value="true"),
            DeclareLaunchArgument("start_lidar_driver", default_value="true"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument(
                "publish_laser_tf",
                default_value="false",
                description="Enable only when the vendor URDF does not publish base_link to laser.",
            ),
            DeclareLaunchArgument("base_frame", default_value="base_link"),
            DeclareLaunchArgument("laser_frame", default_value="laser"),
            DeclareLaunchArgument("laser_x", default_value="0.0"),
            DeclareLaunchArgument("laser_y", default_value="0.0"),
            DeclareLaunchArgument("laser_z", default_value="0.0"),
            DeclareLaunchArgument("laser_yaw", default_value="3.141592653589793"),
            bringup,
            laser_tf,
            slam,
        ]
    )
