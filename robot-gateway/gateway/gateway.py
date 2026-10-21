"""Robot Gateway 主循环骨架。

真实部署时使用 rclpy 订阅 /robot/status 与标注帧，并把状态写入 Redis；
从 Redis 读取命令后映射到 ALLOWED_TOPICS 发布。当前阶段为契约实现。
"""
if __package__:
    from .contracts import ALLOWED_TOPICS, FORBIDDEN_TOPICS
else:
    from contracts import ALLOWED_TOPICS, FORBIDDEN_TOPICS


def validate_command(command: dict) -> None:
    topic = command.get("topic")
    if topic in FORBIDDEN_TOPICS:
        raise ValueError(f"禁止直接发布 {topic}，安全链不可绕过")
    if topic not in ALLOWED_TOPICS:
        raise ValueError(f"未授权的话题：{topic}")


def main() -> None:
    print("Robot Gateway skeleton: 等待 Docker/Redis 后启用。")


if __name__ == "__main__":
    main()
