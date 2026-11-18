# Robot file format: proposal (RFC-0014 step 0)

Status: decided 2026-11-18, all seven decisions as recommended (the operator: "All as
recommended"). Written 2026-11-18; built the same day in `control/src/mission_control/robotfile.py`
and `robots.py`, with `control/tests/test_robotfile.py` (the NXT's file keeps `takeover` empty:
nxt-web's own list applies, and its speeds are `adapter.full_speed_mps` and `full_turn_rps`).
Checked: VDA 5050 **3.0.0** (published 2026-03-18) and Open-RMF `rmf_ros2` **2.15.0**,
`rmf_api_msgs` **0.7.1**, `rmf_demos` main (2026-11-13). Sources are listed at the end.

## 1. What each spec is for

**VDA 5050** is a protocol between a fleet control and mobile robots, over MQTT with JSON
messages (order, instantActions, state, connection, factsheet, zoneSet, visualization).
The fleet control sends an order as a graph of nodes and edges; the robot reports its state.
The factsheet is a retained message in which a robot describes its type, limits and actions.

**Open-RMF** is a ROS 2 framework that schedules tasks across fleets of robots and keeps their
paths from colliding in one building. A fleet adapter connects each vendor's fleet to it; the
fleet is described by a `config.yaml` and a navigation graph, and tasks are JSON requests.

Neither spec describes a robot file the way we use one. VDA's factsheet is the closest thing.
Open-RMF's `config.yaml` is the fleet adapter's settings, not a robot description.

## 2. Field-by-field mapping

Our fields are those read by `control/src/mission_control/robots.py` (RFC-0014 §3.3.1, §3.3.2).

| Our field | VDA 5050 3.0.0 factsheet | Open-RMF | Proposal |
| --- | --- | --- | --- |
| `id` | `manufacturer` + `serialNumber` (chars A-Z a-z 0-9 _ . : -) | fleet `name` + robot name | keep ours; add optional `serialNumber` |
| `label` | none (`seriesName`, `seriesDescription` are for the type) | none | keep ours |
| `kind` | `typeSpecification.seriesName` (free text) | none | keep ours (it keys `robots/<kind>/`) |
| `adapter.*` | none (transport is fixed: MQTT topics) | `fleet_manager` block (url, user, password) | keep ours |
| `capabilities.drive.max_vx` | `physicalParameters.maximumSpeed` [m/s] | `limits.linear[0]` | borrow VDA name and unit |
| `capabilities.drive.max_vyaw` | `physicalParameters.maximumAngularSpeed` [rad/s] | `limits.angular[0]` | borrow VDA name and unit |
| `capabilities.drive.deadman_s` | none | none | keep ours |
| (new) acceleration | `maximumAcceleration`, `maximumDeceleration` (required in VDA) | `limits.linear[1]`, `limits.angular[1]` | add, optional |
| (new) size | `physicalParameters.width`, `length` [m]; `mobileRobotGeometry.envelopes2d` | `profile.footprint`, `vicinity` (circle radii) | add width and length; the URDF stays the body |
| (new) drive type | `typeSpecification.mobileRobotKinematics` (DIFFERENTIAL, OMNIDIRECTIONAL, THREE_WHEEL; extensible) | `reversible` | add, VDA name |
| `capabilities.localisation` | `typeSpecification.localizationTypes` (NATURAL, REFLECTOR, RFID, DMC, SPOT, GRID; extensible) | `reference_coordinates` (frame transform) | keep ours; its `frame` has no VDA equivalent |
| `capabilities.map` | none in the factsheet; maps are `state.maps[]` with `mapId`, `mapVersion` | nav graph, one `map` name per level | keep ours; reuse `mapId` as the name of the site frame's map |
| `capabilities.navigator.goal_kinds` | none (VDA has no goal; it has an order graph) | `task_capabilities` (`loop`, `delivery`, ...) | keep ours |
| `capabilities.navigator.conditions` | node `allowedDeviationXY`, `allowedDeviationTheta` (in the order) | none | keep ours |
| `capabilities.navigationTypes` (new) | `typeSpecification.navigationTypes` (FREELY_NAVIGATING, ...) | none | add, VDA name |
| `capabilities.recognisers` | none (VDA has `detectObject` as an action) | none | keep ours |
| `capabilities.sensors` | none | none | keep ours |
| `capabilities.guardrails` and top-level `guardrails` | `supportedZones` (BLOCKED, SPEED_LIMIT, ...); edge `maximumSpeed` | none | keep ours; see decision 4 in section 5 |
| `capabilities.skills` | `protocolFeatures.mobileRobotActions[]` (`actionType`, `actionScopes`, `blockingTypes`, `pauseAllowed`, `cancelAllowed`) | `actions` list in config; `perform_action` | keep `skills`; add VDA's `pauseAllowed`, `cancelAllowed` per skill |
| `capabilities.description` | none | none | keep ours (it names the body, RFC-0011) |
| `rates.state_hz` | `protocolLimits.timing.defaultStateInterval` [s] | `robot_state_update_frequency` [Hz] | keep ours (Hz) |
| `rates.max_state_hz` | `protocolLimits.timing.minimumStateInterval` [s] | none | keep ours |
| `lease_s`, `takeover` | none (no control lock in VDA; `operatingMode` is how a robot says it is not under fleet control) | `commission` flags (`dispatch_tasks`, `direct_tasks`) | keep ours |
| `online_after_s` | `connection.connectionState` (ONLINE, OFFLINE, HIBERNATING, CONNECTION_BROKEN) | `robot_state.status` has `offline` | keep ours (measured, RFC-0014 §3.3.1) |
| `teams` | none | none | keep ours |
| battery limits (new, optional) | `mobileRobotConfiguration.batteryCharging.criticalLowChargingLevel` etc. | `recharge_threshold`, `recharge_soc` | not now; neither robot reports a battery |

## 3. Verification of RFC-0014 §3.12's table

| # | Row | Verdict | Source and note |
| --- | --- | --- | --- |
| 1 | robot file = factsheet | **Confirmed in part.** | Factsheet: VDA 7.10. It holds type, physical limits, protocol limits, features, geometry, load. "Supported actions" is `protocolFeatures.mobileRobotActions`. Fleet `config.yaml`: rmf_demos `config.yaml`. |
| 2 | robot online = connection topic | **Confirmed.** | VDA 6.5, 7.7: ONLINE, OFFLINE, HIBERNATING, CONNECTION_BROKEN (broker's last will). Open-RMF: `robot_state.status` enum has `offline`. |
| 3 | `point` = order with one node | **Corrected.** | VDA 6.1.1: the first node must be where the robot already is and is not reported. A goal needs two nodes and one edge (start at the current pose, then the target), or the temporary start node of 6.1.3.1. |
| 4 | `go_to_place` task | **Corrected.** | `go_to_place` is an event (activity), not a task: `event_description__go_to_place.json`. Task schemas are `patrol`, `delivery`, `clean`, `zone`, `compose`. A single trip is a `compose` task with one `go_to_place` phase. |
| 5 | `go_to_object` resolved by Mission Control | **Confirmed as a design.** | Neither spec has objects or rooms. VDA zones are geometric (7.6, 6.4); Open-RMF places are waypoint names (`place.json`). Resolving is ours. |
| 6 | `go_to_area` = node inside the area | **Confirmed as a design.** | Open-RMF has a `zone` task (`task_description__zone.json`, "a named zone"); VDA has none. Not read in depth. |
| 7 | patrol = order with several nodes | **Confirmed.** | VDA 6.1.1 (node and edge lists). Open-RMF `task_description__patrol.json`: `places`, `rounds`. |
| 8 | `explore`, `inventory` = custom actions or task kinds | **Confirmed, narrower.** | VDA: any `actionType` the factsheet lists. Open-RMF: `perform_action` (`category`, `description`), registered by the adapter. VDA also has `detectObject`. |
| 9 | goal run state = state message | **Confirmed.** | VDA 7.8: `orderId`, `nodeStates`, `edgeStates`, `actionStates`, `errors`, `operatingMode`, `driving`, `paused`. Open-RMF `task_state.json`: `phases`, `active`, `status`. Battery: VDA `powerSupply`, RMF `robot_state.battery` (0 to 1). |
| 10 | progress = action states / task logs | **Confirmed.** | VDA action states (INITIALIZING, RUNNING, PAUSED, FINISHED, FAILED, RETRIABLE; 6.2.3.2). Open-RMF `task_log.json`. |
| 11 | STOP: VDA "instant action for stop or pause" | **Corrected.** | VDA has no stop action. It has `cancelOrder` and `startPause`/`stopPause` (all robots must support them) and reports an emergency stop in `safetyState.activeEmergencyStop` (MANUAL, REMOTE, NONE). Open-RMF "not used" is also wrong: the adapter's `stop()` exists, and the API has `interrupt_task` and `kill_task`. Our rule (STOP goes straight to the robot) still holds for both. |
| 12 | team goal = one order per robot / task assignment | **Confirmed in part.** | VDA orders are per robot (topic has `serialNumber`). Open-RMF `dispatch_task_request.json` exists; how a fleet adapter bids was not read. |
| 13 | site objects and areas = named places | **Confirmed as a design.** | See rows 5 and 6. |

The closing claim ("a VDA 5050 robot joins by an adapter that reads its factsheet into
`capabilities`") holds for speed, size, kinematics, localisation and actions. It does not
hold for `recognisers`, `map`, `goal_kinds` or `guardrails`: the factsheet has no field for them.

## 4. Proposed format

Idea: a `factsheet` block that is a **subset of VDA's factsheet, with VDA's names verbatim**
(camelCase, SI units), so a real VDA robot's factsheet can fill it later. Everything VDA has
no field for stays ours, in `snake_case`, beside it. The body stays the URDF (RFC-0011).

Simulated duck (`robots/duck-sim.json`):

```json
{
  "id": "duck-sim", "label": "Simulated duck", "kind": "duck",
  "adapter": {"type": "duck-sim", "gate_socket": "~/.cache/duck-sim/duck-a-gate.sock"},
  "factsheet": {
    "typeSpecification": {
      "seriesName": "Microduck", "mobileRobotKinematics": "LEGGED",
      "localizationTypes": ["NATURAL"], "navigationTypes": ["FREELY_NAVIGATING"]
    },
    "physicalParameters": {"maximumSpeed": 0.3, "maximumAngularSpeed": 1.5},
    "protocolFeatures": {"mobileRobotActions": []}
  },
  "control": {"deadman_s": 0.5, "lease_s": 20.0, "takeover": []},
  "capabilities": {
    "recognisers": [{"name": "sim-camera", "kinds": ["fridge", "sofa"], "frame": "site"}],
    "localisation": {"frame": "site", "how": "dock"},
    "map": {"kind": "occupancy_grid", "resolution_m": 0.05},
    "navigator": {"goal_kinds": ["point", "go_to_object", "go_to_area", "explore", "inventory"],
                  "conditions": ["within_s"]},
    "guardrails": ["contact", "fall", "drop_clearance", "stuck", "time_limit", "no_go_area"],
    "sensors": []
  },
  "guardrails": [{"name": "max_speed", "mps": 0.3}],
  "rates": {"state_hz": 2.0, "map_hz": 1.0, "max_state_hz": 10.0}
}
```

LEGO NXT Shooterbot (`robots/nxt-1.json`; speeds and size are not measured yet, so absent):

```json
{
  "id": "nxt-1", "label": "NXT Shooterbot", "kind": "nxt-shooterbot",
  "adapter": {"type": "nxt-web", "url": "http://127.0.0.1:8000"},
  "factsheet": {
    "typeSpecification": {"seriesName": "LEGO NXT 2.0 (8547)", "mobileRobotKinematics": "DIFFERENTIAL"},
    "protocolFeatures": {"mobileRobotActions": [
      {"actionType": "fire", "actionScopes": ["INSTANT"], "blockingTypes": ["HARD"],
       "pauseAllowed": false, "cancelAllowed": false, "irreversible": true}]}
  },
  "control": {"deadman_s": 0.5, "lease_s": 20.0, "takeover": ["operator-laptop"]},
  "capabilities": {"guardrails": ["max_speed", "time_limit"], "sensors": []},
  "guardrails": []
}
```

**Borrowed:** the block name `factsheet` and its field names and units for type, speed,
size, kinematics, localisation, navigation type and actions; `connectionState` words for
a later `online` status; `mapId` as the map's name. **Ours:** `id`, `label`, `kind`,
`adapter`, `control` (lease, takeover, deadman: the lock is ours, RFC-0017), `rates`,
`teams`, `recognisers`, `map`, `navigator`, `guardrails`, `sensors`, `description`.
Open-RMF gives only ideas (`limits`, recharge thresholds, `perform_action`); no names are taken.

**Why:** the overlap with VDA is real but small (about 10 fields), so a full factsheet copy
would be mostly empty. Verbatim names for that small part cost nothing now, and make a VDA
adapter a copy, not a translation. The rest is what the specs lack and Mission Control needs.

## 5. Open decisions for the operator

1. **Rename the existing fields now?** Options: (a) rename `drive.max_vx` and `max_vyaw`
   into `factsheet.physicalParameters` now; (b) keep ours, map in a future VDA adapter;
   (c) accept both. Recommend (a): two robot files and their tests exist, so it is cheapest now.
2. **Case.** Options: (a) VDA names verbatim (camelCase) inside `factsheet`, snake_case
   elsewhere; (b) snake_case everywhere. Recommend (a): a copy from a real factsheet stays
   mechanical. The cost is two cases in one file.
3. **`LEGGED` for the duck.** `mobileRobotKinematics` is an extensible enum, so a new value
   is allowed, but it is not in the spec. Options: our own `LEGGED`; or omit the field.
   Recommend `LEGGED`, marked as ours in the contract.
4. **Where `max_speed` lives.** It is in `physicalParameters.maximumSpeed` and in the
   `guardrails` list. Options: keep both (one is the robot's ability, one the limit applied);
   or the guardrail may only be at or below the ability. Recommend the second as a check.
5. **`id` rule.** Ours is lower-case with dashes; VDA's `serialNumber` allows more characters.
   Recommend: keep `id`; add optional `manufacturer` and `serialNumber` only when a VDA
   robot is added.
6. **File type.** JSON (ours, VDA) or YAML (Open-RMF). Recommend JSON, unchanged.
7. **Build a VDA adapter now?** Recommend no. Only the format is in scope for step 0.

## 6. NOT VERIFIED

- VDA 5050 JSON schemas (`json_schemas/factsheet.schema`): not read; the Markdown spec was.
- VDA's `version` field value for 3.0.0 messages and whether 2.x factsheets differ: not read.
- Open-RMF navigation graph file format and the building map: not read.
- How an Open-RMF fleet adapter bids for dispatched tasks: not read.
- Whether `loop` (in rmf_demos configs) is still a task kind: no `loop` schema in
  `rmf_fleet_adapter/schemas`; a `test_Loop.cpp` exists. Not resolved.
- `go_to_area`: whether VDA 3.0.0 has anything beyond geometric zones: not found.
- The duck's and the NXT's size and speed values: not in the repo robot files or measured;
  the NXT's geometry is uncalibrated (`nxt/src/nxt_lab/config.py`). The duck's 0.3 m/s and
  1.5 rad/s come from `control/robots.sim/duck-sim.json`.
- `adapter.url` for the NXT is a placeholder; the NXT adapter is step 4 and not built.
- Open-RMF's `rmf_ros2` version 2.15.0 is the tag list's newest; the Kilted or Jazzy release
  line it matches was not checked.
- Nothing was run: no loader change, no test of either example against `RobotConfig`.

## Sources

- VDA 5050 3.0.0 spec: <https://github.com/VDA5050/VDA5050/blob/main/VDA5050_EN.md>
  (release <https://github.com/VDA5050/VDA5050/releases/tag/3.0.0>; sections cited by number).
- VDA 5050 schemas directory: <https://github.com/VDA5050/VDA5050/tree/main/json_schemas>
- Open-RMF fleet adapter integration:
  <https://osrf.github.io/ros2multirobotbook/integration_fleets.html>
- Fleet config example (`rmf_fleet`, `limits`, `profile`, `task_capabilities`, `robots`):
  <https://github.com/open-rmf/rmf_demos/blob/main/rmf_demos/config/clinic/tinyRobot_config.yaml>
  and <https://github.com/open-rmf/fleet_adapter_template/blob/main/fleet_adapter_template/config.yaml>
- Task and event schemas: <https://github.com/open-rmf/rmf_ros2/tree/main/rmf_fleet_adapter/schemas>
- RMF API schemas (`robot_state`, `task_state`, `commission`, `dispatch_task_request`, ...):
  <https://github.com/open-rmf/rmf_api_msgs/tree/main/rmf_api_msgs/schemas>
