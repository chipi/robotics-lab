"""The simulated duck as a ROS 2 robot (RFC-0015 §3.2, the spike's first version): robotd's state and the depth sensor in,
/cmd_vel out. Runs in the nav2 container, `--network host`, with ~/.cache/duck-sim at /duck-sim and the repository's duck/ at
/duck (read-only). It reuses duck_lab's own sensor geometry (nav/cliff.py), so both brains read the same depth.

Publishes (all stamped with this node's clock, use_sim_time false):
  /odom and tf odom -> base_link   odometry x, y by the calibration's scale (0.91), yaw as is; base_link is the trunk's
                                   level frame ON THE FLOOR (z 0 = floor), not the trunk's centre 0.116 m up: the depth
                                   points come from cliff.depth_points already in it, with their height above the floor
  /depth/obstacles                 PointCloud2 in base_link: the returns that are obstacles (marking)
  /depth/floor                     PointCloud2 in base_link: the returns that are floor, heights near 0 (clearing, RFC-0015
                                   §3.2's floor-band cloud)
  /drops                           PointCloud2 in base_link: where the floor should have been (cliff.drop_points)
Subscribes /cmd_vel (Twist) and sends robot.move at 10 Hz through the locomotion adapter (RFC-0015 §3.3, steps d, c, b; the
kick (a) is not built): no backwards, no forward walk under 0.2 m/s, a pivot creeps with vx -0.06; 0.3 s of silence is
one explicit zero.
"""

import json
import math
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/duck/src")

import rclpy  # noqa: E402
from geometry_msgs.msg import Twist, TransformStamped  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import PointCloud2, PointField  # noqa: E402
from tf2_ros import TransformBroadcaster  # noqa: E402

from duck_lab.nav import cliff  # noqa: E402
from duck_lab.nav.client import Rpc, StateStream, odom_pose  # noqa: E402

SIM = Path("/duck-sim")
CAL = json.loads(Path("/duck/calibration/sim.json").read_text())
SCALE = CAL["odom_scale"]
PIVOT_VX = CAL["pivot"]["vx_mps"]
MIN_WALK = 0.2
SILENCE_S = 0.3


def cloud(stamp, points: list) -> PointCloud2:
    msg = PointCloud2()
    msg.header.stamp, msg.header.frame_id = stamp, "base_link"
    msg.height, msg.width = 1, len(points)
    msg.fields = [PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1) for i, n in enumerate("xyz")]
    msg.is_bigendian, msg.point_step, msg.row_step, msg.is_dense = False, 12, 12 * len(points), True
    msg.data = b"".join(struct.pack("<fff", *p) for p in points)
    return msg


class Bridge(Node):
    def __init__(self):
        super().__init__("duck_bridge")
        cliff.configure(**{"pitch_offset_deg": CAL["tof"]["pitch_offset_deg"], "range_kind": CAL["tof"]["range"]})
        self.odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self.tf = TransformBroadcaster(self)
        self.obstacles = self.create_publisher(PointCloud2, "/depth/obstacles", 10)
        self.floor = self.create_publisher(PointCloud2, "/depth/floor", 10)
        self.drops = self.create_publisher(PointCloud2, "/drops", 10)
        self.create_subscription(Twist, "/cmd_vel", self.on_cmd, 10)
        self.robot = Rpc(SIM / "duck-a.sock")
        self.state = None
        self._prev = None
        self.cmd, self.cmd_t = Twist(), 0.0
        self.sent_zero = True
        self.counts = {"backwards_dropped": 0, "raised_to_min": 0, "pivots": 0, "frames": 0}
        StateStream(SIM / "duck-a.sock", hz=20, on_state=self.on_state)
        threading.Thread(target=self.tof_loop, daemon=True).start()
        self.create_timer(0.1, self.send)
        self.create_timer(10.0, lambda: self.get_logger().info(f"adapter: {self.counts}"))

    def on_state(self, st: dict) -> None:
        self.state = st
        x, y, yaw = odom_pose(st)
        x, y = x * SCALE, y * SCALE
        now = self.get_clock().now()
        vx = vyaw = 0.0
        if self._prev is not None and (now - self._prev[0]).nanoseconds > 0:
            dt = (now - self._prev[0]).nanoseconds / 1e9
            dx, dy = x - self._prev[1], y - self._prev[2]
            vx = (math.cos(yaw) * dx + math.sin(yaw) * dy) / dt
            vyaw = math.atan2(math.sin(yaw - self._prev[3]), math.cos(yaw - self._prev[3])) / dt
        self._prev = (now, x, y, yaw)
        t = TransformStamped()
        t.header.stamp, t.header.frame_id, t.child_frame_id = now.to_msg(), "odom", "base_link"
        t.transform.translation.x, t.transform.translation.y = x, y
        t.transform.rotation.z, t.transform.rotation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        self.tf.sendTransform(t)
        o = Odometry()
        o.header, o.child_frame_id = t.header, "base_link"
        o.pose.pose.position.x, o.pose.pose.position.y = x, y
        o.pose.pose.orientation = t.transform.rotation
        o.twist.twist.linear.x, o.twist.twist.angular.z = vx, vyaw
        self.odom_pub.publish(o)

    def tof_loop(self) -> None:
        s = socket.socket(socket.AF_UNIX)
        s.connect(str(SIM / "duck-a-tof.sock"))
        f = s.makefile("rw")
        f.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tof.stream"}) + "\n")
        f.flush()
        for line in f:
            msg = json.loads(line)
            if msg.get("method") != "tof.frame" or self.state is None:
                continue
            fr, st = msg["params"], self.state
            try:
                pts = cliff.depth_points(fr, st)
                drops = cliff.drop_points(fr, st)
            except (KeyError, TypeError, ValueError):
                continue
            stamp = self.get_clock().now().to_msg()
            self.obstacles.publish(cloud(stamp, [(p[0], p[1], p[2]) for p in pts if p[3] == "obstacle"]))
            self.floor.publish(cloud(stamp, [(p[0], p[1], 0.0) for p in pts if p[3] == "floor"]))
            self.drops.publish(cloud(stamp, [(d[0], d[1], 0.15) for d in drops]))
            self.counts["frames"] += 1

    def on_cmd(self, tw: Twist) -> None:
        self.cmd, self.cmd_t = tw, time.monotonic()

    def adapt(self, vx: float, vyaw: float) -> tuple:
        if vx < 0:
            self.counts["backwards_dropped"] += 1
            vx = 0.0
        if 0 < vx < MIN_WALK:
            self.counts["raised_to_min"] += 1
            vx = MIN_WALK
        if vx == 0 and vyaw != 0:
            self.counts["pivots"] += 1
            vx = PIVOT_VX
        return vx, vyaw

    def send(self) -> None:
        if time.monotonic() - self.cmd_t > SILENCE_S:
            if not self.sent_zero:
                self.robot.call("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
                self.sent_zero = True
            return
        vx, vyaw = self.adapt(self.cmd.linear.x, self.cmd.angular.z)
        self.robot.call("robot.move", {"vx": vx, "vy": 0.0, "vyaw": vyaw})
        self.sent_zero = False


def main() -> None:
    rclpy.init()
    rclpy.spin(Bridge())


if __name__ == "__main__":
    main()
