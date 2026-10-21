"""Time-based confirmation and a durable outbox. No motion commands live here."""
import base64
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4


class DetectionTracks:
    """Associate boxes over time before confirming an individual visual candidate."""
    def __init__(self, expiry_sec=10.):
        self.tracks, self.sequence, self.expiry_sec = {}, 0, expiry_sec

    @staticmethod
    def iou(a, b):
        left, top, right, bottom = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
        intersection = max(0., right-left) * max(0., bottom-top)
        union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
        return intersection / union if union > 0 else 0.

    def update(self, candidates, now):
        self.tracks = {k:v for k,v in self.tracks.items() if now-v['time'] < self.expiry_sec}
        used = set()
        for candidate in sorted(candidates, key=lambda c:c['confidence'], reverse=True):
            scores = [(self.iou(candidate['box'], track['box']), key) for key, track in self.tracks.items()
                      if key not in used and track['type'] == candidate['type']]
            overlap, ident = max(scores, default=(0., None))
            if overlap < .25:
                self.sequence += 1
                ident = str(self.sequence)
            self.tracks[ident] = {'box':candidate['box'], 'type':candidate['type'], 'time':now}
            candidate['key'] = candidate['type'] + ':track:' + ident
            used.add(ident)
        return candidates


class EventGate:
    def __init__(self, confirm_sec=2.0, clear_sec=5.0, max_gap_sec=1.0):
        self.confirm_sec, self.clear_sec, self.max_gap_sec = confirm_sec, clear_sec, max_gap_sec
        self.entries = {}

    def update(self, candidates, now):
        emitted, present = [], set()
        for candidate in candidates:
            key = candidate['key']
            if key in present:
                continue
            present.add(key)
            previous = self.entries.get(key)
            if previous and now - previous['last'] >= self.clear_sec:
                previous = None
            if previous is None:
                previous = {'first': now, 'last': now, 'sent': False}
                self.entries[key] = previous
            elif not previous['sent'] and now - previous['last'] > self.max_gap_sec:
                previous['first'] = now
            previous['last'] = now
            if not previous['sent'] and now - previous['first'] >= self.confirm_sec:
                emitted.append(dict(candidate))
                previous['sent'] = True
        for key in list(self.entries):
            if key not in present and now - self.entries[key]['last'] >= self.clear_sec:
                del self.entries[key]
        return emitted

    def reset_pending(self):
        self.entries = {k: v for k, v in self.entries.items() if v['sent']}


class SafetyOutbox:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL, jpeg BLOB NOT NULL, ack INTEGER NOT NULL DEFAULT 0)')

    def _connect(self):
        return sqlite3.connect(str(self.path), timeout=5)

    def put(self, event, jpeg):
        if not jpeg:
            raise ValueError('异常缺少现场图片，保留候选等待重试')
        event = {**event, 'event_id': event.get('event_id') or str(uuid4())}
        with self.lock, self._connect() as db:
            db.execute('INSERT INTO events(id,body,jpeg) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING',
                       (event['event_id'], json.dumps(event, ensure_ascii=False, allow_nan=False), jpeg))
        return event

    def pending(self, limit=10):
        with self.lock, self._connect() as db:
            rows = db.execute('SELECT body,jpeg FROM events WHERE ack=0 ORDER BY rowid LIMIT ?', (min(20, max(1, limit)),)).fetchall()
        return [{**json.loads(body), 'snapshot_base64': base64.b64encode(jpeg).decode('ascii')} for body, jpeg in rows]

    def acknowledge(self, ids):
        if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(x, str) for x in ids):
            raise ValueError('事件确认列表无效')
        with self.lock, self._connect() as db:
            db.executemany("UPDATE events SET ack=1,jpeg=X'' WHERE id=?", [(x,) for x in ids])
            db.execute('DELETE FROM events WHERE ack=1 AND id NOT IN (SELECT id FROM events WHERE ack=1 ORDER BY rowid DESC LIMIT 1000)')


def corridor_candidate(points, zones, pose, map_identity, *, now, scan_at, pose_fresh, min_points=4):
    """Only configured map corridors count; any obstacle ahead is not a blockage."""
    if not pose_fresh or now - scan_at > .6 or not pose or not pose.get('ok'):
        return []
    x, y, yaw = (pose[k] for k in ('x', 'y', 'yaw'))
    if not all(math.isfinite(v) for v in (x, y, yaw)):
        return []
    c, s = math.cos(yaw), math.sin(yaw)
    result = []
    for zone in zones:
        if zone.get('map_key') != map_identity:
            continue
        polygon = zone['polygon']
        occupied = 0
        axis = zone.get('axis_yaw', 0.)
        lateral = lambda px, py: -math.sin(axis) * px + math.cos(axis) * py
        edges = [lateral(px, py) for px, py in polygon]
        lower, upper = min(edges), max(edges)
        samples = []
        longitudinal = lambda px, py: math.cos(axis) * px + math.sin(axis) * py
        for px, py in points:
            wx, wy = x + c * px - s * py, y + s * px + c * py
            inside = False
            j = len(polygon) - 1
            for i, (ax, ay) in enumerate(polygon):
                bx, by = polygon[j]
                if (ay > wy) != (by > wy) and wx < (bx - ax) * (wy - ay) / (by - ay) + ax:
                    inside = not inside
                j = i
            occupied += inside
            if inside:
                samples.append((longitudinal(wx, wy), lateral(wx, wy)))
        # A few points near one wall must not label a still-passable corridor blocked.
        free_width, obstructed = upper-lower, False
        for along, _ in samples:
            section = [side for depth, side in samples if along <= depth <= along + .3]
            if len(section) < min_points:
                continue
            cursor, gap = lower, 0.
            for value in sorted(section):
                gap = max(gap, value - .08 - cursor)
                cursor = max(cursor, value + .08)
            gap = max(gap, upper - cursor)
            if gap < zone.get('required_free_width_m', .65):
                free_width, obstructed = min(free_width, gap), True
        if occupied >= min_points and obstructed:
            result.append({'key': 'corridor:' + zone['id'], 'type': 'blocked_passage',
                           'label': '通道持续占用', 'zone_id': zone['id'], 'points': occupied,
                           'free_width_estimate_m': round(max(0., free_width), 3),
                           'polygon': polygon, 'laser_points': [[round(v,3) for v in p] for p in points[::max(1,len(points)//180)][:180]],
                           'camera_coverage': 'not_calibrated',
                           'method': 'configured_corridor_lidar_occupancy'})
    return result
