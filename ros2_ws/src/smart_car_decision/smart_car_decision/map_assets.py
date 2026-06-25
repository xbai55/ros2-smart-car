import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zlib

import yaml


MAP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_map_id(value):
    map_id = str(value or "")
    if not MAP_ID_PATTERN.fullmatch(map_id):
        raise ValueError("map id must use letters, numbers, dot, underscore, or dash")
    return map_id


def _next_pgm_token(data, offset):
    length = len(data)
    while offset < length:
        if data[offset] in b" \t\r\n":
            offset += 1
            continue
        if data[offset] == ord("#"):
            newline = data.find(b"\n", offset)
            offset = length if newline < 0 else newline + 1
            continue
        break
    start = offset
    while offset < length and data[offset] not in b" \t\r\n#":
        offset += 1
    if start == offset:
        raise ValueError("invalid PGM header")
    return data[start:offset], offset


def read_pgm(path):
    data = Path(path).read_bytes()
    offset = 0
    tokens = []
    for _ in range(4):
        token, offset = _next_pgm_token(data, offset)
        tokens.append(token)

    magic = tokens[0]
    width, height, max_value = (int(value) for value in tokens[1:])
    expected = width * height
    if width <= 0 or height <= 0 or not 0 < max_value <= 255:
        raise ValueError("unsupported PGM dimensions or bit depth")

    if magic == b"P2":
        pixels = []
        for _ in range(expected):
            token, offset = _next_pgm_token(data, offset)
            pixels.append(int(token))
    elif magic == b"P5":
        if data[offset:offset + 2] == b"\r\n":
            offset += 2
        elif offset < len(data) and data[offset] in b" \t\r\n":
            offset += 1
        pixels = list(data[offset:offset + expected])
    else:
        raise ValueError("only P2 and 8-bit P5 PGM maps are supported")

    if len(pixels) != expected or any(not 0 <= value <= max_value for value in pixels):
        raise ValueError("PGM pixel payload is incomplete or invalid")
    return width, height, max_value, pixels


def inspect_map(map_yaml):
    map_yaml = Path(map_yaml)
    config = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
    image_path = (map_yaml.parent / config["image"]).resolve()
    width, height, max_value, pixels = read_pgm(image_path)
    negate = bool(config.get("negate", 0))
    occupied_threshold = float(config.get("occupied_thresh", 0.65))
    free_threshold = float(config.get("free_thresh", 0.25))
    mode = str(config.get("mode", "trinary"))

    counts = {"occupied": 0, "free": 0, "unknown": 0}
    for value in pixels:
        if mode == "trinary" and value == 205:
            counts["unknown"] += 1
            continue
        occupancy = value / max_value if negate else (max_value - value) / max_value
        if occupancy > occupied_threshold:
            counts["occupied"] += 1
        elif occupancy < free_threshold:
            counts["free"] += 1
        else:
            counts["unknown"] += 1

    total = width * height
    return {
        "width": width,
        "height": height,
        "resolution": float(config["resolution"]),
        "occupied_ratio": round(counts["occupied"] / total, 4),
        "free_ratio": round(counts["free"] / total, 4),
        "unknown_ratio": round(counts["unknown"] / total, 4),
    }


def _png_chunk(chunk_type, payload):
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", checksum)


def write_map_preview(map_yaml, destination):
    map_yaml = Path(map_yaml)
    config = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
    image_path = (map_yaml.parent / config["image"]).resolve()
    width, height, max_value, pixels = read_pgm(image_path)
    grayscale = bytes(round(value * 255 / max_value) for value in pixels)
    rows = b"".join(
        b"\x00" + grayscale[row * width:(row + 1) * width]
        for row in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows))
        + _png_chunk(b"IEND", b"")
    )
    Path(destination).write_bytes(png)


def build_map_metadata(
    *, map_id, site, map_yaml, git_commit, platform, ros_distro, bag_path=""
):
    return {
        "map_id": validate_map_id(map_id),
        "site": str(site),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": str(git_commit),
        "platform": str(platform),
        "ros_distro": str(ros_distro),
        "bag_path": str(bag_path),
        "quality": inspect_map(map_yaml),
        "verification": {
            "map_reloaded": False,
            "second_run_compared": False,
            "notes": "Pending Jetson field verification",
        },
    }


def _git_commit():
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def save_map_asset(*, map_id, output_root, site, platform, ros_distro, bag_path=""):
    map_id = validate_map_id(map_id)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / map_id
    if destination.exists():
        raise FileExistsError(f"map asset already exists: {destination}")

    temporary = Path(tempfile.mkdtemp(prefix=f".{map_id}-", dir=root))
    try:
        prefix = temporary / "map"
        subprocess.run(
            ["ros2", "run", "nav2_map_server", "map_saver_cli", "-f", str(prefix)],
            check=True,
        )
        map_yaml = temporary / "map.yaml"
        map_image = temporary / "map.pgm"
        if not map_yaml.is_file() or not map_image.is_file():
            raise RuntimeError("map_saver_cli did not create map.yaml and map.pgm")

        metadata = build_map_metadata(
            map_id=map_id,
            site=site,
            map_yaml=map_yaml,
            git_commit=_git_commit(),
            platform=platform,
            ros_distro=ros_distro,
            bag_path=bag_path,
        )
        write_map_preview(map_yaml, temporary / "preview.png")
        (temporary / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (temporary / "notes.md").write_text(
            "# Map verification notes\n\n- Reload test: pending\n- Second run comparison: pending\n",
            encoding="utf-8",
        )
        temporary.rename(destination)
        return destination
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Save and inspect smart-car map assets")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save = subparsers.add_parser("save", help="save the current /map as a traceable asset")
    save.add_argument("map_id")
    save.add_argument("--site", default="unspecified")
    save.add_argument("--output-root", default="maps")
    save.add_argument("--platform", default=os.environ.get("MAP_PLATFORM", "jetson"))
    save.add_argument("--ros-distro", default=os.environ.get("ROS_DISTRO", "humble"))
    save.add_argument("--bag-path", default="")

    inspect = subparsers.add_parser("inspect", help="print quality metrics for a map YAML")
    inspect.add_argument("map_yaml")
    args = parser.parse_args(argv)

    if args.command == "save":
        destination = save_map_asset(
            map_id=args.map_id,
            output_root=args.output_root,
            site=args.site,
            platform=args.platform,
            ros_distro=args.ros_distro,
            bag_path=args.bag_path,
        )
        print(destination)
    else:
        print(json.dumps(inspect_map(args.map_yaml), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
