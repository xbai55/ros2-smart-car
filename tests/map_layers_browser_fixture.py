"""Uploaded-floorplan UI QA: fake status/planner, real calibration, no ROS/vehicle."""
import io
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2_ws/src/smart_car_decision"))
from fastapi.responses import Response
from PIL import Image, ImageDraw
from conftest import FakeWebNode
from navigation_browser_fixture import SimulatedNavigation
from smart_car_decision.navigation_config import NavigationConfigStore, validate_map_goal
from smart_car_decision.web_api import create_app

DRAWING = {"id": "qa-upload", "name": "演示平面图（模拟数据）", "width": 600, "height": 320, "kind": "uploaded", "revision": "maps/qa-upload.png"}
PAIRS = [{"drawing": {"x": x, "y": y}, "world": {"x": x * .025 - 1, "y": 7 - y * .025}} for x, y in ((30, 30), (570, 30), (30, 290), (570, 290))]

def app():
    node = FakeWebNode(ros_status_age_sec=.1)
    node.store.update(lidar={"ok": True}, map={"ok": True}, odom={"ok": True}, tf={"ok": True},
                      map_pose={"ok": True, "x": 2, "y": 2, "yaw": math.pi / 2}, updated_at=time.time())
    data = [0] * (300 * 160)
    for y in range(160):
        for x in range(300):
            if x < 6 or y < 6 or x > 293 or y > 153 or (145 <= x <= 149 and y > 65):
                data[y * 300 + x] = 100
            elif x > 265 and y < 35:
                data[y * 300 + x] = -1
    snapshot = {"header": {"frame_id": "map"}, "info": {"width": 300, "height": 160, "resolution": .05,
                "origin": {"x": -1., "y": -1., "yaw": 0.}}, "data": data, "updated_at": time.time()}
    node.map_snapshot.update(snapshot)
    config_path = ROOT / "output/map-layers-qa/navigation.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # Each launch starts with no registration so the browser can exercise the wizard.
    node.navigation_config = NavigationConfigStore(config_path.parent / f"session-{time.time_ns()}.json")
    nav = SimulatedNavigation(node)
    original_plan = nav.plan
    async def checked_plan(payload):
        validate_map_goal(payload["goal"], node.map_snapshot.snapshot())
        return await original_plan(payload)
    nav.plan = checked_plan
    node.navigation = nav
    api = create_app(node, static_dir=ROOT / "web-console/dist")
    image = Image.new("RGB", (600, 320), "#ffffff")
    pen = ImageDraw.Draw(image)
    pen.rectangle((12, 12, 588, 308), outline="#475569", width=4)
    pen.line((292, 12, 292, 190), fill="#475569", width=4)
    pen.text((80, 55), "ROOM A", fill="#94a3b8")
    pen.text((380, 55), "ROOM B", fill="#94a3b8")
    pen.text((180, 240), "CORRIDOR", fill="#94a3b8")
    buf = io.BytesIO(); image.save(buf, format="PNG")
    @api.get("/api/v1/maps")
    def maps():
        return [{**DRAWING, "image_url": "/api/v1/maps/qa-upload/image", "image_key": DRAWING["revision"], "active": True, "floor": "1F", "description": "模拟 UI 验证", "created_at": "2026-10-13T00:00:00Z", "updated_at": None, "metadata": {}}]
    @api.get("/api/v1/maps/qa-upload/image")
    def map_image(): return Response(buf.getvalue(), media_type="image/png")
    @api.get("/api/v1/maps/qa-upload/places")
    def places(): return [{"id": "qa-door", "map_id": DRAWING["id"], "name": "门口（模拟）", "x": 100, "y": 230, "yaw": 0}]
    @api.get("/qa/anchors")
    def anchors(): return {"anchors": PAIRS, "drawing": DRAWING}
    return api

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app(), host="127.0.0.1", port=8099, log_level="warning")
