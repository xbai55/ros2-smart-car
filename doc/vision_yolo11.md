# YOLO11 camera vision node

This repository did not contain a YOLO11s model or a camera inference node before
`yolo11_camera_node` was added. The existing decision controller already listens
to `/vision/detection`, so the camera node publishes high-level commands to that
topic.

## Current camera logic

```text
camera frame
  -> YOLO11 inference
  -> class/result mapping
  -> /vision/detection std_msgs/String
  -> decision_controller
  -> /cmd_vel
```

The node reads frames with OpenCV `VideoCapture`, runs Ultralytics YOLO, then
maps detections to the commands already supported by `decision_controller`:

| YOLO result | Published command | Effect |
| --- | --- | --- |
| `stop sign` | `stop` | stop the car |
| red `traffic light` crop | `red_light` | stop the car |
| green `traffic light` crop | `green_light` | move forward |
| `person`, `car`, `truck`, `bus`, `motorcycle`, `bicycle` | `slow` | slow forward |
| no useful detection | `no_light` | normal forward/lane following |

Traffic-light color is estimated with a simple HSV color check inside the YOLO
traffic-light bounding box. For example, YOLO first finds "there is a traffic
light here", then HSV decides whether the bright color is red or green.

## Model weights

Recommended default for Jetson Orin Nano 8GB:

```text
yolo11s.pt
```

The repository already includes the official YOLO11s weight here:

```text
ros2_ws/src/smart_car_decision/models/yolo11s.pt
```

During `colcon build`, `setup.py` installs this file to the ROS2 package share
directory. Because `config/decision.yaml` uses `model_path: yolo11s.pt`, the node
will first look for the packaged weight before falling back to Ultralytics'
automatic download behavior.

Official open weights are available from Ultralytics:

- Docs: https://docs.ultralytics.com/models/yolo11/
- Hugging Face model repo: https://huggingface.co/Ultralytics/YOLO11
- Direct file page: https://huggingface.co/Ultralytics/YOLO11/blob/main/yolo11s.pt

If you replace the model with another file, put it in `models/` and update
`model_path` in `config/decision.yaml`.

## Install on Jetson

```bash
cd ~/ros2-smart-car/ros2_ws
source /opt/ros/humble/setup.bash
pip install -r src/smart_car_decision/requirements-vision.txt
colcon build --packages-select smart_car_decision
source install/setup.bash
```

## Run

Start the decision stack:

```bash
ros2 launch smart_car_decision decision_bringup.launch.py
```

Start YOLO11 camera recognition in another terminal:

```bash
ros2 launch smart_car_decision yolo11_camera.launch.py
```

Check the vision result:

```bash
ros2 topic echo /vision/detection
```

## Jetson Orin Nano 8GB deployment suggestion

Start with PyTorch weight `yolo11s.pt` for correctness. After the logic works,
export TensorRT FP16 on the Jetson:

```bash
yolo export model=yolo11s.pt format=engine half=True imgsz=640 device=0
```

Then update `model_path` in `config/decision.yaml`:

```yaml
model_path: yolo11s.engine
```

If the frame rate is not enough, try these in order:

1. Change `model_path` to `yolo11n.pt`.
2. Change `imgsz` from `640` to `512`.
3. Lower `inference_rate_hz` to `5.0`.
