import json
from pathlib import Path

import pytest
import yaml

from smart_car_decision.map_assets import (
    build_map_metadata,
    inspect_map,
    validate_map_id,
    write_map_preview,
)


def write_test_map(tmp_path):
    pgm = tmp_path / "map.pgm"
    pgm.write_text("P2\n# test map\n2 2\n255\n0 254 205 254\n", encoding="ascii")
    config = tmp_path / "map.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "image": "map.pgm",
                "mode": "trinary",
                "resolution": 0.05,
                "origin": [0.0, 0.0, 0.0],
                "negate": 0,
                "occupied_thresh": 0.65,
                "free_thresh": 0.25,
            }
        ),
        encoding="utf-8",
    )
    return config


def test_map_id_rejects_paths_and_accepts_stable_slug():
    assert validate_map_id("lab-a_20260621") == "lab-a_20260621"
    for invalid in ("", "../map", "a/b", "map name", ".hidden"):
        with pytest.raises(ValueError):
            validate_map_id(invalid)


def test_inspect_map_reports_dimensions_and_occupancy_ratios(tmp_path):
    report = inspect_map(write_test_map(tmp_path))

    assert report["width"] == 2
    assert report["height"] == 2
    assert report["resolution"] == 0.05
    assert report["occupied_ratio"] == 0.25
    assert report["free_ratio"] == 0.5
    assert report["unknown_ratio"] == 0.25


def test_map_metadata_is_json_serializable_and_traceable(tmp_path):
    map_yaml = write_test_map(tmp_path)

    metadata = build_map_metadata(
        map_id="lab-a",
        site="engineering-lab",
        map_yaml=map_yaml,
        git_commit="abc1234",
        platform="jetson",
        ros_distro="humble",
        bag_path="bags/lab-a",
    )

    assert metadata["map_id"] == "lab-a"
    assert metadata["site"] == "engineering-lab"
    assert metadata["git_commit"] == "abc1234"
    assert metadata["quality"]["width"] == 2
    json.dumps(metadata)


def test_map_preview_is_a_valid_png_file(tmp_path):
    map_yaml = write_test_map(tmp_path)
    preview = tmp_path / "preview.png"

    write_map_preview(map_yaml, preview)

    assert preview.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert preview.stat().st_size > 40


def test_map_loading_launch_starts_map_server_with_lifecycle_manager():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "ros2_ws/src/smart_car_decision/launch/map_view.launch.py"
    ).read_text(encoding="utf-8")

    assert "nav2_map_server" in source
    assert "nav2_lifecycle_manager" in source
    assert "yaml_filename" in source
    assert "map_server" in source
