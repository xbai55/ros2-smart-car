"""轻量级结构补齐。

开发环境沿用已有的 smart_patrol.db，SQLAlchemy 的 create_all 不会为已存在的表
新增列。这里在启动时对比模型与真实表结构，只做 ADD COLUMN 补齐，不删除、不改类型。
"""
from sqlalchemy import Engine, inspect, text
from sqlalchemy.sql.schema import Column

from .base import Base


def _add_column_ddl(column: Column, dialect) -> str:
    sql = f'"{column.name}" {column.type.compile(dialect)}'
    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        value = default.arg
        if isinstance(value, bool):
            sql += f" DEFAULT {1 if value else 0}"
        elif isinstance(value, (int, float)):
            sql += f" DEFAULT {value}"
        elif isinstance(value, str):
            escaped = value.replace("'", "''")
            sql += f" DEFAULT '{escaped}'"
    return sql


def ensure_schema(engine: Engine) -> list[str]:
    added: list[str] = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = _add_column_ddl(column, engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
            existing.add(column.name)
            added.append(f"{table.name}.{column.name}")
    return added
