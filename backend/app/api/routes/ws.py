"""实时通道。

- /ws/v1/robots/{robot_id}：推送机器人实时状态（robot:status:{robot_id}，Redis 优先）
- /ws/v1/notifications：推送异常事件、任务状态变化和系统通知

连接管理见 services/ws_manager.py，消息结构保持与现有 Flutter 控制台兼容：
{"type": "robot_status", "robot_id": ..., "status": {...}}
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, or_, and_

from ...core.config import settings
from ...core.security import decode_token
from ...db.session import SessionLocal
from ...models import Notification, User
from ...services.realtime import get_realtime_store
from ...services.ws_manager import notification_manager, robot_manager

router = APIRouter(tags=["websocket"])

PING_FRAMES = {"ping", '{"type":"ping"}'}


@router.websocket("/ws/v1/robots/{robot_id}")
async def robot_status_ws(websocket: WebSocket, robot_id: str) -> None:
    await robot_manager.connect(websocket, room=robot_id)
    store = get_realtime_store()
    try:
        initial = store.get_status(robot_id)
        if initial is not None:
            await websocket.send_json(
                {
                    "type": "robot_status",
                    "robot_id": robot_id,
                    "status": {**initial, "robot_id": robot_id},
                }
            )
        last_version = store.version(robot_id)
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                if message in PING_FRAMES:
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass

            version = store.version(robot_id)
            if version != last_version:
                last_version = version
                status = store.get_status(robot_id) or {"status": "offline"}
                await websocket.send_json(
                    {
                        "type": "robot_status",
                        "robot_id": robot_id,
                        "status": {**status, "robot_id": robot_id},
                    }
                )
    except WebSocketDisconnect:
        return
    finally:
        robot_manager.disconnect(websocket, room=robot_id)


def _ws_user_id(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if not token:
        header = websocket.headers.get("authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    if not token:
        return None
    try:
        payload = decode_token(token, settings.jwt_secret)
    except ValueError:
        return None
    if payload.get("type") != "access":
        return None
    return payload.get("sub")


@router.websocket("/ws/v1/notifications")
async def notifications_ws(websocket: WebSocket) -> None:
    user_id = _ws_user_id(websocket)
    with SessionLocal() as db:
        user = db.get(User, user_id) if user_id else None
        if not user or not user.active or 'notifications.read' not in user.permissions:
            await websocket.close(code=1008)
            return
    await notification_manager.connect(websocket)
    last_cursor = None
    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                if message in PING_FRAMES:
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass

            db = SessionLocal()
            try:
                user = db.get(User, user_id)
                if not user or not user.active or 'notifications.read' not in user.permissions or _ws_user_id(websocket) != user_id:
                    await websocket.close(code=1008)
                    return
                query = select(Notification).where(Notification.user_id == user_id)
                if last_cursor is not None:
                    created, ident = last_cursor
                    query = query.where(or_(Notification.created_at > created,
                                            and_(Notification.created_at == created, Notification.id > ident)))
                query = query.order_by(Notification.created_at.asc(), Notification.id.asc()).limit(20)
                for item in db.execute(query).scalars().all():
                    await websocket.send_json(
                        {
                            "type": "notification_created",
                            "notification": {
                                "id": item.id,
                                "kind": item.kind,
                                "title": item.title,
                                "body": item.body,
                                "ref_id": item.ref_id,
                                "read": item.read,
                                "created_at": item.created_at.isoformat() if item.created_at else None,
                            },
                        }
                    )
                    last_cursor = (item.created_at, item.id)
            finally:
                db.close()

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    finally:
        notification_manager.disconnect(websocket)
