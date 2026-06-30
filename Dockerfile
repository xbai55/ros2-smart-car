ARG BASE_IMAGE=ros:humble-ros-base
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DOMAIN_ID=77
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ENV SMART_CAR_ROOT=/workspace/ros2-smart-car

WORKDIR /workspace/ros2-smart-car

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    iproute2 \
    psmisc \
    python3-colcon-common-extensions \
    python3-opencv \
    python3-pip \
    python3-yaml \
    ros-humble-cv-bridge \
    ros-humble-geometry-msgs \
    ros-humble-nav2-lifecycle-manager \
    ros-humble-nav2-map-server \
    ros-humble-robot-state-publisher \
    ros-humble-sensor-msgs \
    ros-humble-slam-toolbox \
    ros-humble-std-msgs \
    ros-humble-tf2-ros \
    && rm -rf /var/lib/apt/lists/*

COPY ros2_ws/src/smart_car_decision/requirements-web.txt /tmp/requirements-web.txt
COPY ros2_ws/src/smart_car_decision/requirements-vision.txt /tmp/requirements-vision.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements-web.txt -r /tmp/requirements-vision.txt
RUN pip3 install --no-cache-dir pyserial

COPY ros2_ws ./ros2_ws
COPY docker ./docker

RUN /bin/bash -lc "source /opt/ros/humble/setup.bash && cd ros2_ws && colcon build --packages-select smart_car_decision"
RUN chmod +x docker/*.sh

EXPOSE 8080 9999

ENTRYPOINT ["/workspace/ros2-smart-car/docker/entrypoint.sh"]
CMD ["ros2", "launch", "smart_car_decision", "bringup_all.launch.py"]
