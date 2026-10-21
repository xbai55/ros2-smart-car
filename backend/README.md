# InsightRover 主机端 Backend

FastAPI + SQLAlchemy 的业务后端，为 InsightRover 智巡 Web 控制台提供认证、权限、机器人、
任务、地图路线、异常、通知、统计、审计与实时通信能力。数据库默认 SQLite
（`sqlite:///./smart_patrol.db`），可通过 `DATABASE_URL` 切换 PostgreSQL。

## 启动

```bash
cd backend
python -m app.seed                       # 初始化角色/权限/用户/示例数据（幂等）
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

登录账号：`admin/admin123`、`operator/operator123`、`auditor/auditor123`。
API 文档：`http://127.0.0.1:8000/docs`。

测试：

```bash
cd backend
python -m pytest -q
```

## 接口路径约定

同一业务的两套路径**并存且行为一致**，避免推翻现有实现：

| 业务 | 现有路径（Flutter 控制台使用） | 项目文档路径 |
| --- | --- | --- |
| 巡检任务 | `/api/v1/patrols`、`/api/v1/patrols/{id}/actions` | `/api/v1/patrol-tasks`、`/{id}`、`/{id}/start`、`/{id}/stop` |
| 运输任务 | `/api/v1/missions`、`/api/v1/missions/{id}/actions` | `/api/v1/mission-tasks`、`/{id}` |
| 角色 / 权限 | `/api/v1/users/roles`、`/api/v1/users/permissions` | `/api/v1/roles`、`/api/v1/permissions` |
| 系统设置 | `/api/v1/settings` | `/api/v1/system/settings`、`/api/v1/system/config`、`/api/v1/system/info` |
| 统计 | `/api/v1/analytics/summary` | `/api/v1/analytics/overview|tasks|robots|incidents`、`/api/v1/statistics/*` |

其余文档接口：`/api/v1/robots`（GET/POST）、`/api/v1/robots/{id}`（GET/PUT）、
`/api/v1/robots/{id}/status`、`/api/v1/robots/{id}/control`、`/api/v1/robots/{id}/emergency-stop`、
`/api/v1/maps`、`/api/v1/routes`、`/api/v1/incidents`、`/api/v1/notifications`、
`/api/v1/audit-logs`、`/api/v1/media/presign`、`/api/v1/media/complete`、
WebSocket `/ws/v1/robots/{id}`、`/ws/v1/notifications`。

## 返回结构与分页

沿用项目既有约定（前端直接消费裸 JSON），未额外包裹 `{code, message, data}` 外壳：

- 列表接口不传 `page` / `page_size` 时返回**裸数组**；
- 传了 `page` 或 `page_size` 时返回 `{"items": [...], "total": n, "page": p, "page_size": ps}`；
- 错误统一为 `{"detail": {"code": "...", "message": "..."}}`。

支持的筛选：机器人 `status`、`keyword`；巡检任务 `status`、`robot_id`、`keyword`；
运输任务 `status`、`robot_id`；异常 `severity`、`status`、`robot_id`、`type`；通知 `unread`、`kind`。

## 架构要点

- `app/gateway/robot_gateway.py`：FastAPI 与车端之间的唯一通信边界，只表达控制意图
  （模式、手动命令、急停、速度比例、任务指令），永远不发布 `/cmd_vel`。未配置
  `ROBOT_WEB_URL` 或车端不可达时返回结构化“未下发”结果，不抛异常。
- `app/services/realtime.py`：机器人实时状态 `robot:status:{robot_id}`。Redis 可用时优先，
  否则退回内存实现；`/api/v1/robots/{id}/status` 与机器人 WebSocket 都经由此抽象。
- `app/services/storage.py`：MinIO 优先、本地目录兜底的对象存储抽象。
- `app/services/ws_manager.py`：WebSocket 连接管理（按 `robot_id` 分房间）。
- `app/db/migrate.py`：启动时对比模型与真实表结构，仅 `ADD COLUMN` 补齐新增字段，
  不删除、不改类型，保证已有 `smart_patrol.db` 可直接使用。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./smart_patrol.db` | 切换 PostgreSQL |
| `JWT_SECRET` | `dev-secret-change-me` | 生产必须替换 |
| `REDIS_URL` / `REDIS_ENABLED` | `redis://127.0.0.1:6379/0` / `true` | 未安装 redis 依赖时自动降级 |
| `MINIO_ENDPOINT` 等 | 空 | 留空使用本地对象存储 |
| `ROBOT_WEB_URL` / `ROBOT_GATEWAY_URL` | 空 | 车端 Web 节点地址 |
| `CORS_ORIGINS` | 本地 8080/8888 | 允许的前端来源 |
