# Running robotics-lab "prod" on the X3: a proposal

Asked by the operator on 2026-11-24, after the host decision: the robotics-lab stack runs on the
X3, deployed from a main checkout under `~/deploy`. The question is how to keep what we call prod
apart from the test and dev work that runs on the same box. A proposal, not built. The engine
setup is the homelab's infrastructure (agentic-ai-homelab `infra/x3/AGENTS.md`), so it goes there
for review and lands there as its script and ADR.

## What is there today (measured 2026-11-24)

- **The engine:** one Docker engine, Docker 29.7.2, the system `dockerd` (`-H fd://`, the shared
  `/run/containerd`). Its data lives in `/var/lib/docker` and `/var/lib/containerd`, which are the
  `@docker` and `@containerd` subvolumes (ADR-0011).
- **The contexts:** `default` and `dev` both point at the same socket.
- **What runs in it:** about 40 containers.
  - The deployed robotics-lab stack (`robotics-lab`: the Observatory and Mission Control).
  - `robotics-lichtblick`.
  - Flotilla's remote workers.
  - The podcast test databases.
  - The assistant UI eval.
  - A website preview.
  - About fifteen unnamed containers from other sessions' runs.
  - Our own test stacks (`robotics-lab-test`) when they run.
- **The deploy:** prod is deployed from `/work/robotics-lab/main`, against the X3 rule (deploys come
  from `~/deploy`, `/work` is the dev tree). Its data is `/work/robotics-lab/data` (1.9 GB) and its
  state is `/work/robotics-lab/state` (97 MB).
- **No rootless Docker** on the box (no `dockerd-rootless.sh`, no `rootlesskit`). The operator
  already has subuids (`marko:100000:65536`).
- **Host networking:** the stack needs the host's network. The deploy runs both containers on host
  networking at 127.0.0.1. The navigator is TCP on the host's loopback, and the gate is a Unix
  socket.

The risk is shared state. A `compose down`, a prune, a rebuild under the tag `local`, or a port
clash from any session lands on the same engine that runs prod. Nothing tells prod from test except
a project name.

## Decided (the operator, 2026-11-24, after the homelab's review)

- **Option A, with prod's own containerd.** Docker 29 keeps images in containerd's content
  store, so a second `dockerd` on the shared containerd would separate no images. It would also
  share the X3's open containerd fault (fs-verity reads, NEXT_STEPS.md). Prod gets its own
  containerd unit, with its root on `@docker-prod` and its own socket. Both units get
  `RequiresMountsFor=/var/lib/docker-prod`.
- **A wall, not only separation.** Every agent on the X3 runs as the operator's uid, so a socket
  or a folder owned by the operator keeps no agent out. The prod socket is `root:root 0600`, and
  deploys go through one sudoers-allowed script (like the mini's devengine rule) that runs
  `deploy.py` against the prod context from `~/deploy/robotics-lab`. Prod's data and state are
  owned by a service user.
- **Who builds what:**
  - The homelab writes the ADR, the setup script, the units, the subvolume part
    (workstation/storage) and the agents' recipe. The operator runs the one sudo step.
  - robotics-lab sets `network_mode: host` on every prod service, so compose creates no network,
    and fits `deploy.py` to the script's interface.
  - Image builds on the prod engine wait for the X3 maintenance window.
- **The steps:**
  1. Meanwhile, the deploy moves to `~/deploy/robotics-lab` on the current engine (independent of
     the engine).
  2. When the engine is up, the cut-over below follows.

The sections below are the proposal as reviewed; where they differ from the decision above, the
decision holds.

## What "prod" means for robotics-lab

1. **The code:** prod runs a named commit on `main`, from `~/deploy/robotics-lab`, a checkout that is
   only ever pulled. `scripts/deploy.py` builds it from `git archive`, never from a working tree.
2. **The engine:** prod runs on an engine of its own, reached by one Docker context, `prod`. Nothing
   else runs there. Every dev and test job keeps using `default` and `dev`.
3. **The data:** prod's data and state live outside `/work`, under one root (proposed:
   `~/prod/robotics-lab/{data,data-archive,state}`, on `@home`). Tests never point at it. The
   installation file used by prod names it, and test stacks keep their own folders under
   `~/.cache/robotics-lab-tests`.
4. **Identity in telemetry:** `deployment.environment.name` is `prod` for that stack and `dev` for
   everything else. The Grafana dashboard shows one or the other.
5. **Changes:** prod changes only through `make deploy` and `make deploy-rollback`, after a green
   test stack on the dev engine, and with the operator's go. This is the 4c grant, made permanent
   or narrowed by the operator.
6. **Backups:** state goes into the encrypted nightly backup, and data needs an off-site store (the
   homelab's proposal, parked for the operator).
7. **Access:** prod listens on 127.0.0.1 only. The tailnet reaches it through `tailscale serve`
   (the operator's step), not a new open port.

## The engine: the options

| | A. A second rootful `dockerd` (recommended) | B. Rootless Docker for prod | C. No engine: user units | D. Same engine, rules only |
| --- | --- | --- | --- | --- |
| What | `docker-prod.service`: own socket `/run/docker-prod.sock`, own data root (a new `@docker-prod` subvolume), own containerd namespace, `--iptables=false --bridge=none` | `dockerd-rootless` under the operator (or a dedicated user) as a user unit | Observatory and Mission Control as `systemctl --user` units from `~/deploy` venvs (`uv sync --frozen`) | Keep one engine; reserve the `robotics-lab` project; agent rules forbid touching it |
| Separation | Full: images, containers, volumes, build cache, a prune on one leaves the other | Full | Full (no containers) | None: one prune or `down` away |
| Host loopback for the navigator | Yes (host network, no NAT: the reason iptables can be off) | **No**: rootless "host" networking is rootlesskit's namespace. The navigator would need a Unix socket, which is a code change | Yes | Yes |
| X3 rules | Needs one root system unit and a sudo setup step (the operator's), so an exception to "user units only" | Fits "user units only", but needs a new package (docker-rootless-extras) | Fits exactly: user units, `~/deploy` | Fits |
| Deploy we built in 4c | Unchanged; `deploy.py --context prod` | Changes (sockets, networking) | Replaced: rollback becomes `git checkout` plus `uv sync`, no images | Unchanged |
| Cost | A setup script and ADR in agentic-ai-homelab (as `mini-dev-engine-setup.sh`); about 1 GB for images | The package, the networking change, proof | Rewrites the deploy; loses the pinned image | None, and no protection |

**Recommendation: A.** It is the mini's split turned around: there the production engine is the
old one and dev got its own; here dev keeps the existing engine and prod gets the new one, so
nobody's work moves.

- With host networking only, prod's `dockerd` needs no bridge and no iptables rules. That avoids
  the known trouble of two daemons managing iptables on one host.
- A separate containerd namespace keeps the two daemons' containers apart on the shared
  containerd.
- B is the right choice if the operator wants no root daemon at all, at the cost of the navigator's
  transport.
- C is the right choice if containers are not wanted for prod.

## What A needs

1. **The operator, once, by hand:**
   - a new Btrfs subvolume `@docker-prod` mounted at `/var/lib/docker-prod`;
   - the `docker-prod.service` unit (a drop-in from agentic-ai-homelab), with `dockerd --host
     unix:///run/docker-prod.sock --data-root /var/lib/docker-prod --exec-root /run/docker-prod
     --pidfile /run/docker-prod.pid --containerd /run/containerd/containerd.sock
     --containerd-namespace robotics-prod --containerd-plugins-namespace robotics-prod-plugins
     --iptables=false --ip6tables=false --bridge=none`;
   - the socket's group: the operator's user only, not the `docker` group the agents use;
   - `systemctl enable --now docker-prod`.

   The flags are a draft and none of them has been run. The homelab's review settles them.
2. **The homelab:** the script and an ADR (the X3 runs one root daemon for prod, and why), and
   the `prod` context.
3. **robotics-lab:**
   - `deploy.py --context prod` (the default for `make deploy`);
   - the test stack on the dev engine;
   - the prod installation file and prod's data root;
   - `~/deploy/robotics-lab`;
   - a one-time move of `/work/robotics-lab/{data,state}` to the prod root (a copy, checked, then
     the old one kept until the operator says);
   - `environment: prod` in prod's telemetry block;
   - the agent rules (`docs/recipes`): never the `prod` context except through `deploy.py` and
     `deploy-verify`.
4. **The cut-over:**
   1. Deploy the current main to the prod engine.
   2. Run the smoke.
   3. Stop the old `robotics-lab` project on the shared engine; its containers are kept until the
      operator says to remove them.
   4. `tailscale serve`.
   5. Roll back by starting the old project again.

## Not covered

- How the two daemons share containerd under load, and the exact flags. These are drafts, not run.
- Whether the operator wants prod's socket readable by agents at all. The draft says no: a deploy
  then runs as the operator.
- `robotics-lichtblick`, which also belongs to robotics-lab and runs on the shared engine. It is
  not moved in this proposal.
- GPU and USB. Prod's containers need neither: the NXT link (nxt-web) and the simulators run on
  the host, outside containers.
- The DGX's role in MVP 2 (Gazebo), which has its own GPU-mode rules.
