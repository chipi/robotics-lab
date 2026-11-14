# NXT parts to look for (eBay, BrickLink, BrickOwl)

For the bigger NXT robots and the arm robot in [IDEAS.md](IDEAS.md). Written 2026-11-14. NXT parts
are no longer made, so expect second-hand. Prices and availability were **not** checked.

"Checked" = the number or code was confirmed by a web search on 2026-11-14; "from memory" = not
confirmed, check the listing's photo and description.

## Must-haves for the arm robot

| What | Search for | Why | Code |
| --- | --- | --- | --- |
| Extra NXT motors (3+) | "LEGO 9842 NXT motor" | Arm: shoulder, elbow, gripper | 9842, checked |
| A second NXT brick | "LEGO 9841 NXT intelligent brick" | 3 more motor and 4 more sensor ports, no new drivers | 9841, checked |
| NXT cables | "LEGO NXT cable pack 8528", "NXT cables 6 wire" | Every extra motor and sensor needs one; long ones for an arm | 8528 from memory |
| Technic gears, esp. **worm gears**, turntables, beams | "LEGO Technic worm gear", "LEGO Technic turntable", "LEGO Technic bulk lot" | Arm joints that hold position without power; a rotating base | — |

## Sensors (all supported by our software library, nxt-python)

| What | Search for | Why | Code |
| --- | --- | --- | --- |
| Touch sensors | "LEGO 9843 NXT touch sensor" | Bumpers, gripper contact (2 may already be in the NXT 2.0 box) | 9843 from memory |
| Second ultrasonic | "LEGO 9846 NXT ultrasonic sensor" | Look forward and down / to the side | 9846 from memory |
| Second colour sensor | "LEGO 9694 NXT color sensor" | One on the gripper for pin colours | 9694, checked |
| Temperature sensor | "LEGO 9749 NXT temperature sensor" | Fun extra for patrols | 9749, checked |
| **HiTechnic Gyro** | "HiTechnic NXT gyro NGY1044" | Accurate turning and heading; fixes track slip for mapping | NGY1044, checked |
| **HiTechnic Compass** | "HiTechnic NXT compass NMC1034" | Absolute heading (affected by metal and motors) | NMC1034, checked |
| HiTechnic Accelerometer | "HiTechnic NXT accelerometer" | Tilt, bumps, "was it knocked over?" | from memory: NAC1040 |
| **HiTechnic IR Seeker V2** + an IR ball | "HiTechnic IR seeker V2 NSK1042", "HiTechnic IR ball" | Find and follow a ball or beacon: dog games, "find the device" | NSK1042, checked |
| Mindsensors LineLeader | "mindsensors NXT LineLeader" | 8-sensor line following bar | from memory |
| Mindsensors DIST | "mindsensors DIST-Nx" | Infrared distance, sharper than ultrasonic | from memory |

## Multiplexers and controllers

| What | Search for | Supported by nxt-python? | Code |
| --- | --- | --- | --- |
| **Mindsensors NXTMMX** (motor multiplexer for NXT motors) | "mindsensors NXTMMX" | Yes (`mindsensors.MMX`) | from memory |
| HiTechnic Sensor Multiplexer (4 sensors on 1 port) | "HiTechnic sensor multiplexer NSX2020", "HiTechnic SMUX" | **No**, we would write the driver | NSX2020, checked |
| HiTechnic DC motor / servo controller | "HiTechnic motor controller", "HiTechnic servo controller", "TETRIX" | Yes (`hitechnic.MotorCon`, `ServoCon`) | — |

## Power

| What | Search for | Why | Code |
| --- | --- | --- | --- |
| NXT rechargeable battery | "LEGO 9798 NXT rechargeable battery" | Long sessions; note a second brick needs its own | 9798, checked |
| NXT battery charger / transformer | "LEGO 9833 transformer" | Charges the 9798 | 9833 from memory |

## Dead reckoning for the NXT

Dead reckoning = an odometer and a heading between fixes, plus fixes from known landmarks to
correct the drift (as on a boat). The NXT already has the odometer: each motor counts rotation to
1° (the tacho counts in the logs). Tracks skid when turning, so heading from track counts is poor.

| What | Role | Notes |
| --- | --- | --- |
| HiTechnic Gyro (NGY1044, checked) | Heading: integrate the turn rate | Drifts slowly; corrected by fixes or the compass. Supported by nxt-python |
| HiTechnic Compass (NMC1034, checked) | Absolute heading, no drift | Disturbed indoors by motors and steel: mount it high, use it to correct the gyro |
| An unpowered odometry wheel | Distance that does not slip | A free-rolling wheel turning an encoder: a spare NXT motor (its rotation sensor works unpowered) or a HiTechnic Angle sensor (from memory). Costs a port |
| HiTechnic Accelerometer | Bumps, lifted, tilted: "the dead reckoning is now wrong" | Supported |
| Touch sensors as bumpers | A collision is a position error and a stop | Probably in the NXT 2.0 box |

Fixes (landmarks):

| What | Fix |
| --- | --- |
| Coloured tape on the floor + the colour sensor (have it) | Crossing a mark at a known spot = an exact position; the cheapest fix |
| Ultrasonic (have it), a second one | Distance to known walls; with front + side, wall following and squaring up |
| HiTechnic IR Seeker V2 (NSK1042, checked) + IR beacons or an IR ball | Bearings to known beacons; two beacons triangulate |
| Later: a camera (a Pi on the robot, or the duck watching) | Recognising landmarks |

Build choice: two driven wheels and a caster slip far less than tracks, so the motor counts alone
give usable heading. Minimum kit: the gyro + an odometry wheel (or wheels instead of tracks) +
colour-tape fixes.

## A computer on board the NXT

The brick (48 MHz, 64 KB RAM) cannot run Linux or ROS. Three ways to give the robot one
([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)); not yet decided:

| Option | What it is | Gives | Costs |
| --- | --- | --- | --- |
| **Raspberry Pi on the brick, by USB** (recommended first) | The brick keeps motors and sensors; the Pi is the on-board computer, on Wi-Fi | Runs `nxt-web`, the NXT service, a ROS 2 node if wanted, the navigator on board; a Pi camera | Its own power bank; a Pi Zero 2 W (512 MB) is tight for ROS 2 (from memory), a Pi 4/5 comfortable |
| **ESP32 on the brick** | A microcontroller: a Wi-Fi↔Bluetooth bridge, or a micro-ROS node (micro-ROS officially supports the ESP32, with an agent on a PC) | Small, light, wireless | No Linux, no camera worth having, no navigator on board; must be an original ESP32 for classic Bluetooth |
| **BrickPi3** (Dexter Industries) replacing the brick | A Raspberry Pi board driving NXT and EV3 motors and sensors directly (4 motor, 4 sensor ports; NXT ultrasonic, colour, light, touch; custom I2C sensors) | The robot becomes a Linux computer: more ports, camera, ROS/MoveIt-ready — a strong fit for the arm robot | NXC programs and the brick's screen go; code moves from nxt-python to BrickPi3's library; availability not checked |

### Shopping: a Raspberry Pi on the brick (NL shops, prices and stock as seen 2026-11-14)

A **Pi 4 (4 GB)** over a Pi 5 here: it runs on an ordinary 5 V / 3 A USB-C power bank (a Pi 5 wants
5 A, which power banks do not really give; on 3 A it works with its USB ports limited), the camera
connects with its own cable, and it was in stock. The Pi Zero 2 W was sold out at most retailers
and has 512 MB.

| Item | Where | Seen |
| --- | --- | --- |
| Raspberry Pi 4 Model B 4 GB | [Tinytronics](https://www.tinytronics.nl/en/development-boards/single-board-computers/raspberry-pi-4-model-b-4gb) | €125, in stock |
| (or) Raspberry Pi 5 4 GB | [Kiwi Electronics](https://www.kiwi-electronics.com/en/raspberry-pi-5-4gb-11579) | €118.99, out of stock |
| Camera Module 3 Wide (12 MP) — sees more of the room | [Tinytronics](https://www.tinytronics.nl/en/sensors/optical/cameras-and-scanners/raspberry-pi-camera-module-3-wide-12mp) | €44 |
| (or) Camera Module 3 (12 MP) | [Tinytronics](https://www.tinytronics.nl/en/sensors/optical/cameras-and-scanners/raspberry-pi-camera-module-3-12mp) | €35 |
| Pi 5 only: camera cable Standard–Mini 200 mm | [Kiwi Electronics](https://www.kiwi-electronics.com/en/raspberry-pi-camera-cable-standard-mini-200mm-11588) | €1.13 |
| microSD 32 GB, A1/A2 | [Amazon.nl search](https://www.amazon.nl/s?k=microsd+32gb+a2) | no listing picked |
| USB-C PD power bank, ~10,000 mAh, steady 5 V / 3 A, no auto-off at low current | [Amazon.nl search](https://www.amazon.nl/s?k=powerbank+usb-c+pd+10000mah) | no model verified |
| Mounting | a normal Pi 4 case on Technic beams (velcro, zip ties) or a 3D-printed adapter; the [Pi-Blox LEGO case](https://elektronicavoorjou.nl/product/pi-blox-raspberry-pi-lego-behuizing-wit/) is for Pi 2/3 and was out of stock | — |
| USB-A to USB-B cable | the NXT's own | have it |

## Do not buy for the NXT

- **EV3 sensors and motors' sensors** (EV3 uses a different sensor protocol the NXT firmware does
  not speak; NXT sensors do work on an EV3, not the other way round).
- **Power Functions / Powered Up motors** (no rotation sensor, different connectors) unless you plan
  an adapter.

## Worth a look

- Whole **NXT 1.0 / 2.0 or Education (9797) sets** — often the cheapest way to get a brick, 3 motors
  and sensors at once.
- **"LEGO Mindstorms NXT lot"** — mixed lots with spare motors, cables and sensors.
