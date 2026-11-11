"""ROS-free confirmation, vocabulary validation and geometric association."""
import hashlib
import json
import math
from collections import deque

PRESETS = {'手机': ['cell phone'], '电话': ['cell phone'], '水瓶': ['bottle'], '瓶子': ['bottle'],
           '杯子': ['cup'], '背包': ['backpack'], '书包': ['backpack'], '椅子': ['chair'],
           '书': ['book'], '笔记本电脑': ['laptop'], '键盘': ['keyboard'], '鼠标': ['mouse'],
           '服务器': ['server rack'], '服务器机柜': ['server rack'], '示波器': ['oscilloscope'],
           '实验电源': ['laboratory power supply'], '显微镜': ['microscope'],
           '实验器材': ['oscilloscope', 'laboratory power supply', 'microscope']}
CLUTTER = ['bottle', 'cardboard box', 'bag', 'backpack', 'chair']


def targets(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError('请设置 1–8 个目标')
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('目标须包含名称及英文提示')
        label, prompt = item.get('name', ''), item.get('prompt', '')
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or not isinstance(prompt, str):
            raise ValueError('目标名称或英文提示无效')
        prompts = [prompt.strip()] if prompt.strip() else PRESETS.get(label.strip(), [label.strip()] if label.isascii() else [])
        if not prompts:
            raise ValueError('未知中文目标，请补充英文提示')
        for text in prompts:
            if not text.isascii() or not 1 <= len(text) <= 100 or not all(c.isalnum() or c in ' -' for c in text):
                raise ValueError('英文提示仅接受字母、数字、空格和连字符')
            if text.lower() not in [x['prompt'] for x in result]:
                result.append({'name': label.strip(), 'prompt': text.lower()})
    if len(result) > 8:
        raise ValueError('展开后最多允许 8 个目标类别')
    return result


def vocabulary_id(prompts):
    return hashlib.sha256(json.dumps(prompts, sort_keys=True).encode()).hexdigest()


class Confirmation:
    def __init__(self):
        self.frames = deque(maxlen=5)
        self.last_sequence = -1

    def observe(self, sequence, captured, now, detections):
        if sequence <= self.last_sequence or not 0 <= now-captured <= .5:
            return None
        self.last_sequence = sequence
        usable = [d for d in detections if math.isfinite(d.get('confidence', float('nan')))
                  and d['confidence'] >= .45 and d.get('key')]
        self.frames.append((now, usable))
        for candidate in usable:
            hits = [at for at, values in self.frames if now-at <= 1.5 and any(d['key'] == candidate['key'] for d in values)]
            if len(hits) >= 3 and hits[-1]-hits[0] >= .4-1e-6:
                return candidate
        return None


def associate_clutter(box, points, calibration, image_size, frame_at, scan_at):
    """Project calibrated base-frame lidar points; no monocular distance guesses."""
    if not calibration or abs(frame_at-scan_at) > .15:
        return None
    try:
        k, t = calibration['intrinsics'], calibration['base_to_camera']
        if calibration['image_size'] != list(image_size) or len(k) != 4 or len(t) != 12:
            return None
        if not all(type(v) in (float, int) and math.isfinite(v) for v in k+t) or min(k[:2]) <= 0:
            return None
        matches = []
        for x,y,z in points:
            # Current straight forward corridor, not the entire camera view.
            if not .0935 < x < 2. or abs(y) > .25:
                continue
            a,b,c = (sum(t[i+j]*v for j,v in enumerate((x,y,z)))+t[i+3] for i in (0,4,8))
            if c <= 0:
                continue
            u,v = k[0]*a/c+k[2], k[1]*b/c+k[3]
            if box[0] <= u <= box[2] and box[1] <= v <= box[3]:
                matches.append(x-.0935)
        return {'distance_m': min(matches), 'points': len(matches)} if matches else None
    except (KeyError, TypeError, ValueError, IndexError):
        return None
