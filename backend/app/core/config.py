import os


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL", "sqlite:///./smart_patrol.db"
        )
        self.jwt_secret = os.getenv("JWT_SECRET", "dev-secret-change-me")
        self.access_token_expire_minutes = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        )
        self.refresh_token_expire_days = int(
            os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
        )
        self.cors_origins = [
            o.strip()
            for o in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:8080,http://127.0.0.1:8080,http://127.0.0.1:8888,http://localhost:8888",
            ).split(",")
            if o.strip()
        ]

        self.system_name = os.getenv("SYSTEM_NAME", "InsightRover 智巡控制台")
        self.app_version = os.getenv("APP_VERSION", "0.2.0")

        # Redis：机器人实时状态缓存 robot:status:{robot_id}
        self.redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.redis_enabled = _env_bool("REDIS_ENABLED", True)
        self.redis_socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT", "0.3"))

        # MinIO / 对象存储：留空则退回本地文件存储
        self.minio_endpoint = os.getenv("MINIO_ENDPOINT", "")
        self.minio_access_key = os.getenv("MINIO_ACCESS_KEY", "")
        self.minio_secret_key = os.getenv("MINIO_SECRET_KEY", "")
        self.minio_bucket = os.getenv("MINIO_BUCKET", "smart-patrol")
        self.minio_secure = _env_bool("MINIO_SECURE", False)
        self.storage_local_dir = os.getenv("STORAGE_LOCAL_DIR", "./storage")

        # 车端：Robot Gateway / 车端 Web 节点 / 视频服务
        self.robot_gateway_url = os.getenv("ROBOT_GATEWAY_URL", "")
        self.robot_web_url = os.getenv("ROBOT_WEB_URL", "")
        self.video_service_url = os.getenv("VIDEO_SERVICE_URL", "")
        self.robot_gateway_timeout = float(os.getenv("ROBOT_GATEWAY_TIMEOUT", "2.0"))
        self.heartbeat_timeout_seconds = float(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "30"))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def database_backend(self) -> str:
        return "sqlite" if self.is_sqlite else "postgresql"


settings = Settings()
