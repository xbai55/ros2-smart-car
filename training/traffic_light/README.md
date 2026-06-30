# 交通灯状态识别 YOLO 微调说明

本文档记录本次交通灯识别模块的改进内容、训练数据、模型指标和后续优化方向，便于后续撰写项目报告或答辩材料时参考。

## 改进背景

原有交通灯识别逻辑不是完全端到端的状态识别流程：YOLO 主要负责检测 `traffic light` 这一类目标，红灯、绿灯等状态再通过 HSV 颜色规则判断。这个方案实现简单，但容易受光照、曝光、反光、摄像头白平衡和灯体距离影响。例如同一个红灯在强光下可能偏橙，在远距离时像素区域很小，HSV 阈值会变得不稳定。

本次改进将交通灯状态直接加入 YOLO 检测类别，使模型直接输出：

```text
red_light
yellow_light
green_light
off_light
unknown_light
```

这样推理结果从“先检测交通灯，再用颜色规则判断状态”变为“模型直接检测状态类别”。控制逻辑可以直接根据类别映射车辆行为，例如 `red_light` 停车、`yellow_light` 减速、`green_light` 通行。

## 数据集与标签处理

本次使用 Udacity Self-Driving Car Annotated Driving Dataset 2 作为公开数据源。该数据集可以直接下载，包含道路图像和目标检测标注，其中交通灯相关标签包括 `Red`、`Yellow`、`Green`、`RedLeft`、`YellowLeft`、`GreenLeft` 和 `trafficLight`。

转换时只保留交通灯相关目标，并统一映射为本项目使用的 YOLO 类别：

| 原始标签 | 统一标签 | 含义 |
| --- | --- | --- |
| `Red`, `RedLeft` | `red_light` | 红灯或左转红灯 |
| `Yellow`, `YellowLeft` | `yellow_light` | 黄灯或左转黄灯 |
| `Green`, `GreenLeft` | `green_light` | 绿灯或左转绿灯 |
| `trafficLight` | `unknown_light` | 有交通灯但状态不明确 |

转换后的数据集采用标准 YOLO 检测格式：

```text
C:/Users/xbai55/Desktop/综设/datasets/traffic_light/
  images/train
  images/val
  labels/train
  labels/val
  data.yaml
```

类别顺序固定如下：

```yaml
names:
  0: red_light
  1: yellow_light
  2: green_light
  3: off_light
  4: unknown_light
```

本次转换后的数据规模为：

| 项目 | 数量 |
| --- | ---: |
| 总图像数 | 4828 |
| 训练图像数 | 4104 |
| 验证图像数 | 724 |
| `red_light` 标注框 | 8613 |
| `green_light` 标注框 | 5802 |
| `yellow_light` 标注框 | 278 |
| `unknown_light` 标注框 | 2560 |

可以看到黄灯样本明显偏少，这是后续模型改进的重点。

## 训练配置

训练使用本机单独的 `yolo-tl` Conda 环境，避免污染 ROS2 小车运行环境。由于 Ultralytics 在包含中文路径的训练目录上可能出现路径解析问题，实际训练时使用了 `C:/tmp` 下的英文路径中转。

主要训练配置如下：

| 配置项 | 取值 |
| --- | --- |
| 基座模型 | `yolo11s.pt` |
| 输入尺寸 | 640 |
| epoch | 80 |
| batch | 8 |
| 设备 | RTX 4060 Laptop GPU |
| 训练输出 | `C:/tmp/traffic_light_runs/yolo11s_public` |
| 最佳权重 | `C:/tmp/traffic_light_runs/yolo11s_public/weights/best.pt` |

训练完成后，最佳权重已复制到 ROS2 包中：

```text
ros2_ws/src/smart_car_decision/models/traffic_light_yolo11s.pt
```

## 指标结果

本次训练完成 80 个 epoch，最终验证集整体指标如下：

| 类别 | Precision | Recall | mAP50 | mAP50-95 |
| --- | ---: | ---: | ---: | ---: |
| all | 0.904 | 0.789 | 0.840 | 0.486 |
| `red_light` | 0.910 | 0.806 | 0.861 | 0.565 |
| `yellow_light` | 0.906 | 0.741 | 0.788 | 0.345 |
| `green_light` | 0.872 | 0.733 | 0.794 | 0.388 |
| `unknown_light` | 0.928 | 0.877 | 0.917 | 0.645 |

其中 `mAP50` 表示在 IoU=0.5 条件下的平均检测精度，可以理解为“框大致框住目标时的检测能力”；`mAP50-95` 是从 IoU=0.5 到 0.95 多个严格阈值的平均值，更能反映框的位置精度和稳定性。

从结果看，`mAP50=0.840` 说明模型已经能较好识别交通灯状态，适合作为第一版端到端红绿灯检测模型进行上车低速验证。`mAP50-95=0.486` 说明高精度定位能力仍有提升空间，尤其是远距离小目标和复杂光照下的框定位。

分类别来看，红灯和未知灯表现较好，绿灯基本可用，黄灯由于样本数量少，指标可信度相对较低。举例来说，红灯训练样本有数千个，而黄灯只有几百个框，模型对黄灯的经验明显不足。因此黄灯建议先用于减速提示，不建议直接作为强制停车信号。

## ROS2 部署逻辑

模型权重已经复制到 ROS2 包中。后续如果要将默认自动驾驶识别链路切换到该交通灯状态模型，可以把 ROS2 配置文件中的模型路径指向：

```yaml
model_path: traffic_light_yolo11s.pt
```

类别到控制命令的映射为：

```text
red_light -> red_light
yellow_light -> slow
green_light -> green_light
off_light -> no_light
unknown_light -> no_light
```

切换时还需要同步类别到控制命令的映射，例如将 `red_light` 映射为停车、`yellow_light` 映射为减速、`green_light` 映射为通行。原有安全滤波、雷达急停和 `/vision/detection` 话题应继续保留，避免视觉模型单独决定所有安全行为。

## 验证结果

训练后完成了两类验证：

1. 静态预测验证：使用最佳权重对验证集 724 张图像进行预测，模型可以正常加载，并能输出 `red_light`、`yellow_light`、`green_light` 和 `unknown_light` 等类别。
2. 项目测试验证：当前仓库运行项目测试集，结果为 `78 passed`，说明新增模型资产和文档整理没有破坏已有 ROS2 决策逻辑测试。

静态预测输出目录：

```text
C:/tmp/traffic_light_predict/best_val
```

## 当前效果评价

本次模型已经完成从规则辅助识别到端到端状态检测的第一步升级。相比原来的 `traffic light + HSV` 方式，新模型直接输出交通灯状态，减少了手写颜色阈值对环境光照的依赖，也更容易通过继续补充数据来提升性能。

不过，该模型仍然主要由公开道路数据训练得到，与本项目小车摄像头的实际视角、赛道环境、图像分辨率和曝光条件存在差异。因此目前更适合作为“可上车低速验证的第一版模型”，还不建议直接作为最终稳定版本。

## 后续改进策略

后续最有效的改进方式是补充本车摄像头数据进行二次微调。建议采集 100 到 300 张本车图像，覆盖红灯、绿灯、黄灯、灯灭、远距离小灯、近距离大灯、反光干扰和无灯背景等情况。

优先级建议如下：

1. 优先补黄灯样本。当前黄灯数据最少，实际可靠性最容易波动。
2. 补充本车视角数据。公开数据和小车场景存在域差异，本车数据对实车稳定性提升最大。
3. 保留连续帧滤波。红灯建议连续 2 到 3 帧稳定识别后再触发停车，减少单帧误检。
4. 分类别设置置信度阈值。红灯可使用较高阈值以减少误停，绿灯可适当降低阈值以减少漏检。
5. 记录实车误检样本。将红灯漏检、绿灯误判为红灯、背景误判为红灯等样本加入下一轮训练集。

整体上，本次改进已经建立了可持续迭代的训练与部署流程。后续只需要不断加入本车场景样本，模型就可以通过二次微调逐步适应实际赛道和摄像头条件。
