# Deployment notes: where each part runs

Started 2026-11-24 from the operator's direction: what runs next to the robots and what runs on
a remote machine shapes how the parts are set up, packaged and connected. That is an input to
MVP 2's architecture. These are notes for an RFC, not a decision. The parts that are decided are
marked.

## The environments

| Name | Where | What | Status |
| --- | --- | --- | --- |
| dev | the worktrees on the X3, the shared Docker engine | development, test stacks, simulator jobs | exists |
| staging | the X3's separate engine (homelab ADR-0013), from a root-owned main checkout through a sudoers script | the stable stack the operator uses with the robots | engine installed 2026-11-24; the cut-over is [STAGING-CUTOVER.md](STAGING-CUTOVER.md) |
| prod | a remote machine, for example a Hetzner VPS of its own, separate from the podcast VPS | what does not need to be near a robot | an idea for later (the operator, 2026-11-24) |

**Decided (2026-11-24):** the X3 is staging, dev is the worktrees and the shared engine, and prod
comes later. The telemetry environments are `dev`, `staging` and `prod`.

## The placement rule

A part runs **next to the robot** (the edge) when it does any of these:

- touches hardware;
- is on a robot's safety path;
- needs low latency to the robot.

Otherwise it can run **remote**.

| Part | Edge or remote | Why |
| --- | --- | --- |
| Robot links (NXT USB and Bluetooth, the duck's ssh forwards) | edge | hardware and the LAN |
| The gate, the navigator, robotd, mapd | edge | the control loop; Unix sockets and loopback today |
| STOP | edge, always | a stop must not depend on the internet; the robot's own deadman is the backstop |
| Simulators (MuJoCo, NXT kinematic) | edge (the X3) | CPU, and the same sockets as a robot |
| Gazebo, model training | the DGX (its robotics GPU mode) | GPU |
| Mission Control | edge today; remote only after the control path is designed for a network | it drives robots |
| The Observatory (run viewer) | remote candidate | read-only, shareable, always on |
| Run data | written at the edge, replicated remote | the replica doubles as the off-site copy |
| Telemetry stores, dashboards | the homelab (the mini) | exists |

## What it changes in the architecture (for MVP 2)

- **Connections:** today the navigator is TCP on 127.0.0.1 and the gate is a Unix socket. A part that
  moves needs a transport that crosses machines, with authentication: the tailnet plus a token, or
  mTLS. This is RFC-0025's connector territory. Loopback stays the fast path at the edge.
- **Packaging:**
  - Edge parts are host processes or host-network containers next to devices.
  - Remote parts are ordinary containers with published ports behind TLS.
  - One image per part, built by CI rather than on the X3, which removes the X3 build hold for
    good.
- **Data flow:**
  - Runs are written at the edge and pushed or synced to prod, one-way, so prod never writes
    edge data.
  - The Observatory index is built where the viewer runs.
  - Retention runs at the edge, after the backup.
- **Identity and access:**
  - A remote viewer needs real users or tokens and a public name.
  - The edge stays tailnet-only.
  - The `actions` tokens Mission Control has now are the start.
- **Configuration:** the installation file is per machine already (an edge file and a remote file).
  The placement of each part becomes explicit in it, not implied by 127.0.0.1.
- **Observability:** every part carries `deployment.environment.name` and a host kind, so the
  dashboards split dev, staging and prod.

## Decided for MVP 2 (the operator, 2026-11-24)

1. **Mission Control stays at the edge.** A remote page reaches it through an authenticated link
   (the tailnet and a token, the cut-over's `tailscale serve`); it never drives robots across the
   internet, and STOP never depends on it.
2. **Run data: the edge pushes finished runs to prod, one-way (rsync).** A finished run does not
   change; prod never writes edge data. The restic copy stays the backup, not the replica.
   Freshness: minutes are enough for a viewer.
3. **The remote viewer is tailnet-only, shared by link.** Public access (real users, a public
   name) is not in MVP 2.
4. **Images are built by GitHub Actions and pushed to a registry (GHCR); the edge pulls them.**
   Staging and prod run the image CI tested, and no image is built on the X3.
5. **The VPS is decided when the Observatory actually goes remote,** not before; the homelab
   sizes it then. It is off the robots' critical path.

## Not covered

- Prices, which are unchecked.
- The Pi augmentation module (MVP 2's own edge host for the NXT): it is one more edge machine
  under the same rule.
