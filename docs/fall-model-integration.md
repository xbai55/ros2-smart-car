# YOLO11 人员倒地专项模型接入

本分支在 `feature/insightrover-v4-agent` 上接入 YOLO11 Human Fall Detection，不改通用 YOLOE-11s、巡航、站点停留或后台入库流程。

## 模型和类别

固定模型来自 [human-fall-detection](https://huggingface.co/melihuzunoglu/human-fall-detection)，权重版本 `97261b03632a9715a27481b2cfdac6a78e26d2d9`，SHA256 为 `3f56ad30358d5c63bf8dbc0c1299cf68818c3d291dfb10c94107b94110aadd4c`。实际类别为：

- `fallen`：倒地或已躺卧姿态；这是当前唯一映射的异常类别。
- `sitting`：坐姿，保留为未映射类别。
- `standing`：站立，保留为未映射类别。

该模型做的是姿态状态检测，不能从单帧判断“跌倒动作”是否发生，也不能区分地面、床、沙发或主动躺下。弯腰、蹲下、坐地和正常躺卧的车端表现需要现场验收；本配置不会用宽高比或通用 `person` 框代替专项模型。

## 获取模型

当前接入分支已直接包含这份 5.47 MB 权重，合作者拉取分支后可以立即测试。仓库仍忽略新生成的其他 `*.pt` 文件；如果需要在没有该分支权重的环境重新获取，执行：

```powershell
python scripts/fetch_fall_model.py --output "$HOME/.ros/insightrover/models/yolo11-fall.pt"
```

Windows PowerShell 中 `$HOME` 可替换为实际用户目录；Jetson 上使用 `python3` 和同样的输出路径。脚本下载固定版本并在原子替换前校验 SHA256。

## 车端配置

将 `ros2_ws/src/smart_car_decision/config/safety-vision.example.json` 复制到车端 `~/.ros/insightrover/safety-vision.json`，保留已有烟火模型，再把倒地条目作为第二个 `models` 元素。倒地路径使用 `models/yolo11-fall.pt`；车端会优先读取配置旁的路径，再读取已安装包中的 `models/` 权重，因此同步并构建本分支后可以直接测试。模型类别映射和 SHA256 已填好；烟火权重的真实路径和映射保留原配置。

`enabled` 必须为 `true`。默认 `confirm_sec=2`：同一倒地目标持续可见约2秒才上报；短暂断帧会重新累计，清除10秒后再次出现才产生新事件。报警不会主动停车，车辆继续按现有巡航策略运行。

专项线程从共享摄像头服务读取最新 JPEG，不重新打开 USB 摄像头。每个专项模型都收到同一张未标注原始帧，绘制框只发生在两套推理完成后；状态中会记录每个模型的 SHA256、类别和本次推理耗时。

## 检查和验证

本分支可以先运行：

```powershell
python -m pytest tests/test_safety_events.py -q
```

已有离线验证表明此权重的 `fallen` 识别可用于本地演示，但“小车视角下的倒地、弯腰、蹲下、坐地、多人和遮挡”尚未完成实车验收。接入前应记录每类场景的召回、每小时误报、首报延迟，并在烟火模型同时启用时记录 `model_inference_ms` 的 P50/P95、帧龄、GPU 内存和温度。

后台 `fallen_person` 入库和通知接口已在基线分支支持，事件照片仍先写车端 outbox，再由后台保存、入库、通知和确认。
