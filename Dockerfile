FROM ros:humble-ros-base

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /workspace/ros2-smart-car

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-opencv \
    ros-humble-cv-bridge \
    ros-humble-sensor-msgs \
    ros-humble-geometry-msgs \
    ros-humble-std-msgs \
    && rm -rf /var/lib/apt/lists/*

COPY ros2_ws/src/smart_car_decision/requirements-web.txt /tmp/requirements-web.txt
COPY ros2_ws/src/smart_car_decision/requirements-vision.txt /tmp/requirements-vision.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements-web.txt -r /tmp/requirements-vision.txt

COPY ros2_ws ./ros2_ws

RUN /bin/bash -lc "source /opt/ros/humble/setup.bash && cd ros2_ws && colcon build --packages-select smart_car_decision"

EXPOSE 8080

CMD ["/bin/bash", "-lc", "source /opt/ros/humble/setup.bash && source /workspace/ros2-smart-car/ros2_ws/install/setup.bash && ros2 launch smart_car_decision bringup_all.launch.py"]
