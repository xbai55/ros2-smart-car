from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    package_share = Path(get_package_share_directory("smart_car_decision"))
    slam_share = Path(get_package_share_directory("slam_toolbox"))

    start_base = LaunchConfiguration("start_base_driver")
    start_lidar = LaunchConfiguration("start_lidar_driver")
    use_sim_time = LaunchConfiguration("use_sim_time")

    bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(package_share / "launch" / "bringup_all.launch.py")),
        launch_arguments={
            "start_base_driver": start_base,
            "start_lidar_driver": start_lidar,
            "start_base_odom": LaunchConfiguration("start_base_odom"),
            "start_robot_description": LaunchConfiguration("start_robot_description"),
            "publish_scan_laser_tf": LaunchConfiguration("publish_laser_tf"),
            **{name: LaunchConfiguration(name) for name in (
                "base_frame", "laser_frame", "laser_x", "laser_y", "laser_z", "laser_yaw",
            )},
        }.items(),
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
            DeclareLaunchArgument("start_base_odom", default_value="true"),
            DeclareLaunchArgument("start_robot_description", default_value="true"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument(
                "publish_laser_tf",
                default_value="true",
                description="Publish one base_link to laser TF through bringup; disable when an external launch already owns this frame.",
            ),
            DeclareLaunchArgument("base_frame", default_value="base_link"),
            DeclareLaunchArgument("laser_frame", default_value="laser"),
            DeclareLaunchArgument("laser_x", default_value="0.0435"),
            DeclareLaunchArgument("laser_y", default_value="0.00005258"),
            DeclareLaunchArgument("laser_z", default_value="0.11"),
            DeclareLaunchArgument("laser_yaw", default_value="3.141592653589793"),
            bringup,
            slam,
        ]
    )
