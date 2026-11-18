#!/usr/bin/env bash
# The spike's first drive (RFC-0015 §4 step 2): Nav2 on the simulated duck through bridge.py. Run INSIDE the container:
#   docker run --rm --name robotics-lab-nav2-drive --network host -v ~/.cache/duck-sim:/duck-sim \
#       -v $PWD/duck:/duck:ro -v $PWD/nav2:/nav2:ro -v /tmp/nav2-out:/out robotics-lab-nav2:spike bash /nav2/first_drive.sh X Y
# X Y: the goal in the odom/map frame (the dock is 0, 0; the simulator must be freshly reset). Logs to /out.
set +u
. /opt/ros/jazzy/setup.sh
. /ws/install/setup.sh
GX=${1:-1.0} GY=${2:-0.0}
python3 /nav2/merge_params.py /opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml /nav2/params_overrides.yaml > /out/nav2_duck.yaml
python3 /nav2/bridge.py > /out/bridge.log 2>&1 &
ros2 run tf2_ros static_transform_publisher --frame-id map --child-frame-id odom > /out/static_tf.log 2>&1 &
ros2 launch nav2_bringup navigation_launch.py params_file:=/out/nav2_duck.yaml use_sim_time:=false autostart:=true \
    use_composition:=False > /out/nav2.log 2>&1 &
sleep 60
ros2 topic list > /out/topics.txt 2>&1
python3 /nav2/costmap_probe.py before > /out/costmaps.txt 2>&1
timeout 90 ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
    "{pose: {header: {frame_id: map}, pose: {position: {x: $GX, y: $GY}, orientation: {w: 1.0}}}}" > /out/goal.txt 2>&1 &
GOAL=$!
sleep 6
timeout 5 ros2 topic echo --once --no-arr /plan > /out/plan.txt 2>&1
timeout 6 ros2 topic echo /cmd_vel > /out/cmd_vel.txt 2>&1
timeout 6 ros2 topic echo /cmd_vel_nav > /out/cmd_vel_nav.txt 2>&1
wait $GOAL
echo "GOAL EXIT=$?" >> /out/goal.txt
python3 /nav2/costmap_probe.py after >> /out/costmaps.txt 2>&1
kill %1 %2 %3 2>/dev/null
