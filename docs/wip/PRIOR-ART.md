# Prior art: what we build, and what the field already does

The operator, 2026-11-18: "are we reinventing the ocean? … note all of this in a doc where we can
check in with reality and maintain it". One row per part of the duck's brain: the established
concept and where it comes from, our status against it, the evidence, and when the row was last
checked against the code.

**Status:** `adopted` (we use the concept, named as the field names it), `partly` (we have a version
of it, with a gap written down), `ours` (a deliberate difference, with its reason), `gap` (we lack
it). **Checked:** the date the row was last compared with the code and the source; `memory` means it
is from knowledge, not yet read against the source. The "What the source suggests" column names a
concrete next step where the field's practice points to one.

**How it is kept true:**

- A fix that touches a row updates the row in the same commit (status, evidence, date).
- A new problem gets looked up here first: if the field has a name for it, the row says so before
  anything is built (stream A's loop: rank, reproduce, look up, fix, replay, batch).
- Once a month, or before a big decision, every `memory` row is read against its source.

## Navigation (Nav2 and ROS)

| Ours | The established concept | Source | Status | Evidence | What the source suggests | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| Frontier exploring (`nav/explore.py`) | Frontier-based exploration: BFS from the robot over frontier cells (an unknown cell with a free 4-neighbour), `min_frontier_size`, cost = `potential_scale` x distance - `gain_scale` x size; goals blacklisted on abort or after `progress_timeout` (30 s in the code) | Yamauchi 1997; explore_lite [`frontier_search.cpp`](https://raw.githubusercontent.com/hrnr/m-explore/noetic-devel/explore/src/frontier_search.cpp), [`explore.cpp`](https://raw.githubusercontent.com/hrnr/m-explore/noetic-devel/explore/src/explore.cpp) | adopted | rank = distance - `GAIN_PER_M` x size is explore_lite's form; ours uses the cluster's extent (bounding diagonal), not its cell count; `explore_run.failed` (`AVOID_M` 0.4 m) plays the blacklist, with 15 s no-progress (`run.Progress`) against explore_lite's 30 s; the wall filter (`WALL_M`) and the 0.6 m minimum distance are ours | explore_lite's distance is the BFS distance through the map; ours is straight-line to the nearest usable point; scoring by the A* path length would stop a frontier behind a wall winning | 2026-11-18 |
| Lethal zone and margin ring (`nav/grid.py`) | Costmap inflation: lethal, inscribed, then cost decaying exponentially with distance (`cost_scaling_factor` default 10.0, `inflation_radius` default 0.55 m) | [Nav2 inflation layer](https://docs.nav2.org/configuration/packages/costmap-plugins/inflation.html) (search summary) | partly (was adopted) | `margin_cost` falls quadratically from 100 at the lethal edge to 1 at `INFLATE_M`; its docstring says "as Nav2's inflation decays", but Nav2's decay is exponential; no inscribed level | name the shape honestly in the docstring, or try an exponential on the same replay (`margin_replay.py`); Nav2's two knobs (steepness, radius) are what we tuned as edge cost and `INFLATE_M` | 2026-11-18 |
| Remembered obstacle points (`Navigator.blocked`) | Obstacle layer: marks from sensor returns and clears by ray-tracing (`raytrace_max_range` 3.0 m default, `marking`, `clearing`, `observation_persistence`, `footprint_clearing_enabled`); a voxel layer for 3D | [Nav2 obstacle layer](https://docs.nav2.org/configuration/packages/costmap-plugins/obstacle.html), [costmap_2d guide](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/costmap_2d/) | partly | `_remember` only appends; the one removal is `forget_blocked_near` (called by hand when the start is boxed in); suspected drops are cleared when a glance sees floor (`SuspectMemory.clear`), obstacles never; stale points measured 4-21 cm off (`map_relative_error.py`) | clear a remembered point when a later depth ray passes through it to a farther return (Nav2's ray-trace clearing); never for drops (trial 3 fell) | 2026-11-18 |
| The map frame and drift | SLAM with loop closure (pose-graph optimisation); a localization mode against a saved graph with a rolling scan buffer; AMCL for particle-filter localization | [slam_toolbox](https://github.com/SteveMacenski/slam_toolbox); AMCL and Cartographer not read | partly | mapd fixes every second; belief 0.05-0.9 m off the world, mostly drifting with the map (mapd not read this pass) | slam_toolbox corrects drift when it recognises a revisited place; if mapd has no loop closure, drift between revisits is the gap to name | 2026-11-18 (source side only) |
| Turn to the path after a reflex stop, "cleared", "trapped", hold-off | Recovery behaviours (ClearEntireCostmap, ClearCostmapAroundRobot, Spin, Wait, BackUp, DriveOnHeading) under a `RecoveryNode` with a retry count (6 in the default tree), ordered by a behaviour tree | [Nav2 behavior tree walkthrough](https://docs.nav2.org/behavior_trees/overview/detailed_behavior_tree_walkthrough.html), [BT nodes](https://docs.nav2.org/configuration/packages/configuring-bt-xml.html) (search summaries) | partly | pieces exist: `forget_blocked_near` (clear around), `tight_pivot` (spin with a collision check), `MAX_REFUSALS` = 6 then "trapped" (`explore_run.py`), "stalled" after 15 s; no BackUp, no Wait, no one ordered set | one table of recoveries tried in a fixed order with a per-leg retry count, logged as one decision; BackUp is the missing one and needs a rear check the duck does not have | 2026-11-18 |
| The reflex stop | Collision monitor: a separate node on the velocity command; zones Polygon, Circle, VelocityPolygon (footprint for approach); actions stop, slowdown, limit, approach (time to collision); data from scan, point cloud, range or costmap | [Nav2 collision monitor README](https://raw.githubusercontent.com/ros-navigation/navigation2/main/nav2_collision_monitor/README.md), [node parameters](https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html) (search summary) | partly | a straight corridor (`REFLEX_HALF_W_M` 0.123 m, `REFLEX_AHEAD_M` 0.30 m, `EMERGENCY_MM` 150) checked inside `Navigator.run`'s leg loop; no slow-down zone; does not follow the path's bend; `explore_run.turn` pivots up to 8 s with one clearance check before and none per tick | take the stop out of the leg loop into one layer every velocity command passes (pivots and survey turns too); a zone that grows with speed (VelocityPolygon) and an approach zone by time to collision; the duck cannot walk below 0.2 m/s (`follow.py`), so a slow-down zone buys 0.3 to 0.2 m/s only | 2026-11-18 |
| Path following | Regulated Pure Pursuit: velocity-scaled lookahead (`use_velocity_scaled_lookahead_dist`, `lookahead_time`), curvature regulation (`regulated_linear_scaling_min_radius`), cost regulation (`cost_scaling_dist`, `cost_scaling_gain`), approach slowdown, collision look-ahead to the carrot (`max_allowed_time_to_collision_up_to_carrot`) | [Nav2 Regulated Pure Pursuit](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/) | partly (was adopted) | fixed lookahead 0.30 m, 0.15 m inside a margin; a hard turn slows to `ARC_MPS` near obstacles (`SLOW_CLEAR_M`): cost regulation in spirit; no curvature regulation, no velocity-scaled lookahead; the turn on the spot with a kick is the duck's own; `_arc_clear` is a short look-ahead | a forward look along the planned path against the grid and the drop memory, with a time to collision, instead of the arc-only check; curvature-based slowdown where the path bends | 2026-11-18 |
| A* on the cost grid | Global planners: Smac 2D (8-connected cost-aware A*), Hybrid-A* (SE2, Dubins or Reeds-Shepp), State Lattice (control sets, with a legged preset) | [Nav2 Smac README](https://api.nav2.org/nav2-jazzy/html/md_nav2_smac_planner_README.html) | adopted | `grid.plan`: 8-connected A* over cell cost x step length, Euclidean heuristic; turning room not in the plan (the planner RFC) | State Lattice lists a legged control-set preset: the first place to look for "turning room in the plan" | 2026-11-18 |

## Perception and terrain

| Ours | The established concept | Source | Status | Evidence | What the source suggests | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| Look before you step (`nav/step_check.py`) | Traversability from a robot-centric 2.5D elevation map: each cell holds height and variance, pose uncertainty is carried into it, new data is fused by Mahalanobis distance | [ANYbotics elevation_mapping](https://github.com/ANYbotics/elevation_mapping); Wellhausen and Hutter's traversability papers seen by search only | partly | `unseen_ahead`: a 0.2-0.4 m strip of the path (0.1 m half width) must be floor the sensor has seen; seen is yes or no, with no age and no uncertainty | give each seen-floor cell the belief error since it was seen: a cell seen when the belief was 0.5 m off is not "seen" in today's frame; re-look when the drift since exceeds the strip's margin | 2026-11-18 |
| Cliff check, side drops, glances | Negative-obstacle detection (holes, ditches, drops): information falls off with range faster than for positive obstacles; tilted lidar, stereo plus thermal, elevated viewpoints | [MDPI Sensors 24 07929](https://mdpi-res.com/d_attachment/sensors/sensors-24-07929/article_deploy/sensors-24-07929.pdf), [ORNL](https://impact.ornl.gov/en/publications/shape-estimation-of-negative-obstacles-for-autonomous-navigation/) (search summaries) | ours | `cliff.drop_ahead` on a 45 deg 8x8 depth sensor, 3-frame streak, `CLIFF_STOP_M` 0.60; `SuspectMemory` (below-floor ratio per cell); glances along the edge | the surveys' point (range makes drops hard) matches our 0.6 m stop distance and the look along the edge; their elevated-viewpoint idea has an analogue in raising the head | 2026-11-18 |
| Corners never seen up close | Active perception: next-best-view, utility of a candidate view as information gain against cost | [Placed et al., Active SLAM survey](https://arxiv.org/pdf/2207.00254) (abstract level) | gap | the door-frame contacts (`corner_seen.py`): the corner never seen within 5 cm | a "view the corner before the turn" candidate has the same shape as our glance, scored against its cost | 2026-11-18 (abstract only) |

## Safety and testing (autonomous vehicles)

| Ours | The established concept | Source | Status | Evidence | What the source suggests | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| The challenge course (RFC-0008) and its bar | Scenario-based testing: abstract, logical (some parameter left open) and concrete scenarios, composable | [ASAM OpenSCENARIO](https://openscenario.asam.net/ASAM_OpenSCENARIO_DSL/v2.2.0/conceptual-overview/scenario-abstraction.html) | partly | challenges 1-16 with seeds (each seed is a concrete scenario); no logical form, no parameter ranges written down | write each challenge as a logical scenario (door width, drop distance, clutter ranges) so a seed is a draw from stated ranges; no need to adopt the XML | 2026-11-18 |
| The apartment and its rooms | Operational design domain: a hierarchical taxonomy of static and dynamic operating conditions the system is designed for; aimed at level 3-4 driving systems; it does not cover how attributes are monitored | [ISO 34503:2023](https://www.iso.org/fr/standard/78952.html) via [CCAM summary](https://www.ccam.eu/new-iso-standard-regarding-specification-for-operational-design-domain/); the standard text not read | gap | the domain is implicit (one apartment, flat floor, one staircase) | a one-page attribute list: floor types, door widths, lighting, drops, doors open or closed, people and pets; with the monitoring named for each | 2026-11-18 (summary only) |
| Failures found by runs (corner cut, false drop) | Triggering conditions; scenarios in four areas (known or unknown, safe or unsafe); the goal is to shrink the known-unsafe and unknown-unsafe areas | [ISO 21448 preview](https://webstore.ansi.org/preview-pages/ISO/preview_ISO+21448-2022.pdf), [summary](https://hardwareaireview.pages.dev/articles/what-is-sotif-a-practical-guide-to-iso-21448-for-autonomous-systems-engineers) | partly | each found and fixed one by one; not catalogued as triggering conditions | one table: trigger, what the sensor or belief did wrong, the rule that now covers it, the replay that proves it | 2026-11-18 (summary only) |
| 100 % safety, 8 of 10 reached | A safety case: goals, argument, evidence; a hazard log is a required work product | [UL 4600](https://webstore.ansi.org/standards/ul/UL4600Ed2020), [overview](https://www.ansys.com/blog/ul4600-making-the-case) | gap | the bar is a number, not an argued case | claims per hazard (drop, collision, trap), each with the replay and run that is its evidence; the hazard log is the SOTIF table above | 2026-11-18 (summary only) |
| Replay before a batch (`frontier_replay`, `margin_replay`, `step_check_replay`) | Log replay and regression testing on recorded drives | AV development practice | adopted | each fix replayed on recordings before a batch | not looked up (no single source named) | memory |

## Fleet and robots

| Ours | The established concept | Source | Status | Evidence | What the source suggests | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| The robot file (RFC-0014) | VDA 5050: MQTT and JSON topics order, instantActions, state, visualization, connection, factsheet, zoneSet; orders are graphs of nodes and edges with actions. Open-RMF: a fleet adapter wraps a robot API (navigate, stop, start activity, status) and runs task kinds | [VDA 5050 main](https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md) (reads as version 3.0.0 there); [Open-RMF fleet adapter tutorial](https://osrf.github.io/ros2multirobotbook/integration_fleets_adapter_tutorial.html) (search summary) | partly | decided to borrow both; our robot file not re-read this pass | the factsheet (capabilities, limits) and state topics map to the robot file's capabilities and state; Open-RMF's four calls are a minimal robot API to match | 2026-11-18 (our side not read) |
| Robot bodies (RFC-0011) | URDF: XML of links and joints (tree only), with visual and collision models | [ROS URDF XML](https://wiki.ros.org/urdf/XML/model) (search summary) | adopted | robots/ described URDF-like (not re-read this pass) | tree-only: the duck's body fits; a closed-chain mechanism would not | 2026-11-18 (our side not read) |

## Where we differ on purpose

- **No ROS foundation** ([ADR-0001](../adr/ADR-0001-ros-aligned-foxglove.md)): ROS terms and shapes,
  our own code. Running Nav2 itself on the simulated duck, as a comparison, would reopen that
  decision; it is noted here, not decided.
- **A legged robot with a narrow depth sensor on a head**: most of the stack above assumes a lidar on
  a wheeled base. Looks (glances, look before you step) are how the duck makes up for it.

## Next

- A research pass reads each `memory` row against its source and dates it; rows whose status
  changes go to stream A's list (`EXPLORE-PROGRESS.md`).

## Research pass 2026-11-18

Read against the Nav2 docs and READMEs, the explore_lite source, the slam_toolbox and
elevation_mapping READMEs, the VDA 5050 spec, and search summaries for the standards; the duck side
against `nav/*.py`.

### Rows whose status changed

- Lethal zone and margin ring: adopted to partly. The decay is quadratic, Nav2's is exponential, and
  the docstring in `grid.py` says "as Nav2's"; there is no inscribed level.
- Path following: adopted to partly. No curvature regulation, no velocity-scaled lookahead; cost
  regulation exists in spirit (hard turns slow near obstacles).

### Other corrections to the rows

- Frontier: explore_lite's distance is a BFS distance and its size a cell count; ours is straight
  distance and cluster extent. Its blacklist timeout is 30 s, ours 15 s.
- Obstacle memory: the only removal is a hand-called clear around the robot.
- Collision monitor: zone types and actions as the README gives them; the node docs list four action
  types (stop, slowdown, limit, approach), the README three.
- Reflex: the survey turn in `explore_run.turn` has one clearance check before and none per tick.

### The three practices to adopt next for the apartment

1. Clear remembered obstacle points by ray-tracing (Nav2's obstacle layer), with drops excluded.
   Stale points of 4-21 cm are what close doorways in the margin ring and what the boxed-in
   "forget" hack papers over.
2. One independent stop layer on every velocity command, as the collision monitor is: pivots and
   survey turns included, a zone that grows with speed, an approach zone by time to collision.
3. Give seen-floor cells an age and the belief error since they were seen (elevation_mapping keeps
   a variance per cell). Look-before-you-step then re-looks when the drift since exceeds its
   margin; the belief drifts 0.05-0.9 m, which is the apartment's risk.

### Rows left at `memory`

- Replay before a batch: no single source was named, and none was looked up.

### Not verified in this pass

- Our side of the map frame (mapd), the robot file and `robots/`: not read, so those rows carry the
  date for the source side only.
- Standards (ISO 21448, ISO 34503, UL 4600) are paywalled: summaries only, not the text.
- Nav2 inflation, behaviour-tree and collision-monitor node pages came from search summaries because
  direct fetches returned 404; the collision monitor README, Smac README and the jazzy costmap and
  Regulated Pure Pursuit pages were read directly.
- AMCL, Cartographer, Wellhausen and Hutter's traversability papers, and the Open-RMF integration
  page were not read.
- Nav2's exact inflation formula was not read from source code; "exponential" is the docs wording.
