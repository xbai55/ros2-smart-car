from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router, ws_router
from .api.routes.health import router as health_router
from .core.config import settings
from .db.base import Base
from .db.migrate import ensure_schema
from .db.session import engine
from .services.realtime import get_realtime_store
from .services.storage import get_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    # 提前确定实时层与存储层实现，便于日志与 /api/v1/system/info 展示
    get_realtime_store()
    get_storage()
    from .services.safety_ingest import run_safety_ingest
    worker = asyncio.create_task(run_safety_ingest()) if settings.database_url != 'sqlite://' else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


app = FastAPI(title="InsightRover Smart Patrol API", version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)
app.include_router(health_router)
