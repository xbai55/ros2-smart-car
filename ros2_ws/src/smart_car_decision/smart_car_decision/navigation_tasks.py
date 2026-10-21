"""Persistent delivery/patrol orchestration over the single Nav2 bridge.

Only matching goal results advance a task. Restarted processes never resume motion.
"""
import asyncio
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from uuid import uuid4

from .navigation_config import drawing_identity, finite_number, map_key, transform_point, validate_map_goal

TERMINAL = {"idle", "completed", "failed", "cancelled"}


def _write_record(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class NavigationTaskRunner:
    def __init__(self, node, path="~/.ros/insightrover/navigation-task.json"):
        self.node, self.path = node, Path(path).expanduser()
        self.lock = threading.RLock()
        self.operation_lock = asyncio.Lock()
        self.worker = None
        self.epoch = 0
        self._last_odom = None
        self._distance = 0.0
        self.state = {"state": "idle", "message": "暂无执行任务"}
        if self.path.is_file():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.state, dict) or not isinstance(self.state.get("state"), str):
                raise ValueError("导航任务记录格式无效")
            if self.state.get("run_id"):
                historical = self.path.parent / "navigation-runs" / (hashlib.sha256(self.state["run_id"].encode()).hexdigest() + ".json")
                if historical.is_file():
                    self.state = json.loads(historical.read_text(encoding="utf-8"))
            self._distance = float(self.state.get('distance_m', 0.))
            if self.state.get("state") not in TERMINAL:
                node.set_command("stop")
                node.set_mode("stop")
                node.navigation.cancel("车端重启，停止遗留任务", failed=True)
                self._update(state="failed", message="车端进程重启，任务已中止；确认定位后重新创建")

    @property
    def active(self):
        return self.snapshot()["state"] not in TERMINAL

    def snapshot(self):
        with self.lock:
            value = copy.deepcopy(self.state)
            value['distance_m'] = max(value.get('distance_m', 0.0), self._distance)
            return value

    def observe_odometry(self, x, y, stamp):
        if not all(math.isfinite(v) for v in (x, y, stamp)):
            return
        with self.lock:
            previous, self._last_odom = self._last_odom, (x, y, stamp)
            if previous and self.state['state'] in {'planning', 'running', 'returning', 'dwelling'}:
                dt = stamp - previous[2]
                distance = math.hypot(x - previous[0], y - previous[1])
                if 0 < dt <= 1.0 and distance <= max(.05, dt * 1.5):
                    self._distance += distance

    def snapshot_for(self, run_id=None):
        if not run_id or run_id == self.state.get("run_id"):
            return self.snapshot()
        path = self.path.parent / "navigation-runs" / (hashlib.sha256(run_id.encode()).hexdigest() + ".json")
        if not path.is_file():
            raise ValueError("车端没有此任务的执行记录")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("state") not in TERMINAL:
            value.update(state="failed", message="该任务不再是当前执行，已停止；请核对定位后新建任务", version=value.get("version", 0) + 1)
        return value

    def _update(self, **values):
        with self.lock:
            reset = values.pop("_reset", False)
            next_state = {**({} if reset else self.state), **values, "updated_at": time.time(),
                          "version": 1 if reset else self.state.get("version", 0) + 1}
            next_state['distance_m'] = self._distance
            self.path.parent.mkdir(parents=True, exist_ok=True)
            targets = []
            if next_state.get("run_id"):
                history = self.path.parent / "navigation-runs"
                history.mkdir(exist_ok=True)
                targets.append(history / (hashlib.sha256(next_state["run_id"].encode()).hexdigest() + ".json"))
            targets.append(self.path)
            for target in targets:
                _write_record(target, next_state)
                self.state = next_state
            self.state = next_state

    def _context(self):
        state = self.snapshot()
        snapshot = self.node.map_snapshot.snapshot()
        calibration = self.node.navigation_config.snapshot().get("calibration")
        if (not snapshot or not calibration or calibration.get("invalidated") or
                map_key(snapshot) != state["map_key"] or calibration["matrix"] != state["calibration_matrix"] or
                drawing_identity(calibration.get("drawing")) != drawing_identity(state["calibration_drawing"])):
            raise RuntimeError("任务所用地图或标定已变化，请取消后重新创建")
        error = self.node.navigation._health()
        if error:
            raise RuntimeError(error)

    async def create(self, payload):
        async with self.operation_lock:
            return self._create(payload)

    def _create(self, payload):
        with self.node.navigation.lock:
            # Stable caller ID makes retrying a lost HTTP response non-dispatching.
            ident = payload.get("run_id")
            if not isinstance(ident, str) or not 1 <= len(ident) <= 128:
                raise ValueError("任务请求标识无效")
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if self.state.get("run_id") == ident:
                if self.state.get("request_fingerprint") != fingerprint:
                    raise RuntimeError("同一请求标识的地图或目标已变化，请新建任务")
                return self.snapshot()
            previous_path = self.path.parent / "navigation-runs" / (hashlib.sha256(ident.encode()).hexdigest() + ".json")
            if previous_path.is_file():
                previous = self.snapshot_for(ident)
                if previous.get("request_fingerprint") != fingerprint:
                    raise RuntimeError("同一请求标识的目标已变化，请新建任务")
                return previous
            if self.active or self.node.navigation.snapshot()["state"] in {"starting", "running"}:
                raise RuntimeError("小车已有任务或导航，请先结束当前执行")
            error = self.node.navigation._health()
            if error:
                raise RuntimeError(error)
            kind = payload.get("kind")
            if kind not in {"delivery", "patrol"}:
                raise ValueError("任务类型无效")
            cycles, dwell = payload.get('cycles', 1), payload.get('dwell_sec', 0)
            if type(cycles) is not int or not 1 <= cycles <= 100:
                raise ValueError('巡航圈数须为 1–100 的整数')
            if isinstance(dwell, bool) or not isinstance(dwell, (int, float)) or not math.isfinite(dwell) or not 0 <= dwell <= 600:
                raise ValueError('站点停留须在 0–600 秒之间')
            if kind == 'delivery' and (cycles != 1 or dwell != 0):
                raise ValueError('运输任务不支持巡航圈数或停留设置')
            calibration = self.node.navigation_config.snapshot()["calibration"]
            snapshot = self.node.map_snapshot.snapshot()
            if snapshot.get("session_id") and payload.get("control_session_id") != snapshot["session_id"]:
                raise ValueError("控制连接已变化，请刷新后核对当前小车")
            if (payload.get("map_key") != map_key(snapshot) or payload.get("calibration_matrix") != calibration["matrix"] or
                    drawing_identity(payload.get("calibration_drawing")) != drawing_identity(calibration.get("drawing"))):
                raise ValueError("地图或平面图标定已变化")
            points = payload.get("waypoints")
            if not isinstance(points, list) or not 1 <= len(points) <= (1 if kind == "delivery" else 30):
                raise ValueError("运输需选择一个目的地，巡航需选择 1–30 个站点")
            matrix, goals = calibration["matrix"], []
            for item in points:
                p = transform_point(item["drawing"], matrix)
                validate_map_goal(p, self.node.navigation_map.snapshot(), self.node.navigation.radius)
                yaw = finite_number(item.get("yaw", 0))
                x, y = math.cos(yaw), math.sin(yaw)
                p["yaw"] = math.atan2(matrix[3] * x + matrix[4] * y, matrix[0] * x + matrix[1] * y)
                goals.append({**p, "name": str(item.get("name", "目标"))[:128]})
            pose = self.node.store.snapshot()["map_pose"]
            origin = {k: finite_number(pose[k]) for k in ("x", "y", "yaw")}
            if payload.get("return_to_start") is True:
                validate_map_goal(origin, self.node.navigation_map.snapshot(), self.node.navigation.radius)
            self.epoch += 1
            self._distance, self._last_odom = 0.0, None
            self._update(_reset=True, request_fingerprint=fingerprint, run_id=ident, task_id=payload.get("task_id"), kind=kind, state="waiting_load" if kind == "delivery" else "prepared",
                         message="请放入文件并确认装件" if kind == "delivery" else "巡航已就绪，请开始执行",
                         map_key=map_key(snapshot), calibration_matrix=list(matrix), calibration_drawing=calibration.get("drawing"),
                         goals=goals, index=0, origin=origin, return_to_start=payload.get("return_to_start") is True,
                         returning=False, goal_id=None, completed_stops=0, created_at=time.time())
            self._update(cycles=cycles, dwell_sec=float(dwell), cycle_index=0, dwell_remaining_sec=0.0,
                         total_stops=len(goals) * cycles, elapsed_sec=0.0)
            return self.snapshot()

    async def action(self, payload):
        async with self.operation_lock:
            state = self.snapshot()
            if payload.get("run_id") != state.get("run_id"):
                if payload.get("action") == "cancel" and isinstance(payload.get("run_id"), str) and 1 <= len(payload["run_id"]) <= 128:
                    ident = payload["run_id"]
                    path = self.path.parent / "navigation-runs" / (hashlib.sha256(ident.encode()).hexdigest() + ".json")
                    if path.is_file():
                        return self.snapshot_for(ident)
                    if not payload.get("task_id") or payload.get("kind") not in {"delivery", "patrol"}:
                        raise ValueError("取消未派发任务需要业务任务标识")
                    tombstone = {"run_id": ident, "task_id": payload["task_id"], "kind": payload["kind"], "state": "cancelled",
                                 "message": "未确认的执行请求已取消", "version": 1, "updated_at": time.time()}
                    _write_record(path, tombstone)
                    return tombstone
                raise ValueError("执行任务已变化，请刷新页面")
            action = payload.get("action")
            if action == "cancel":
                if state["state"] not in TERMINAL:
                    self._interrupt()
                    self._update(state="cancelled", message="任务已取消")
            elif action == "pause" and state["state"] in {"planning", "running", "returning", "dwelling"}:
                self._interrupt()
                self._update(state="paused", message="任务已暂停，恢复后从当前位置重新规划")
            elif ((action == "loaded" and state["state"] == "waiting_load") or
                  (action == "start" and state["state"] == "prepared") or
                  (action == "resume" and state["state"] == "paused")):
                self._context()
                self._launch()
            elif action == "handover" and state["state"] == "waiting_handover":
                if state["return_to_start"]:
                    self._context()
                    self._update(returning=True)
                    self._launch()
                else:
                    self._update(state="completed", message="文件已取走，运输完成", completed_at=time.time())
            else:
                raise RuntimeError("当前任务阶段不允许此操作")
            return self.snapshot()

    def _launch(self):
        self.epoch += 1
        epoch = self.epoch
        self._update(state="planning", message="正在规划路线", goal_id=None)
        self.worker = asyncio.create_task(self._run(epoch))

    def _interrupt(self):
        self.epoch += 1
        if self.worker:
            self.worker.get_loop().call_soon_threadsafe(self.worker.cancel)
        self.node.navigation.cancel("任务暂停或取消")

    def interrupt(self, message="导航已停止，任务已取消"):
        if self.active:
            self._interrupt()
            self._update(state="cancelled", message=message)

    async def _run(self, epoch):
        try:
            while epoch == self.epoch:
                self._context()
                state = self.snapshot()
                remaining = state.get('dwell_remaining_sec', 0)
                if remaining > 0:
                    await self._dwell(epoch, remaining)
                    if epoch != self.epoch:
                        return
                    if self._advance_patrol():
                        return
                    continue
                goal = state["origin"] if state["returning"] else state["goals"][state["index"]]
                plan = await self.node.navigation.plan({"goal": goal, "map_key": state["map_key"],
                                                       "calibration_matrix": state["calibration_matrix"],
                                                       "calibration_drawing": state["calibration_drawing"]})
                if epoch != self.epoch:
                    return
                started = await self.node.navigation.start({"plan_id": plan["plan_id"]}, guard=lambda: epoch == self.epoch)
                if epoch != self.epoch:
                    self.node.navigation.cancel()
                    return
                self._update(state="returning" if state["returning"] else "running", goal_id=started["goal_id"],
                             message="正在返回起点" if state["returning"] else f"正在前往{goal.get('name', '目的地')}")
                deadline = time.monotonic() + 1800
                observed_at = time.monotonic()
                while epoch == self.epoch:
                    current_time = time.monotonic()
                    with self.lock:
                        self.state['elapsed_sec'] = self.state.get('elapsed_sec', 0) + current_time - observed_at
                    observed_at = current_time
                    result = self.node.navigation.snapshot()
                    if result["goal_id"] != started["goal_id"]:
                        raise RuntimeError("导航目标被其他操作替换，任务已中止")
                    if result["state"] == "succeeded":
                        break
                    if result["state"] in {"failed", "canceled"}:
                        raise RuntimeError(result["message"])
                    if time.monotonic() > deadline:
                        raise RuntimeError("本段导航超过 30 分钟，任务已停止")
                    await asyncio.sleep(.1)
                if epoch != self.epoch:
                    return
                # A matching Nav2 success is required before handover/completion.
                if state["returning"]:
                    current = self.snapshot()
                    self._update(state="completed", message="巡航完成，小车已返回起点" if state['kind'] == 'patrol' else "文件已交接，小车已返回起点", completed_at=time.time(),
                                 acceptance_met=self._distance >= 20 and current.get('elapsed_sec', 0) >= 600 if state['kind'] == 'patrol' else None)
                    return
                completed = state["index"] + 1
                if state["kind"] == "delivery":
                    self._update(completed_stops=completed, state="waiting_handover", message="已到达，请取走文件并确认")
                    return
                self._update(state='dwelling', dwell_remaining_sec=state.get('dwell_sec', 0),
                             message=f"已到达{goal.get('name', '站点')}，正在停留观察")
                if state.get('dwell_sec', 0):
                    await self._dwell(epoch, state['dwell_sec'])
                    if epoch != self.epoch:
                        return
                if self._advance_patrol():
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if epoch == self.epoch:
                self.node.navigation.cancel(str(exc), failed=True)
                try:
                    self._update(state="failed", message=str(exc))
                except OSError:
                    with self.lock:
                        self.state.update(state="failed", message=f"任务已停止，执行记录写入失败：{exc}")

    async def _dwell(self, epoch, remaining):
        self._update(state='dwelling', message='站点停留观察中')
        previous = time.monotonic()
        while remaining > 0 and epoch == self.epoch:
            self._context()
            await asyncio.sleep(min(.1, remaining))
            now = time.monotonic()
            delta, previous = now - previous, now
            remaining = max(0., remaining - delta)
            with self.lock:
                self.state['dwell_remaining_sec'] = remaining
                self.state['elapsed_sec'] = self.state.get('elapsed_sec', 0) + delta

    def _advance_patrol(self):
        state = self.snapshot()
        completed = state.get('completed_stops', 0) + 1
        total = state.get('total_stops', len(state['goals']))
        if completed >= total:
            if state['return_to_start']:
                self._update(completed_stops=completed, returning=True, state='planning', dwell_remaining_sec=0., message='正在规划返程')
                return False
            self._update(completed_stops=completed, state='completed', completed_at=time.time(), dwell_remaining_sec=0.,
                         message='所有巡航站点已到达', acceptance_met=self._distance >= 20 and state.get('elapsed_sec', 0) >= 600)
            return True
        self._update(completed_stops=completed, index=completed % len(state['goals']), cycle_index=completed // len(state['goals']),
                     state='planning', dwell_remaining_sec=0., message='正在规划下一站')
        return False
