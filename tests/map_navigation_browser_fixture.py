"""Isolated UI acceptance fixture: real business APIs and task runner, fake robot/Nav2.

No physical vehicle URL, ROS topics or production database is used.
"""
import asyncio
import io
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/map-navigation-20261015"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + (OUTPUT / f"ui-{uuid4().hex}.sqlite3").as_posix()
os.environ["JWT_SECRET"] = "isolated-ui-fixture-only"
os.environ["REDIS_ENABLED"] = "false"
os.environ["ROBOT_WEB_URL"] = ""
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "ros2_ws/src/smart_car_decision"))

from PIL import Image, ImageDraw
from app.api.router import api_router
from app.db.session import engine, SessionLocal
from app.db.base import Base
from app.models import Robot, MapModel, MapPlace, AppSetting
from app.seed import seed_session
from app.services import storage
from app.services.slam_maps import snapshot_assets
from app.gateway.robot_gateway import RobotGateway
from conftest import FakeWebNode
from navigation_browser_fixture import SimulatedNavigation
from smart_car_decision.navigation_config import NavigationConfigStore, fit_calibration
from smart_car_decision.navigation_tasks import NavigationTaskRunner
from smart_car_decision.web_api import create_app


def app():
    Base.metadata.create_all(engine)
    storage._storage = storage.LocalStorageService(str(OUTPUT / "ui-storage"))
    node = FakeWebNode(ros_status_age_sec=.1)
    node.store.update(mode="stop", emergency_stop=False, lidar={"ok": True}, map={"ok": True}, odom={"ok": True}, tf={"ok": True},
                      map_pose={"ok": True, "x": 1, "y": 1, "yaw": 0}, updated_at=time.time())
    data = [0] * 16000
    for y in range(100):
        for x in range(160):
            if x < 3 or y < 3 or x > 156 or y > 96:
                data[y * 160 + x] = 100
    data[65 * 160 + 80] = 100
    snapshot = {"session_id": "qa-session", "header": {"frame_id": "map", "stamp": {"sec": 1, "nanosec": 0}},
                "info": {"width": 160, "height": 100, "resolution": .05, "origin": {"x": -1, "y": -1, "yaw": 0}}, "data": data, "updated_at": time.time()}
    node.map_snapshot.update(snapshot)
    drawing = {"id": "qa-drawing", "kind": "uploaded", "name": "实验室平面图（模拟）", "width": 600, "height": 400, "revision": "maps/qa-drawing.png"}
    anchors = [{"drawing": {"x": x, "y": y}, "world": {"x": x * .01, "y": 4 - y * .01}}
               for x, y in [(0, 0), (600, 0), (0, 400), (600, 400)]]
    node.navigation_config = NavigationConfigStore(OUTPUT / f"ui-navigation-{uuid4().hex}.json")
    node.navigation_config.calibrate(anchors, snapshot, drawing)
    node.navigation_map = node.map_snapshot

    class DemoBridge(SimulatedNavigation):
        radius = .25
        lock = threading.RLock()

        def _health(self):
            return ""

        async def start(self, payload, guard=None):
            if guard and not guard():
                raise RuntimeError("模拟任务已取消")
            result = await super().start(payload)
            goal_id = result["goal_id"]
            async def complete():
                await asyncio.sleep(2)
                if self.state["goal_id"] == goal_id and self.state["state"] == "running":
                    self.state.update(state="succeeded", message="模拟到达", distance_remaining=0)
                    node.set_mode("stop")
            asyncio.create_task(complete())
            return result

        def cancel(self, message="模拟停止", failed=False):
            return super().cancel(message)

    node.navigation = DemoBridge(node)
    node.navigation_tasks = NavigationTaskRunner(node, OUTPUT / f"ui-task-{uuid4().hex}.json")
    node.navigation_runtime = type("DemoRuntime", (), {"snapshot": lambda self: {"state": "ready", "localized": True, "digest": "demo", "map_id": "qa-slam", "message": "模拟定位已就绪"}})()
    api = create_app(node, static_dir=ROOT / "web-console/dist")
    api.include_router(api_router)
    packed = snapshot_assets(snapshot)
    with SessionLocal() as db:
        seed_session(db)
        db.add(Robot(id="qa-robot", name="模拟小车（无实车连接）", serial="QA-ONLY"))
        assets = {}
        for filename, (content, mime) in packed["assets"].items():
            key = f"maps/qa-slam/{packed['digest']}/{filename}"
            storage.get_storage().put(key, content, content_type=mime)
            assets[filename] = key
        db.add(MapModel(id="qa-slam", name="SLAM 原图（模拟）", width=160, height=100, resolution=.05, origin=json.dumps([-1, -1, 0]),
                        image_key=assets["preview.png"], active=True, meta=json.dumps({"source": "slam", "digest": packed["digest"], "session_id": "qa-session", "frame_id": "map", "assets": assets})))
        image = Image.new("RGB", (600, 400), "#f9fafb")
        pen = ImageDraw.Draw(image)
        pen.rectangle((10, 10, 590, 390), outline="#425466", width=6)
        pen.text((40, 40), "LOCAL SIMULATION - NO ROBOT", fill="#425466")
        out = io.BytesIO(); image.save(out, format="PNG")
        storage.get_storage().put("maps/qa-drawing.png", out.getvalue(), content_type="image/png")
        db.add(MapModel(id="qa-drawing", name=drawing["name"], width=600, height=400, active=True, image_key="maps/qa-drawing.png", meta=json.dumps({"source": "uploaded_image"})))
        db.add(MapPlace(id="qa-teacher", map_id="qa-drawing", name="老师处（模拟）", x=500, y=100, yaw=0))
        selection = db.query(AppSetting).filter(AppSetting.key == "navigation_map_id").first()
        if selection: selection.value = "qa-drawing"
        else: db.add(AppSetting(id=str(uuid4()), key="navigation_map_id", value="qa-drawing"))
        db.commit()

    async def gateway_request(self, path, payload=None, *, query=None):
        if path == "task/action": return await node.navigation_tasks.action(payload)
        if path == "task": return await node.navigation_tasks.create(payload) if payload else node.navigation_tasks.snapshot_for((query or {}).get("run_id"))
        raise RuntimeError("模拟环境不启动定位进程")
    RobotGateway.navigation_request = gateway_request
    return api


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app(), host="127.0.0.1", port=8105, log_level="warning")
