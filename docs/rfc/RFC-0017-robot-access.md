# RFC-0017 — Robot access: who may watch, who may drive, and one driver at a time

**Status:** Accepted, revision 2 (2026-11-18). Built: §5 step 1 (the gate library,
`duck/src/duck_lab/gate.py`, 6a39053) and step 4's `nxt-web` side (`/api/lock`,
`nxt/src/nxt_lab/lock.py`, 7056d97; Mission Control's NXT adapter is built, `control/src/mission_control/nxt.py`,
tested against `nxt-web --fake`; file upload and delete pass the lock too since 1ded610, config and
connect stay open; nxt-web's own page takes the lock and a command with no session is now refused,
"no lease, no motion", the hw_* script that drives over HTTP carries a session and was not run)
and step 2
(the gate stands in front of RFC-0014's fake robot, `control/`, eb6a560: its tests run the real
rules) and step 3 (`duck-gate`, `duck/src/duck_lab/gate_proxy.py`, e3aaa54: the socket proxy in
front of the simulator's `robotd`, the navigator's robot socket a setting, and the three
scenarios, which `make sim-gate-scenarios` runs on the real simulator: all pass, 2026-11-18).
Not built: the real duck's gate on its computer (RFC-0014 step 8), the EV3, pairing.
**Builds on:** [RFC-0014](RFC-0014-mission-control.md) (§3.3.3 the exclusive control lock, §3.8
safety, §3.9 access, §3.10 swarm),
[RFC-0003](RFC-0003-robot-interface.md) (one robot interface, the deadman),
[RFC-0002](RFC-0002-robot-brain.md) (several robots, §3.6 situation rules, STOP never goes through
a planner), [RFC-0001](RFC-0001-nxt-web-ui.md) (`nxt-web`, a client that already exists),
[ADR-0015](../adr/ADR-0015-scenario-runner.md) (scenarios as tests).
**Serves:** RFC-0014 §5 question 3 (where the NXT's lock lives, now closed, §3.2) and §3.3.3's
pointer to this RFC for ejection between different people's clients.

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

RFC-0014 gave one lock and one operator. It does not say how a client gets the right to drive a
robot, what happens when the clients belong to different people, or what stops a client from going
around the lock. This RFC does that for every robot kind (Lego NXT, Lego EV3, the duck, the
simulator) with one model.

### 1.1 How this revision came about

Revision 1 (a first draft, same day) had the full machinery: key pairs, TLS, pairing with a
six-digit check, roles, mDNS discovery, a fencing token in every command. The operator reviewed it
and approved its 12 open questions with the recommendations given. An independent review (the
advisor, a stronger model) then went through it against the code. The operator, on seeing it: "Take
the advisor version, all is good feedback." Six of the 12 recommendations are replaced by the
advisor's, and the rest of the machinery is cut from the first version (§3.9). Where the two differ
this text follows the advisor. What changed, in one list:

- STOP now ends the lease (§3.4).
- The fencing token is gone: the lease is bound to the connection (§3.3).
- On the duck the gate is the one door for our clients, not a security boundary (§3.2).
- The lease is 10 to 30 seconds, not the deadman time (§3.3).
- No `open_stop` flag: STOP from any connection, always (§3.4).
- The NXT's lock lives in `nxt-web` now (§3.2).
- Keys, TLS, the six-digit check, mDNS, roles, several owners and the idle cap wait (§3.9).
- The claim that the gate refuses `fire` from an agent is dropped (§3.8).

### 1.2 Words used

| Word | Meaning here |
| --- | --- |
| client | Anything that sends commands or watches: Mission Control, `nxt-web`, the navigator, an agent over MCP, a script, another person's laptop |
| gate | The one process in front of a robot that every command of our clients passes (§3.2) |
| connection | One client's open link to the gate; a reconnect is a new connection |
| lease | The right to drive one robot, bound to a connection |
| holder | The connection that has the lease now |
| deadman | The robot's own watchdog: no command for a short time stops the motors (RFC-0003 §2.3) |
| lease id | A whole number that grows with every lease, for the log and `gate.who` (§3.3) |

## 2. Goals and non-goals

### 2.1 Goals

- One driver per robot, enforced where our clients cannot go around it.
- A crashed, frozen or disconnected holder never leaves a robot driven or locked for ever, and a
  holder that wakes up late cannot act.
- While a client holds a robot, a peer cannot eject it. Only an allowed owner can take a robot, and
  that is recorded and announced.
- STOP is never refused to anyone.
- The same model for the NXT, the EV3, the duck and the simulator, with Mission Control, `nxt-web`,
  the navigator, an agent and a script all being plain clients.
- One client may hold many robots (a swarm); many clients may run in one room.
- Small: what the home lab needs now is built; what a room of strangers needs is designed (§3.9)
  and waits.

### 2.2 Non-goals

- **Not a security product.** The tailnet is the authentication in the home lab (RFC-0014 §3.9).
  The gate is the one door for our clients, so that they cannot drive the same robot by mistake.
  It is not a boundary against a program that opens the robot's own socket (§3.2).
- **Not a replacement for physical safety.** A power switch, a hand on the robot and the robot's
  own deadman and obstacle stops stay (RFC-0003 §2.3, RFC-0014 §3.8).
- **No new accounts or cloud.** No sign-in service, no server owned by anyone.
- **No code of ours on the duck in v1** (RFC-0002's non-goal). The duck's gate runs beside the
  navigator, not on the duck.
- **No ROS, no MQTT broker, no VDA 5050 stack now.** §4 says what we borrow; RFC-0014 §3.12 holds
  the VDA 5050 plan.
- **Not RFC-0014's goal runs or planner.** A goal run is a client that holds a lease.

## 3. Proposal

### 3.1 The gate, and the dev / home-lab mode

The check lives in **one process in front of each robot**, the gate: it is where our clients'
commands pass, so a client that asks for the robot is refused there and not in its own code.

```text
 Mission Control   nav server   nxt-web   agent (via MC)   script
        \              |           |            |            /
         '----- JSON-RPC (RFC-0003 shapes, unchanged) + gate.* -----'
                                   |
                                THE GATE      lease, who, takeover, stop, log
                                   |
                       the robot's own interface
                                   |
                                the robot
```

In v1 the gate runs in **dev / home-lab mode**: no pairing, no keys. A client says who it is in its
first message, `hello {client: "mission-control"}`, and the tailnet is the trust (RFC-0014 §3.9).
The lease is still enforced in full. This is the mode the first build ships in (§5).

The gate is a **pass-through**. It checks, then forwards the call unchanged (RFC-0003's method
shapes are not touched). It never resends a command and never holds the last one: the robot's
deadman has to see silence when the holder goes silent. The gate adds a few methods of its own:
`gate.acquire`, `gate.release`, `gate.who`, `gate.takeover`. Reading (state, map, the stream) and
STOP pass without a lease.

**The protocol's number** (RFC-0018 §5.3, phase 5): `protocol: 1` is in `gate.who`, in every other
`gate.*` reply, in a refusal's `data` and in the answer to `hello`; the robot's own replies are
the robot's and carry none. A client reads it at its `hello` (`robotgate.check_protocol`): a
missing number is 0, accepted with one warning; a newer number is refused, both numbers said. A
change that adds a field keeps the number; one that changes or removes meaning raises it.

### 3.2 Where the gate lives, per robot

| Robot | The gate | What it is, and is not |
| --- | --- | --- |
| Duck (simulator) | A socket proxy in front of the simulator's `robotd` socket, with its own socket in `~/.cache/duck-sim/`; the navigator's robot socket path becomes a setting (`nav/run.py` hard-codes `duck-a.sock`) | A **test fixture**: the simulator's sockets are plain files, any process can open them |
| Duck (real) | The same proxy, on the computer that runs the navigator (RFC-0014 §3.7), not on the duck | The **one door for our clients**: Mission Control, the nav server, agents, scripts. **Not a security boundary**: the duck has other doors that stay (Pollen's app and WebRTC, the HF relay, the gamepad, `autod`; `mapd` also connects to `robotd`'s socket). RFC-0002 §3.6 handles them: the navigator watches `robot.state`'s `move.source` and `autonomous`, and when another source drives, the gate emits `someone_else_drives` and stops and reports |
| NXT | `nxt-web`'s `Controller` (`nxt/src/nxt_lab/web.py`), which gets the lock now (`/api/lock`) | The only process on the link. `nxt/README.md`: "Only one program at a time may talk to the brick. A second connection on the same `/dev/rfcomm0` (or USB) scrambles replies". Mission Control's NXT adapter drives through `nxt-web`'s `/api/drive` and so passes the same lock. This closes the open part of RFC-0014 §5 question 3 |
| EV3 | The same shape: the process that owns its link | Not designed; waits for the EV3's own interface (RFC-0014 §3.7) |
| Fake robot (RFC-0014 §3.7) | The same gate library in front of the fake | So tests run the real rules |

**Not required:** that `robotd`'s socket be readable only by the gate's user. It would break `mapd`
(unverified) and RFC-0002's v1 non-goal "no code of ours on the duck". The gate is a convention
that all of *our* programs follow because they have no other way to reach the robot.

**Who holds the lease.** The process that sends `robot.move` holds it. For a duck goal that is the
nav server (RFC-0014 §3.7): it acquires at `goal.start` and releases at the end. Mission Control's
manual drive acquires in its own name. The `lock` field of `GET /robots/{id}` (RFC-0014 §3.3.3)
mirrors what `gate.who` says; it is not a second lock. For the NXT, Mission Control's adapter
and `nxt-web` both go through the Controller's lock.

### 3.3 The lease

- **Bound to the connection.** The gate is both the lock and the resource, so no token is sent in
  commands: the lease belongs to the connection that acquired it, and a command on any other
  connection is refused. A frozen client's old connection is refused because its lease expired; if
  it reconnects it is a **new session** and must acquire again, which works only if the robot is
  free.
- **Acquire.** `gate.acquire` on a free robot gives the lease. On a held robot it is refused with
  who holds it and since when ("driven by mission-control since 14:02").
- **Expire.** The lease lasts 10 to 30 seconds without a motion command or a keepalive from the
  holder. The gate judges by its own clock, not the client's. When it ends, the gate stops the
  robot (§3.4's stop) and the robot is free.
- **Release on disconnect.** If the connection closes, the lease is released at once and the robot
  is stopped. A crash of the holder frees the robot in the time it takes the socket to close, not
  in 10 seconds; expiry is for a client that is frozen with the socket still open.
- **Release.** `gate.release` by the holder: stop, then free.
- **Why 10 to 30 seconds, not the deadman time.** The deadman (0.5 s) is the *safety* stop and runs
  on the robot (RFC-0003 §2.3). The lease only decides *when someone else may take over* and
  whether a Wi-Fi hiccup loses a goal. At 0.5 s any hiccup would lose the goal and the robot.
- **A lease id** grows with every lease, for the log and `gate.who`. Clients do not send it back.
- **Watching needs no lease** and no pairing: state, map and stream are open to any connection
  (RFC-0014 §3.3.3).
- **One client, many leases.** A lease is per robot; a client holds several (§3.5.3).

**Peers cannot eject.** There is no way for a client to take a robot another client holds, short
of `gate.takeover`, which only some clients may call.

**Takeover.** `gate.takeover` is allowed to the client names in a config file (the operator's own
clients). It stops the robot, ends the holder's lease with the reason `taken_over_by <name>`, tells
the old holder at once (a `lease_lost` event), gives the new caller a lease, and writes the record:
who, from whom, when. The operator's rule, 2026-11-18: **a borrowed robot's owner may take it
back, and among owners of different robots nobody ejects anybody.** That is the whole policy for
a room: the list of takeover-allowed names is per robot, and each person's own laptops are on the
list of their own robots only.

### 3.4 STOP latches

A STOP is accepted **from any connection, always**, with or without a lease, and is logged with the
connection's name. A STOP **ends the holder's lease** with the reason `stopped_by <who>`. The
holder's next motion command is refused with that reason, and it must acquire again, which clears
it.

Why it latches: the navigator resends `robot.move` at 10 Hz (`duck/src/duck_lab/nav/run.py`) and
`nxt-web` every 200 ms, so a STOP that only stopped the motors would last one tick. RFC-0014 §3.8
already requires the goal run to be `cancelled` after a STOP; this gives it the way to know.

**The gate's stop, everywhere a lease ends** (STOP, release, expiry, disconnect, takeover): on the
duck it is `robot.stop`, then an explicit zero `robot.move`. `robotd` keeps the last request after
its deadman fired, and `mapd` then never sees a stop, so the zero move is needed. On the NXT it is
the Controller's stop, then the deadman.

**No flag to refuse a STOP.** A refused STOP risks a collision; an unwanted one stands the robot
still. The cost is that anyone on the tailnet can stop a robot; every STOP is in the log with the
name that sent it.

**Is a stop for anyone wise?** Yes. The norms treat a stop as a function that must not wait for
permission: an industrial robot's emergency stop works in every mode, and the enabling device is
stop-on-release, not a go (§4: from memory and a manual, the standard's text not read). VDA 5050's
`cancelOrder` and `startPause` are instant actions (read).

### 3.5 The scenarios

#### 3.5.1 Five laptops, five robots, one room (v1 and later)

*In v1:* each robot has its gate; a laptop's client asks for a robot, gets it if free, and a second
laptop is refused with who holds it. Nothing else keeps laptop 4 away from robot 3 except that
robot 3 is held. Everyone on the tailnet sees all five robots and who drives which. That is
adequate for the home lab, and it is not "you drive only your robot".

*Later* (when a second person with a laptop shows up): pairing. A robot accepts a client on a
console command plus a **pairing code**, issues the client a random secret kept in a file, and
the client sends it in `hello`. The gate keeps the paired list. Then laptop 4 is refused at
`hello` on robot 3. It is called a pairing code, not a "six-digit check": without a key agreement
(§3.9) a displayed number checks nothing.

#### 3.5.2 Three ducks, three laptops

Each duck has its own gate. Laptops A, B and C run Mission Control. A drives duck 1; B drives
duck 2; C drives duck 3, or none. C asks for duck 1 and A is away: C is on duck 1's takeover list
(the operator's laptops are), takes it, it is recorded, A is told, duck 1 stops before C's first
command. A friend's laptop D is on no list.

#### 3.5.3 One laptop, several robots (a swarm)

A goal run for a team (RFC-0014 §3.4.4) runs in the nav server, which acquires **one lease per
robot, in the order of the robot ids**, so two runs cannot each hold half a team and wait for the
other. If one acquire fails the run releases the ones it took and fails with the name of the
robot that was held. Losing one lease interrupts that robot's part; the run decides about the rest
(RFC-0014 §3.4). The idle cap, if it ever comes (§3.9), applies to manual drive only, never to a
goal run's lease.

#### 3.5.4 A crashed laptop

Its connection closes; the gate stops the robot and frees it at once. If the laptop froze and the
socket stays open, the lease expires in 10 to 30 s and the same happens. A laptop that wakes up
after that is on a dead lease: its next command is refused, it reconnects, it is a new session.

#### 3.5.5 The operator takes over

Mission Control calls `gate.takeover` from a takeover-allowed name. The robot stops, the old
holder is told, the new lease starts. The record is in the gate's log and on RFC-0014 §3.2's event
stream.

#### 3.5.6 A running goal that loses its lease

The nav server reports lease loss on RFC-0014 §3.2's event stream, and RFC-0014's situation
rules decide the state: a **takeover** makes the goal run `interrupted`; a **STOP** makes it
`cancelled`.

#### 3.5.7 An agent over MCP

An agent is Mission Control's client, so it drives through Mission Control's lease and Mission
Control enforces its limits (§3.8). It can watch, drive, run goals and STOP; it cannot take over,
because it is on no takeover list.

### 3.6 The log

The gate writes a **jsonl log** beside its config: lease acquired, refused (and why), released,
expired, taken over, stopped by (name), `someone_else_drives`. It is forwarded to Mission
Control's event stream (RFC-0014 §3.2). The log is the record the operator asked for.

### 3.7 Containers

mDNS does not cross Docker bridge networks, so **discovery stays with Mission Control's registry**
and its robot files (RFC-0014 §3.3.2); host networking is an extra, not a plan. A client's secret
(§3.5.1, later) becomes a mounted secret. The NXT bridge stays on the host, with the Bluetooth.

### 3.8 Safety

- **Lease loss stops the robot** (§3.4). The deadman stays as the backstop if the gate dies or the
  link breaks.
- **No lease, no motion** through the gate.
- **A stale holder is refused** because its lease is bound to a connection that is gone or dead
  (§3.3).
- **STOP from anyone, latching** (§3.4).
- **Our own gate cannot see the other doors of the duck.** The gate stops *our* clients from
  fighting; Pollen's app or a gamepad can still move the duck. RFC-0002 §3.6 is the rule for that:
  watch `move.source`, stop and report.
- **The NXT's 0.5 s deadman** rests on robotd-lite (RFC-0003 §2.3), **which has not yet been
  checked on the real brick** in this RFC's work (hardware test `nxt/tests/hw_deadman.py`).
- **Fire** is irreversible (RFC-0003 §2.3, RFC-0014 §3.8) and **"an MCP agent may not fire" is
  enforced by Mission Control**: the agent is Mission Control's client, and Mission Control does
  not pass `fire` to it. The gate does not do it; revision 1 wrongly said it did. An agent's
  identity lives in Mission Control's per-client tokens (RFC-0014 §3.9) until an agent is a direct
  client of a gate.
- **The gate failing is safe**: no gate, no commands from us, so the deadman stops the robot.

### 3.9 What is cut from v1, and what comes when

The threat is a stale or second client of ours on a trusted tailnet, not a stranger. Revision 1
built machinery for the stranger. Cut from v1:

| Cut | Why it waits | When it comes |
| --- | --- | --- |
| Key pairs and TLS | The tailnet is the authentication. Python's `ssl` cannot generate keys or certificates: that needs the `openssl` binary or the `cryptography` package, so it is a **dependency decision** (revision 1 wrongly said "TLS from the standard library") | When a second person brings a laptop: a per-client random secret issued at pairing, sent in `hello` |
| The six-digit check | Without a key agreement it is just a pairing code | With pairing, called a pairing code |
| mDNS discovery | Does not cross Docker bridges (§3.7); the registry already lists robots | If a room needs it |
| The `watch` role, any roles | Watching is open to any connection (RFC-0014 §3.3.3) | With pairing, if needed |
| Several owners' lists, `gate.request` | A config list of takeover-allowed names does it now; ask-and-release has no user yet | Later, with the room |
| The idle cap | Manual drive only, if kept (§3.5.3) | Only if forgotten laptops hold robots |
| Unpair, physical reset | Irrelevant until keys exist | With pairing |
| The fencing token | The gate is the lock and the resource; the connection-bound lease does the job (§3.3) | Not needed |
| The `open_stop` flag | STOP always (§3.4) | Not needed |

## 4. What fits which standard

"Verified" means I fetched the page or a search result for it (the sources are in §7). "Memory"
means I did not read it. Where the page itself was blocked or paywalled I say so. The table is
revision 1's research; the "our concept" column now reads against the smaller v1.

| Standard | What it gives | Our concept it matches | Status |
| --- | --- | --- | --- |
| Bluetooth pairing and bonding | Keys made at pairing, stored by bonding "to form a trusted device pair"; a ceremony (passkey, numeric comparison) | Pairing and its list (later, §3.5.1) | Verified (SIG page; numeric comparison from search results) |
| Bluetooth, who may connect | Nothing beyond the bond; the page does not address access control | None: the lease is ours | Verified (absence) |
| ISO 10218 single point of control | Only specified devices, such as the pendant, may enable the robot to start | One driver; others locked out while it holds | Partly: a manufacturer's manual, not the standard |
| ISO 10218 enabling device, emergency stop | A hold-to-run switch; stops work in every mode | STOP from anyone; lease loss stops | Memory |
| ISO 3691-4, IEC 61508 | A safe state on loss of control or link | The deadman, the stop on lease loss | Memory, no claim beyond that |
| VDA 5050 fleet control | One fleet control assumed; no second one described; orders rejected as outdated or when another is active; `cancelOrder`, `startPause` | One controller by construction; STOP as an instant action | Verified (text, in part) |
| VDA 5050 operating mode | Automatic, semi-automatic, manual, service, teach-in (names only) | Not used | Verified (names only) |
| Open-RMF fleet adapter | One adapter per fleet; the fleet manager controls the robots | One controller by construction | Verified |
| ROS 2 / DDS-Security | PKI authentication, per-topic permissions signed by a CA, encryption; no exclusive control | The later secret and takeover list | Verified (design article); tutorials blocked |
| MQTT ACLs (Mosquitto) | `read`, `write`, `readwrite`, `deny` per topic and user | Says who may, not who does | Verified |
| MAVLink 2 signing | A shared 32-byte key; a timestamp that must grow per link; no per-GCS exclusivity | The later secret | Verified |
| MAVLink operator control | A GCS requests or releases control; status broadcast; the holder says whether takeover needs permission | The lease, `lease_lost`, takeover | Search results of pull requests only; spec not read |
| DJI binding | One aircraft, one bound remote; binding a new one unbinds the first | One holder | Forum threads, search results |
| Leases and fencing tokens | A lease expires; a growing token checked by the resource refuses a stale holder | The lease (§3.3). The token is cut because lock and resource are one process | Verified (Kleppmann) |
| Robot vacuums | Not researched; from memory the vendor's cloud account decides | The model we do not want | Memory |

### 4.1 Notes

- **Bluetooth.** Pairing "is performed to establish keys which can then be used to encrypt a
  link"; bonding is storing them. The SIG page says nothing about who may connect once paired, so
  Bluetooth gives a pairing ceremony and not a lease. The NXT's exclusive link is the one in
  `nxt/README.md` (a second connection scrambles replies), and the brick has its own on-brick
  pairing confirmation (from the coordinator's review; the brick's firmware not read by me).
  Lego's default passkey 1234 is from search results of LEGO's help pages.
- **ISO 10218.** A manufacturer's manual describes "single point of control" as limiting the robot
  start so that only specified devices, such as the teach pendant, can enable the robot. The
  standard itself is paywalled and not read; the concept matches ours: one chosen source of
  control, others locked out while it holds.
- **VDA 5050.** The text read speaks of one "fleet control" and has no rule for a second. What keeps
  a second one out in practice is the MQTT broker, a deployment matter.
- **Open-RMF.** One adapter per fleet; the fleet manager is what controls the robots (read).
- **ROS 2.** DDS-Security has authentication, per-topic access control and encryption, and says
  nothing of exclusive control. The SROS2 tutorial pages were blocked; I read the design article.
- **MAVLink.** Signing refuses replays by timestamp and has no per-GCS exclusivity. The
  operator-control command appears in search results of pull requests; the released spec not read.
- **As a whole:** the industrial and fleet world get one controller by **construction**; drone and
  hobby links by **binding**; none has many equal clients on one network, so the lease bound to a
  connection is ours.

## 5. Order

The first build, the smallest slice:

1. **A gate library, stdlib only, with a fake clock:** a per-connection lease; acquire, release,
   who, takeover; a STOP from anyone that ends the lease; release on disconnect; expiry on silence;
   pass-through of RFC-0003 methods; the jsonl log; takeover allowed to the client names in a
   config file.
2. **In front of RFC-0014's fake robot**, so Mission Control's lock (RFC-0014 step 1) is this one.
3. **A socket proxy in front of the simulator's `robotd`**, with its socket in `~/.cache/duck-sim/`,
   the navigator's robot socket path made configurable, and three tests through the scenario
   runner (ADR-0015):
   a. a second navigator is refused;
   b. the first navigator is killed: the robot stops and is free;
   c. a client frozen, then resumed, is refused.
4. **The lease in `nxt-web`'s Controller** with `/api/lock`; Mission Control's NXT adapter uses it.

**Later, each its own step, when a second person shows up with a laptop:** pairing with a secret and
a pairing code, roles, discovery, `gate.request`, the idle cap; the real duck's gate on its
computer (RFC-0014 step 8); the EV3.

## 6. Alternatives considered

- **A lock in the client library only.** Rejected: a program that does not use it bypasses it. The
  operator's rule is "built in".
- **A lock service (a server everyone asks).** Rejected: a new thing that must be up; the gate is
  the lock and the check in one.
- **Rely on Bluetooth alone** (one connection at a time). Rejected: the duck and the simulator are
  not on Bluetooth, and a link limit gives no takeover or record. It stays a useful extra for the
  NXT.
- **A broker with ACLs** (MQTT, as VDA 5050 does). Rejected for now: a new server to run; an ACL
  decides who may, not who does.
- **ROS 2 / DDS-Security.** Rejected now (RFC-0014's ROS-shaped terms, no ROS foundation).
- **Last-writer-wins.** Rejected: it is "two things drive the same robot", one after the other.
- **One shared password per robot.** Rejected: it cannot tell clients apart.
- **A fencing token in every command** (revision 1). Rejected after review: the gate is both lock
  and resource, so binding the lease to the connection does the same with no change to RFC-0003's
  method shapes.
- **Key pairs and TLS now** (revision 1). Rejected after review: a home lab on a tailnet, and
  Python's `ssl` cannot make keys or certificates (§3.9).
- **A gate that makes `robotd`'s socket private** (revision 1). Rejected after review: it would
  break `mapd` (unverified) and RFC-0002's "no code of ours on the duck".
- **A flag to refuse STOP from unpaired clients** (revision 1's `open_stop`). Rejected: a refused
  STOP risks a collision.

## 7. Discussion

- 2026-11-18, revision 1: written after the operator widened question 3 of RFC-0014 (the quotes in
  §1). The operator approved its 12 open questions with the recommendations given.
- 2026-11-18, revision 2: the advisor's review (checked against the code, e.g.
  `duck/src/duck_lab/nav/run.py` and `nxt/README.md`) replaced six of the recommendations (lease
  length, no `open_stop`, the pairing and keys timing, the duck's gate and how the NXT is
  protected, what the first build is, the discovery mechanism) and cut the rest of the machinery
  from v1. The operator: "Take the advisor version, all is good feedback." Status: Accepted.
- **The 12 questions, as answered:**
  1. Lease: 10 to 30 s plus release on disconnect.
  2. Pairing: none in v1 (dev mode); a console command and a pairing code later.
  3. Watching: open to any connection in v1.
  4. STOP: no flag; always accepted.
  5. Hand-over: ask-and-release only; `gate.request` deferred.
  6. Idle cap: deferred; manual drive only if kept.
  7. Owners: a config list of takeover-allowed client names in v1; several owners later.
  8. The NXT around the bridge: Bluetooth visibility off after pairing, plus the on-brick
     confirmation (not a passkey change), **tested on hardware, not yet done**.
  9. Keys and transport: none in v1; a per-client secret later; the stdlib-TLS claim corrected.
  10. The duck's gate: the one door for our clients, not a boundary.
  11. A lost owner key: a physical reset; irrelevant until keys exist.
  12. RFC-0014: edited now (another writer does it).
- **Sources I fetched and read** (summarised by the fetch tool, not read line by line):
  [Kleppmann on leases and fencing](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html);
  [VDA 5050 text](https://raw.githubusercontent.com/VDA5050/VDA5050/main/VDA5050_EN.md) (the
  GitHub page was truncated; the raw text answered only in part: no "master control" wording, one
  fleet control, order-rejection reasons, three instant actions);
  [ROS 2 DDS-Security design](https://design.ros2.org/articles/ros2_dds_security.html);
  [Mosquitto configuration](https://mosquitto.org/man/mosquitto-conf-5.html);
  [MAVLink 2 message signing](https://mavlink.io/en/guide/message_signing.html);
  [Bluetooth SIG, pairing part 1](https://www.bluetooth.com/blog/bluetooth-pairing-part-1-pairing-feature-exchange/);
  [Open-RMF fleet adapters](https://osrf.github.io/ros2multirobotbook/integration_fleets.html).
- **Known only from search results** (page not read): the MAVLink operator-control command (pull
  requests in [mavlink-devguide](https://github.com/mavlink/mavlink-devguide/pull/556) and
  [ArduPilot/mavlink](https://github.com/ArduPilot/mavlink/pull/382)); ISO 10218 "single point of
  control" (a [Denso manual](https://www.manualslib.com/manual/254821/Denso-Rc5.html?page=23));
  Lego's passkey ([LEGO help](https://www.lego.com/en-sg/service/help-topics/article/connecting-your-lego-mindstorms-ev3-to-bluetooth));
  DJI's single binding ([forum](https://forum.dji.com/thread-287629-1-1.html),
  [mavicpilots](https://mavicpilots.com/threads/link-second-remote-control.115990/)); SROS2's
  permissions files ([ROS 2 access controls](https://docs.ros.org/en/iron/Tutorials/Advanced/Security/Access-Controls.html),
  blocked when fetched).
- **Not verified:** the text of ISO 10218-1/-2 and ISO 3691-4 (paywalled); whether the NXT or EV3
  refuse a second Bluetooth controller beyond what `nxt/README.md` says of the serial link; the
  on-brick pairing confirmation and Bluetooth-visibility behaviour on the real brick; robotd-lite's
  0.5 s deadman on the real brick; whether `mapd` would break if `robotd`'s socket were private;
  robot vacuum practice; whether MAVLink operator control is in the released spec.

## 8. Open questions

All twelve of revision 1 are answered (§7). Left:

1. **The takeover list's format**: a per-robot file of client names beside the gate's config. A
   name is only a label in dev mode, so this is a convention until a secret exists (§3.9).
   Recommend: a plain file, one name per line.
2. **The hardware test for the NXT** (visibility off after pairing, the on-brick confirmation, a
   second host refused) and the check of robotd-lite's deadman on the real brick. Needs the
   operator at the brick. Recommend: before step 4 is called done.
3. **Whether `mapd` reads `robotd`'s socket in a way a proxy would change.** Answered in step 3
   (2026-11-18): `mapd` is not behind the gate; it keeps reading `robotd`'s own socket, and mapped
   normally in all three scenarios while the navigators drove through the gate. The takeover
   list is a plain file, one name per line (question 1), as `duck-gate --takeover-names` reads it.
