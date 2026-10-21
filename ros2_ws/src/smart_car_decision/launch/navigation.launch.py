"""Humble Nav2 with every velocity output routed through decision_controller."""
import atexit
import tempfile
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def merge_parameters(base, overrides):
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_parameters(base[key], value)
        else:
            base[key] = value
    return base


def launch_navigation(context):
    share = Path(get_package_share_directory("smart_car_decision"))
    nav_share = Path(get_package_share_directory("nav2_bringup"))
    map_path = Path(LaunchConfiguration("map").perform(context)).expanduser().resolve()
    if not map_path.is_file():
        raise RuntimeError("Provide an existing saved map: map:=/absolute/path/lab.yaml")
    # Inherit the installed Humble BT plugin list instead of duplicating it.
    parameters = yaml.safe_load((nav_share / "params" / "nav2_params.yaml").read_text())
    overrides = yaml.safe_load((share / "config" / "navigation.yaml").read_text())
    merge_parameters(parameters, overrides)
    radius = float(LaunchConfiguration('robot_radius').perform(context))
    if not .01 <= radius <= 2: raise RuntimeError('Invalid robot radius')
    keepout = LaunchConfiguration('keepout').perform(context)
    if keepout and not Path(keepout).is_file(): raise RuntimeError('Keepout file is missing')
    for group in parameters.values():
        if "ros__parameters" in group:
            group["ros__parameters"]["use_sim_time"] = False
    for name in ("local_costmap", "global_costmap"):
        parameters[name][name]["ros__parameters"]["use_sim_time"] = False
        group=parameters[name][name]['ros__parameters']
        group['robot_radius']=radius
        # The configured radius is the complete conservative footprint used by
        # both the goal guard and the pre-expanded keepout mask.
        group['footprint_padding']=0.0
        if keepout:
            group['filters']=['keepout_filter']
            group['keepout_filter']={'plugin':'nav2_costmap_2d::KeepoutFilter','enabled':True,
                                     'filter_info_topic':'/navigation/keepout_filter_info'}
    parameters["map_server"]["ros__parameters"]["yaml_filename"] = str(map_path)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(parameters, handle)
        params_file = handle.name
    atexit.register(lambda: Path(params_file).unlink(missing_ok=True))
    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(nav_share / "launch" / "localization_launch.py")),
        # Humble evaluates `not use_composition` as a Python expression.
        # Unlike YAML booleans, this argument must use Python's capital F.
        launch_arguments={"map": str(map_path), "params_file": params_file, "use_sim_time": "false", "autostart": "true", "use_composition": "False"}.items(),
    )
    nodes = []
    if keepout:
        nodes.extend([
            Node(package='nav2_map_server',executable='map_server',name='keepout_mask_server',output='screen',parameters=[{
                'yaml_filename':keepout,'topic_name':'/navigation/keepout_mask','frame_id':'map','use_sim_time':False}]),
            Node(package='nav2_map_server',executable='costmap_filter_info_server',name='keepout_filter_info_server',output='screen',parameters=[{
                'filter_info_topic':'/navigation/keepout_filter_info','mask_topic':'/navigation/keepout_mask',
                'type':0,'base':0.0,'multiplier':1.0,'use_sim_time':False}]),
            Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',name='lifecycle_manager_keepout',output='screen',parameters=[{
                'use_sim_time':False,'autostart':True,'node_names':['keepout_mask_server','keepout_filter_info_server']}])])
    definitions = [
        ("nav2_controller", "controller_server", [("cmd_vel", "/navigation/raw_cmd_vel")]),
        ("nav2_smoother", "smoother_server", []),
        ("nav2_planner", "planner_server", []),
        ("nav2_behaviors", "behavior_server", [("cmd_vel", "/navigation/raw_cmd_vel")]),
        ("nav2_bt_navigator", "bt_navigator", []),
        ("nav2_waypoint_follower", "waypoint_follower", []),
        ("nav2_velocity_smoother", "velocity_smoother", [("cmd_vel", "/navigation/raw_cmd_vel"), ("cmd_vel_smoothed", "/navigation/cmd_vel")]),
    ]
    for package, executable, remappings in definitions:
        nodes.append(Node(package=package, executable=executable, name=executable, output="screen", parameters=[params_file], remappings=remappings))
    nodes.append(Node(package="nav2_lifecycle_manager", executable="lifecycle_manager", name="lifecycle_manager_navigation", output="screen",
                      parameters=[{"use_sim_time": False, "autostart": True, "node_names": [name for _, name, _ in definitions]}]))
    return [localization, *nodes]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("map", description="Absolute path to the saved laboratory map YAML."),
        DeclareLaunchArgument('keepout', default_value='', description='Optional footprint-expanded keepout YAML.'),
        DeclareLaunchArgument('robot_radius', default_value='0.25'),
        OpaqueFunction(function=launch_navigation),
    ])
