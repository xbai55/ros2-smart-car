"""轻量级结构补齐。

开发环境沿用已有的 smart_patrol.db，SQLAlchemy 的 create_all 不会为已存在的表
新增列。这里在启动时对比模型与真实表结构，只做 ADD COLUMN 补齐，不删除、不改类型。
"""
from uuid import uuid4

from sqlalchemy import Column as TableColumn, Engine, MetaData, String, Table, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.schema import Column

from .base import Base

revisions = Table("schema_migrations", MetaData(), TableColumn("revision", String(64), primary_key=True))


def _permission_revision(engine, revision, grants):
    from ..models import Permission, Role

    with engine.begin() as connection:
        revisions.create(connection, checkfirst=True)
        if connection.scalar(select(revisions.c.revision).where(revisions.c.revision == revision)):
            return
        with Session(bind=connection) as db:
            roles = {role.name: role for role in db.scalars(select(Role))}
            for name, (description, role_names) in grants.items():
                permission = db.scalar(select(Permission).where(Permission.name == name))
                if permission is None:
                    permission = Permission(id=str(uuid4()), name=name, description=description)
                    db.add(permission)
                for role_name in role_names & roles.keys():
                    role = roles[role_name]
                    if permission not in role.permissions:
                        role.permissions.append(permission)
            db.flush()
        connection.execute(revisions.insert().values(revision=revision))


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
    if {"roles", "permissions", "role_permissions"} <= tables:
        _permission_revision(engine, "v4-assistant-permissions-1", {
            "assistant.read": ("查看自己的助手会话", {"admin", "operator", "viewer", "auditor"}),
            "assistant.use": ("向助手发送消息", {"admin", "operator"}),
            "assistant.settings": ("管理助手模型启用状态", {"admin"}),
        })
        _permission_revision(engine, "v4-diagnostics-permissions-1", {
            "diagnostics.read": ("查看系统运行摘要", {"admin", "operator"}),
            "diagnostics.technical": ("查看技术诊断", {"admin"}),
            "diagnostics.export": ("导出诊断包", {"admin"}),
        })
    if "assistant_events" in tables:
        with engine.begin() as connection:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_assistant_events_execution_id ON assistant_events (execution_id)"))
    if "capability_acceptances" in tables:
        with engine.begin() as connection:
            revisions.create(connection, checkfirst=True)
            revision = "v4-capability-evidence-1"
            if not connection.scalar(select(revisions.c.revision).where(revisions.c.revision == revision)):
                connection.execute(revisions.insert().values(revision=revision))
    if "assistant_trial_authorizations" in tables:
        with engine.begin() as connection:
            revisions.create(connection, checkfirst=True)
            revision = "v4-assistant-trials-1"
            if not connection.scalar(select(revisions.c.revision).where(revisions.c.revision == revision)):
                connection.execute(revisions.insert().values(revision=revision))
    return added
