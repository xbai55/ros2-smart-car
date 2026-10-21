"""Non-destructive editing of an occupancy grid in image coordinates."""
import copy
import hashlib
import json
import math
from collections import deque
from PIL import Image, ImageDraw

from .slam_maps import snapshot_assets


def isolated_candidates(snapshot, limit=2):
    """Return stable image-coordinate components, without editing any cells."""
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError("清噪仅支持 1–8 格的小连通区域")
    width, height = snapshot['info']['width'], snapshot['info']['height']
    data, seen, candidates = snapshot['data'], bytearray(len(snapshot['data'])), []
    for index, value in enumerate(data):
        if value < 65 or seen[index]:
            continue
        queue, cells, count = deque([index]), [], 0
        seen[index] = 1
        while queue:
            current = queue.popleft()
            count += 1
            if len(cells) <= limit:
                cells.append(current)
            x, y = current % width, current // width
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not (dx or dy) or not 0 <= x+dx < width or not 0 <= y+dy < height:
                        continue
                    n = (y+dy)*width+x+dx
                    if not seen[n] and data[n] >= 65:
                        seen[n] = 1
                        queue.append(n)
        if count <= limit:
            candidates.append({'id': str(index), 'cells': [[i % width, height-1-i//width] for i in cells],
                               'area_m2': count * snapshot['info']['resolution']**2})
    return candidates


def paint(data, info, operation, selected=None):
    """Rasterize in a bounded tile: no full-size canvas per brush stroke."""
    width, height, resolution = info['width'], info['height'], info['resolution']
    value = operation.get('value')
    if type(value) is not int or value not in (-1, 0, 100):
        raise ValueError('绘制状态必须为障碍、可通行或未知')
    shape = operation.get('shape')
    points = operation.get('points', [])
    if shape not in ('brush', 'line', 'rectangle', 'cells') or not isinstance(points, list) or not 1 <= len(points) <= 20000:
        raise ValueError('绘制工具或点数无效')
    coords = []
    for p in points:
        if not isinstance(p, dict):
            raise ValueError('绘制坐标无效')
        x, y = p.get('x'), p.get('y')
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (int,float)) or not isinstance(y, (int,float)) or not math.isfinite(x) or not math.isfinite(y) or not 0 <= x < width or not 0 <= y < height:
            raise ValueError('绘制点须位于地图内')
        coords.append((float(x), float(y)))
    if shape == 'cells':
        if selected is None:
            raise ValueError('候选清理需要校验原始候选')
        for x,y in coords:
            index = (height-1-int(y))*width+int(x)
            if index not in selected:
                raise ValueError('候选已经变化，请重新分析')
            data[index] = value
        return
    if shape in ('line','rectangle') and len(coords) != 2:
        raise ValueError('直线或矩形需要两个端点')
    thickness = operation.get('width_m', .10)
    if isinstance(thickness,bool) or not isinstance(thickness,(int,float)) or not math.isfinite(thickness) or not .01 <= thickness <= 2:
        raise ValueError('笔刷宽度须为 0.01–2 米')
    stroke = max(1, round(thickness/resolution))
    pad = stroke/2+1
    left, top = max(0, math.floor(min(p[0] for p in coords)-pad)), max(0, math.floor(min(p[1] for p in coords)-pad))
    right, bottom = min(width, math.ceil(max(p[0] for p in coords)+pad)+1), min(height, math.ceil(max(p[1] for p in coords)+pad)+1)
    tile = Image.new('1', (right-left,bottom-top))
    draw = ImageDraw.Draw(tile)
    pts = [(x-left,y-top) for x,y in coords]
    if shape == 'rectangle':
        box = (min(p[0] for p in pts),min(p[1] for p in pts),max(p[0] for p in pts),max(p[1] for p in pts))
        draw.rectangle(box, fill=1 if operation.get('filled',False) else None, outline=1, width=stroke)
    else:
        if len(pts)>1:
            draw.line(pts,fill=1,width=stroke)
        radius = max(.5,stroke/2)
        for x,y in pts:
            draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=1)
            draw.point((int(x),int(y)),fill=1)
    for row in range(tile.height):
        for col in range(tile.width):
            if tile.getpixel((col,row)):
                data[(height-1-top-row)*width+left+col] = value


def optimize_snapshot(snapshot, operations):
    snapshot_assets(snapshot)
    if not isinstance(operations, list) or not 1 <= len(operations) <= 100:
        raise ValueError("请提供 1–100 个编辑操作")
    # Geometry/metadata are immutable here; copying millions of scalar cells
    # recursively makes every small brush edit unnecessarily expensive.
    result = {**snapshot, 'info':copy.deepcopy(snapshot['info']), 'data':list(snapshot['data'])}
    width, height = result["info"]["width"], result["info"]["height"]
    data, changed = result["data"], set()
    original_mask = list(snapshot.get('keepout', [0]*len(data)))
    mask = list(original_mask)
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("地图编辑操作格式无效")
        if operation.get('type') in ('paint', 'keepout', 'candidate'):
            target = mask if operation['type'] == 'keepout' else data
            if operation['type'] == 'keepout' and operation.get('value') not in (0,100):
                raise ValueError('禁行遮罩只支持添加或擦除')
            selected = None
            if operation['type'] == 'candidate':
                if operation.get('shape') != 'cells' or operation.get('value') not in (-1,0):
                    raise ValueError('候选只能改为未知或可通行')
                selected = {(result['info']['height']-1-y)*width+x for c in isolated_candidates(result, operation.get('max_cells',2)) for x,y in c['cells']}
            paint(target, result['info'], operation, selected)
        elif operation.get("type") == "despeckle":
            limit = operation.get("max_cells", 2)
            if type(limit) is not int or not 1 <= limit <= 8:
                raise ValueError("清噪仅支持 1–8 格的小连通区域")
            seen = bytearray(len(data))
            for index, value in enumerate(data):
                if value < 65 or seen[index]:
                    continue
                queue, component, count = deque([index]), [], 0
                seen[index] = 1
                while queue:
                    current = queue.popleft()
                    count += 1
                    if len(component) <= limit:
                        component.append(current)
                    x, y = current % width, current // width
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if not (dx or dy) or not 0 <= x + dx < width or not 0 <= y + dy < height:
                                continue
                            neighbor = (y + dy) * width + x + dx
                            if not seen[neighbor] and data[neighbor] >= 65:
                                seen[neighbor] = 1
                                queue.append(neighbor)
                if count <= limit:
                    for current in component:
                        data[current] = -1
                        changed.add(current)
        elif operation.get("type") == "wall":
            try:
                ax, ay = (float(operation["start"][k]) for k in ("x", "y"))
                bx, by = (float(operation["end"][k]) for k in ("x", "y"))
                thickness = float(operation.get("width_m", .10))
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError("墙线参数无效") from exc
            if (not all(math.isfinite(v) for v in (ax, ay, bx, by, thickness)) or
                    not .02 <= thickness <= .5 or
                    not all(0 <= x < width and 0 <= y < height for x, y in ((ax, ay), (bx, by)))):
                raise ValueError("墙线端点须位于图内，宽度须为 0.02–0.5 米")
            radius = max(math.sqrt(.5), thickness / result["info"]["resolution"] / 2)
            dx, dy = bx - ax, by - ay
            denominator = dx * dx + dy * dy
            for y in range(max(0, math.floor(min(ay, by) - radius)), min(height, math.ceil(max(ay, by) + radius + 1))):
                for x in range(max(0, math.floor(min(ax, bx) - radius)), min(width, math.ceil(max(ax, bx) + radius + 1))):
                    t = min(1, max(0, ((x + .5 - ax) * dx + (y + .5 - ay) * dy) / denominator)) if denominator else 0
                    if math.hypot(x + .5 - ax - t * dx, y + .5 - ay - t * dy) <= radius:
                        index = (height - 1 - y) * width + x
                        if data[index] != 100:
                            data[index] = 100
                            changed.add(index)
        else:
            raise ValueError("不支持的地图编辑操作")
    # Edited occupancy cannot impersonate the original live session.
    result["session_id"] = "derived-" + hashlib.sha256(json.dumps({"parent": snapshot, "operations": operations}, sort_keys=True).encode()).hexdigest()[:32]
    result["revision"] = 1
    result.pop("asset_digest", None)
    if any(mask) or 'keepout' in snapshot:
        result['keepout'] = mask
        result['map_features'] = ['keepout-v1']
    return result, sum(a != b or m != old for a,b,m,old in zip(data,snapshot['data'],mask,original_mask))
