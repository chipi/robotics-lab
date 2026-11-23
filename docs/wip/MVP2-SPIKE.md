# MVP 2 spike: the TurtleBot3 Burger in Gazebo (one day, 2026-11-23)

**Status:** run on 2026-11-23, about three hours. Nothing here is platform code, and nothing in
this repository was changed except this file. All work files are outside the repository, in
`~/.cache/robotics-lab-tests/mvp2-spike/` (Dockerfile, launch overrides, scripts, maps, bags, logs).

**Status update (extensions A, B, C, same day):** three extensions the operator approved were run
afterwards (sections 18 to 20). Total work was about four hours. Still no platform code and nothing
in the repository except this file.

## Answers in brief

- **Versions:** ROS 2 Jazzy, Gazebo Harmonic (Sim 8.15.0), `turtlebot3_gazebo` 2.3.7, SLAM Toolbox
  2.8.5, `ros_gz` 1.0.25. `/cmd_vel` is `TwistStamped`.
- **Headless:** works with no GPU; real-time factor 1.00 with SLAM Toolbox running, about 1 core.
- **SLAM Toolbox:** clean map; against Gazebo's truth the pose error was at most 5.4 cm over a
  30 m loop (mean 2.3 cm); nine pillars in place to one 5 cm cell (section 18).
- **Stamps:** the bridge stamps simulation time; `use_sim_time` false fails tf lookups.
- **Stop:** the simulator's DiffDrive holds the last velocity. The real Burger on ROS 2 holds it
  too while its node lives; a 500 ms timeout exists only for the older firmware and as a
  heartbeat. The connector's own deadman worked: velocity zero 0.6 s after the last command.
- **Reset:** 0.26 s, but only if the robot is part of the world file; otherwise it deletes the
  robot and a respawn crashes Gazebo. The sim clock goes back to 0; after a reset my prototype's
  tf-based belief froze (section 20, unresolved).
- **Scan schema:** `foxglove.LaserScan` exists; our run format needs changes to carry it
  (section 20 lists the lines).
- **Bag:** MCAP by default.
- **Explore:** `explore_lite` built from source and mapped the whole room in 51 s (section 18).
- **Cameras:** RGB and depth 640 x 480 at 30 Hz work on software rendering; +1.7 cores; 3.9 GB a
  minute raw, 17 to 25 MB a minute compressed (flat render) (section 19).
- **Connector prototype:** served `robot.*` over a socket, wrote a run with `libs/runfile`
  unchanged, and the Observatory replayed it (section 20).

## 1. What was asked and why

[RFC-0025](../rfc/RFC-0025-mvp1-to-mvp2.md) section 6.1 (step 0b) asks for a one-day spike before
the MVP 2 RFCs: the TurtleBot3 Burger (ROS 2) starting in Gazebo. The operator approved it on
2026-11-23 with "no platform code". The spike must answer, with measurements:

- which ROS 2 and Gazebo versions work together with the TurtleBot3 simulation
- whether the Burger can be driven and read headless (no GUI) in a container
- whether SLAM Toolbox builds and saves a map
- the real-time factor and the load
- how the ROS to Gazebo bridge stamps messages (this decides the clock rule, question 13)
- whether the simulated base stops when commands stop, and what the real Burger's firmware does
- what a reset costs, and whether SLAM Toolbox needs a restart
- whether Foxglove has a laser scan schema for MCAP
- whether `ros2 bag record` writes MCAP by default

Rules followed: Docker only, nothing installed on the host; every container and image is named
`mvp2-spike...`; the simulator lock (`/tmp/claude-1000/-work-robotics-lab-main/sim.lock`) was held
by `flock` around every Gazebo session; no prune; no other container touched.

## 2. Setup

Host: Arch Linux, AMD Ryzen AI MAX+ 395 (32 threads), 124 GiB RAM. The host has an AMD integrated
GPU. No GPU device was passed into the container (no `--device`), and `nvidia-smi` does not
exist. Gazebo's lidar rendering therefore ran without GPU access. I did not check which Mesa
renderer was used. Mesa (`libgl1-mesa-dri 25.2.8`) is in the image.

Versions that were running (from `dpkg -l` in the image and `gz sim --version`):

| Part | Version |
| --- | --- |
| OS in the image | Ubuntu 24.04.5 |
| ROS 2 | Jazzy (`ros:jazzy-ros-base`) |
| Gazebo | Gazebo Sim 8.15.0 (Harmonic), from `ros-jazzy-gz-sim-vendor 0.0.13` |
| ros_gz (bridge, sim) | `ros-jazzy-ros-gz-bridge` and `ros-jazzy-ros-gz-sim` 1.0.25 |
| TurtleBot3 | `ros-jazzy-turtlebot3-gazebo` 2.3.7, `-description` 2.3.7, `-msgs` 2.4.0 |
| SLAM Toolbox | `ros-jazzy-slam-toolbox` 2.8.5 |
| MCAP storage | `ros-jazzy-rosbag2-storage-mcap` 0.26.11 |

The image (`~/.cache/robotics-lab-tests/mvp2-spike/Dockerfile`):

```dockerfile
FROM ros:jazzy-ros-base
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-turtlebot3-gazebo ros-jazzy-turtlebot3-description ros-jazzy-turtlebot3-msgs \
    ros-jazzy-ros-gz-sim ros-jazzy-ros-gz-bridge ros-jazzy-slam-toolbox \
    ros-jazzy-rosbag2-storage-mcap ros-jazzy-nav2-map-server python3-pil \
    && rm -rf /var/lib/apt/lists/*
ENV TURTLEBOT3_MODEL=burger ROS_DOMAIN_ID=77
```

Rerun (the launch file is the package's `turtlebot3_world.launch.py` with the one line
`ld.add_action(gzclient_cmd)` removed, so only the server runs):

```bash
cd ~/.cache/robotics-lab-tests/mvp2-spike
docker build -t mvp2-spike:jazzy .
docker run --rm mvp2-spike:jazzy cat \
  /opt/ros/jazzy/share/turtlebot3_gazebo/launch/turtlebot3_world.launch.py \
  | grep -v "ld.add_action(gzclient_cmd)" > headless_world.launch.py
flock -w 7200 /tmp/claude-1000/-work-robotics-lab-main/sim.lock \
  docker run --rm --user 1000:1000 -e HOME=/tmp --name mvp2-spike-gz \
  -v $PWD:/spike mvp2-spike:jazzy bash -c \
  '. /opt/ros/jazzy/setup.bash; exec ros2 launch /spike/headless_world.launch.py'
# in a second shell, one command at a time:
docker exec mvp2-spike-gz bash -c '. /opt/ros/jazzy/setup.bash; ros2 topic list'
docker exec -d mvp2-spike-gz bash -c '. /opt/ros/jazzy/setup.bash; \
  ros2 launch slam_toolbox online_async_launch.py use_sim_time:=true'
```

Network: no `--network host`. Everything (Gazebo, bridge, SLAM, my probe scripts) ran inside one
container, so DDS needed nothing from the host. `ROS_DOMAIN_ID=77` is set in the image.

Probe scripts, all in the work directory: `tflookup.py` (tf lookups), `stoptest.py` (stop test),
`wander.py` and `wallfollow.py` (drivers that publish `/cmd_vel` from the scan),
`resettest*.sh`, `run*.sh`. The outputs quoted below are in `out/`.

## 3. Goal 1: versions

**Answer: ROS 2 Jazzy with Gazebo Harmonic (Gazebo Sim 8) works, and is what ROBOTIS documents
for Jazzy. No second pair was needed.**

What I read:

- `git ls-remote --heads` on `ROBOTIS-GIT/turtlebot3_simulations` lists `humble`, `jazzy`, `main`,
  `noetic`, `feature-gazebo-sim-migration`, `feature-autorace-2025`. The `jazzy` branch exists.
- `turtlebot3_gazebo/package.xml` on the `jazzy` branch (version 2.3.7) depends on `ros_gz_bridge`,
  `ros_gz_sim`, `ros_gz_image`, `gz_sim_vendor`, `gz_plugin_vendor`, `gz_math_vendor`.
- The ROBOTIS e-Manual simulation page
  (<https://emanual.robotis.com/docs/en/platform/turtlebot3/simulation/>) covers Humble, Jazzy
  ("ros-gz package and Gazebo Harmonic") and Noetic (Gazebo Classic). For Jazzy it says to clone
  `turtlebot3_simulations` with `-b jazzy` and launch `turtlebot3_world.launch.py`. I read it
  through a fetch tool that summarises pages, not the raw page.
- The packages are in the apt archive (packages.ros.org through the base image) as the versions in
  section 2. No source build was needed.

Facts that differ from the parked Nav2 image or from older TurtleBot3 guides:

- `/cmd_vel` is `geometry_msgs/msg/TwistStamped` in the Jazzy bridge, not `Twist`. The bridge file
  (`turtlebot3_gazebo/params/turtlebot3_burger_bridge.yaml`) says "If you use Twist, you need to
  change the type to Twist". Plain `Twist` publishers (many teleop tools) will not connect.
- The package does not install ROBOTIS's teleop. I drove with my own scripts that publish
  `TwistStamped`. `ros2 topic pub` would also work with the stamped type.

Not verified: that the `main` branch (newer ROS) works; support dates of Jazzy and Harmonic.

## 4. Goal 2: the Burger headless, driven, read

**Answer: it works. Server only (`gz sim -r -s`), no display, no GPU, in a container.**

Gazebo logs `Unable to open display. Trying to run in headless mode.` and carries on. Topics
(`ros2 topic list`): `/clock /cmd_vel /imu /joint_states /odom /robot_description /scan /tf
/tf_static` (and the standard ones).

Rates and shapes, measured with `ros2 topic hz --window 50` at a real-time factor of 1:

| Topic | Type | Rate seen | Notes |
| --- | --- | --- | --- |
| `/scan` | `sensor_msgs/LaserScan` | 5.0 Hz | 360 beams over 0 to 6.28 rad, range 0.12 to 3.5 m, frame `base_scan`, RELIABLE |
| `/odom` | `nav_msgs/Odometry` | 50.0 Hz | frames `odom` to `base_footprint`; the SDF says 30 Hz, I did not find why it is 50 |
| `/imu` | `sensor_msgs/Imu` | 200 Hz | frame id `burger/imu_link/tb3_imu` |
| `/tf` | `tf2_msgs/TFMessage` | about 70 Hz | only `odom` to `base_footprint` here; the robot's fixed links are on `/tf_static` |
| `/clock` | `rosgraph_msgs/Clock` | 1000 Hz | one message per 1 ms physics step |

`/tf_static` comes from `robot_state_publisher`, which the launch file starts. In my last
session I used a variant world without it and SLAM Toolbox then had no `base_footprint` to
`base_scan` transform (see goal 7).

Driving: a `TwistStamped` at 0.15 m/s for 3 s moved the odometry from x 0.000 to 0.439 (goal 6
output). Teleop by command line works with `ros2 topic pub -r 10 /cmd_vel
geometry_msgs/msg/TwistStamped ...`; I used the scripts instead.

## 5. Goal 3: SLAM Toolbox, a map, saved

**Answer: online asynchronous SLAM Toolbox (`online_async_launch.py`, `use_sim_time:=true`,
default parameters) built a clean map of the TurtleBot3 world while a script drove a loop.**

Driver: `wallfollow.py` follows the left wall at 0.55 m, 0.18 m/s, for 170 s (30.0 m of path).
Saved with `nav2_map_server map_saver_cli -f map3` plus the SLAM pose graph
(`/slam_toolbox/serialize_map`).

```text
map3.pgm: 85 x 108 cells, 0.050 m per cell (4.25 m x 5.4 m), origin [-3.101, -2.675, 0]
cells: 4503 unknown (205), 4214 free (254), 463 occupied (0)
files: map3.pgm 9194 bytes, map3.yaml 126 bytes (mode: trinary)
posegraph3.posegraph 1.84 MB, posegraph3.data 0.80 MB
```

What it looks like (`out/map3.png`, the .pgm at 4 times scale, which I looked at): a hexagonal
room with crisp outer walls, and nine round pillars shown as small black arcs on the sides that
face the lidar, with grey shadows behind them. The map frame is rotated relative to the world,
(I believe because SLAM Toolbox starts its map at the robot's pose when it starts; not checked).
One corner is a little
bent (a kink in the top left). I did not measure the error against the world file.

Honest notes on the runs:

- My first driver (`wander.py`, obstacle avoidance) drove out of the hexagon through a gap after
  about 100 s and made a messy map (`map1.png`, 195 x 174 cells). The second run stayed in a small
  area (`map2.png`, 89 x 103). Only the wall-following run (`map3`) covered the whole room.
- Loop closure: I did not read the loop-closure events. I cannot say if one fired.
- The map is saved in the standard ROS format; `map3.yaml` gives the origin and resolution.

## 6. Goal 4: real-time factor, CPU, memory

**Answer: the real-time factor is 1.00 with the whole stack running. The cost is about 0.7 of
one core and 0.6 GiB. Gazebo can run 10 times faster than real time when asked.**

Measured with `gz topic -e -t /stats` (`real_time_factor`) and `docker stats --no-stream`
(CPU is a percent of one core):

| Situation | Real-time factor | CPU (docker stats) | Memory |
| --- | --- | --- | --- |
| Gazebo + bridge, robot idle | 1.0000 (spot reads) | 44 to 71 % (6 samples) | 507 to 511 MiB |
| + SLAM Toolbox, wander driving (12 samples over 150 s) | 0.9997 to 1.0003 | 60 to 95 % (mostly 65 to 85) | 591 to 597 MiB |
| + SLAM Toolbox, wall following (14 samples) | not sampled | 70 to 78 % | 611 to 617 MiB |
| Same, real-time factor asked at 10 (`set_physics`) | 9.98 to 10.01 | 260 to 264 % | 575 MiB |

Notes:

- The clock against the wall clock agrees: `/clock` read 129.348 s then 140.270 s while the wall
  clock advanced 10.945 s between the two reads (10.922 s of simulated time). That is 0.998.
- The world file sets `real_time_factor 1` and a 1 ms step. To go faster:
  `gz service -s /world/default/set_physics --reqtype gz.msgs.Physics --reptype gz.msgs.Boolean
  --req 'real_time_factor: 10'`. It reached 10.0 with SLAM Toolbox running. I did not look for the
  upper limit, and I did not check that SLAM Toolbox's maps stay good at 10 times.
- All figures are with no GPU and no GUI, on one machine with other jobs sometimes running. The
  Gazebo Sim server for this small world is cheap.

## 7. Goal 5: how the bridge stamps `header.stamp`

**Answer: simulation time. The bridge forwards Gazebo's stamps; nothing is wall time.**

Evidence: four messages read one after another, with the wall clock before and after
(`out/headers.txt`):

```text
wall: 1795453008.593079890
/scan header:  stamp: sec: 39  nanosec: 400000000   frame_id: base_scan
/odom header:  stamp: sec: 40  nanosec: 280000000   frame_id: odom
/imu header:   stamp: sec: 41  nanosec:  90000000   frame_id: burger/imu_link/tb3_imu
/clock:        sec: 41 nanosec: 885000000
wall: 1795453012.126233570
/tf stamp:     sec: 42 nanosec: 700000000   (odom -> base_footprint)
```

The wall clock is 1.79e9 seconds (year 2026); the message stamps are 39 to 43 seconds, the time
since the simulator started. Sim time starts at 0 when Gazebo starts, not at wall time.

The tf lookup, `tflookup.py` (`out/tflookup.txt`), a node with `use_sim_time` true and one with
false, each asks for `odom` to `base_footprint`:

```text
use_sim_time=True  node clock now = 123.009 s; wall = 1795453093.113
  latest (Time(0)):  OK, tf stamp 123.000000000
  at node now():     FAIL ExtrapolationException: ... Requested time 123.009000 but the latest
                     data is at time 123.000000 ...
use_sim_time=False node clock now = 1795453097.505 s; wall = 1795453097.505
  latest (Time(0)):  OK, tf stamp 127.380000000
  at node now():     FAIL ExtrapolationException: ... Requested time 1795453097.504547 but the
                     latest data is at time 127.380000 ...
```

What this says:

- With `use_sim_time` true, the node's clock and the stamps are the same clock. The "now" lookup
  failed here only by 9 ms, because the odometry is published every 20 ms and "now" is a little
  ahead of the newest sample. That is normal tf behaviour; a lookup at a slightly older time or
  with a wait would succeed. I did not test the wait (the synchronous rclpy buffer does not
  receive messages while it blocks).
- With `use_sim_time` false, "now" is 1.79e9 and the data is at about 127: every lookup at a wall
  time fails; only "latest" (`Time(0)`) works. This matches RFC-0025 section 3.6: wall-stamped
  consumers and sim-stamped bridge data cannot meet in tf.
- Other things confirmed: SLAM Toolbox with `use_sim_time:=true` ran correctly on these stamps.
  The bag recorder stamps its own receive time: with `--use-sim-time` the bag starts at 125.7 s
  (a date in 1970); without it, at wall 1795455459.39 (see goal 9).

Not verified: other bridge message types (images, point clouds) and a Gazebo sensor with its own
clock. The stamps of `/scan` and `/imu` are sensor times from inside Gazebo; they were not
compared at sub-step precision.

## 8. Goal 6: stopping

**Answer, simulator: no. The diff-drive plugin keeps the last velocity. There is no command
timeout.** The robot drives on until something stops it.

`stoptest.py` (`out/stoptest.txt`): publish `TwistStamped` vx 0.15 for 3 s at 20 Hz, then stop
publishing, and read `/odom` for 6 s more:

```text
sim t0=151.68  x0=0.000
commands stopped (last publish) at sim t=154.70  vx=0.150 x=0.439
  + 0.50 sim s after last cmd: vx=0.1500 m/s  x=0.514
  + 3.00 sim s after last cmd: vx=0.1500 m/s  x=0.889
  + 6.00 sim s after last cmd: vx=0.1500 m/s  x=1.339
```

The velocity stays at 0.1500 m/s exactly. The model's plugin settings (`model.sdf`) have no
timeout setting for the DiffDrive plugin; it has `max_linear_acceleration` 1.0 only. I stopped
reading after 6 s; the robot kept moving until I sent zeros (and later until the container was
restarted). I did not test the plugin on a `Twist` that is all zero as a "stop".

**The real Burger's OpenCR firmware.** I read the source (a shallow clone of
`ROBOTIS-GIT/OpenCR`, branch `master`, last commit 68ec75d of 2023-08-01, and
`ROBOTIS-GIT/turtlebot3`, branch `jazzy`, commit 0c0be84 of 2026-06-15). The answer depends on
which firmware.

- ROS 1 / rosserial-style firmware, `libraries/turtlebot3/examples/turtlebot3_burger/
  turtlebot3_core/turtlebot3_core_config.h:46`: `#define CONTROL_MOTOR_TIMEOUT 500 //ms`.
  In `turtlebot3_core.ino:85`: if the time since the last command is above
  `CONTROL_MOTOR_TIMEOUT`, `controlMotor(... zero_velocity)` is called. So the "500 ms"
  recollection is **correct for this firmware**: a command timeout of 500 ms stops the motors.
- ROS 2 firmware, `libraries/turtlebot3_ros2/src/turtlebot3/turtlebot3.cpp`: there is **no
  cmd_vel timeout**. `cmd_vel` values arrive in the control table (`ADDR_CMD_VEL_LINEAR_X` at line
  816) and are held. What exists is a heartbeat: `HEARTBEAT_TIMEOUT_MS = 500` (line 107). If the
  `turtlebot3_node` on the computer stops writing its heartbeat for 500 ms, the firmware sets the
  node as not connected, and lines 618 to 619 then zero the commanded velocity
  (`memset(goal_velocity_from_cmd, 0, ...)`). The node writes the heartbeat from a 100 ms timer
  (`turtlebot3_node/src/turtlebot3.cpp:226`). So: **a dead node stops the base within about
  500 ms, but a live node that stops sending `/cmd_vel` does not.** `turtlebot3_node` has no
  cmd_vel timeout either (I grepped `turtlebot3_node/src`).

So for the real Burger on ROS 2, a stale `/cmd_vel` stream is not a safe stop by itself; the
platform's own velocity path must send zero (RFC-0025 section 3.3). Not verified: I did not run
the real robot, and the firmware actually flashed on the operator's Burger is unknown (it is the
firmware's version that decides). The e-Manual says nothing about a timeout that I found; I did
not read it end to end.

## 9. Goal 7: reset

**Answer: a world reset is fast (about 0.26 s) but, with the stock launch, it deletes the robot
and a respawn crashes the Gazebo server. Resetting needs the robot to be part of the world file,
or a server restart. SLAM Toolbox does not need a restart for a fresh map.**

Timings below include the start of the `gz` command-line tool, so the service itself is faster.

| Operation | Wall time | Effect seen |
| --- | --- | --- |
| `set_pose` service (teleport the model) | 0.26 s | The model moved to (-2.0, -0.5) at once. `/odom` did **not** change (0.4530 before and after): odometry integrates wheel motion, not the pose. |
| world control `reset: {all: true}` (stock launch, robot spawned by `ros_gz_sim create`) | 0.26 s | Sim time went to 0. **The `burger` model was removed** (`gz model --list`: only `ground_plane`, `turtlebot3_world`). `/odom` and `/imu` stopped for good (checked for about 10 minutes of sim time). |
| respawn after that (`ros_gz_sim create -name burger`) | 0.7 s | **The Gazebo server crashed** (segmentation fault in the render thread: `Another item already exists with name: burger::wheel_right_link`; `launch2.log`). With the stock launch's `on_exit_shutdown` the whole launch stopped. |
| world control `reset: {model_only: true}` | 0.26 s | No visible effect: the model's pose and the sim time did not change, odometry did not change. |
| world control `reset: {all: true}`, robot **included in the world file** | 0.26 s | Works: sim time to 0.74 s, odometry back to 0 (the model pose itself was not read), `/odom` and `/imu` publishing at once. |
| restart of the whole Gazebo container | 48 s | measured once, from `docker run` to the first `/odom`, image already local |

The "robot included in the world" variant is `world_static.world` (the stock world with an
`<include>` of `model://turtlebot3_burger` named `burger` at -2.0, -0.5) and `static_launch.py`
(Gazebo server and bridge, no spawn). It needs `robot_state_publisher` started separately.

**SLAM Toolbox through a reset.** The sim clock jumps back to 0 on a reset:

- With the robot kept in the world, SLAM Toolbox logged `Detected jump back in time. Clearing TF
  buffer.` and then ran on, with no dropped-scan warnings in the next 40 s.
- With the robot deleted (stock launch), it kept dropping scans (`Message Filter dropping message
  ... earlier than all the data in the transform cache`) because nothing published odometry.
- The service `/slam_toolbox/reset` (type `slam_toolbox/srv/Reset`) restarts the map without
  restarting the node. After the call (0.65 s with the CLI start) the map changed from 81 x 103
  to 79 x 102 cells three seconds later, so it re-initialised. I did not compare the old and new
  maps visually, and did not test it on a long map. So the answer "no restart needed" rests on
  the service existing and being accepted, plus that one size change.
- A SLAM Toolbox node that ran while `/tf_static` was missing (no `robot_state_publisher`)
  produced no map and dropped scans; once `robot_state_publisher` was started it produced a map
  (81 x 103 cells) without a restart.

What was not tried: `gz sim --reset`-like server restarts through `/server_control`; the time to
reset other worlds.

## 10. Goal 8: a laser scan schema in Foxglove

**Answer: yes. `foxglove.LaserScan` exists.** Source: the Foxglove docs page
(<https://docs.foxglove.dev/docs/sdk/schemas/laser-scan>, fetched 2026-11-23) lists the fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `timestamp` | Timestamp | scan capture time |
| `frame_id` | string | frame of reference |
| `pose` | Pose | origin of the scan relative to the frame |
| `start_angle`, `end_angle` | float64 | bearing of first and last point, radians |
| `ranges` | float64[] | distances, equally spaced in angle |
| `intensities` | float64[] | signal strength |

The page says the schema is available as JSON, Protobuf, ROS 1 (`foxglove_msgs/LaserScan`), ROS 2
(`foxglove_msgs/msg/LaserScan`), FlatBuffers and OMG IDL, "used in the 3D and Image panels", and
that the exact schema name `foxglove.LaserScan` is needed for Foxglove to recognise it. The
repository `foxglove/schemas` is named as the source in a search result I did not open. A
[Lichtblick page](https://lichtblick-suite.github.io/docs/visualization/message-schemas/laser-scan.html)
for the same schema also appeared in search results; I did not open it either.

For robotics-lab: `wire.py:23-34` already maps channels to Foxglove schemas (`foxglove.Grid`,
`foxglove.PointCloud`, ...). A laser scan would be one more entry (for example `/scan` to
`foxglove.LaserScan`). The Foxglove scan has no `angle_increment`, no `range_min` or `range_max`:
the angle step is derived from the two angles and the count, and the sensor's range limits are
lost on conversion. Differences from the ROS `sensor_msgs/LaserScan` I saw (goal 2): ROS has
`scan_time`, `time_increment`, the range limits and float32. Not verified: that our Lichtblick
viewer (`robotics-lichtblick`) draws the schema (the page says the 3D panel does); I did not test a
file in a viewer. A ROS bag in MCAP with `sensor_msgs/LaserScan` (cdr) is a different, also
supported, route, which I did not test in a viewer either.

## 11. Goal 9: recording

**Answer: yes. In Jazzy `ros2 bag record` writes MCAP by default.**

`ros2 bag record --help`: `-s {mcap,sqlite3}, --storage ...  defaults to 'mcap'`. The MCAP plugin
(`ros-jazzy-rosbag2-storage-mcap`) was installed in my image on purpose; in `ros:jazzy-ros-base`
without it I did not check. Compression is off by default (`--compression-mode`, default none).

Recording 30 s of `/scan /odom /tf` while the robot drove and SLAM Toolbox ran
(`ros2 bag record -o bag1 /scan /odom /tf --use-sim-time`, then `ros2 bag info`):

```text
Storage id:        mcap
Bag size:          2.1 MiB      (bag1_0.mcap 2,207,725 bytes, metadata.yaml 2,730 bytes)
Duration:          29.68 s
Messages:          5196
  /odom  nav_msgs/msg/Odometry    1485   cdr
  /scan  sensor_msgs/msg/LaserScan 148   cdr
  /tf    tf2_msgs/msg/TFMessage   3563   cdr
```

The count agrees with the rates: 148 scans in 29.7 s is 5 Hz; 1485 odometry messages is 50 Hz.
About 75 kB per second in total, 90 % of it tf and odometry. A second 10 s bag without
`--use-sim-time` was 726.4 KiB, and its start time was the wall clock
(`Nov 23 2026 17:37:39`): the bag's own time is the receive time on whichever clock the recorder
uses, while the header stamps inside stay sim time. Not verified: a bag replayed into a viewer.

## 12. Goal 10: image sizes

| Image | Size (`docker images`) | Notes |
| --- | --- | --- |
| `mvp2-spike:jazzy` | 4.32 GB | built here; `docker image inspect --format '{{.Size}}'` says 931,510,866 bytes (the content size, not the unpacked size; the two numbers are different measures) |
| `mvp2-spike:jazzy-nav2` | 5.18 GB | `FROM mvp2-spike:jazzy`; adds Nav2 (apt, 660 MB layer), `nav2-minimal-tb3-sim`, git and colcon (73 MB), `m-explore-ros2` built in `/ws` (`Dockerfile.nav2`) |
| `mvp2-spike:jazzy-proto` | 5.28 GB | `FROM mvp2-spike:jazzy-nav2`; adds pip, venv and `/opt/venv` with `mcap`, `protobuf` 7.36.2, `foxglove-schemas-protobuf`, `pillow` (`Dockerfile.proto`) |

The apt layer with TurtleBot3, ros_gz, Gazebo and SLAM Toolbox is 2.4 GB of the total
(`docker history`); the base layers of `ros:jazzy-ros-base` are the rest. The base was pulled
by the build, but `docker images` shows no separate `ros:jazzy-ros-base` entry (this Docker uses
the containerd image store), so I cannot list its size on its own. Build time: 157 s for the
apt step, about 48 s to export. The two images added in the extensions are in the table.
Containers: all
`mvp2-spike-gz`, removed with `docker stop` (they were started with `--rm`).

## 13. What this means for RFC-0025

**The clock rule (question 13).** The facts support the rule as written: the bridge stamps with
simulation time, starting near 0; a node with `use_sim_time` false fails every tf lookup at its
own time; with `use_sim_time` true, the stamps and the node clock match. So "ROS on simulator
time inside the graph, our program stamps wall time at the boundary" is workable. Three things the
rule must also say, which the spike found:

1. The simulator clock is not monotonic across a reset. It goes back to 0 (tf2 reports "Detected
   jump back in time"). The connector must not assume a sim stamp only grows: record an epoch
   number for each sim-clock restart next to each sim stamp, or map stamps with an offset
   computed anew at each reset.
2. The real-time factor was 1.00 in every run, and Gazebo can be told to run at 10. The rule
   holds only at a factor of 1 if wall time and sim stamps are to stay one-to-one; record the
   factor, as the RFC already decides.
3. The ROS-side tools write their own time: `ros2 bag record` stamps the bag with sim time or
   wall time depending on `--use-sim-time`. Our run file should take its wall time from the
   connector, not from a bag.

**The stop timeout.** The simulator holds the last velocity: a stale `/cmd_vel` stream drives on
at the last value. The real Burger on ROS 2 also holds it while `turtlebot3_node` lives; only a
dead node (500 ms heartbeat) stops it. The recollection of "about 500 ms" is a true number for the
older ROS 1 firmware and for the heartbeat, not for a `/cmd_vel` timeout in ROS 2. So the
platform needs its own deadman: the connector must send zero velocity when a command goes
stale, in the simulator and on the real robot. That matches ADR-0020 decision 2 (the connector
owns the velocity path).

**Versions.** ROS 2 Jazzy with Gazebo Harmonic (Gazebo Sim 8.15.0), `turtlebot3_gazebo` 2.3.7, SLAM
Toolbox 2.8.5, `ros_gz` 1.0.25. The parked Nav2 image's Jazzy base is right. Noted: `/cmd_vel` is
`TwistStamped`.

**The scan schema.** `foxglove.LaserScan` exists, so a scan can be a Foxglove channel in the run
file next to the others, and a ROS bag in MCAP is a second route. The Foxglove form drops the range
limits and the angle step; the connector should carry them in the run's header or the profile.

**Reset.** A reset is 0.26 s, but only if the robot is part of the world file. With the stock
launch (robot spawned after start), `reset all` deletes the robot, and re-spawning it crashed
Gazebo. The simhost's reset for a Gazebo host kind should be "start Gazebo from a world that
includes the robot, then `reset all`", or a container restart (48 s, measured once). Odometry resets
with the world, but not with `set_pose`. SLAM Toolbox does not need a restart for a fresh map
(`/slam_toolbox/reset`), within the limits in section 9.

**From the extensions (sections 18 to 20).**

- **The connector works as RFC-0025 section 3.3 describes it.** One node served `robot.move`,
  `robot.stop` and `robot.state`, published `/cmd_vel` only from them, and its own deadman stopped
  the robot 0.6 s after the last command while the plugin kept the last velocity. The gate's
  stop-then-zero sequence ran unchanged. The deadman belongs in the connector, as written.
- **The clock rule needs one more clause: a clock epoch.** At a reset, wall time stayed monotonic,
  the sim stamp jumped from 65.4 s back to 0.2 s, and the epoch counter, a `clock_epoch` event and
  a new `map_to_world` record marked it. The run's own time must stay wall time
  (`mcapio.py:193` rejects time going back). Open: a ROS tf buffer does not survive the jump
  (the belief froze in the prototype), so the connector has to rebuild its tf state, and probably
  SLAM Toolbox's, at each epoch; I did not make that work.
- **The scan schema needs run-format changes**, listed with lines in section 20: `wire.py` and
  `mcapio.py` take only the channels in `CHANNELS`. Until then the scan goes out as `/depth`
  points with the range limits in `raw`.
- **A Gazebo host kind needs a truth reader.** The bridge drops entity names from the pose
  stream; `simhost.truth` must read Gazebo's pose another way (section 20, table).
- **Cameras are affordable in the simulator and expensive in the run.** 640 x 480 RGB and depth at
  30 Hz cost about 1.7 cores on software rendering and 3.9 GB a minute raw: the run's companion
  streams (section 3.6) need compression, and a lower rate or size for a default.
- **SLAM against truth is good in the simulator** (5.4 cm at most over 30 m) because Gazebo's
  odometry is nearly ideal; that says nothing about a real Burger's slip. The judge's idea
  (belief against truth) works unchanged on SLAM Toolbox's pose.
- **A frontier explorer exists for ROS.** `explore_lite` (from source, with Nav2) mapped the room
  in 51 s; it needs Nav2 and a `Twist` to `TwistStamped` relay in Jazzy.

## 14. Comparison with the duck's simulator

Sources for the duck: [MICRODUCK](MICRODUCK.md), [DUCK-SIM-FOR-AGENTS](DUCK-SIM-FOR-AGENTS.md),
[RANGE](RANGE.md), [PHASE0-SPIKE](PHASE0-SPIKE.md), `robots/duck/profile.json`,
`libs/runner/src/labrunner/camera.py`. For Gazebo: what I ran today. The "Good at" row is
general knowledge, not something measured in this spike. For things I did not run, I say "not
verified".

| | Duck: Pollen's `duck-sim` (MuJoCo) | Burger: Gazebo Sim 8 |
| --- | --- | --- |
| Physics engine | MuJoCo, body from `microduck_rl` (`robotd --sim` against a MuJoCo body) | Gazebo's physics plugin (which engine: not checked here; the world has a 1 ms step) |
| Good at | legged contact and a policy at 50 Hz that must run at or above real time | wheeled bases, ray and camera sensors from a world file, a ROS bridge |
| Who makes the sensors | the robot's own daemons run unchanged: `robotd` (joints, IMU, odometry), `tofd` (8x8 depth), `mapd` (map); the simulator gives them a body and rays (`tof.py` casts `mj_ray`) | sensor plugins named in the model's SDF: lidar (5 Hz) and IMU (200 Hz) in `model.sdf`, odometry from the DiffDrive plugin |
| Camera | a stand-in recogniser from the layout (`sim_camera.py`), served by the host on a socket, 60 degrees, 3.0 m, every 0.5 s; guesses, not measured | none in the Burger model used here (the package has a camera bridge file for other models; not tested) |
| Worlds | MJCF scenes (the apartment) plus our layout JSON | SDF worlds (`turtlebot3_world.world`), models by `model://` |
| Rendering, GUI | a rendered head camera on port 8080 by Pollen; our views are the Observatory and Mission Control | headless server (`-s`), no GUI used; lidar needs a rendering engine even without a display (Ogre2 started headless here) |
| Real-time control | must be at or above real time or the policy cannot balance | real-time factor 1.00 here; can be set to 10 |
| Reset | `duck-sim down` and `up` through `simhost.reset` (a challenge run restarts it every ~70 s) | `reset all` 0.26 s, if the robot is in the world (section 9) |
| ROS | none; the daemons use Unix sockets; our code reads those | `ros_gz_bridge` with a YAML list of topics; stamps with sim time |
| Resource use | not measured here | 0.45 to 0.95 of one core, 0.5 to 0.6 GiB, with SLAM Toolbox; no GPU |

The main difference: the duck simulator is a body that runs the real robot's software, so the
sensors are whatever the daemons compute (and what mapd assumes about them is a known issue,
K34 in `KNOWN-ISSUES.md`). Gazebo is a world with sensor plugins and no robot software; the
robot's behaviour comes from the SDF and the bridge. The Burger's "daemons" would be
`turtlebot3_node` and the lidar driver on the real robot, and the plugins in the simulator, with
nothing shared between the two.

## 15. SLAM Toolbox, and the duck's mapper

**What it does.** A 2D SLAM for ROS 2: it builds an occupancy grid from laser scans and keeps a
graph of poses, to correct the map when the robot returns (loop closure). Source: the repository
README (<https://github.com/SteveMacenski/slam_toolbox>, fetched 2026-11-23; read through a
summarising fetch tool). Modes, as the README lists them:

- **Synchronous:** processes every scan, however much it lags.
- **Asynchronous:** runs independently of the scan rate and may skip scans (used here).
- **Localization:** matches against a saved map with a rolling buffer of recent scans.
- **Lifelong:** keeps refining and updating saved pose graphs.

**Inputs and outputs.** In: a laser scan topic (`/scan`) and a transform from the odometry frame
to the base frame (`odom` to `base_footprint` here); the fixed link to the lidar (`base_footprint`
to `base_scan`, from `/tf_static`) must exist too (I met that failure, section 4). Out: `/map`
(occupancy grid; I saw it latched, `transient_local`), the `map` to `odom` transform, and the
serialized pose graph (`.posegraph` and `.data`, written by `/slam_toolbox/serialize_map`), which
can be loaded again. The default parameters I used: resolution 0.05 m, a map update every 5 s,
`minimum_travel_distance` 0.5 m, loop closing on, solver Ceres.

**What I saw.**

- Map quality: good in a small, clean world (section 5).
- Drift: not measured against truth. Odometry in Gazebo is the plugin's integration of ideal
  wheels, so it is better than a real robot's.
- CPU: SLAM Toolbox plus Gazebo plus bridge took 0.6 to 0.95 of one core in total; Gazebo alone
  idle was 0.44 to 0.71.
- Scans were dropped (`Message Filter dropping message ... queue is full`) while the clock jumped
  or when the transform was missing; one in a normal run (`slam3.log`).

**Compared with `mapd`** (read from `docs/wip/RANGE.md`, `KNOWN-ISSUES.md`, `EXPLORE-PROGRESS.md`;
not from the Pollen source): `mapd` builds an occupancy grid of 5 cm cells from the duck's 8 x 8
depth sensor (`tofd`) and the robot's odometry; it keeps keyframes and loop closures; it maps at
stops (the duck stands still at each frontier, `EXPLORE-PROGRESS.md`); its model of the sensor
is fixed (`range_is_axial = true`, 3 degrees pitch; K34), and it cannot be told "you are here"
(no set-pose, only a wipe; K5). The operator's note on "fixes from landmarks" I did not find as
such; what the docs say is keyframes and loop closures (K4, K26). Differences that matter:

| | SLAM Toolbox | `mapd` |
| --- | --- | --- |
| Input | 360 beams, 5 Hz, 0.12 to 3.5 m, 2D | 8 x 8 zones over 45 degrees, short range, at stops |
| Pose in | odometry transform, corrected by scan matching | the robot's odometry (reads 10 to 18 % long on the duck's walk; K39) |
| Reset | `/slam_toolbox/reset`, and a saved pose graph | a wipe only |
| Output | `/map`, `map` to `odom` transform, pose graph | its own socket (Mission Control reads it directly) |

**For the platform.** A mapper is a robot-specific part: each robot's profile should say which
mapper it has, and the run records the map it produced (`/map` to `foxglove.Grid` already fits,
`wire.py`). The navigator's duck-only assumptions (K10) are the same ones the Burger breaks: it
has no `mapd`, no 8 x 8 depth and no head.

## 16. Sensors across robots and simulators

| Sensor | Who makes it: simulator | Who makes it: real robot | Topic or socket | Shape, rate, range |
| --- | --- | --- | --- | --- |
| Burger 2D lidar | Gazebo lidar sensor plugin (SDF, `base_scan`) through the bridge | the lidar's own driver node (`hls_lfcd_lds_driver` or `ld08_driver`, separate repos in the ROBOTIS list; not read) | `/scan` | LaserScan, 360 beams, 5 Hz, 0.12 to 3.5 m (sim, measured); real values not verified |
| Burger IMU | Gazebo IMU plugin (SDF) | OpenCR board, read by `turtlebot3_node` (`sensors/imu.cpp`) | `/imu` | Imu, 200 Hz in the simulator, frame `burger/imu_link/tb3_imu`; real rate not verified |
| Burger wheel odometry | DiffDrive plugin | `turtlebot3_node` computes it from joint states and the IMU (`odometry.cpp`), stamped with the node's clock | `/odom` and `odom` to `base_footprint` in `/tf` | Odometry, 50 Hz (sim, measured); real rate not verified |
| Duck 8x8 depth | the simulator's `tof.py` (`mj_ray`, radial, noise 0.003 + 0.02 x range/4 m) feeding `tofd` | the VL53L5CX sensor, `tofd` | the `depth` socket | 8 x 8 zones over 45 degrees; the profile says radial in the simulator |
| Duck camera | a stand-in recogniser from the layout (`sim_camera.py`, `labrunner.camera`) | a real camera and detector are not yet built (RFC-0016) | the camera socket, `camera.detect` | detections relative to the duck; 60 degrees, 3.0 m, every 0.5 s (guesses) |
| Duck IMU | the simulated body, published by `robotd` | `robotd` | the `robot` socket | not looked up here |
| Duck odometry | `robotd` odometry from the simulated body | `robotd` | the `robot` socket | reads about 10 % long in the simulator; the profile scales it |

What this means for a robot-neutral sensor layer:

- The two sets overlap only in IMU and odometry. The lidar and the 8 x 8 depth are different
  shapes (a ring of 360 ranges against a grid of 64 zones), so one stream kind per sensor kind is
  right: `laser_scan` (with angles and range limits) beside the existing `depth_frame`.
- Who stamps differs: in Gazebo the bridge forwards sim time; on the real Burger the node stamps
  with its own clock; on the duck, the daemons' clock. The connector must stamp wall time on
  receipt in all three cases, and keep the source stamp beside it (RFC-0025 section 3.6).
- A host kind must say which sensor kinds it can simulate: the Gazebo host can give a laser
  scan, an IMU and odometry from the SDF; it has no 8 x 8 depth sensor. The duck host can give
  depth, IMU and odometry, and a camera only as a recogniser. A robot profile that declares a
  sensor the host kind cannot simulate must fail at the start, not silently run without it.
- The sensors in a profile should carry the numbers the simulator and the real robot disagree
  on (range model, pitch, scale), as the duck's profile already does (`tof8x8.mount`).

## 17. Not covered

- The real Burger: nothing ran on hardware; the OpenCR statements come from source code on
  GitHub (2023 firmware for the ROS 1 style, `master` for the ROS 2 style), not from the
  operator's robot, and the real sensor rates and ranges were not checked.
- Another ROS or Gazebo pair, the `main` branch, and Humble: not tried.
- Gazebo's physics engine name and the lidar's renderer (software or GPU): not checked.
- A GUI or a camera: no GUI; no camera sensor tested (only the lidar, IMU, odometry).
- Teleop through ROBOTIS's own `turtlebot3_teleop` (not installed); my scripts drive instead.
- Nav2 on the Burger, `explore_lite`, autonomous goals: not run.
- Map accuracy against the world file, drift, and loop-closure events: not measured.
- `/slam_toolbox/reset` visually compared; localization mode; lifelong mode; synchronous mode.
- Upper limit of the real-time factor, and SLAM Toolbox quality when sped up.
- Resource use of the duck simulator: not measured; the numbers above are for Gazebo only.
- Replay of the bag or a viewer for `foxglove.LaserScan`; the `foxglove_msgs` ROS package.
- `Twist` (unstamped) commands: the Jazzy bridge in this image is built for `TwistStamped`.
- A reset from the server side (`/server_control`), and resets with other worlds.
- Work files left in the cache directory: `out/map1.*` and `out/posegraph1.*` are owned by root
  (the first container ran as root); I did not remove them, since removing needs root or a
  container. All other files are owned by the operator.

## 18. Extension A: SLAM against truth, and explore_lite

Approved by the operator on 2026-11-23 as an extension. Same rules as before.

**Answer: SLAM Toolbox's pose stayed within 5.4 cm of Gazebo's true pose over a 30 m loop, with a
heading error under 1 degree except for one 11.6 degree sample that the odometry shows too.
`explore_lite` mapped the whole room in about 51 s; my wall-following script mapped about half in
175 s.**

How: the container ran Gazebo (robot in the world file), `robot_state_publisher`, SLAM Toolbox,
and `truthlog.py` (`out/A1.csv`), which every 0.2 s of sim time writes SLAM's pose (`map` to
`base_footprint`; `base_link` sits 1 cm above it with no xy offset), the odometry pose, and
Gazebo's true pose of the model `burger`. The truth comes from `gz topic -e -t
/world/default/dynamic_pose/info --json-output`, read by the script (see the finding at the end
of section 20 about why not the bridge). `analyse.py` aligns SLAM's frame to the world and
compares. The driver was `wallfollow.py` for 175 s (the loop: 30.8 m of odometry path).

```text
samples 897, duration 179.4 sim s, truth path 29.9 m
SLAM, first-pose alignment: pos err mean 0.023 m, max 0.054 m, end 0.036 m
                            heading err mean|.| 0.51 deg, max 11.64, end 0.99
SLAM, best-fit alignment:   pos err mean 0.010 m, max 0.048 m, end 0.009 m
odometry, first-pose:       pos err mean 0.014 m, max 0.054 m, end 0.021 m; heading max 11.64
```

Error over time (SLAM, first-pose alignment): 0.016 m at 15 s, 0.010 at 45 s, 0.025 at 104 s,
0.043 at 133 s, 0.036 at 178 s; heading 0.5, -0.4, 0.3, 0.8, 1.0 degrees. It grows slowly and
does not blow up.

What this does and does not say:

- The odometry of Gazebo's DiffDrive plugin is nearly ideal (mean 1.4 cm against truth), so SLAM
  had good input. SLAM Toolbox did not make it worse (2.3 cm mean). A real Burger's wheel
  odometry slips and drifts; this test cannot say how SLAM Toolbox does then.
- The 11.6 degree heading maximum appears in the odometry too, at the same instant: I take it as
  a pairing artefact (the truth sample and the tf sample are not from the same instant while the
  robot spins), not as a SLAM error. Not verified.
- Alignment matters. With the first pose as the anchor, the error is as above. A best fit over
  the whole path is lower in position and slightly higher in heading.

Map against the world's walls. The world file has nine pillars (cylinders, radius 0.15 m, at
x, y in {-1.1, 0, 1.1}; read from the `turtlebot3_world` model). For each pillar I took the
nearest occupied map cell in the world frame:

```text
nearest occupied cell minus 0.15 m: -0.05 for all nine pillars (mean 0.052 m, max 0.053 m)
best-fit alignment instead:         mean 0.068 m, max 0.096 m
overlay: out/A1_overlay.png (map cells red, pillars blue circles, true path green)
```

So every pillar is where it should be to within one 5 cm cell, in the same direction (the
occupied cell is one cell inside the true surface). A wall check is not done: I did not extract
the hexagon's wall geometry from the mesh. The wall-following run covered the west part only
(map extent in the world frame x -2.95 to 1.10, y -2.55 to 2.55).

**Loop closures.** SLAM Toolbox with `debug_logging: true` wrote no loop-closure line (the log has
only the solver and the parameters). The graph topic `/slam_toolbox/graph_visualization` held 59
nodes and two edge markers: a blue one with 228 points (114 edges) and a cyan one with 0 points.
I read the empty one as "no loop-closure edge", but I did not verify what the colours mean, so I
cannot say if a closure fired. The saved `posegraphA1b.posegraph` is binary; I did not parse it.

**explore_lite.** Built from source in `mvp2-spike:jazzy-nav2` (section 12): Nav2 from apt
(1.3.14) and `robo-friends/m-explore-ros2` cloned with `--depth 1` and built with `colcon build
--packages-up-to explore_lite` as RFC-0015 section 8 did; it built without changes. To run it:

- Jazzy's Nav2 publishes `Twist` on `/cmd_vel` and the Gazebo bridge wants `TwistStamped`. I
  changed the collision monitor's output topic to `cmd_vel_raw` in a copy of the parameters
  (`nav2_params.yaml`, also `robot_radius` 0.12) and added a 15-line relay (`twist_relay.py`)
  that stamps it. (Our own connector would own this step.)
- SLAM Toolbox gives `/map` and the `map` to `odom` transform; Nav2's navigation launch
  (`navigation_launch.py`, no AMCL, no map server) and `explore.launch.py` ran on top.

Result (`out/cov_explore.csv`, `out/mapA2.png`):

| Run | Time | Known area | Free | Notes |
| --- | --- | --- | --- | --- |
| `explore_lite` | 51 s wall = sim (it logged "Successfully returned to initial pose") | 21.35 m2 | 19.57 m2 | whole hexagon, nine complete pillars; 19 m2 reached at sim 67.8 s |
| `wallfollow.py` | 175 s | 11.67 m2 | 10.57 m2 | west half only |

The comparison is not fair to wall following: my script is a crude left-wall follower I wrote in
a few minutes, it stayed in the west part, and it is not a tuned algorithm. A coverage curve for
it over time was not recorded (the run I tried failed because SLAM Toolbox had not been
activated; see "not covered"). `explore_lite` needs Nav2 and a costmap, so it is a heavier stack
(CPU of that stack not measured).

## 19. Extension B: cameras in Gazebo

**Answer: an RGB camera and a depth camera at 640 x 480, 30 Hz, work headless on software
rendering at a real-time factor of 1.00. They cost about 1.7 extra cores and make 3.9 GB a minute
raw.**

Setup: a copy of the Burger model in `~/.cache/robotics-lab-tests/mvp2-spike/models/
turtlebot3_burger_rgbd/` (the stock files are untouched). It adds one link `camera_link` (0.04 m
forward, 0.12 m up, no collision, no visual so the lidar is not blocked) with one sensor of type
`rgbd_camera`: 640 x 480, `R8G8B8`, horizontal field of view 1.2 rad, clip 0.2 to 5.0 m for both
the colour and the depth camera, `update_rate` 30. `world_cam.world` includes it as `burger`;
`bridge_cam.yaml` adds `/camera/image`, `/camera/depth_image` and `/camera/camera_info`. I did
not bridge the point cloud (`/camera/points`).

Measured with `camstat.py` (a Python subscriber, 12 s) and `ros2 bag`:

| Item | RGB | Depth |
| --- | --- | --- |
| Message | `sensor_msgs/Image`, `rgb8`, 640 x 480, step 1920 | `sensor_msgs/Image`, `32FC1` (metres), step 2560 |
| Bytes per message | 921,600 | 1,228,800 |
| Rate seen | 30.0 Hz wall (29.6 Hz sim) | 29.9 Hz wall (29.5 Hz sim) |
| Raw per minute | 1,661 MB | 2,207 MB |
| One frame compressed | PNG 9,214 B; JPEG q80 14,098 B | 16-bit PNG (mm) 13,571 B |
| Compressed per minute | PNG 17 MB; JPEG 25 MB | 24 MB |

- Depth: 82 % of pixels have a value (min 0.26 m, max 4.89 m); the other 18 % are infinite (the
  sky, or beyond 5 m). The camera info says `fx` 467.7, `cx` 320, frame `camera_link`. Gazebo's
  frame is `camera_link`, not a ROS optical frame (z forward), so a tool that expects the
  optical convention needs a fixed transform that I did not add.
- The compressed sizes are small because the Gazebo render is flat shaded (grey and green
  shapes, no texture, no noise). A real camera's JPEG would be many times larger; I did not
  measure that. Treat the compressed figures as a lower bound.
- `ros2 topic hz` showed 2.5 Hz and 4.0 Hz for the two image topics. That is the command-line
  tool (Python deserialising 1 MB messages), not the simulator: my subscriber saw 30 Hz, and the
  bag has 824 of each in 27.5 s (30.0 Hz).
- Real-time factor with the cameras: 1.0001 (one `gz topic /stats` read while driving).
- CPU and memory, with SLAM Toolbox running, the wall-follower driving, and the truth topic
  bridged (so the same stack in both rows):

| | CPU (docker stats, percent of one core) | Memory |
| --- | --- | --- |
| Without cameras (6 samples) | 82 to 108 % (about 98 %) | 581 MiB |
| With cameras (6 samples) | 253 to 284 % (about 266 %) | 745 to 757 MiB |

- A 30 s rosbag (`ros2 bag record /camera/image /camera/depth_image /camera/camera_info /scan
  /odom /tf --use-sim-time`): MCAP, 1.7 GiB (1,774,842,601 bytes), 27.46 s of data, 7383
  messages (824 each of image, depth and info). No compression was used. I deleted it after
  reading `ros2 bag info`.
- Headless rendering: the container had no `/dev/dri`, so no GPU. Gazebo logged "Unable to open
  display. Trying to run in headless mode." and the Ogre2 sensors worked on the CPU (software
  rendering). I did not read the renderer's name. The workstation's GPU is an AMD integrated one
  (Strix Halo, `lspci`); it was not used. NVIDIA tools are absent. Whether a GPU would lower the
  1.7 core cost was not tried.
- Frames saved: `out/cam_rgb.png` (a view among the pillars with the green wall), `out/
  cam_depth16.png` (16-bit, millimetres) and `out/cam_depth_vis.png` (8-bit, near is white). I
  looked at the RGB and the depth picture; they match.

Not done: 15 Hz (the sensor ran at 30 only), the point cloud topic, image noise, a lower
resolution, a depth range in a real RealSense's style (0.2 to 5 m was set as asked, not
checked against a RealSense datasheet).

## 20. Extension C: a throwaway connector, end to end

**Answer: a 270-line ROS 2 node (`connector.py`, in the work folder, not in the repository) served
`robot.move`, `robot.stop` and `robot.state` over a Unix socket, enforced its own deadman, wrote a
valid run in format 2 with `libs/runfile` unchanged, and the Observatory replayed it. It broke in
two places that RFC-0025 should know: a world reset leaves the belief frozen, and the run format
cannot take a scan channel without changes.**

What was built (all in `~/.cache/robotics-lab-tests/mvp2-spike/`):

- `connector.py`: JSON-RPC 2.0, one request per line, on `/tmp/burger-connector.sock`, the framing
  of `labrunner/camera.py`. Methods `robot.move {vx, vyaw}`, `robot.stop`, `robot.state`, plus
  `connector.log` and `connector.close`. It clamps to 0.22 m/s and 2.84 rad/s (the Burger's
  limits as I remember them from the e-Manual; not re-checked).
- Publishing: a 20 Hz timer publishes `TwistStamped` on `/cmd_vel` only while a `robot.move` is
  alive, and zero for 1 s after a stop or a trip. Nothing else publishes. The gate's own stop
  (`_gate_stop`, `libs/gate/src/robotgate/__init__.py:313-319`) sends `robot.stop` and then a
  zero `robot.move {vx, vy, vyaw}`; the connector accepts both.
- Image: `mvp2-spike:jazzy-proto` (section 12) holds a virtualenv `/opt/venv` with `mcap`,
  `protobuf` 7.36.2 and `foxglove-schemas-protobuf`, which `libs/runfile` needs (the system's
  protobuf is 4.21). The worktree is mounted read-only at `/mc`; `runfile` is imported from
  `/mc/libs/runfile/src`.

**1. The deadman, proven** (`out/runC.txt`). First, with no connector (the same plugin test as
goal 6, once more): a plain publisher stopped after 3 s and the velocity stayed at 0.1500 m/s.
Then through the connector: `robot.move {vx: 0.15}` at 10 Hz for 2 s, then silence:

```text
  +0.50 s: requested 0.15  applied 0.1500  mode moving  deadman_tripped False
  +0.60 s: requested 0.00  applied 0.0000  mode stopped  deadman_tripped True
applied velocity below 0.01 m/s after 0.60 s
events: [('deadman', 0.541)]          (the trip, 0.54 s after the last call)
```

The trip comes at 0.54 s (0.5 s timeout plus up to one 50 ms timer step) and the odometry reads
zero at the next sample. The plugin kept the last velocity; the connector's zero is what stopped
it. This is the behaviour RFC-0025 section 3.3 asks of the connector.

**2. Wall stamps, ROS stamps, clock epochs** (`out/runC.txt`, `readrun.py` output). Every message
the connector takes in (scan, odom, map, truth, clock) is logged with `wall_ns` (its own receipt
time), the ROS stamp, and the current epoch (`connector_log.json`). A tick carries `t` (seconds of
wall time since the run began), `t_src` (the ROS stamp, in sim seconds) and, in `tick_extra`'s
`raw`, `wall_ns`, `ros_stamp_ns`, `epoch`. Across one world reset in the middle of the run:

```text
state before reset: {'wall_ns': 1795458269356782140, 'epoch': 0, 'sim_s': 65.414}
state after reset:  {'wall_ns': 1795458273640549031, 'epoch': 1, 'sim_s': 4.001, ...}
t=61.38 event clock_epoch: the simulator clock went back from 65.583 s to 0.000 s
t=61.60 epoch  map_to_world [-1.98771, -0.49498, 0.0008]   (a second pairing of SLAM's frame
                                                            with truth, after the first at t=0.51)
sim stamp goes back at ticks: [(303, 65.4, 0.2)]      t monotonic: True   epoch field: [0, 1]
```

So: wall time is monotonic, the sim stamp jumps back 65.4 s to 0.2 s, and the epoch counter says
where. That is the rule proposed in section 3.6, and it works. It also shows why the run's own
time must be wall time: `Recorder._check_open` raises `time goes back: ...`
(`libs/runfile/src/runfile/mcapio.py:193`) for a time that goes back, and sim time would.

**3. The run** (`obsdata/runs/burger/tb3-world/spike-0001/run.mcap`, 1.07 MB, 105.8 s). Written
with `mcapio.Recorder` and `mcapio.new_run`; read back with `mcapio.read`:

```text
records: {'run': 1, 'epoch': 2, 'world': 22, 'tick': 526, 'event': 2, 'end': 1}
ticks: 526 with truth 526 with depth 526       (5 Hz, one per scan)
```

- Belief pose: SLAM Toolbox's `map` to `base_footprint`.
- Truth pose: Gazebo's, in the world frame, from `gz topic`.
- Map: the `/map` grid as a `world` record every 3 s (22 maps; characters `?`, `.`, `#`).
- Epoch: `map_to_world`, from pairing the first belief with the first truth.
- Events: `deadman` and `clock_epoch`.
- Scan: see below.

**The scan channel.** `wire.py` cannot take a new channel without modification: a channel needs a
topic and schema in `CHANNELS` (`wire.py:21`), a record kind in `KINDS` (`wire.py:19`), a branch in
`to_messages` (it ends with `raise ValueError(f"unknown record kind ...")` at `wire.py:253`), its
place in the tick protocol (`TICK_PARTS` `wire.py:260`, `INSIDE` `wire.py:266`), a `PROTO` entry
for protobuf (`wire.py:48`) and the schema registration in `mcapio._channel`
(`mcapio.py:268-273`). I did not modify it. As instructed, the scan went out as the existing
`/depth` point cloud: each beam's end point in the `map` frame, kind `o`, z 0.1 m. The range
limits and the angle step that `foxglove.LaserScan` lacks went in the tick's `raw.scan`
(`angle_min`, `angle_increment`, `range_min` 0.12, `range_max` 3.5, `n` 360, and
`carried_as`). The Observatory drew the points as "Depth obstacle".

**4. The Observatory** (private instance; screenshots `out/obs_spike-0001_t30.png` and
`..._t90.png`). I ran the Observatory from `apps/observatory` with its own virtualenv
(`.venv/bin/observatory`), on port 8131 (not 8070 or 8060), with an installation file of my own
(`installation.json`: `data` and `index` in `~/.cache/robotics-lab-tests/mvp2-spike/obsdata/`, no
robots) through `ROBOTICS_LAB_INSTALLATION`, so the index is `obsdata/index.sqlite`. Nothing was
written under `/work/robotics-lab/data` or `/work/robotics-lab/state`. A first try without the
installation file found the operator's index (the tool said "a service holds the index ...
not rebuilding it under the service" and wrote nothing), which is why the file is there. The
page (`/web/three/index.html`, driven as `observatory.shots` does, through `launch(p)` and
`window.miniview`) loaded the run with no console errors. At t = 30 s it shows the hexagon
map, the nine pillars, the scan points, belief and truth poses 0.009 m apart, and the command
0.18 m/s. A scene file for `tb3-world` was not needed. No robot body was drawn (no `burger`
description folder under `robots/`).

**What broke.**

1. After the world reset, the belief and the truth in the run are frozen. In run 1, the 222
   ticks after the reset have one distinct belief position and one distinct truth position
   (`readrun.py`: "epoch 1: distinct belief positions 1, distinct truth positions 1"); the
   screenshot at t = 90 s shows both at (1.944, 0.183) while the scan points swing around.
   The connector logged 6235 `TF_OLD_DATA ignoring data from the past for frame base_footprint
   at time 0.02` warnings: its Python tf buffer ignores data that is older than data it holds,
   and does not clear on a clock that goes back (SLAM Toolbox's C++ listener does: "Detected
   jump back in time. Clearing TF buffer"). In run 2 I replaced the buffer at each epoch
   (`CONNECTOR_FIX_TF=1`): the warnings fell to 2221, but the belief did not come back: no
   ticks at all after the reset (`readrun.py` on spike-0002: 306 ticks, all epoch 0), and a
   `TF_OLD_DATA` for frame `odom` at 44.8 s remained. I did not find the cause of the frozen
   truth in run 1 (the truth stream itself is fine after a reset: I checked with `gz topic`
   afterwards, 6 messages, `burger x` moving), nor why run 2's belief lookup stays empty. A
   guess, not verified: after a reset SLAM Toolbox's `map` to `odom` transform keeps stale
   stamps from the old sim time (an earlier `/tf` read after a reset showed a stamp of 423 s),
   so a fresh tf buffer ignores the new ones until the sim clock catches up. What it means: the
   connector cannot trust any ROS tf lookup across a reset, and must restart its tf buffers
   and probably SLAM Toolbox at each epoch (section 9 found SLAM Toolbox itself coped).
2. The tick protocol has no field for the epoch (it went into `raw`), and a new epoch of SLAM's
   frame is an `epoch` record (a `map_to_world`), which the run format has, but nothing in it says
   why (I wrote an event beside it).
3. `robot.state` has no place for a simulator clock epoch in the gate's contract (the duck's keys
   are in `DuckAdapter.state`, `duck.py:416-429`); mine returns it as `epoch` and `sim_s`.
4. The truth through the ROS bridge is not usable by name: the bridge turns Gazebo's
   `/world/default/dynamic_pose/info` into a `tf2_msgs/TFMessage`, but every `child_frame_id` is
   empty (the Gazebo pose carries a `name` that the conversion drops; `ros2 topic echo
   /truth_tf` showed `child_frame_id: ''` for all entities). The connector (and my
   `truthlog.py`) therefore read it with the `gz` command line as JSON. A Gazebo host kind needs a
   real reader (gz-transport, or an `OdometryPublisher` or `PosePublisher` plugin in the world's
   `<include>`), which I did not try. Also, `gz topic` as a subprocess cost visible CPU (the
   truth stream is 58 messages a second of 8 entities).

**Where our platform code would have to change** (this is the main output for RFC-0025; the
lines are in the worktree as read on 2026-11-23, not edited):

| Where | What has to change | Why (from this spike) |
| --- | --- | --- |
| `libs/runfile/src/runfile/wire.py:21` (`CHANNELS`), `:19` (`KINDS`), `:48` (`PROTO`), `:167-253` (`to_messages`), `:260-266` (tick protocol) | a scan channel: `foxglove.LaserScan` plus a place for the range limits and angle step | the scan could only go out as `/depth` points |
| `libs/runfile/src/runfile/mcapio.py:268-273` (`_channel`) | register the new schema | same |
| `libs/runfile/src/runfile/validate.py:65` | the depth point `kind` is one character; a scan point kind needs a name in the viewer | I used `o`; the viewer drew it as "Depth obstacle" |
| `libs/runfile/src/runfile/wire.py` tick `raw` and `mcapio.py` (`begin_tick`) | a first-class clock epoch next to `t_src` | I put `epoch` and `wall_ns` in `raw` |
| `libs/runfile/src/runfile/mcapio.py:193` | none (keep it): the writer's time must be wall time, and that is what the connector did | sim time goes back at a reset |
| `libs/simhost/src/simhost/simulator.py:25-79` (`duck_sim`, `reset`, `down`) | a Gazebo host kind: reset by `reset all` on a world that already holds the robot; restart as the fallback | the stock launch deletes the robot (section 9) |
| `libs/simhost/src/simhost/truth.py:26-35` (`Sample`, `Body`) | a Gazebo reader of the true pose, with `sim_time`; `Sample.sim_time` (`:32`) already exists | the bridge drops entity names |
| `libs/gate/src/robotgate/__init__.py:23-27,313-319` | none for the calls: `robot.move`, `robot.stop`, `robot.state` and the stop-then-zero sequence worked unchanged; the deadman stays the connector's | proven in part 1 |
| the navigator's `robot.state` consumers (`duck.py:416-429`) | the epoch and the clock as keys | RFC-0025 section 3.6 |
| `apps/observatory` (robots folder, `robots.py:names`) | a `burger` description (URDF) so the body is drawn; none was needed to open the run | no body in the screenshot |

Not done in this part: a Mission Control or gate in front of the connector (my client talked to
the connector directly); the `/tf` record `world` to `map` over time beyond two epochs; a
`companion stream` for images (the camera topics were not recorded in this run, only measured in
section 19); the 3D view of the run (only the top view was captured).

Not covered by the extensions (sections 18 to 20):

- Extension A: loop closures (no way to read them was found; the colour meaning of the graph
  markers is unverified); SLAM against truth with a noisy or slipping odometry; the wall geometry
  against the map; a coverage curve for wall following; Nav2's CPU; explore_lite on another world;
  the SLAM Toolbox node that failed to activate in one container (`change_state` timeout, seen
  once after I had killed and restarted nodes by hand; not diagnosed).
- Extension B: 15 Hz and other sizes; the point cloud; noise models; a real camera's compression
  ratio; a GPU run; the renderer's name; an optical frame; a recording with companion streams.
- Extension C: the frozen belief after a reset (cause unknown, two runs, one fix tried that did
  not work); the connector behind our gate and Mission Control; the Observatory's 3D and "map"
  views of the run; a connector for the real Burger; images in the run; throughput of the
  connector (it ran at 5 Hz ticks only); a `Twist` in place of `TwistStamped`.
- All parts: single runs, not repeats; the numbers are one workstation's.
