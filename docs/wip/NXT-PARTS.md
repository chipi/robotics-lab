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

## Do not buy for the NXT

- **EV3 sensors and motors' sensors** (EV3 uses a different sensor protocol the NXT firmware does
  not speak; NXT sensors do work on an EV3, not the other way round).
- **Power Functions / Powered Up motors** (no rotation sensor, different connectors) unless you plan
  an adapter.

## Worth a look

- Whole **NXT 1.0 / 2.0 or Education (9797) sets** — often the cheapest way to get a brick, 3 motors
  and sensors at once.
- **"LEGO Mindstorms NXT lot"** — mixed lots with spare motors, cables and sensors.
