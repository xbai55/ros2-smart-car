"""Validate metric SLAM snapshots and store portable assets, without ROS dependencies."""
import hashlib
import io
import json
import math

from PIL import Image

MAX_CELLS = 16_000_000


def snapshot_assets(snapshot):
    try:
        info = snapshot["info"]
        width, height = info["width"], info["height"]
        if (type(width) is not int or type(height) is not int or width <= 0 or height <= 0 or width > 16384 or height > 16384
                or width * height > MAX_CELLS):
            raise ValueError("地图尺寸无效或过大")
        resolution = float(info["resolution"])
        origin = [float(info["origin"][k]) for k in ("x", "y", "yaw")]
        if not math.isfinite(resolution) or resolution <= 0 or not all(math.isfinite(v) for v in origin):
            raise ValueError("地图分辨率或原点无效")
        data = snapshot["data"]
        if not isinstance(data, list) or len(data) != width * height:
            raise ValueError("栅格数据长度与尺寸不一致")
        if any(type(v) is not int or v < -1 or v > 100 for v in data) or all(v == -1 for v in data):
            raise ValueError("地图没有有效栅格数据")
        mask = snapshot.get('keepout')
        if mask is not None and (not isinstance(mask,list) or len(mask) != len(data) or any(type(v) is not int or v not in (0,100) for v in mask)):
            raise ValueError('禁行遮罩尺寸或栅格无效')
        session = snapshot["session_id"]
        frame = snapshot["header"]["frame_id"]
        if not isinstance(session, str) or not session or len(session) > 128 or not isinstance(frame, str) or not frame or len(frame) > 128:
            raise ValueError("地图会话或坐标系无效")
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("车端地图快照格式无效") from exc
    raw = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    pixels = bytes(205 if value < 0 or 25 <= value < 65 else 0 if value >= 65 else 254
                   for y in range(height - 1, -1, -1) for value in data[y * width:(y + 1) * width])
    png = io.BytesIO()
    Image.frombytes("L", (width, height), pixels).save(png, format="PNG")
    pgm = f"P5\n{width} {height}\n255\n".encode() + pixels
    yaml = (f"image: map.pgm\nmode: trinary\nresolution: {resolution}\norigin: {origin}\n"
            "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n").encode()
    assets = {"preview.png": (png.getvalue(), "image/png"), "map.pgm": (pgm, "image/x-portable-graymap"),
              "map.yaml": (yaml, "application/yaml"), "snapshot.json": (raw, "application/json")}
    if mask is not None:
        mask_pixels = bytes(0 if v else 254 for y in range(height-1,-1,-1) for v in mask[y*width:(y+1)*width])
        assets['keepout.pgm'] = (f'P5\n{width} {height}\n255\n'.encode()+mask_pixels, 'image/x-portable-graymap')
        assets['keepout.yaml'] = (yaml.replace(b'map.pgm',b'keepout.pgm'), 'application/yaml')
        overlay = Image.new('RGBA',(width,height),(231,62,67))
        overlay.putalpha(Image.frombytes('L',(width,height),bytes(150 if v else 0 for y in range(height-1,-1,-1) for v in mask[y*width:(y+1)*width])))
        buffer = io.BytesIO(); overlay.save(buffer,format='PNG')
        assets['keepout.png'] = (buffer.getvalue(),'image/png')
    return {"width": width, "height": height, "resolution": resolution, "origin": origin,
            "digest": digest, "session_id": session, "frame_id": frame,
            'terrain_digest':hashlib.sha256(pgm).hexdigest(),
            'keepout_digest':hashlib.sha256(assets['keepout.pgm'][0]).hexdigest() if mask is not None else None,
            "assets": assets}
