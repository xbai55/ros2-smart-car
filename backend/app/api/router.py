from fastapi import APIRouter

from .routes import (
    analytics,
    audit,
    auth,
    incidents,
    maps,
    media,
    mission_tasks,
    navigation_tasks,
    missions,
    notifications,
    patrol_tasks,
    patrols,
    robots,
    roles,
    routes,
    settings,
    system,
    users,
    ws,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(robots.router)
api_router.include_router(maps.router)
api_router.include_router(routes.router)
api_router.include_router(patrols.router)
api_router.include_router(patrol_tasks.router)
api_router.include_router(missions.router)
api_router.include_router(mission_tasks.router)
api_router.include_router(navigation_tasks.router)
api_router.include_router(incidents.router)
api_router.include_router(analytics.router)
api_router.include_router(analytics.statistics_router)
api_router.include_router(notifications.router)
api_router.include_router(audit.router)
api_router.include_router(settings.router)
api_router.include_router(system.router)
api_router.include_router(media.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)

# WebSocket 路由不挂 /api/v1 前缀，挂到 app 根路径。
ws_router = APIRouter()
ws_router.include_router(ws.router)
