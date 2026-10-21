"""列表接口的分页辅助。

约定（与现有 Flutter 前端保持兼容）：
- 不传 page / page_size 时返回裸数组，保持既有返回结构；
- 传了任一参数时返回 {"items": [...], "total": n, "page": p, "page_size": ps}。
"""
from typing import Any, Callable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


def resolve_page(page: int | None, page_size: int | None) -> tuple[int, int]:
    resolved_page = page or 1
    resolved_size = page_size or DEFAULT_PAGE_SIZE
    return resolved_page, min(resolved_size, MAX_PAGE_SIZE)


def run_list(
    db: Session,
    stmt: Select,
    serializer: Callable[[Any], dict],
    page: int | None = None,
    page_size: int | None = None,
) -> Any:
    """执行列表查询；未请求分页时返回裸数组，否则返回带 items/total 的对象。"""
    if page is None and page_size is None:
        rows: Sequence[Any] = db.execute(stmt).scalars().all()
        return [serializer(row) for row in rows]

    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()
    resolved_page, resolved_size = resolve_page(page, page_size)
    rows = db.execute(
        stmt.limit(resolved_size).offset((resolved_page - 1) * resolved_size)
    ).scalars().all()
    return {
        "items": [serializer(row) for row in rows],
        "total": total,
        "page": resolved_page,
        "page_size": resolved_size,
    }


def build_envelope(items: list[Any], total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
