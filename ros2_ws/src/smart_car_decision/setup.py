from glob import glob
from setuptools import setup

package_name = "smart_car_decision"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/models", glob("models/*.pt")),
        ("share/" + package_name + "/web/static", glob("web/static/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="xbai55",
    maintainer_email="xbai55@example.com",
    description="Decision and safety control nodes for the ROSMASTER X3 smart car.",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "decision_controller = smart_car_decision.decision_controller:main",
            "mode_manager = smart_car_decision.mode_manager:main",
            "laser_obstacle_monitor = smart_car_decision.laser_obstacle_monitor:main",
            "tcp_command_bridge = smart_car_decision.tcp_command_bridge:main",
            "yolo11_camera_node = smart_car_decision.yolo11_camera_node:main",
            "color_tracker_node = smart_car_decision.color_tracker_node:main",
            "object_follow_node = smart_car_decision.object_follow_node:main",
            "system_status_node = smart_car_decision.system_status_node:main",
            "web_app_node = smart_car_decision.web_app_node:main",
        ],
    },
)
