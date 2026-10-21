# 地图管理

业务后端位于本项目 `backend/`。首次部署按 `backend/README.md` 初始化账户；现有数据库在应用启动时自动创建 `map_places` 表，保留原有表和记录。

## 本机运行

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端开发服务器将 `/api/v1` 转发到 `BUSINESS_PROXY_TARGET`，默认 `http://127.0.0.1:8000`。该代理与车端 `ROBOT_PROXY_TARGET` 独立。生产部署需为 `/api/v1` 配置指向业务后端的反向代理；将前端单独放到车端静态目录不会自动提供业务服务。

进入 `#/maps`，使用现有系统账户登录。operator/admin 可以管理地图，auditor/viewer 可以查看。登录接口接入现有 JWT 与权限服务，访问令牌过期时自动刷新，退出时清除本机令牌。

1. 点击“添加地图”，填写名称与区域，选择 PNG/JPG/WebP 图片，最大 10 MB、1600 万像素。
2. 点击“上传并标注地点”，图片经服务端解码校验后保存，宽高由实际图片确定。
3. 在详情页点击“标注地点”，点击图片，填写“老师处”“门口”等名称，点击“保存地点”。
4. 点击已有标记或地点列表的编辑按钮，可以修改名称与坐标，也可再次点击图片移动地点。
5. 地点和地图删除前有确认弹窗。地图已有路线或任务引用时返回 409 并保留原记录，解除关联后方可删除。删除地图会删除其地点标注和本接口创建的图片文件。

地点坐标以原始图片左上角为原点，x 向右、y 向下，单位为像素。图片显示缩放不改变保存坐标；导航部署需再与真实定位地图对齐。地图的“启用”字段属于地图库管理状态，不表示已加载到小车。

## 存储与接口

默认数据库：`backend/smart_patrol.db`（SQLite），可通过 `DATABASE_URL` 使用 PostgreSQL。图片保存到 `STORAGE_LOCAL_DIR/maps/`，默认 `backend/storage/maps/`；配置 MinIO 时复用项目的对象存储实现。数据库保存图片 key、尺寸与地点关系，不存大块图片数据。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/maps`、`/api/v1/maps/{id}` | 查询地图 |
| POST | `/api/v1/maps/upload?name=...&floor=...&description=...` | 以图片二进制请求体上传，Content-Type 为图片 MIME |
| GET | `/api/v1/maps/{id}/image` | 带认证读取地图图片 |
| PUT / DELETE | `/api/v1/maps/{id}` | 修改属性 / 删除地图 |
| GET / POST | `/api/v1/maps/{id}/places` | 查询 / 新增地点 |
| PUT / DELETE | `/api/v1/maps/{id}/places/{place_id}` | 修改 / 删除地点 |

所有地图接口均需 Bearer 令牌。读取要求 `maps.read`，修改要求 `maps.manage`。图片请求通过认证接口获取 Blob 后展示，操作写入审计日志。地点名在同一地图内唯一，坐标必须在对应图片范围内。
