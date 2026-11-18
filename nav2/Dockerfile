# Nav2 on the simulated duck (RFC-0015, ADR-0018): a comparison and learning tool; nothing of ours depends on it.
#   docker build -t robotics-lab/nav2:spike nav2/
#   docker run --rm -it --network host -v ~/.cache/duck-sim:/duck-sim robotics-lab/nav2:spike
FROM ros:jazzy-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-navigation2 \
        ros-jazzy-nav2-bringup \
        ros-jazzy-slam-toolbox \
        ros-jazzy-foxglove-bridge \
        ros-jazzy-rosbag2-storage-mcap \
        python3-colcon-common-extensions \
        git \
    && rm -rf /var/lib/apt/lists/*

# explore_lite: from source (m-explore-ros2) unless Jazzy has a package; the spike records which
WORKDIR /ws
RUN git clone --depth 1 https://github.com/robo-friends/m-explore-ros2.git src/m-explore-ros2 \
    && . /opt/ros/jazzy/setup.sh \
    && colcon build --packages-up-to explore_lite --cmake-args -DCMAKE_BUILD_TYPE=Release

RUN echo '. /opt/ros/jazzy/setup.sh && . /ws/install/setup.sh' >> /root/.bashrc
CMD ["bash"]
