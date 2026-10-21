from fastapi import APIRouter
from sqlalchemy import text

from ..deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> dict:
    checks: dict[str, str] = {"database": "ok"}
    try:
        db = next(get_db())
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        checks["database"] = "error"
    ready = all(v == "ok" for v in checks.values())
    return {"status": "ready" if ready else "not_ready", "checks": checks}