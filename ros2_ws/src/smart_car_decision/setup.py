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
            "laser_obstacle_monitor = smart_car_decision.laser_obstacle_monitor:main",
            "tcp_command_bridge = smart_car_decision.tcp_command_bridge:main",
            "yolo11_camera_node = smart_car_decision.yolo11_camera_node:main",
        ],
    },
)
