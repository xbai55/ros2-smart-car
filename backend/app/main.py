from contextlib import asynccontextmanager
import os
from pathlib import Path
import asyncio
from contextlib import suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router, ws_router
from .api.routes.health import router as health_router
from .api.routes.vehicle_control import router as vehicle_control_router
from .core.config import settings
from .db.base import Base
from .db.migrate import ensure_schema
from .db.session import engine
from .services.realtime import get_realtime_store
from .services.storage import get_storage
from .services.robot_context import robot_context_service
from .services.task_reconciler import run_task_reconciler
from .services.control_leases import control_lease_manager
from .services.assistant_worker import AssistantWorker, cancel_on_desktop_exit
from .services import diagnostics
from .services.diagnostics.vehicle import ingest_vehicle


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    # 提前确定实时层与存储层实现，便于日志与 /api/v1/system/info 展示
    get_realtime_store()
    get_storage()
    from .services.safety_ingest import run_safety_ingest
    workers = [asyncio.create_task(run_safety_ingest()),
               asyncio.create_task(control_lease_manager.run()),
               asyncio.create_task(run_task_reconciler()),
               asyncio.create_task(AssistantWorker().run()),
               asyncio.create_task(robot_context_service.run())] if settings.database_url != 'sqlite://' else []
    if settings.database_url != 'sqlite://' and os.getenv('DIAGNOSTICS_ENABLED', '1') != '0':
        path = Path(os.getenv('DIAGNOSTICS_DIR', settings.storage_local_dir)) / 'diagnostics.sqlite3'
        def bounded_int(name, default):
            try:
                return int(os.getenv(name, default))
            except ValueError:
                return default

        diagnostics.store = diagnostics.DiagnosticStore(
            path, max_mib=bounded_int('DIAGNOSTICS_MAX_MIB', 48),
            normal_days=bounded_int('DIAGNOSTICS_NORMAL_DAYS', 7),
            critical_days=bounded_int('DIAGNOSTICS_CRITICAL_DAYS', 14),
        )
        diagnostics.store.start()
        diagnostics.emit('host.started', 'startup', module='lifespan')
        if os.getenv('DIAGNOSTICS_VEHICLE_SYNC', '1') != '0':
            workers.append(asyncio.create_task(ingest_vehicle(diagnostics.store)))
    try:
        yield
    finally:
        for worker in workers:
            worker.cancel()
        for worker in workers:
            with suppress(asyncio.CancelledError):
                await worker
        if getattr(app.state, "exit_requested", False):
            await cancel_on_desktop_exit()
        if diagnostics.store:
            diagnostics.emit('host.stopping', 'shutdown', module='lifespan')
            await asyncio.to_thread(diagnostics.store.close)
            diagnostics.store = None


app = FastAPI(title="InsightRover Smart Patrol API", version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(diagnostics.DiagnosticMiddleware)

app.include_router(api_router)
app.include_router(ws_router)
app.include_router(health_router)
app.include_router(vehicle_control_router)
