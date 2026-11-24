# The profile's `sensors` kinds against ROS 2 and a TurtleBot3 Burger

**Status:** check done 2026-11-24, unit E4's loose end. The `sensors` block (kinds `range`,
`colour`, `scan2d`, `imu`, `odometry`, `image`, `depth_image`) was designed for a TurtleBot3 Burger
without reading ROS. This note compares each kind with the ROS message and with what the Burger
publishes, and lists the schema changes made. **Code:** `SENSOR_KINDS` in
`libs/runfile/src/runfile/profile.py`; test `libs/runfile/tests/test_profile_schema.py`.

Every claim is marked **verified** (a fetched primary source, named) or **unconfirmed**. Sources
were fetched on 2026-11-24 (ROS message files from the `rolling` branch, ROBOTIS code from the
`humble` branch unless said).

## Sources

- ROS messages (`common_interfaces`):
  [LaserScan](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/LaserScan.msg),
  [Imu](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/Imu.msg),
  [Image](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/Image.msg),
  [CameraInfo](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/CameraInfo.msg),
  [Range](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/Range.msg),
  [Odometry](https://github.com/ros2/common_interfaces/blob/rolling/nav_msgs/msg/Odometry.msg).
  PointCloud2 was not fetched.
- REPs:
  [REP-103](https://github.com/ros-infrastructure/rep/blob/master/rep-0103.rst),
  [REP-105](https://github.com/ros-infrastructure/rep/blob/master/rep-0105.rst),
  [REP-145](https://github.com/ros-infrastructure/rep/blob/master/rep-0145.rst).
- TurtleBot3, `ROBOTIS-GIT/turtlebot3` branch `humble`:
  [burger URDF](https://github.com/ROBOTIS-GIT/turtlebot3/blob/humble/turtlebot3_description/urdf/turtlebot3_burger.urdf),
  [burger.yaml](https://github.com/ROBOTIS-GIT/turtlebot3/blob/humble/turtlebot3_bringup/param/burger.yaml),
  [turtlebot3.cpp](https://github.com/ROBOTIS-GIT/turtlebot3/blob/humble/turtlebot3_node/src/turtlebot3.cpp),
  [imu.cpp](https://github.com/ROBOTIS-GIT/turtlebot3/blob/humble/turtlebot3_node/src/sensors/imu.cpp),
  [odometry.cpp](https://github.com/ROBOTIS-GIT/turtlebot3/blob/humble/turtlebot3_node/src/odometry.cpp),
  [robot.launch.py](https://github.com/ROBOTIS-GIT/turtlebot3/blob/humble/turtlebot3_bringup/launch/robot.launch.py).
- LDS drivers:
  [LDS-01](https://github.com/ROBOTIS-GIT/hls_lfcd_lds_driver/blob/main/src/hlds_laser_publisher.cpp),
  [LDS-02 (ld08)](https://github.com/ROBOTIS-GIT/ld08_driver/blob/main/src/lipkg.cpp).
- Simulator model:
  [burger model.sdf](https://github.com/ROBOTIS-GIT/turtlebot3_simulations/blob/humble/turtlebot3_gazebo/models/turtlebot3_burger/model.sdf),
  [waffle_pi model.sdf](https://github.com/ROBOTIS-GIT/turtlebot3_simulations/blob/humble/turtlebot3_gazebo/models/turtlebot3_waffle_pi/model.sdf).
- e-Manual:
  [LDS-01](https://emanual.robotis.com/docs/en/platform/turtlebot3/appendix_lds_01/),
  [LDS-02](https://emanual.robotis.com/docs/en/platform/turtlebot3/appendix_lds_02/),
  [features](https://emanual.robotis.com/docs/en/platform/turtlebot3/features/).

## Conventions: ROS against the profile

| Topic | ROS says | Profile |
| --- | --- | --- |
| Units | metres, radians, seconds (REP-103) | `_m`, `_deg` (angles), `_s`, `_hz` |
| Body axes | x forward, y left, z up (REP-103) | `mount` x, y, z in the same axes |
| Rotation | fixed-axis roll, pitch, yaw (REP-103) | `mount.roll_deg/pitch_deg/yaw_deg` |
| Frame name | `header.frame_id` of each message | `frame` (odometry: also `child_frame`) |
| Camera frame | an `_optical` frame: x right, y down, z in | `frame` is that name |
| Uncertainty | covariance matrices; all zeros = unknown | `noise`: a standard deviation |
| Mount parent | the URDF joint's parent, here `base_link` | `base_link`, not a field |

All **verified** in REP-103 (units, axes, `_optical` suffix, fixed-axis rpy), REP-105
(`odom` is the world-fixed drifting frame; `base_link` is the body), REP-145 (IMU `frame_id` is the
sensor frame, default `imu_link`; its mount relative to `base_link` is the mounting; orientation is
optional) and the message files (Imu: "all zeros = covariance unknown", element 0 = -1 = no
estimate). Degrees in the profile where ROS has radians is a deliberate human-facing choice; the
adapter converts. `noise` is a standard deviation (the Gazebo model's `stddev`); ROS's covariance
is its square, and the real Burger fills none (below).

## Field by field

"Had" is the schema before this check; "Now" is after. ROS fields with no profile field and no
need are under *Not carried*.

### scan2d against LaserScan and the Burger's LDS

| ROS field | Had | Now | Burger value (source) |
| --- | --- | --- | --- |
| `angle_min` | none (fov only) | `angle_min_deg` | 0 (LDS-01 driver, verified) |
| `angle_max` | none | `angle_max_deg` | 2 pi - 1 deg = 359 (driver, verified) |
| `angle_increment` | none | `angle_increment_deg` | 1 deg (driver, verified) |
| `range_min` | `range_min_m` | same | 0.12 m (driver, sdf, e-Manual) |
| `range_max` | `range_m` | same | 3.5 m (driver, sdf, e-Manual) |
| rays | `samples` | same | 360 (driver, sdf, verified) |
| `scan_time` | `rate_hz` | same | 5 Hz (sdf `update_rate`; 300 rpm) |
| `header.frame_id` | `frame` | same | `base_scan` (launch, sdf) |
| `ranges` noise | `noise.range_m` | same | stddev 0.01 m (sdf only) |

- **Wrong:** a 360-ray scan with `fov_deg: 360` is not what the driver publishes. The driver's
  `angle_max` is 2 pi minus one increment, so a consumer rebuilding bearings from `fov_deg` and
  `samples` is off by one ray's width (`fov / samples` against `fov / (samples - 1)`). The start
  angle and the increment were also missing, and a scanner may start at -pi (a 0 start is the
  LDS's own choice). Fixed with the three angle fields; `fov_deg` stays for the duck-style readers.
- Mount (verified, URDF): `base_scan` is `x -0.032, y 0, z 0.172` in `base_link`, rpy 0. The sdf
  puts it at z 0.171 in the model frame; `base_link` itself is 0.010 above `base_footprint`.
- **LDS-02 against LDS-01:** the e-Manual features page lists the Burger with an LDS-02
  (verified), range 0.16 to 8.0 m, 1 degree, 2.3 kHz sampling; the LDS-01 page: 0.12 to 3.5 m,
  1 degree, 1.8 kHz, 300 +/- 10 rpm (verified). The LDS-02 driver publishes `range_min 0.0` and
  `range_max 100.0`, not the datasheet's (verified, `lipkg.cpp`), and an increment that varies
  with the motor speed (`mSpeed / 2300`). So a profile of an LDS-02 Burger states the datasheet
  range and says so in `measured`/`why`. The LDS-02 scan rate is **unconfirmed** (not on the page
  fetched). The profile and its test use the LDS-01 numbers: that is what `turtlebot3_gazebo`
  simulates.
- Real accuracy (LDS-01, verified): +/- 15 mm at 120 to 499 mm, +/- 5 % at 500 to 3500 mm. Not
  a single stddev; `noise.range_m` is the simulator's 0.01 m only.
- The real LDS-01 driver also fills `intensities`, `time_increment` and `scan_time` (verified).

### imu against Imu (REP-145) and the OpenCR

| ROS field | Had | Now | Burger value (source) |
| --- | --- | --- | --- |
| `header.frame_id` | `frame` | same | `imu_link` (imu.cpp, verified) |
| mounting | `mount` | same | x -0.032, z 0.068 (URDF) |
| `orientation` present | none | `orientation` bool | yes: the node copies w,x,y,z |
| gyro covariance | `noise.gyro_rad_s` | same | stddev 2e-4 rad/s (sdf only) |
| accel covariance | `noise.accel_mps2` | same | stddev 1.7e-2 m/s^2 (sdf only) |
| rate | `rate_hz` | same | 20 Hz (node timer, 50 ms) |

- **Wrong:** the old test block said 200 Hz and noise 0.001 and 0.02. 200 Hz is the Gazebo
  sensor's `update_rate`; the real node publishes at the 50 ms timer, 20 Hz (verified,
  `turtlebot3.cpp`). The noise numbers were invented; the sdf's are above.
- The real `imu.cpp` sets no covariance at all (searched: no match), so on the robot the
  covariance is all zeros = unknown (REP-145 / Imu.msg, verified). A real-variant profile leaves
  `noise` out or says `measured`; only the sim variant has the sdf's numbers.
- `orientation` was missing: whether an IMU gives a fused orientation changes what a consumer may
  use (REP-145: absent = covariance element 0 is -1). The node fills the quaternion (verified).
- The OpenCR's IMU is a 3-axis gyro and 3-axis accelerometer (e-Manual, verified); the node also
  publishes `/magnetic_field` from the same board (verified, `turtlebot3.cpp`).

### odometry against nav_msgs/Odometry and the Burger

| ROS field | Had | Now | Burger value (source) |
| --- | --- | --- | --- |
| `header.frame_id` | `frame` | same | `odom` (burger.yaml, verified) |
| `child_frame_id` | none | `child_frame` | `base_footprint` (burger.yaml) |
| rate | `rate_hz` | same | 20 Hz (derived, see below) |
| pose/twist covariance | `noise` | same | none: commented out in code |

- **Missing:** the child frame. An odometry says where `child_frame_id` is in `frame_id`; with one
  `frame` the profile could not say `odom -> base_footprint`, which REP-105 and the node's
  `publish_tf` use (verified). Added as `child_frame`, on `odometry` only.
- Rate: the node's odometry runs on the `joint_states` message (with `use_imu: true` it
  synchronises it with the IMU), and `joint_states` goes out on the same 50 ms timer, so 20 Hz.
  That chain is read from the code, not measured: **unconfirmed on a robot**. The old test said
  30 Hz, the sdf's `update_rate` for Gazebo.
- Covariance: the node's pose and twist covariance lines are comments (a TODO in `odometry.cpp`,
  verified), so they are zeros = unknown.

### image and depth_image against Image and CameraInfo

| ROS field | Had | Now | Waffle Pi value (source) |
| --- | --- | --- | --- |
| `width`, `height` | `width_px`, `height_px` | same | 640 x 480 (sdf, launch) |
| `encoding` | none | `encoding` | `R8G8B8` in the sdf (`rgb8`) |
| horizontal fov | `hfov_deg` | same | 1.085595 rad = 62.2 deg (sdf) |
| `header.frame_id` | `frame` | same | `camera_rgb_optical_frame` (URDF) |
| rate | `rate_hz` | same | 30 Hz (sdf) |
| min range (depth) | none | `range_min_m` on `depth_image` | sdf `near` 0.03 (clip) |

- The Burger has **no camera**: its URDF has no camera joint (verified, the joint list ends with
  `scan_joint`); the Waffle Pi's URDF has `camera_rgb_optical_frame`. The old test block's camera
  was not a Burger's. The Burger block now has three sensors; the Waffle Pi's camera is its own
  test block.
- `encoding` was missing: it says what `data` is, with the row length `step` and
  `is_bigendian` following from it. The `frame_id` of an `Image` should be the optical frame
  (Image.msg, REP-103, verified), so a profile that names `camera_link` is wrong for pixels.
- A pinhole camera is fixed by size and horizontal fov (`fx = w / (2 tan(hfov / 2))`, standard
  geometry, not from a ROS page), so `CameraInfo`'s `k` is derivable; `d`, `r`, `p` and the
  distortion model are not carried.

### range against Range

| ROS field | Had | Now |
| --- | --- | --- |
| `min_range` | none | `range_min_m` |
| `max_range` | `range_m` | same |
| `field_of_view` | `fov_deg` | same |
| `variance` | `noise` (stddev) | same |
| `radiation_type` | none | not carried: the kind and `source` say it |

Range.msg also says the message is not for laser scanners, which is why `scan2d` is its own kind
(verified). The NXT's ultrasonic (`range_m` 2.55) stays valid with no change: the new field is
optional.

### Not carried (decided, not found missing)

- **PointCloud2:** no kind. The Burger publishes none. A Waffle with a depth camera, or an
  RGB-D robot, would need a `pointcloud` kind (frame, rate, point count, fields). Unconfirmed
  whether any robot of ours will; PointCloud2.msg was not fetched.
- **Magnetometer** (`/magnetic_field`, REP-145 says Tesla) and the `/battery_state` and
  `/sensor_state` topics of the Burger: the profile has no kind for them. `joints` and the battery
  guard carry what the platform reads today.
- **Header stamps, QoS** (the LDS-02 driver uses `SensorDataQoS`: best effort), per-axis covariance
  matrices, `intensities`, `time_increment`: the adapter's concern, not a profile field.

## What the schema now is

| Kind | Added fields |
| --- | --- |
| `scan2d` | `angle_min_deg`, `angle_max_deg`, `angle_increment_deg` |
| `range` | `range_min_m` |
| `imu` | `orientation` (bool) |
| `odometry` | `child_frame` |
| `image`, `depth_image` | `encoding`; `depth_image` also `range_min_m` |

Additive only: no profile version change (as `profile.py` already says of kinds and fields).
`tof8x8` and `camera`, the duck's two blocks, are untouched: the duck's profile checksum was
`sha256:e4ccb265...ada585` before and after, and so was the validated profile.

## Not covered by this check

- No consistency rule between fields: `angle_max_deg` above `angle_min_deg`,
  `samples` against `(max - min) / increment + 1`, `hfov_deg` against `width_px`. A wrong
  triple validates.
- No run against a real ROS graph or a live Burger: every "Burger value" is from source or
  datasheet, none from `ros2 topic echo`. The 20 Hz rates are read from code.
- The adapter that turns a sensor entry into a ROS subscription is not written; degrees to
  radians and `noise` to covariance live there.
- REP-103 and REP-145 were checked for the facts quoted, not read end to end. The Jazzy or Rolling
  `.msg` files may differ from Humble's, which ships on the Burger; not compared.
