from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="smart_car_decision",
                executable="patrol_executor",
                name="patrol_executor",
                output="screen",
            ),
            Node(
                package="smart_car_decision",
                executable="mission_executor",
                name="mission_executor",
                output="screen",
            ),
        ]
    )
