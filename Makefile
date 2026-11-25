# robotics-lab — Makefile
#
# Layered tiers, as in the operator's other projects (flotilla, eval-harness):
#   - lint / test-unit / test-duck / test-observatory / test-control / test-observatory-pages /
#     test-integration / test-observatory-image  → atomic (one project, one kind of check)
#   - ci-fast                             → what every push must pass (fast feedback)
#   - ci                                  → what every merge must pass (full gate)
#   CI (.github/workflows/ci.yml) runs these same targets.
#   - nxt-*                               → run, package and program the NXT
#   - test-hardware                       → checks against the real NXT (manual, never in CI)
#   - docs-*                              → MkDocs site (preview + strict build) and markdownlint
#
# Convention (global AGENTS.md #17): end unattended runs with an exit signal:
#   make <target>; echo "MAKE_EXIT=$?"

SHELL          := /usr/bin/env bash
.SHELLFLAGS    := -eu -o pipefail -c
.DEFAULT_GOAL  := help

# ---- Tunables ----------------------------------------------------------------

# Temporary files go to the disk, not /tmp: /tmp here is a tmpfs whose ~1M inodes every session on the
# machine shares, and it filled on 2026-11-19. Each test also removes its own folder at exit.
TEST_TMP       ?= $(HOME)/.cache/robotics-lab-tests
export TMPDIR  := $(TEST_TMP)
$(shell mkdir -p $(TEST_TMP))

PYTHON         ?= python3
VENV_DIR       ?= .venv
VENV_BIN       := $(VENV_DIR)/bin
PIP            := $(VENV_BIN)/pip
MKDOCS         := $(VENV_BIN)/mkdocs

DOCS_REQS      := requirements-docs.txt
DOCS_PORT      ?= 8765
DOCS_BIND      ?= 127.0.0.1

NXT_DIR        := apps/nxt-web
NXT_PY         := $(NXT_DIR)/.venv/bin/python
NXT_HOST       ?= 127.0.0.1
NXT_PORT       ?= 8000
NXT_LINK       ?= auto
NXT_IMAGE      ?= robotics-lab/nxt-web:dev
NXT_DATA       ?= nxt-web-data

DUCK_DIR       := robots/duck
OBSERVATORY_DIR     := apps/observatory
OBSERVATORY_IMAGE   ?= observatory:ci
CONTROL_DIR    := apps/mission-control
# every simulator target runs under this (docs/wip/DUCK-SIM-FOR-AGENTS.md): one simulator job at a time, a human's or an agent's
SIM_LOCK       := $(abspath scripts/sim-lock)
CONTROL_PORT   ?= 8060
CONTROL_STATE  ?= /work/robotics-lab/state/control

# ---- Meta --------------------------------------------------------------------

.PHONY: help
help: ## Show this help (default target)
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} \
		/^[a-zA-Z0-9_.-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)

# ---- Atomic ------------------------------------------------------------------

.PHONY: nxt-sync
nxt-sync: ## Create/refresh the NXT project's venv from its lock (uv)
	@cd $(NXT_DIR) && uv sync --frozen && echo "nxt-sync PASS"

.PHONY: control-sync
control-sync: ## Create/refresh Mission Control's venv from its lock (uv; the gate and the run format are path sources, no robot's package)
	@cd $(CONTROL_DIR) && uv sync --frozen && echo "control-sync PASS"

.PHONY: duck-sync observatory-sync libs-sync test-libs test-web
duck-sync: ## Create/refresh the duck project's venv from its lock (uv, with its dev tools: the tests need rerun-sdk)
	@cd $(DUCK_DIR) && uv sync --frozen && echo "duck-sync PASS"

# The libraries' own tests (phase 5 step 1, the architecture review of 2026-11-22): each library in its own environment, no robot's
# package installed, so a library is proven without the duck (test_import: the runner imports with none). Tests of the runner that
# need a robot (its simulator files, its profile) stay in the duck's.
LIBS_TESTS := runfile:tests/test_profile_schema.py runfile:tests/test_installation.py runfile:tests/test_truthcopy.py simhost:tests/test_simhost.py \
              runfile:tests/test_profilestore.py runfile:tests/test_observatory_paths.py gate:tests/test_gate.py runner:tests/test_gate_proxy.py \
              runner:tests/test_profile_source.py runner:tests/test_navapi_notruth.py runfile:tests/test_registration.py runner:tests/test_remote_contract.py runfile:tests/test_stops_before.py runfile:tests/test_store_anomaly.py runfile:tests/test_scenefile.py runner:tests/test_import.py runner:tests/test_navapi_calibration.py runner:tests/test_link.py runner:tests/test_navapi_clock.py runner:tests/test_no_navigator.py runner:tests/test_measure.py runfile:tests/test_linkcheck.py runfile:tests/test_retention.py runfile:tests/test_dashboard.py
libs-sync: ## Create/refresh each library's own venv from its lock (libs/runfile, simhost, gate, runner)
	@for d in runfile simhost gate runner; do (cd libs/$$d && uv sync --frozen --quiet) || exit 1; done; echo "libs-sync PASS"

test-libs: libs-sync ## The libraries' own tests, each in its own environment (no robot installed)
	@fail=0; for t in $(LIBS_TESTS); do d=$${t%%:*}; f=$${t#*:}; log=$$(mktemp); \
	  if (cd libs/$$d && uv run --frozen python $$f) >$$log 2>&1; then echo "PASS libs/$$d/$$f"; \
	  else echo "FAIL libs/$$d/$$f"; cat $$log; fail=1; fi; rm -f $$log; \
	done; [ $$fail = 0 ] && echo "test-libs PASS" || { echo "test-libs FAIL"; exit 1; }

test-web: ## The shared web library (libs/web, RFC-0024): one token file no app declares again, one three.js (standard library only; its pages' tests are the two apps')
	@for t in libs/web/tests/test_*.py; do $(PYTHON) $$t >/tmp/robotics-lab-test_web.log 2>&1 && echo "PASS $$t" \
	  || { cat /tmp/robotics-lab-test_web.log; echo "test-web FAIL $$t"; exit 1; }; done
	@echo "test-web PASS"

observatory-sync: ## Create/refresh the Observatory's venv from its lock (uv, with Playwright)
	@cd $(OBSERVATORY_DIR) && uv sync --frozen && echo "observatory-sync PASS"

.PHONY: lint
lint: ## Byte-compile every Python file of every project
	@$(PYTHON) -m compileall -q $(NXT_DIR)/src $(NXT_DIR)/scripts $(NXT_DIR)/tests \
	  $(DUCK_DIR)/src $(DUCK_DIR)/tests $(DUCK_DIR)/sim $(OBSERVATORY_DIR)/src $(OBSERVATORY_DIR)/tests \
	  $(CONTROL_DIR)/src $(CONTROL_DIR)/tests libs/runfile/src libs/gate/src libs/worldmodel/src scripts >/dev/null \
	  || { echo "lint FAIL: Python does not compile"; exit 1; }
	@uv run --no-project --quiet --with pyyaml python scripts/check_workflows.py \
	  || { echo "lint FAIL: a GitHub workflow does not parse"; exit 1; }
	@$(MAKE) --no-print-directory check-boundaries
	@echo "lint PASS"

.PHONY: check-boundaries
check-boundaries: ## Which package may import which (RFC-0018): scripts/check_boundaries.py and its self-test; part of lint
	@$(PYTHON) scripts/test_check_boundaries.py >/tmp/robotics-lab-test_check_boundaries.log 2>&1 \
	  || { cat /tmp/robotics-lab-test_check_boundaries.log; echo "check-boundaries FAIL: the checker's self-test"; exit 1; }
	@$(PYTHON) scripts/check_boundaries.py || { echo "check-boundaries FAIL: a package imports one it may not (RFC-0018 section 10)"; exit 1; }
	@echo "check-boundaries PASS"

# One line per test file: PASS, or FAIL with its output. $(1) the project dir, $(2) the test files.
define run_tests
	@fail=0; for t in $(2); do \
	  log=$$(mktemp); \
	  if (cd $(1) && uv run --frozen $(3) python $$t) >$$log 2>&1; then echo "PASS $(1)/$$t"; \
	  else echo "FAIL $(1)/$$t"; cat $$log; fail=1; fi; rm -f $$log; \
	done; exit $$fail
endef

DUCK_TESTS          := tests/test_nav.py tests/test_frames.py tests/test_recovery.py tests/test_record.py tests/test_explore.py tests/test_explore_hazards.py tests/test_cliff.py tests/test_step_check.py \
                       tests/test_world.py tests/test_miniview.py tests/test_replay.py tests/test_challenge.py tests/test_side_drops.py \
                       tests/test_world_model.py tests/test_stuck.py tests/test_site.py tests/test_guardrails.py tests/test_profile.py tests/test_plugins.py tests/test_anomaly.py tests/test_goals.py tests/test_probe_rows.py tests/test_pace.py tests/test_payload.py tests/test_camera_server.py tests/test_nav_server.py tests/test_forget_replay.py tests/test_registration_file.py tests/test_contract.py tests/test_scene_layout.py tests/test_body.py tests/test_calibration.py
OBSERVATORY_TESTS       := tests/test_env.py tests/test_duck_adapter.py tests/test_query.py tests/test_mcapio.py tests/test_reading.py \
                       tests/test_index.py tests/test_review2.py tests/test_server.py tests/test_nxt.py tests/test_depth_frames.py \
                       tests/test_kinematics.py tests/test_render_service.py tests/test_robots.py tests/test_ldraw.py \
                       tests/test_semantic.py tests/test_video_semantic.py tests/test_anomalies.py tests/test_control_proxy.py tests/test_archive.py tests/test_mcp.py
OBSERVATORY_PAGE_TESTS   := tests/test_live_page.py tests/test_store_page.py tests/test_ui.py tests/test_nxt_pages.py tests/test_replay_pages.py tests/test_export_pages.py tests/test_explore_pages.py tests/test_eye_pages.py \
                       tests/test_semantic_pages.py tests/test_anomaly_pages.py tests/test_body_pages.py tests/test_look_ui_pages.py tests/test_look_time_pages.py tests/test_look_shell_pages.py tests/test_look_confirm_pages.py tests/test_look_3d_pages.py tests/test_look_palette_pages.py tests/test_look_signals_pages.py tests/test_look_layout_pages.py tests/test_look_evidence_pages.py

CONTROL_TESTS       := tests/test_geometry.py tests/test_goals.py tests/test_sites.py tests/test_fake.py tests/test_core.py tests/test_api.py tests/test_mcp.py tests/test_duck_adapter.py tests/test_teams.py tests/test_planner.py tests/test_tokens.py tests/test_nxt_adapter.py tests/test_nxt_registered.py tests/test_robotfile.py tests/test_profile_api.py tests/test_calibration_api.py tests/test_sim_first.py tests/test_duck_real.py tests/test_telemetry.py tests/test_telemetry_hook.py

.PHONY: test-control test-duck test-observatory test-observatory-pages
test-control: control-sync nxt-sync ## Mission Control against the fake robot: rules, store, core, the HTTP API and its event stream (no simulator, no robot)
	$(call run_tests,$(CONTROL_DIR),$(CONTROL_TESTS),)
	@echo "test-control PASS"

.PHONY: telemetry-send-check
telemetry-send-check: control-sync ## Send one metric, span and log to the real Victoria stack and poll until each arrives (needs the tailnet; not in CI)
	@cd $(CONTROL_DIR) && uv run --frozen python ../../scripts/telemetry_send_check.py

.PHONY: grafana-dry grafana-import
grafana-dry: ## What grafana-import would post (the dashboard, folder robotics-lab, overwrite): no network, no token
	@$(PYTHON) scripts/grafana_import.py --dry-run
grafana-import: ## POST dashboards/robotics-lab-live.json to $$GRAFANA_HTTP_URL with $$GRAFANA_API_TOKEN (both from the environment only)
	@$(PYTHON) scripts/grafana_import.py

test-duck: duck-sync ## The duck's navigator and tools, no simulator
	$(call run_tests,$(DUCK_DIR),$(DUCK_TESTS),)
	@echo "test-duck PASS"

test-observatory: observatory-sync ## the Observatory: adapter, queries, MCAP, the API and live service
	$(call run_tests,$(OBSERVATORY_DIR),$(OBSERVATORY_TESTS),)
	@echo "test-observatory PASS"

test-observatory-pages: observatory-sync ## the Observatory's two pages in headless Chromium (OBSERVATORY_CHROMIUM, else Playwright's)
	$(call run_tests,$(OBSERVATORY_DIR),$(OBSERVATORY_PAGE_TESTS),)
	@echo "test-observatory-pages PASS"

.PHONY: test-control-page
test-control-page: observatory-sync ## Mission Control's page in headless Chromium at phone and desktop width, light and dark (the Observatory's Playwright and OBSERVATORY_CHROMIUM; control has no browser dependency)
	@for t in test_page test_robot_page test_settings_page test_calibration_page test_body_page test_body_duck_page test_nxt_page test_one_origin_page test_look_page; do log=$$(mktemp); \
	  if (cd $(OBSERVATORY_DIR) && PYTHONPATH=$(abspath $(CONTROL_DIR))/src:$(abspath libs/gate)/src uv run --frozen python $(abspath $(CONTROL_DIR))/tests/$$t.py) >$$log 2>&1; then if grep -q "^SKIP" $$log; then grep "^SKIP" $$log; else echo "PASS $(CONTROL_DIR)/tests/$$t.py"; fi; \
	  else echo "FAIL $(CONTROL_DIR)/tests/$$t.py"; cat $$log; rm -f $$log; exit 1; fi; rm -f $$log; done
	@echo "test-control-page PASS"

.PHONY: test-nxt-page
test-nxt-page: observatory-sync nxt-sync ## nxt-web's page takes, keeps and gives back the control lock, in headless Chromium against nxt-web --fake (the Observatory's Playwright; never a real brick)
	@log=$$(mktemp); \
	  if (cd $(OBSERVATORY_DIR) && uv run --frozen python $(abspath $(NXT_DIR))/tests/test_page_lock.py) >$$log 2>&1; then echo "PASS $(NXT_DIR)/tests/test_page_lock.py"; \
	  else echo "FAIL $(NXT_DIR)/tests/test_page_lock.py"; cat $$log; rm -f $$log; exit 1; fi; rm -f $$log
	@echo "test-nxt-page PASS"

.PHONY: test-unit
test-unit: nxt-sync ## The NXT web UI against the simulated brick (never moves a real robot)
	@$(NXT_PY) $(NXT_DIR)/tests/test_deadman.py >/tmp/robotics-lab-test_deadman.log 2>&1 \
	  && echo "PASS apps/nxt-web/tests/test_deadman.py" \
	  || { echo "FAIL apps/nxt-web/tests/test_deadman.py"; cat /tmp/robotics-lab-test_deadman.log; exit 1; }
	@$(NXT_PY) $(NXT_DIR)/tests/test_config.py >/tmp/robotics-lab-test_config.log 2>&1 \
	  && echo "PASS apps/nxt-web/tests/test_config.py" \
	  || { echo "FAIL apps/nxt-web/tests/test_config.py"; cat /tmp/robotics-lab-test_config.log; exit 1; }
	@$(NXT_PY) $(NXT_DIR)/tests/test_recorder_v2.py >/tmp/robotics-lab-test_recorder_v2.log 2>&1 \
	  && echo "PASS apps/nxt-web/tests/test_recorder_v2.py" \
	  || { echo "FAIL apps/nxt-web/tests/test_recorder_v2.py"; cat /tmp/robotics-lab-test_recorder_v2.log; exit 1; }
	@$(NXT_PY) $(NXT_DIR)/tests/test_recorder_sim.py >/tmp/robotics-lab-test_recorder_sim.log 2>&1 \
	  && echo "PASS apps/nxt-web/tests/test_recorder_sim.py" \
	  || { echo "FAIL apps/nxt-web/tests/test_recorder_sim.py"; cat /tmp/robotics-lab-test_recorder_sim.log; exit 1; }
	@$(NXT_PY) $(NXT_DIR)/tests/test_lock.py >/tmp/robotics-lab-test_lock.log 2>&1 \
	  && echo "PASS apps/nxt-web/tests/test_lock.py" \
	  || { echo "FAIL apps/nxt-web/tests/test_lock.py"; cat /tmp/robotics-lab-test_lock.log; exit 1; }
	@$(NXT_PY) $(NXT_DIR)/tests/test_sim.py >/tmp/robotics-lab-test_sim.log 2>&1 \
	  && echo "PASS apps/nxt-web/tests/test_sim.py" \
	  || { echo "FAIL apps/nxt-web/tests/test_sim.py"; cat /tmp/robotics-lab-test_sim.log; exit 1; }
	@$(NXT_PY) $(NXT_DIR)/tests/test_web_smoke.py >/tmp/robotics-lab-test_web_smoke.log 2>&1 \
	  && { grep -E "^SKIP" /tmp/robotics-lab-test_web_smoke.log || true; echo "PASS apps/nxt-web/tests/test_web_smoke.py"; } \
	  || { echo "FAIL apps/nxt-web/tests/test_web_smoke.py"; grep -E "^(FAIL|SMOKE)" /tmp/robotics-lab-test_web_smoke.log; cat /tmp/robotics-lab-test_web_smoke.log; exit 1; }
	@echo "test-unit PASS"

.PHONY: nxt-programs
nxt-programs: ## Compile every NXC program for the brick (nbc in Docker) into apps/nxt-web/build/
	@for p in $(NXT_DIR)/programs/*.nxc; do $(NXT_DIR)/scripts/nxc.sh $$p; done
	@echo "nxt-programs PASS"

.PHONY: test-integration
test-integration: nxt-image ## The packaged image: start it with the simulated brick, check it answers
	@mv=$$(mktemp -d); chmod 755 $$mv; \
	  cid=$$(docker run -d --rm -p 127.0.0.1::8000 -v $$mv:/observatory -e OBSERVATORY_DATA=/observatory -e NXT_DATA_OWNER=$${NXT_TEST_OWNER-$$(id -u):$$(id -g)} \
	    $(NXT_IMAGE) nxt-web --fake --host 0.0.0.0 --port 8000); \
	  trap 'docker stop $$cid >/dev/null; docker run --rm -v $$mv:/d $(NXT_IMAGE) rm -rf /d/runs; rm -rf $$mv' EXIT; \
	  port=$$(docker port $$cid 8000/tcp | head -1 | sed 's/.*://'); \
	  for i in $$(seq 1 40); do curl -fs -m 2 http://127.0.0.1:$$port/api/status >/tmp/robotics-lab-image-status.json && break; sleep 0.25; done; \
	  grep -q '"connected": true' /tmp/robotics-lab-image-status.json && grep -q '"link": "fake"' /tmp/robotics-lab-image-status.json \
	    && echo "PASS image answers: $$(cat /tmp/robotics-lab-image-status.json | head -c 120)" \
	    || { echo "FAIL image did not answer as expected"; cat /tmp/robotics-lab-image-status.json 2>/dev/null; docker logs $$cid; exit 1; }; \
	  curl -fs -m 5 -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:$$port/api/record/start >/dev/null \
	    && for i in $$(seq 1 60); do curl -fs -m 2 http://127.0.0.1:$$port/api/status | grep -Eq '"rows": [3-9]' && break; sleep 0.25; done \
	    && curl -fs -m 5 -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:$$port/api/record/stop >/dev/null \
	    && curl -fs -m 5 http://127.0.0.1:$$port/api/runs | grep -Eq '"mcap": "run-[0-9-]+\.mcap"' \
	    && echo "PASS image records a recording as an Observatory run (its .mcap is listed)" \
	    || { echo "FAIL image did not record an Observatory run"; docker logs $$cid; exit 1; }; \
	  others=$$(find $$mv -mindepth 1 ! -user $$(id -u) -printf '%u %p\n'); n=$$(find $$mv -mindepth 1 | wc -l); \
	  test $$n -gt 0 && test -z "$$others" && echo "PASS the run it wrote into a host folder is the host user's, not root's ($$n paths)" \
	    || { echo "FAIL files the image wrote into a host folder belong to someone else (ADR-0013):"; echo "$$others"; exit 1; }
	@echo "test-integration PASS"

.PHONY: test-run-compat
test-run-compat: observatory-sync duck-sync ## A run opens fully in Rerun and the Observatory (ADR-0007 Compatibility): explore9 and an NXT run imported, checked in each; Lichtblick's checks are skipped unless COMPAT_LICHTBLICK=1
	$(call run_tests,$(OBSERVATORY_DIR),tests/test_run_compat.py,)
	@echo "test-run-compat PASS"

.PHONY: perf-observatory
perf-observatory: observatory-sync ## NOT in CI: replay robots/duck/runs/phase1-run18 at 20 Hz through the writer with both pages open; prints latency, bytes per page, lock hold time
	@cd $(OBSERVATORY_DIR) && uv run --frozen python perf/perf_viewer.py $(PERF_ARGS)

.PHONY: test-observatory-image
test-observatory-image: ## the Observatory's image: build it, run it with the data read only and the host's state folder (the one index) mounted writable, check what it serves and that it cannot write the data (ADR-0012)
	@docker build -q -f $(OBSERVATORY_DIR)/Dockerfile -t $(OBSERVATORY_IMAGE) . >/dev/null
	@data=$$(mktemp -d); idx=$$(mktemp -d); state=$$(mktemp -d); mkdir -p $$data/runs $$data/scenes; \
	  (cd $(OBSERVATORY_DIR) && OBSERVATORY_INDEX=$$idx/host.sqlite uv run --frozen observatory --data $$data import tests/fixtures/explore9 --scene apartment >/dev/null) \
	    || { echo "FAIL could not import the fixture run on the host"; rm -rf $$data $$idx; exit 1; }; \
	  cid=$$(docker run -d --rm -p 127.0.0.1::8070 -v $$data/runs:/data/runs:ro -v $$data/scenes:/data/scenes:ro -v $$state:/index \
	    --user $$(id -u):$$(id -g) $(OBSERVATORY_IMAGE)); \
	  trap 'docker stop $$cid >/dev/null; rm -rf $$data $$idx $$state' EXIT; \
	  port=$$(docker port $$cid 8070/tcp | head -1 | sed 's/.*://'); \
	  for i in $$(seq 1 60); do curl -fs -m 2 http://127.0.0.1:$$port/api/v1/health >/tmp/robotics-lab-observatory-health.json && break; sleep 0.25; done; \
	  grep -q '"ok":true' /tmp/robotics-lab-observatory-health.json \
	    && curl -fs -m 5 http://127.0.0.1:$$port/api/v1/scenes | grep -q '"format":2' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/api/v1/runs | grep -q 'duck/apartment/explore9' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/api/v1/runs/duck/apartment/explore9 | grep -q '"ticks":116' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/web/three/ | grep -qi '<html' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/web/shell/shell.js >/dev/null \
	    && curl -fs -m 5 http://127.0.0.1:$$port/lib/tokens.css | grep -q -- '--warn' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/lib/vendor/three.module.js >/dev/null \
	    && curl -fs -m 5 http://127.0.0.1:$$port/lib/body/body.js >/dev/null \
	    && curl -fs -m 5 http://127.0.0.1:$$port/lib/fonts/fonts.css | grep -q 'woff2' \
	    && docker exec $$cid test -f /index/index.sqlite \
	    && mounts=$$(docker inspect -f '{{range .Mounts}}{{.Destination}}={{.RW}} {{end}}' $$cid) \
	    && echo "$$mounts" | grep -q '/data/runs=false' && echo "$$mounts" | grep -q '/data/scenes=false' && echo "$$mounts" | grep -q '/index=true' \
	    && ! docker exec $$cid sh -c 'touch /data/runs/x' 2>/dev/null \
	    && ! docker exec $$cid sh -c 'touch /data/scenes/x' 2>/dev/null \
	    && ! docker exec $$cid sh -c 'rm -rf /data/runs/duck' 2>/dev/null \
	    && test -d $$data/runs/duck \
	    && docker exec $$cid sh -c 'touch /index/probe && rm /index/probe' \
	    && test -f $$state/index.sqlite \
	    && echo "PASS Observatory image answers; the data mount is read only, the state folder (the index) is writable and shows on the host: $$(cat /tmp/robotics-lab-observatory-health.json)" \
	    || { echo "FAIL Observatory image"; cat /tmp/robotics-lab-observatory-health.json 2>/dev/null; docker logs $$cid; exit 1; }
	@echo "test-observatory-image PASS"

# ---- Composite tiers ---------------------------------------------------------

.PHONY: ci-fast
ci-fast: lint test-sim-lock test-deploy test-libs test-web test-unit test-duck test-observatory test-control ## What every push must pass (fast feedback): every project's unit tests
	@echo "ci-fast PASS"

.PHONY: ci
ci: ci-fast test-observatory-pages test-control-page test-run-compat test-integration test-observatory-image nxt-programs docs-lint docs-build ## What every merge must pass (full gate)
	@echo "ci PASS"

# ---- NXT: run and package ----------------------------------------------------

.PHONY: nxt-web
nxt-web: nxt-sync ## Serve the NXT web UI on the real robot (NXT_HOST, NXT_PORT, NXT_LINK=auto|usb|bluetooth); recordings are live in the Observatory (OBSERVATORY_DATA)
	cd $(NXT_DIR) && exec .venv/bin/nxt-web --host $(NXT_HOST) --port $(NXT_PORT) --link $(NXT_LINK) --miniview-data $(OBSERVATORY_DATA)

.PHONY: nxt-web-fake
nxt-web-fake: nxt-sync ## Serve the NXT web UI with a simulated brick (no robot needed)
	cd $(NXT_DIR) && exec .venv/bin/nxt-web --fake --host $(NXT_HOST) --port $(NXT_PORT)

.PHONY: nxt-image
nxt-image: ## Build the NXT web UI image (NXT_IMAGE); the context is the repository root (it installs libs/runfile too, ADR-0013)
	docker build -f $(NXT_DIR)/Dockerfile -t $(NXT_IMAGE) .

.PHONY: test-sim-lock
test-sim-lock: ## scripts/sim-lock's self-test: the command runs, waits for a holder, gives up after its timeout, does not wait for itself (no simulator)
	@$(PYTHON) scripts/test_sim_lock.py >$(TEST_TMP)/test_sim_lock.log 2>&1 \
	  || { cat $(TEST_TMP)/test_sim_lock.log; echo "test-sim-lock FAIL"; exit 1; }
	@echo "test-sim-lock PASS"

.PHONY: sim-gate-scenarios
sim-gate-scenarios: duck-sync ## NOT in CI: RFC-0017 step 3 on the real simulator: a second navigator refused, a killed one frees the robot, a frozen one refused after its lease (resets the simulator three times, ~6 min; nobody else may use it)
	cd $(DUCK_DIR) && $(SIM_LOCK) -- .venv/bin/python sim/probes/gate_scenarios.py

.PHONY: sim-duck
sim-duck: control-sync duck-sync ## NOT in CI: Mission Control on the real simulator: the gate, lab-nav-server and the real navigator behind the API, the duck found by its registration file and run by its own environment (resets the simulator, ~10 min; nobody else may use it); ARGS="--only point,cancel" picks scenarios
	cd $(CONTROL_DIR) && $(SIM_LOCK) -- uv run --frozen python tests/sim_duck.py $(ARGS)

.PHONY: sim-nxt
sim-nxt: control-sync nxt-sync observatory-sync ## NOT in CI: Mission Control on the NXT simulator (phase 5 item 4d unit D7): simhost starts nxt-web --sim in the apartment, a client drives it by hand through the API, hits a wall, STOP, takeover, deadman, and the run it left opens in the Observatory with the truth (no Pollen, no brick, ~1 min); ARGS="--only wall,stop" picks scenarios
	cd $(CONTROL_DIR) && $(SIM_LOCK) -- uv run --frozen python tests/sim_nxt.py $(ARGS)

.PHONY: control-run
control-run: control-sync ## Mission Control on 127.0.0.1:$(CONTROL_PORT) in the foreground with the fake robot (apps/mission-control/robots.example), state in $(CONTROL_STATE)
	@mkdir -p $(CONTROL_STATE)
	cd $(CONTROL_DIR) && exec uv run --frozen mission-control serve --robots robots.example --state $(CONTROL_STATE) --host 127.0.0.1 --port $(CONTROL_PORT)

CONTROL_ROBOTS ?= $(abspath $(CONTROL_DIR)/robots.example)
CONTROL_ENV     = MC_PORT=$(CONTROL_PORT) MC_STATE_DIR=$(CONTROL_STATE) MC_ROBOTS_DIR=$(CONTROL_ROBOTS) MC_UID=$$(id -u) MC_GID=$$(id -g)

.PHONY: control-up control-down
control-up: ## Mission Control in Docker on 127.0.0.1:$(CONTROL_PORT): robot files from $(CONTROL_ROBOTS) (the fake robot), state in $(CONTROL_STATE); waits for the health check
	@mkdir -p $(CONTROL_STATE)
	@$(CONTROL_ENV) docker compose -f $(CONTROL_DIR)/compose.yml up -d --build --wait \
	  && echo "mission-control at http://127.0.0.1:$(CONTROL_PORT)/" \
	  || { echo "control-up FAIL"; $(CONTROL_ENV) docker compose -f $(CONTROL_DIR)/compose.yml logs --tail 40; exit 1; }

control-down: ## Stop and remove Mission Control's container (the state folder stays)
	@$(CONTROL_ENV) docker compose -f $(CONTROL_DIR)/compose.yml down

# The Observatory and Mission Control from the root compose file. Ports, state folders and image tags are variables so a second stack can
# run beside one already holding :8070 (make stack-up STACK_VIEWER_PORT=8170 STACK_CONTROL_PORT=8160 STACK_TAG=test STACK_VIEWER_STATE=... ).
STACK_VIEWER_PORT  ?= $(OBSERVATORY_PORT)
STACK_CONTROL_PORT ?= $(CONTROL_PORT)
STACK_VIEWER_STATE ?= $(OBSERVATORY_STATE)
STACK_TAG          ?= local
STACK_ENV           = OBSERVATORY_PORT=$(STACK_VIEWER_PORT) OBSERVATORY_DATA=$(OBSERVATORY_DATA) OBSERVATORY_STATE=$(STACK_VIEWER_STATE) OBSERVATORY_IMAGE_TAG=$(STACK_TAG) \
	MC_PORT=$(STACK_CONTROL_PORT) MC_STATE_DIR=$(CONTROL_STATE) MC_ROBOTS_DIR=$(CONTROL_ROBOTS) MC_IMAGE_TAG=$(STACK_TAG) OBSERVATORY_CONTROL=http://mission-control:8060 \
	OBSERVATORY_UID=$$(id -u) OBSERVATORY_GID=$$(id -g) MC_UID=$$(id -u) MC_GID=$$(id -g)

.PHONY: stack-up stack-down
stack-up: ## The Observatory ($(STACK_VIEWER_PORT)) and Mission Control ($(STACK_CONTROL_PORT)) together from compose.yml, both on loopback, memory capped; waits for both health checks
	@mkdir -p $(OBSERVATORY_DATA)/runs $(OBSERVATORY_DATA)/scenes $(STACK_VIEWER_STATE) $(CONTROL_STATE)
	@$(STACK_ENV) docker compose up -d --build --wait \
	  && echo "observatory at http://127.0.0.1:$(STACK_VIEWER_PORT)/  mission-control at http://127.0.0.1:$(STACK_CONTROL_PORT)/" \
	  || { echo "stack-up FAIL"; $(STACK_ENV) docker compose logs --tail 40; exit 1; }

stack-down: ## Stop and remove the stack's two containers (project robotics-lab); the state folders and the images stay
	@$(STACK_ENV) docker compose down

# The deployed platform (phase 5 item 4c, docs/wip/DEPLOY.md): a NAMED commit, built from `git archive` (not this checkout's files), the host network, the
# installation file's mounts, the Observatory proxying Mission Control at /control/, the solo Observatory project taken down, then a smoke. DEPLOY_ARGS passes
# flags on (--project, --viewer-port, --installation, --tokens, ...; scripts/deploy.py --help); the defaults are the deployed stack's.
.PHONY: deploy deploy-dry deploy-rollback deploy-smoke test-deploy sim-deployed
deploy: ## Deploy the commit COMMIT=<sha|ref> (no default): build it, replace what runs, record it, run the smoke; DEPLOY_ARGS="..." for flags
	@test -n "$(COMMIT)" || { echo "make deploy COMMIT=<sha>: a deploy names what it deploys"; exit 2; }
	@$(PYTHON) scripts/deploy.py up --commit $(COMMIT) $(DEPLOY_ARGS)

deploy-dry: ## What `make deploy COMMIT=<sha>` would do, printed, none of it done
	@test -n "$(COMMIT)" || { echo "make deploy-dry COMMIT=<sha>"; exit 2; }
	@$(PYTHON) scripts/deploy.py up --commit $(COMMIT) --dry-run $(DEPLOY_ARGS)

deploy-rollback: ## Deploy the commit that ran before the current one (the record of scripts/deploy.py)
	@$(PYTHON) scripts/deploy.py rollback $(DEPLOY_ARGS)

deploy-smoke: observatory-sync ## The smoke alone: health of both, /lib/, the pages in headless Chromium, against the stack that runs (DEPLOY_ARGS for its ports)
	@$(PYTHON) scripts/deploy.py smoke $(DEPLOY_ARGS)

test-deploy: ## scripts/deploy.py's self-test: a named commit's files, the overlay and its mounts, the record and the rollback, a dry run changing nothing (no Docker)
	@$(PYTHON) scripts/test_deploy.py >$(TEST_TMP)/test_deploy.log 2>&1 \
	  || { cat $(TEST_TMP)/test_deploy.log; echo "test-deploy FAIL"; exit 1; }
	@echo "test-deploy PASS"

sim-deployed: control-sync duck-sync observatory-sync ## NOT in CI: the deployed Mission Control (a container) drives the simulated duck from the page (phase 5 item 4c unit C2; resets the simulator, ~10 min); COMMIT=<sha> ROOT=<folder> PROJECT=<not robotics-lab> VIEWER_PORT= CONTROL_PORT=
	cd $(CONTROL_DIR) && $(SIM_LOCK) -- uv run --frozen python tests/sim_deployed.py --commit $(COMMIT) --root $(ROOT) --project $(PROJECT) --viewer-port $(VIEWER_PORT) --control-port $(CONTROL_PORT)

.PHONY: viewers viewers-down
viewers: observatory-up ## The viewers on loopback: the Observatory (:8070), Rerun (:9090) and Lichtblick (:8090) (ADR-0002, ADR-0005)
	@OBSERVATORY_DATA=$(OBSERVATORY_DATA) scripts/viewers.sh up

viewers-down: observatory-down ## Stop the viewers started by make viewers
	@scripts/viewers.sh down

ENGINE ?= mujoco
VIDEO_SIZE ?= 1280x720
.PHONY: video
video: observatory-sync ## A run as a video with the robot's model (ADR-0017): make video RUN=<robot/scene/run> [ENGINE=mujoco] [OUT=file.mp4, default the state folder's videos/] [VIDEO_SIZE=1280x720]
	@test -n "$(RUN)" || { echo "video: RUN=<robot/scene/run> is needed"; exit 2; }
	cd $(OBSERVATORY_DIR) && uv run --frozen observatory --data $(OBSERVATORY_DATA) video $(RUN) --engine $(ENGINE) --size $(VIDEO_SIZE) \
	  -o $(abspath $(or $(OUT),$(OBSERVATORY_STATE)/videos/$(subst /,-,$(RUN))-$(ENGINE).mp4))

MUJOCO_PYTHON ?= /work/pollen/microduck_rl/.venv/bin/python
.PHONY: robots rerun-export
robots: ## The robots' descriptions (RFC-0011): the duck's URDF and meshes from Pollen's MuJoCo model (MUJOCO_PYTHON)
	$(MUJOCO_PYTHON) robots/duck/from_mjcf.py

LDRAW_DIR ?= $(HOME)/opt/ldraw/ldraw
.PHONY: robots-lego
robots-lego: observatory-sync ## The LEGO robots' descriptions (RFC-0011): the EV3 Track3r and Spike3r (LDraw OMR 31313) and the NXT Shooterbot, URDF and meshes by robots/ldraw/from_ldraw.py; needs the LDraw parts library in $(LDRAW_DIR) (ldraw.org complete.zip, unpacked in ~/opt/ldraw)
	@test -f $(LDRAW_DIR)/LDConfig.ldr || { echo "robots-lego: no LDraw library in $(LDRAW_DIR); unpack ldraw.org's complete.zip into ~/opt/ldraw or set LDRAW_DIR"; exit 2; }
	LDRAW_DIR=$(LDRAW_DIR) $(OBSERVATORY_DIR)/.venv/bin/python robots/ldraw/from_ldraw.py ev3-track3r ev3-spike3r nxt-shooterbot

rerun-export: duck-sync ## A run in Rerun with the robot drawn as itself (RFC-0011): make rerun-export RUN=<robot/scene/run> [OUT=file.rrd]
	@test -n "$(RUN)" || { echo "rerun-export: RUN=<robot/scene/run> is needed"; exit 2; }
	@test -d robots/$(firstword $(subst /, ,$(RUN)))/meshes || { echo "no meshes for that robot: make robots"; exit 2; }
	$(DUCK_DIR)/.venv/bin/python $(OBSERVATORY_DIR)/src/observatory/export/rerun_robot.py $(OBSERVATORY_DATA) $(RUN) \
	  robots/$(firstword $(subst /, ,$(RUN)))/robot.urdf $(abspath $(or $(OUT),$(OBSERVATORY_STATE)/rerun/$(subst /,-,$(RUN)).rrd))

# The OBSERVATORY_* names; the MINIVIEW_* names of before the rename (RFC-0018) are read when the new ones are not set.
OBSERVATORY_PORT ?= $(or $(MINIVIEW_PORT),8070)
OBSERVATORY_DATA ?= $(or $(MINIVIEW_DATA),/work/robotics-lab/data)
OBSERVATORY_STATE ?= $(or $(MINIVIEW_STATE),/work/robotics-lab/state/miniview)
RENDER_PORT ?= 8071
.PHONY: render-up
render-up: observatory-sync ## The render service on 127.0.0.1:$(RENDER_PORT), in the foreground (ADR-0017): reads $(OBSERVATORY_DATA), writes videos to $(OBSERVATORY_STATE)/videos; the Observatory offers Export video when started with OBSERVATORY_RENDER=http://127.0.0.1:$(RENDER_PORT)
	cd $(OBSERVATORY_DIR) && OBSERVATORY_DATA=$(OBSERVATORY_DATA) OBSERVATORY_STATE=$(OBSERVATORY_STATE) exec uv run --frozen observatory render-serve --host 127.0.0.1 --port $(RENDER_PORT)

OBSERVATORY_ENV   = OBSERVATORY_PORT=$(OBSERVATORY_PORT) OBSERVATORY_DATA=$(OBSERVATORY_DATA) OBSERVATORY_STATE=$(OBSERVATORY_STATE) OBSERVATORY_UID=$$(id -u) OBSERVATORY_GID=$$(id -g)

.PHONY: observatory-up observatory-down
observatory-up: ## The Observatory's service in Docker on 127.0.0.1:$(OBSERVATORY_PORT), data from $(OBSERVATORY_DATA) (RFC-0009)
	@mkdir -p $(OBSERVATORY_DATA)/runs $(OBSERVATORY_DATA)/scenes $(OBSERVATORY_STATE)
	@$(OBSERVATORY_ENV) docker compose -f $(OBSERVATORY_DIR)/compose.yml up -d --build --wait \
	  && echo "observatory at http://127.0.0.1:$(OBSERVATORY_PORT)/" \
	  || { echo "observatory-up FAIL"; $(OBSERVATORY_ENV) docker compose -f $(OBSERVATORY_DIR)/compose.yml logs --tail 40; exit 1; }

observatory-down: ## Stop the Observatory's service
	@$(OBSERVATORY_ENV) docker compose -f $(OBSERVATORY_DIR)/compose.yml down

# The names before the rename (RFC-0018), kept for one release: the same targets under their old names.
.PHONY: viewer-up viewer-down test-viewer
viewer-up: observatory-up ## (alias of observatory-up, until the next release)
viewer-down: observatory-down ## (alias of observatory-down, until the next release)
test-viewer: test-observatory ## (alias of test-observatory, until the next release)

.PHONY: nxt-image-run
nxt-image-run: nxt-image ## Run the image on this machine with the robot's USB/Bluetooth devices, port on 127.0.0.1 only; recordings go to $(OBSERVATORY_DATA) as Observatory runs
	@mkdir -p $(OBSERVATORY_DATA)/runs $(OBSERVATORY_DATA)/scenes
	docker run --rm -it -p 127.0.0.1:$(NXT_PORT):8000 -v $(NXT_DATA):/data -v $(OBSERVATORY_DATA):/observatory -e OBSERVATORY_DATA=/observatory -e NXT_DATA_OWNER=$$(id -u):$$(id -g) \
	  $$(test -d /dev/bus/usb && echo --device /dev/bus/usb) \
	  $$(for d in /dev/rfcomm*; do test -e $$d && echo --device $$d; done) \
	  $(NXT_IMAGE) nxt-web --host 0.0.0.0 --port 8000 --link $(NXT_LINK)

# ---- Hardware (manual, needs the robot; never in CI) -------------------------

.PHONY: test-hardware
test-hardware: nxt-sync ## Checks on the real NXT: sensors, link speed, the robotd deadman, stop-on-SIGTERM, stop-on-connect (MOVES the tracks briefly: lift the robot; stop nxt-web first)
	@read -r -p "Robot lifted and nxt-web stopped? [y/N] " ok; test "$$ok" = y || { echo "test-hardware SKIPPED"; exit 1; }
	$(NXT_DIR)/scripts/nxc.sh $(NXT_DIR)/programs/robotd.nxc
	$(NXT_PY) $(NXT_DIR)/tests/hw_read_sensors.py
	@test -e /dev/rfcomm0 && $(NXT_PY) $(NXT_DIR)/tests/hw_link_speed.py || echo "SKIP hw_link_speed.py: no /dev/rfcomm0"
	$(NXT_PY) $(NXT_DIR)/tests/hw_deadman.py
	$(NXT_PY) $(NXT_DIR)/tests/hw_stop_on_sigterm.py
	$(NXT_PY) $(NXT_DIR)/tests/hw_stop_on_connect.py
	@echo "test-hardware PASS"

# ---- Docs --------------------------------------------------------------------

$(VENV_DIR):
	$(PYTHON) -m venv $(VENV_DIR)
	$(PIP) install --quiet --upgrade pip

.PHONY: docs-install
docs-install: $(VENV_DIR) ## Install/refresh docs dependencies into .venv
	$(PIP) install --quiet -r $(DOCS_REQS)
	@echo "docs deps installed in $(VENV_DIR)"

.PHONY: docs-serve
docs-serve: docs-install ## Run local docs site at http://$(DOCS_BIND):$(DOCS_PORT)
	$(MKDOCS) serve --dev-addr $(DOCS_BIND):$(DOCS_PORT)

.PHONY: docs-build
docs-build: docs-install ## Build static site into ./site (strict — fails on broken refs)
	$(MKDOCS) build --strict --clean
	@echo "docs built → ./site"

# markdownlint-cli, pinned like flotilla; a local install of the same version is used when present.
MARKDOWNLINT ?= $(shell markdownlint --version 2>/dev/null | grep -qx 0.50.0 && echo markdownlint || echo npx --yes markdownlint-cli@0.50.0)

.PHONY: docs-lint
docs-lint: ## Lint every Markdown file (.markdownlint.json)
	@env -u NODE_OPTIONS $(MARKDOWNLINT) . && echo "docs-lint PASS" || { echo "docs-lint FAIL (make docs-lint-fix fixes most)"; exit 1; }

.PHONY: docs-lint-fix
docs-lint-fix: ## Apply markdownlint's own fixes; long lines are left to fix by hand
	@env -u NODE_OPTIONS $(MARKDOWNLINT) --fix . || true
	@$(MAKE) --no-print-directory docs-lint

.PHONY: docs-validate
docs-validate: docs-lint docs-build ## Markdown lint plus the strict build
	@echo "docs validate OK"

.PHONY: docs-clean
docs-clean: ## Remove built site
	rm -rf site/
	@echo "site/ removed"

.PHONY: clean
clean: docs-clean ## Remove all build artifacts (keeps venvs, recordings and config)
	rm -rf $(NXT_DIR)/build
	find . -name __pycache__ -type d -prune -not -path "./.venv/*" -not -path "./$(NXT_DIR)/.venv/*" -exec rm -rf {} +
	@echo "clean PASS"
