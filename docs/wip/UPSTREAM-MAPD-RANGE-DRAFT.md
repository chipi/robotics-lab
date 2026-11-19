# Draft note to Pollen: what range model does mapd assume for the depth sensor? (not sent)

**Status:** a draft for the operator to read and send, or not (2026-11-19, K34). Nothing was sent;
nothing in Pollen's repository was edited (the bench was built offline, into a scratch directory).

**Context.** We drive a simulated Microduck (microduck_rl's `body_server`, `tof.py`) with a
navigator of our own, and use `mapd` for its map and pose. `maploc/src/project.rs` has
`range_is_axial = true` and a 3 degree pitch as defaults, and its comment calls the axial choice
"unsettled for the VL53L5CX". `mapd` builds its `MapperConfig` from the defaults and reads only
`tof_latency_ms` from `robotd.toml`, so in the simulator and on a robot the sensor model is that
one.

**What the simulator reports.** `tof.py` casts one `mj_ray` per zone from the `tof` site along the
unit beam (zone centres at +-19.69 degrees) and reports the hit distance along it, plus noise: so
ranges are radial. We measured it on floor returns in four recordings: read as radial, every pixel
of every row and column gives the same sensor pitch (2.4 to 2.9 degrees more downward than
`frames.tof` says, columns within 0.5 degrees); read as axial, the answer changes by 2 to 3 degrees
between rows and columns. So the simulated sensor is radial, and a radial range read as axial is
1 / (cos elevation x cos azimuth) too long off-axis: 6 % at the bottom row's centre, up to 12.7 %
at the corners.

**What we tried.** Your replay bench (`maploc/examples/replay.rs`) on two sessions recorded from
the simulator (4 and 13 keyframes: walk, stop, walk, in one apartment), `--set
project.range_is_axial=false` against the default, scoring each occupied cell of the exported grid
by its signed distance to the nearest real surface (we have the layout). With the simulator's
truth as the odometry (so only the sensor model differs):

| Session | Model | Occupied cells | Mean signed distance to the surface (+ in front, - inside) | p10 / p90 |
| --- | --- | --- | --- | --- |
| 1 (4 keyframes) | axial | 44 | -0.4 cm | -2.9 / +2.0 |
| 1 | radial | 41 | +2.6 cm | -0.5 / +7.1 |
| 2 (13 keyframes) | axial | 225 | -1.6 cm | -5.2 / +1.6 |
| 2 | radial | 152 | +0.1 cm | -4.0 / +3.2 |

The sign changes between the sessions and the differences are 1 to 2 cm, so we do not ask for the
default to change. With our robot's own odometry (5 to 15 cm of frame error) radial was worse in
both sessions, and the odometry's drift is larger than the effect. The sensor's pitch (2.5, 2.7, 3
degrees) changed the means by 0.2 cm or less.

**The question.** On the real VL53L5CX, are the reported distances along the optical axis or along
the beam? If it is the datasheet's answer and axial is right on the robot, the simulator is the
part to change (its `tof.py` could report the axial component), not `maploc`; if radial, the default
costs the real duck the same 6 to 12 % off-axis. We have no measurement of the real sensor.

**What we did not do.** Two short sessions in one room; no loop closures in them (the mapper matched
2 of 13 keyframes in the longer one); the effect on a route was not measured, only the grid against
the layout.

**What we can share.** The recorder (`robots/duck/sim/probes/record_session.py`), the scorer
(`map_range.py`) and the sessions, if useful.
