"""机器人状态/事件模拟器。

无 redis 时打印 JSON 到 stdout；有 redis 时写入 robot:status:<id>。
"""
import json
import time

try:
    import redis  # noqa
    HAS_REDIS = True
except Exception:
    HAS_REDIS = False

SAMPLE_STATUS = {
    "robot_id": "robot-001",
    "timestamp": None,
    "status": "online",
    "mode": "patrol",
    "emergency_stop": False,
    "battery": 87.5,
    "pose": {"x": 1.2, "y": -0.6, "yaw": 0.4},
    "health": {"lidar": "ok", "odom": "ok", "camera": "ok"},
}


def main() -> None:
    client = None
    if HAS_REDIS:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0)
    for i in range(3):
        status = dict(SAMPLE_STATUS)
        status["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status["pose"]["x"] = round(1.2 + i * 0.1, 2)
        if client is not None:
            client.publish(f"robot:status:{status['robot_id']}", json.dumps(status))
        else:
            print(json.dumps(status, ensure_ascii=False))
        time.sleep(1)


if __name__ == "__main__":
    main()
