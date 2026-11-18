# RFC-0017 — Robot access: who may watch, who may drive, and one driver at a time

**Status:** Proposed (2026-11-18), for the operator's review
**Builds on:** [RFC-0014](RFC-0014-mission-control.md) (§3.3.3 the exclusive control lock, §3.8
safety, §3.9 access, §3.10 swarm),
[RFC-0003](RFC-0003-robot-interface.md) (one robot interface, the deadman),
[RFC-0002](RFC-0002-robot-brain.md) (several robots, STOP never goes through a planner),
[RFC-0001](RFC-0001-nxt-web-ui.md) (`nxt-web`, a client that already exists).
**Serves:** the open question of RFC-0014 §5 question 3 ("where the NXT's lock lives"), and
RFC-0014 §3.3.3's pointer to this RFC for ejection between different people's clients.

## 1. Why

RFC-0014 decided that one robot has one driver at a time. The operator, 2026-11-18: "we should
not allow two things to drive the same robot, so there should be some kind of exclusivity lock
built in. So that's how two things should work together, by not being allowed to work together."

Then he widened it: "It's also good, like, if people gather in a room, 5 laptops, 5 robots, and
everybody can connect only to one, and there needs to be some protocol. Like, it's already on a
Bluetooth, right, where you allow things to be paired, so we have to figure out that, like, how you
can drive only your robot you're allowed to connect to, and then while you're connected, others
cannot eject you, and I don't know what are the standards and norms, so we can think about this
beyond Lego and actually apply to ducks. What happens if I have 3 ducks? And if I have 3 laptops
running this software, how would that work? So let's expand Q3 to more generalistic way about
everything."

RFC-0014 gave one lock and one operator. It does not say how a laptop gets the right to drive a
robot in the first place, what happens when the clients belong to different people, or what stops a
client from going around the lock. This RFC does that, for every robot kind (Lego NXT, Lego EV3,
the duck, the simulator) with one model.

### 1.1 Words used

| Word | Meaning here |
| --- | --- |
| client | Anything that sends commands or watches: Mission Control, `nxt-web`, an agent over MCP, a script, another person's laptop |
| gate | The one process in front of a robot that every command passes (§3.2) |
| key | A client's or a robot's secret, with its public half, that proves who it is (§3.1) |
| pairing | A robot accepts a client once, on an explicit action; the robot writes it down |
| role | What a paired client may do: `watch`, `drive`, `owner` |
| lease | The right to drive one robot, for a short time, renewed by the holder |
| token | A number that grows with every lease; every command carries it (§3.4) |
| holder | The client that has the lease now |
| deadman | The robot's own watchdog: no command for a short time stops the motors (RFC-0003 §2.3) |

## 2. Goals and non-goals

### 2.1 Goals

- One driver per robot, enforced where no client can go around it.
- A client drives only a robot that accepted it. In a room of five laptops and five robots, each
  laptop drives only its own.
- While a client holds a robot, no peer can eject it. Only the robot's owner can force a handover,
  and that is recorded and announced.
- A crashed, asleep or disconnected holder never leaves a robot driven or locked for ever, and a
  holder that wakes up late cannot act.
- STOP is never refused to anyone who is paired.
- The same model for the NXT, the EV3, the duck and the simulator, with Mission Control, `nxt-web`,
  an agent and a script all being plain clients.
- One client may hold many robots (a swarm); many clients may run in one room.

### 2.2 Non-goals

- **Not a full security product.** The aim is the home lab and a room of friends: a stranger on the
  same Wi-Fi, a stale client and a mistaken click, not a state-level attacker. The keys and the
  checks are real; a penetration test is not part of this RFC.
- **Not a replacement for physical safety.** A power switch, a hand on the robot and the robot's own
  deadman and obstacle stops stay (RFC-0003 §2.3, RFC-0014 §3.8).
- **No new accounts or cloud.** No sign-in service, no server owned by anyone. The robot holds its
  own list (the way a Bluetooth device does).
- **No ROS, no MQTT broker, no VDA 5050 stack now.** §4 says what we borrow; RFC-0014 §3.12 holds the
  VDA 5050 plan.
- **Not RFC-0014's goal runs or planner.** A goal run is a client that holds leases.

## 3. Proposal

### 3.1 Identity, pairing and roles

**Identity.** Each robot and each client has an id (a short name) and a key pair. The robot's key
is made on its first start and never leaves it; a client's key is made on its first start and kept
in a file readable only by its user (mode 600). An id is a label; the key is the proof. Two
laptops with the same id are two different clients if their keys differ.

**Pairing.** A robot accepts a client once, by an explicit action at the robot, the way two
Bluetooth devices bond:

1. The owner opens a pairing window on the robot (on the duck, a button or its console; on the
   NXT, EV3 and simulator, a command at the gate's own console; a window lasts 60 seconds and
   closes by itself).
2. A client asks to pair. Both sides show the same six digits; the person at the robot says yes.
3. The robot stores the client's public key, name, role and time in its **paired list** (a file at
   the gate, mode 600). From then on the client proves itself with its key; there is no password.

The **first** client to pair with a fresh robot is its **owner**. A robot has one or more owner
keys; the operator may give a second laptop the owner role (§3.6). Unpairing is by an owner, or by
a physical reset on the robot, which clears the list and the owner.

**Roles.**

| Role | May |
| --- | --- |
| `watch` | read state, the map and the stream; send STOP |
| `drive` | everything `watch` may, and hold the lease, send drive commands and run goals |
| `owner` | everything `drive` may, and pair and unpair clients, set roles, force a takeover |

A role can carry limits as well as rights: a paired client may be refused `fire` (RFC-0014 §3.8),
and that refusal is kept in its entry in the paired list. This is how "an MCP agent may not fire"
becomes a property of the agent's pairing instead of a rule each client must remember (§3.7).

### 3.2 Where it lives: the gate

The check lives in **one process in front of each robot**, the gate, because only a check that every
command passes cannot be bypassed. Clients do not enforce it; they only ask.

```text
 Mission Control   nxt-web   agent (MCP)   script   other laptop
        \             |          |            |         /
         '------ authenticated JSON-RPC (RFC-0003 shapes + gate.*) ------'
                                  |
                               THE GATE      identity, paired list, roles,
                                  |          lease, token, stop, log
                                  |
                      the robot's own interface
                                  |
                              the robot
```

| Robot | The gate | What must be true for it to be the only way in |
| --- | --- | --- |
| Duck (real) | A small process on the duck's computer in front of `robotd`. `robotd` is Pollen's upstream daemon and stays unchanged | `robotd`'s socket is readable by the gate's user only, and nothing else listens on a network |
| Duck (simulator) | The same gateway, in front of the simulator's `robotd` | The same |
| NXT | The bridge: the companion computer that owns the Bluetooth link. `nxt-web` becomes a client of it | The brick is paired over Bluetooth with the companion computer only (see §8, question 8) |
| EV3 | The same, on the computer or small board that owns its link | The same |
| Fake robot (RFC-0014 §3.7) | The same gateway in front of the fake, so tests cover the real rules | n/a |

The gate adds a few methods to the robot interface of RFC-0003: `gate.pair`, `gate.acquire`,
`gate.renew`, `gate.release`, `gate.takeover`, `gate.who`, `gate.unpair`. Every motion method
(`robot.move`, `robot.skill`, a goal call) carries the **token** of the caller's lease. The gate
refuses it unless the caller is authenticated, the token is the current one, and the lease has not
expired. Reading and STOP carry no token.

Mission Control's `POST /robots/{id}/lock` and its sisters (RFC-0014 §3.3.3) become thin calls to
these methods. The `lock` field of `GET /robots/{id}` is what `gate.who` says.

### 3.3 Exclusive control: the lease

- **Acquire.** A paired client with the `drive` role asks `gate.acquire`. If no one holds the robot,
  it gets a lease and a token. If someone holds it, it is refused with who holds it and since when
  ("driven by Anna's laptop since 14:02").
- **Renew.** Every accepted drive command renews the lease. A holder that is not driving sends a
  keepalive, `gate.renew`, at a third of the lease time.
- **Expire.** A lease with no renewal expires after its time (§8, question 1). On expiry the gate
  itself sends the robot a stop. The robot is then free.
- **Release.** The holder says `gate.release`. The gate stops the robot and frees it.
- **One client, many leases.** A lease is per robot. A client may hold several (§3.5.3).
- **Watching needs no lease** (RFC-0014 §3.3.3). It needs a pairing (§8, question 3).
- **Idle cap.** A holder that renews but sends no motion for ten minutes loses the lease and the
  room is told, so a forgotten open laptop does not hold a robot all afternoon (§8, question 6).

**Peers cannot eject.** A second `drive` client that wants the robot may *ask* (`gate.request`): the
holder sees "Ben asks for duck-2" and may release. Nothing else. There is no auto-grant in this
version (§8, question 5).

**Only an owner can force.** `gate.takeover` needs an owner key. The gate stops the robot, ends the
holder's lease with the reason `taken_over_by <name>`, tells the old holder at once (a `lease_lost`
event, and the old holder's page says so), gives the new holder a fresh lease and a higher token, and
writes the record: who, from whom, when, why. Takeover is for one operator with several of his own
clients, as RFC-0014 §3.3.3 says. It is the only way anyone is ever ejected.

### 3.4 The token: a stale holder cannot act

A lease alone is not safe. A laptop can freeze for ten seconds (it sleeps, a debugger stops it, the
Wi-Fi stalls), wake up, and still believe it holds the robot. The remedy named in the distributed
systems literature is a **fencing token**: a number that grows every time the lock is granted,
which the guarded resource checks and refuses when it is not the latest
([Kleppmann](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)).

Here the resource and the lock service are the same process, the gate, so the check is simple:

- Every `gate.acquire` returns the next token for that robot, a whole number that never goes down. The
  gate keeps the last token on disk, so a restart of the gate does not reuse numbers.
- A new acquire always gets a new token, **even for the same client**. A holder that wakes after its
  lease expired sends an old token, and is refused with `lease_expired`, never obeyed. It must
  acquire again, and that works only if the robot is free.
- A command that carries a token that is not the current one is refused with `stale_token`, and the
  refusal is logged. This also covers a command that was in flight when a takeover happened.
- The gate does not rely on the client's clock; it judges expiry by its own.

Two limits are named, not hidden. A command the gate already passed to the robot before the lease
ended is not recalled; the robot's deadman and the stop the gate sends on expiry bound the damage
to the deadman time (0.5 s). And the token protects only if the gate is the **only** way in
(§3.2, the last column).

### 3.5 Discovery, and the scenarios

**Discovery.** Which robots are here and who drives them. Each gate announces itself on the local
network with its id, kind, label, whether a pairing window is open, and whether it is free or held
(DNS-SD over multicast DNS is the usual way; from memory, to be checked at build time). The holder's
name is shown only to clients paired with that robot. A client lists the robots here and sees its own
ones first. Mission Control's registry (RFC-0014 §3.3.2) stays the place for the home lab's known
robots; discovery adds the ones in the room.

#### 3.5.1 Five laptops, five robots, one room

Five people, five robots. Every robot is fresh or already paired with its owner.

1. Each laptop lists the five robots; all show "free" or "held".
2. Anna's laptop asks to pair with robot 3. Robot 3's owner opens the window; the digits match; Anna
   is `drive` on robot 3 and no other.
3. Anna acquires robot 3 and drives it. Robots 1, 2, 4 and 5 are driven by their own people.
4. Anna tries robot 4: refused, "not paired". Ben, paired on robot 3 as `watch`, sees Anna's robot
   but cannot drive it, and cannot eject her. He can ask for it; Anna decides.
5. Anna's laptop dies. After the lease time robot 3 has stopped and is free. Anna's laptop, back
   up, must acquire again.

#### 3.5.2 Three ducks, three laptops

Each duck has its own gate, key and paired list. Laptops A, B and C are the operator's own: each is
paired as `owner` on all three ducks.

- A drives duck 1; B drives duck 2; C drives duck 3, or none.
- C asks for duck 1 and A is away: C takes over, as an owner. It is recorded, A is told, duck 1
  stops before C's first command.
- A friend's laptop D, paired as `drive` on duck 3 only, cannot touch ducks 1 and 2, cannot eject C.

#### 3.5.3 One laptop, several robots: a swarm

A goal run for a team (RFC-0014 §3.4.4) is one client that acquires **one lease per robot**, in
the order of the robot ids, so two goal runs cannot each hold half of a team and wait for the other
(the old deadlock). If one acquire fails the run releases the ones it took and fails with the name
of the robot that was held. Each robot keeps its own token; the run sends each command with that
robot's token. Losing one lease interrupts that robot only; the run decides about the rest
(RFC-0014 §3.4).

#### 3.5.4 A crashed laptop

The holder goes silent. After the lease time the gate stops the robot and frees it; the robot's own
deadman has already stopped the motors. The log says `lease_expired`. A new holder gets a higher
token.

#### 3.5.5 The operator takes over

The operator's laptop is an owner. It calls `gate.takeover`. The robot stops; the old holder is
told; the operator holds a new lease. The record is in the gate's log and on the event stream of
RFC-0014 §3.2.

#### 3.5.6 An agent over MCP

An agent is a client with its own key, paired by the operator as `drive` or `watch`, with `fire`
refused in its entry. It may watch; it may drive and run goals if it holds the lease, with the
limits of RFC-0014 §3.8; the gate refuses `fire` from it, whatever the agent was told. It cannot
eject anyone and cannot take over.

### 3.6 Owners

A robot has an owner list, not one person: the operator's laptops are all owners of his robots. An
owner can pair and unpair clients, change roles, and force a takeover. A friend's robot has the
friend as owner, and the operator is a `drive` client on it at most. Nobody is owner of another
person's robot unless its owner pairs him as one.

### 3.7 Safety

- **Lease loss stops the robot.** When a lease ends for any reason (expiry, release, takeover) the
  gate sends the robot a stop. The deadman stays as the backstop if the gate itself dies or the
  link breaks.
- **No lease, no motion.** A robot with no valid lease receives no motion command from the gate.
- **A stale holder is refused**, by token (§3.4).
- **STOP is always accepted from anyone paired**, including `watch`, and needs no lease or token. It
  does not end the holder's lease; it stops the motors and leaves the robot stopped until the
  holder drives again (RFC-0014 §3.8). Every STOP is logged with who sent it.
- **Is that wise?** Yes, with one limit. The norms treat a stop as a function that must not wait
  for permission: industrial robots keep their emergency stop and protective stop working in every
  mode, and the enabling device is a stop-on-release, not a go (§4; the standard's text itself
  not read). The cost is that a paired nuisance can stop a robot again and again. That is why the
  paired list is the line: STOP needs only a pairing, not a role, and not a lease; and every STOP
  is in the log. Whether an *unpaired* client on the tailnet may also STOP is §8, question 4.
- **Fire is a skill with its own permission** (RFC-0003 §2.3): refused unless the client's entry
  allows it, and always an explicit call.
- **The gate failing is safe**: no gate, no commands, so the deadman stops the robot.

## 4. What fits which standard

"Verified" means I fetched the page or a search result for it in this session (the sources are in
the Discussion). "Memory" means I did not read it. Where the page itself was blocked or paywalled I
say so.

| Standard | What it gives | Our concept it matches | Status |
| --- | --- | --- | --- |
| Bluetooth pairing and bonding | Keys made at pairing, stored by bonding "to form a trusted device pair"; a ceremony (six-digit check, passkey) | Pairing, the paired list, the six-digit check | Verified (SIG page; numeric comparison from search results) |
| Bluetooth, who may connect | Nothing beyond the bond; the page does not address access control | None: the lease is ours | Verified (absence) |
| ISO 10218 single point of control | Only specified devices, such as the pendant, may enable the robot to start | One driver; the others locked out while it holds | Partly: a manufacturer's manual, not the standard |
| ISO 10218 enabling device, emergency stop | A hold-to-run switch; stops work in every mode | STOP always allowed; lease loss stops | Memory |
| ISO 3691-4, IEC 61508 | A safe state on loss of control or link | The deadman, the stop on lease loss | Memory, no claim beyond that |
| VDA 5050 fleet control | One fleet control assumed; no second one described; orders rejected as outdated or when another is active; `cancelOrder`, `startPause` | One controller by construction; the stale token in spirit; STOP as an instant action | Verified (text, in part) |
| VDA 5050 operating mode | Automatic, semi-automatic, manual, service, teach-in (names only) | Roles are different: who, not what mode | Verified (names only) |
| Open-RMF fleet adapter | One adapter per fleet; the fleet manager controls the robots | One controller by construction | Verified |
| ROS 2 / DDS-Security | PKI authentication, per-topic permissions signed by a CA, encryption; no exclusive control | Identity and keys; roles as allow rules | Verified (design article); tutorials blocked |
| MQTT ACLs (Mosquitto) | `read`, `write`, `readwrite`, `deny` per topic and user; `%u`, `%c` patterns | Roles; says who may, not who does | Verified |
| MAVLink 2 signing | A shared 32-byte key; a timestamp that must grow per link; no per-GCS exclusivity | Keys; the token (growing number, replays refused) | Verified |
| MAVLink operator control | A GCS requests or releases control; control status broadcast; the holder says whether takeover needs permission | The lease, `lease_lost` event, the ask-first handover | Search results of pull requests only; spec not read |
| DJI binding | One aircraft, one bound remote; binding a new one unbinds the first | Pairing, but ours allows many paired and one holding | Forum threads, search results |
| Leases and fencing tokens | A lease expires; a growing token, checked by the resource, refuses a stale holder | Lease and token (3.3, 3.4) | Verified (Kleppmann) |
| Robot vacuums | Not researched; from memory the vendor's cloud account decides | The model we do not want | Memory |

### 4.1 Notes on the table

- **Bluetooth.** Pairing "is performed to establish keys which can then be used to encrypt a
  link"; bonding is storing them for later. The Bluetooth SIG page says nothing about who may
  connect once paired, so Bluetooth gives us the pairing ceremony (the six-digit check is the
  numeric comparison model) and not the lease. One device holding the other at a time is a
  property of the device, not of the standard. Lego's NXT and EV3 use a default passkey of 1234
  (search results of LEGO's help pages); that default is why §3.2 puts the gate between the brick
  and everyone else. That they accept only one Bluetooth controller I could not verify.
- **ISO 10218.** The two parts (robots; robot systems) were revised in 2025. A manufacturer's manual
  describes "single point of control" as limiting the robot start so that only specified
  devices, such as the teach pendant, can enable the robot. The standard itself is paywalled and
  I did not read it; the concept, as the manual gives it, is the same as ours: one chosen source of
  control, others locked out while it holds. ISO 3691-4 (driverless industrial trucks) and
  IEC 61508 (functional safety) are from memory only; the one idea we take from them is that
  loss of the control link must lead to a safe state, which is the deadman. No claim beyond that.
- **VDA 5050.** The text read speaks of one "fleet control" and has no rule for a second.
  What keeps a second one out in practice is the MQTT broker (who may publish to the robot's
  `order` topic), which is a deployment matter. It does have orders that are rejected as outdated
  or when another order is active, which matches our stale token in spirit.
- **Open-RMF.** One fleet adapter per fleet; the adapter calls the fleet manager's API, so the
  fleet manager is the one that controls the robot (read). RMF is "one controller, by
  construction", not a lease.
- **ROS 2.** DDS-Security gives authentication (PKI), access control per topic (permissions signed
  by a CA) and encryption. It says nothing of exclusive control: two permitted nodes can both
  publish `cmd_vel`. The SROS2 tutorial pages were blocked when I tried to read them, so I read
  the design article.
- **MQTT.** An ACL is "who may read or write which topic". It decides *who may*, not *who does*.
- **MAVLink.** Signing proves a message comes from a holder of the key and refuses replays by
  timestamp; it has no per-GCS exclusivity. A request-operator-control command with a control-status
  message and a takeover permission flag appears in search results of pull requests; I did not read
  the released spec.
- **Drones and vacuums.** DJI binds an aircraft to one remote controller: binding a new one unbinds
  the first (forum threads, search results, not DJI's own documentation). Robot vacuums: not
  researched; from memory, the vendor's cloud account decides who may command, which is the model
  we do not want (no accounts, no cloud).

What the table says as a whole: the industrial and fleet world get one controller by **construction**
(a single fleet control, a single pendant, a single broker user); drone and hobby links get it by
**binding** (one paired remote); none of them has our case, many equal clients on one network, so
the lease with a token is ours, built from the distributed-systems practice and the pairing ceremony
from Bluetooth.

## 5. Order

1. **The gate as a library** (stdlib only): paired list, roles, lease, token, takeover, stop,
   log, with a fake clock for tests. Tests: stale token after a "sleep"; expiry; takeover mid-drive;
   two clients; STOP from `watch`; `fire` refused; restart keeps the token. Put it in front of
   RFC-0014's fake robot, so Mission Control's lock (RFC-0014 step 1) is this one.
2. **The duck in the simulator**: the gateway in front of the simulator's `robotd`; Mission
   Control gets its own client key (RFC-0014 §3.9's per-client tokens come here); the robot list
   shows who holds each robot.
3. **The NXT bridge**: `nxt-web` and Mission Control become clients of the same gate (RFC-0014
   step 4); the brick is paired with the companion computer only.
4. **Pairing and discovery in the page**: the six-digit check, the paired list, "ask for this
   robot", takeover with its record.
5. **The real duck and the EV3**, each behind its gate, each with its safety review (RFC-0014
   step 8).

**Waits:** a physical pairing button on the NXT (needs robotd-lite to read the brick's button),
agent keys and `fire` limits beyond one agent, a signed log kept outside the robot, and anything
about a room of strangers (key revocation lists, guest passes).

## 6. Alternatives considered

- **A lock in the client library only.** Rejected: `nxt-web` or a script that does not use it
  bypasses it. The operator's rule is "built in".
- **A lock service (a server everyone asks).** Rejected: a new thing that must be up, and a robot
  would still obey a client that skipped it. The gate is the lock service and the checker in one,
  so there is no gap between them.
- **Rely on Bluetooth alone** (the robot accepts one connection at a time). Rejected: the duck
  and the simulator are not on Bluetooth, and a link-level limit gives no owner, no roles, no
  takeover record, no token. It stays a useful extra for the NXT.
- **A broker with ACLs** (MQTT, as VDA 5050 does). Rejected for now: a new dependency and a new
  server to run; the ACL decides who may, not who does, so we would still need the lease.
- **ROS 2 / DDS-Security.** Rejected now (RFC-0014's ADR-0001 stance: ROS-shaped terms, no ROS
  foundation); the model would carry over if it arrives.
- **Last-writer-wins** (the newest client takes the robot). Rejected: it is exactly "two things
  drive the same robot", one after the other, and the operator said they must not.
- **One shared password per robot.** Rejected: it cannot tell clients apart, so no log, no
  revoking one laptop, no `fire` limit for the agent.
- **Locks held by the lease alone, no token.** Rejected: the frozen-laptop case (§3.4).

## 7. Discussion

- 2026-11-18: written after the operator widened question 3 of RFC-0014 (the quotes in §1). RFC-0014
  §3.3.3 keeps the short rule and points here.
- **Sources I fetched and read** (summarised by the fetch tool, not read line by line):
  [Kleppmann on leases and fencing](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html);
  [VDA 5050 text](https://raw.githubusercontent.com/VDA5050/VDA5050/main/VDA5050_EN.md) (a first
  fetch of the GitHub page was truncated; the raw text answered only in part: no "master control"
  wording, one fleet control, order rejection reasons, three instant actions);
  [ROS 2 DDS-Security design](https://design.ros2.org/articles/ros2_dds_security.html);
  [Mosquitto configuration](https://mosquitto.org/man/mosquitto-conf-5.html);
  [MAVLink 2 message signing](https://mavlink.io/en/guide/message_signing.html);
  [Bluetooth SIG, pairing part 1](https://www.bluetooth.com/blog/bluetooth-pairing-part-1-pairing-feature-exchange/);
  [Open-RMF fleet adapters](https://osrf.github.io/ros2multirobotbook/integration_fleets.html).
- **Known only from search results** (the page itself not read): the MAVLink operator-control
  command (pull requests in
  [mavlink-devguide](https://github.com/mavlink/mavlink-devguide/pull/556) and
  [ArduPilot/mavlink](https://github.com/ArduPilot/mavlink/pull/382)); the
  ISO 10218 "single point of control" (a [Denso manual](https://www.manualslib.com/manual/254821/Denso-Rc5.html?page=23));
  Lego's passkey ([LEGO help](https://www.lego.com/en-sg/service/help-topics/article/connecting-your-lego-mindstorms-ev3-to-bluetooth));
  DJI's single binding ([forum](https://forum.dji.com/thread-287629-1-1.html),
  [mavicpilots](https://mavicpilots.com/threads/link-second-remote-control.115990/)); SROS2's
  permissions files ([ROS 2 access controls](https://docs.ros.org/en/iron/Tutorials/Advanced/Security/Access-Controls.html),
  which was blocked when fetched).
- **Not verified:** the text of ISO 10218-1/-2 and ISO 3691-4 (paywalled); whether the NXT or EV3
  refuse a second Bluetooth controller; what the VDA 5050 text says in full on instant actions
  and operating modes; robot vacuum practice; the exact interfaces of the duck's `robotd`
  beyond RFC-0003.

## 8. Open questions

1. **How long is the lease?** RFC-0014 decided: it expires after the robot's deadman time. The
   NXT's deadman is 0.5 s over Bluetooth, which is too short for a lease that survives a Wi-Fi
   hiccup, and renewing that often costs the link (RFC-0003 §2.3: 40 % at the deadman rate).
   **Recommend:** the *motors* stop at the deadman, as now; the *lease* lasts three deadman times,
   at least two seconds, and the gate stops the robot when it ends. This changes RFC-0014's
   wording; your call.
2. **How does a robot with no button accept a pairing?** The NXT bridge, the EV3 and the
   simulator have no button for the window. **Recommend:** a command at the gate's console plus the
   six-digit check on both screens; the NXT's own button later (§5).
3. **May an unpaired client watch?** **Recommend:** discovery shows id, kind, label and free or
   held to anyone on the network; the state, map and stream go to paired clients only, any role.
   (RFC-0014 said "watching needs no lock"; it still needs no lock.)
4. **May an unpaired client on the tailnet STOP?** RFC-0014 §3.8 says STOP needs no token beyond the
   tailnet. **Recommend:** a gate flag `open_stop`, on in the home lab (as RFC-0014), off in a
   room with other people; paired clients may always STOP.
5. **Hand-over by request only, or may a holder allow auto-grant?** MAVLink lets the holder choose
   (from search results). **Recommend:** ask-and-release only now; no auto-grant until you want it.
6. **An idle cap?** **Recommend:** ten minutes with no motion command frees the robot, announced.
7. **Several owners.** **Recommend:** yes, each owner takeover recorded, so the operator's laptops
   are all owners of his robots; a friend's robot has the friend as owner.
8. **Can the brick be reached around the bridge?** The NXT's default passkey is 1234, so anyone in
   Bluetooth range might pair with the brick and bypass the gate. Unverified on this brick.
   **Recommend:** test it on the real brick before step 3 (change the passkey; check whether it
   accepts a second host while the bridge is connected), and record the result here.
9. **Keys and transport.** **Recommend:** self-signed key pairs, pinned on both sides, over TLS
   from the standard library (no new dependency); the key files mode 600; the robot's key
   shown to the client at pairing, not trusted from the network.
10. **Where the duck's gate runs.** **Recommend:** a gateway process on the duck's computer with
    `robotd`'s socket closed to everything else; upstream `robotd` untouched.
11. **A lost owner key.** **Recommend:** a physical reset on the robot (clears the paired list and
    the owner); there is no remote way back.
12. **Does RFC-0014 change?** §3.3.3's lock API becomes calls to the gate, and §3.9's per-client
    tokens become keys from step 2. **Recommend:** yes, edit those two paragraphs when this is
    accepted; not before.
