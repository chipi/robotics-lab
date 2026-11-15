# robotics-lab — Makefile
#
# Layered tiers, as in the operator's other projects (flotilla, eval-harness):
#   - lint / test-unit / test-duck / test-viewer / test-viewer-pages /
#     test-integration / test-viewer-image  → atomic (one project, one kind of check)
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

PYTHON         ?= python3
VENV_DIR       ?= .venv
VENV_BIN       := $(VENV_DIR)/bin
PIP            := $(VENV_BIN)/pip
MKDOCS         := $(VENV_BIN)/mkdocs

DOCS_REQS      := requirements-docs.txt
DOCS_PORT      ?= 8765
DOCS_BIND      ?= 127.0.0.1

NXT_DIR        := nxt
NXT_PY         := $(NXT_DIR)/.venv/bin/python
NXT_HOST       ?= 127.0.0.1
NXT_PORT       ?= 8000
NXT_LINK       ?= auto
NXT_IMAGE      ?= robotics-lab/nxt-web:dev
NXT_DATA       ?= nxt-web-data

DUCK_DIR       := duck
VIEWER_DIR     := viewer
VIEWER_IMAGE   ?= miniview:ci

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

.PHONY: duck-sync viewer-sync
duck-sync: ## Create/refresh the duck project's venv from its lock (uv, with its dev tools: the tests need rerun-sdk)
	@cd $(DUCK_DIR) && uv sync --frozen && echo "duck-sync PASS"

viewer-sync: ## Create/refresh the viewer's venv from its lock (uv, with Playwright)
	@cd $(VIEWER_DIR) && uv sync --frozen && echo "viewer-sync PASS"

.PHONY: lint
lint: ## Byte-compile every Python file of every project
	@$(PYTHON) -m compileall -q $(NXT_DIR)/src $(NXT_DIR)/scripts $(NXT_DIR)/tests \
	  $(DUCK_DIR)/src $(DUCK_DIR)/tests $(DUCK_DIR)/sim $(VIEWER_DIR)/src $(VIEWER_DIR)/tests >/dev/null \
	  || { echo "lint FAIL: Python does not compile"; exit 1; }
	@echo "lint PASS"

# One line per test file: PASS, or FAIL with its output. $(1) the project dir, $(2) the test files.
define run_tests
	@fail=0; for t in $(2); do \
	  log=$$(mktemp); \
	  if (cd $(1) && uv run --frozen $(3) python $$t) >$$log 2>&1; then echo "PASS $(1)/$$t"; \
	  else echo "FAIL $(1)/$$t"; cat $$log; fail=1; fi; rm -f $$log; \
	done; exit $$fail
endef

DUCK_TESTS          := tests/test_nav.py tests/test_record.py tests/test_explore.py tests/test_cliff.py \
                       tests/test_world.py tests/test_miniview.py
VIEWER_TESTS        := tests/test_duck_adapter.py tests/test_query.py tests/test_mcapio.py tests/test_reading.py \
                       tests/test_index.py tests/test_server.py
VIEWER_PAGE_TESTS   := tests/test_live_page.py tests/test_store_page.py tests/test_ui.py

.PHONY: test-duck test-viewer test-viewer-pages
test-duck: duck-sync ## The duck's navigator and tools, no simulator
	$(call run_tests,$(DUCK_DIR),$(DUCK_TESTS),)
	@echo "test-duck PASS"

test-viewer: viewer-sync ## miniview: adapter, queries, MCAP, the API and live service
	$(call run_tests,$(VIEWER_DIR),$(VIEWER_TESTS),)
	@echo "test-viewer PASS"

test-viewer-pages: viewer-sync ## miniview's two pages in headless Chromium (MINIVIEW_CHROMIUM, else Playwright's)
	$(call run_tests,$(VIEWER_DIR),$(VIEWER_PAGE_TESTS),)
	@echo "test-viewer-pages PASS"

.PHONY: test-unit
test-unit: nxt-sync ## The NXT web UI against the simulated brick (never moves a real robot)
	@$(NXT_PY) $(NXT_DIR)/tests/test_deadman.py >/tmp/robotics-lab-test_deadman.log 2>&1 \
	  && echo "PASS nxt/tests/test_deadman.py" \
	  || { echo "FAIL nxt/tests/test_deadman.py"; cat /tmp/robotics-lab-test_deadman.log; exit 1; }
	@$(NXT_PY) $(NXT_DIR)/tests/test_web_smoke.py >/tmp/robotics-lab-test_web_smoke.log 2>&1 \
	  && { grep -E "^SKIP" /tmp/robotics-lab-test_web_smoke.log || true; echo "PASS nxt/tests/test_web_smoke.py"; } \
	  || { echo "FAIL nxt/tests/test_web_smoke.py"; grep -E "^(FAIL|SMOKE)" /tmp/robotics-lab-test_web_smoke.log; cat /tmp/robotics-lab-test_web_smoke.log; exit 1; }
	@echo "test-unit PASS"

.PHONY: nxt-programs
nxt-programs: ## Compile every NXC program for the brick (nbc in Docker) into nxt/build/
	@for p in $(NXT_DIR)/programs/*.nxc; do $(NXT_DIR)/scripts/nxc.sh $$p; done
	@echo "nxt-programs PASS"

.PHONY: test-integration
test-integration: nxt-image ## The packaged image: start it with the simulated brick, check it answers
	@cid=$$(docker run -d --rm -p 127.0.0.1::8000 $(NXT_IMAGE) nxt-web --fake --host 0.0.0.0 --port 8000); \
	  trap 'docker stop $$cid >/dev/null' EXIT; \
	  port=$$(docker port $$cid 8000/tcp | head -1 | sed 's/.*://'); \
	  for i in $$(seq 1 40); do curl -fs -m 2 http://127.0.0.1:$$port/api/status >/tmp/robotics-lab-image-status.json && break; sleep 0.25; done; \
	  grep -q '"connected": true' /tmp/robotics-lab-image-status.json && grep -q '"link": "fake"' /tmp/robotics-lab-image-status.json \
	    && echo "PASS image answers: $$(cat /tmp/robotics-lab-image-status.json | head -c 120)" \
	    || { echo "FAIL image did not answer as expected"; cat /tmp/robotics-lab-image-status.json 2>/dev/null; docker logs $$cid; exit 1; }
	@echo "test-integration PASS"

.PHONY: test-run-compat
test-run-compat: viewer-sync duck-sync ## A run opens fully in Rerun, Lichtblick and miniview (ADR-0007 Compatibility): explore9 imported, checked in each
	$(call run_tests,$(VIEWER_DIR),tests/test_run_compat.py,)
	@echo "test-run-compat PASS"

.PHONY: perf-viewer
perf-viewer: viewer-sync ## NOT in CI: replay duck/runs/phase1-run18 at 20 Hz through the writer with both pages open; prints latency, bytes per page, lock hold time
	@cd $(VIEWER_DIR) && uv run --frozen python perf/perf_viewer.py $(PERF_ARGS)

.PHONY: test-viewer-image
test-viewer-image: ## miniview's image: build it, run it with the data read only and the index on its own volume, check what it serves and that it cannot write the data (ADR-0012)
	@docker build -q -t $(VIEWER_IMAGE) $(VIEWER_DIR) >/dev/null
	@data=$$(mktemp -d); idx=$$(mktemp -d); vol=miniview-test-index-$$$$; mkdir -p $$data/runs $$data/scenes; \
	  (cd $(VIEWER_DIR) && MINIVIEW_INDEX=$$idx/host.sqlite uv run --frozen miniview --data $$data import tests/fixtures/explore9 --scene apartment >/dev/null) \
	    || { echo "FAIL could not import the fixture run on the host"; rm -rf $$data $$idx; exit 1; }; \
	  docker volume create $$vol >/dev/null; \
	  cid=$$(docker run -d --rm -p 127.0.0.1::8070 -v $$data/runs:/data/runs:ro -v $$data/scenes:/data/scenes:ro -v $$vol:/index \
	    --user $$(id -u):$$(id -g) $(VIEWER_IMAGE)); \
	  trap 'docker stop $$cid >/dev/null; for i in 1 2 3 4 5 6 7 8 9 10; do docker volume rm $$vol >/dev/null 2>&1 && break; sleep 0.5; done; rm -rf $$data $$idx' EXIT; \
	  port=$$(docker port $$cid 8070/tcp | head -1 | sed 's/.*://'); \
	  for i in $$(seq 1 60); do curl -fs -m 2 http://127.0.0.1:$$port/api/v1/health >/tmp/robotics-lab-miniview-health.json && break; sleep 0.25; done; \
	  grep -q '"ok":true' /tmp/robotics-lab-miniview-health.json \
	    && curl -fs -m 5 http://127.0.0.1:$$port/api/v1/scenes | grep -q '"format":2' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/api/v1/runs | grep -q 'duck/apartment/explore9' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/api/v1/runs/duck/apartment/explore9 | grep -q '"ticks":116' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/web/three/ | grep -qi '<html' \
	    && curl -fs -m 5 http://127.0.0.1:$$port/web/shell/shell.js >/dev/null \
	    && curl -fs -m 5 http://127.0.0.1:$$port/web/fonts/fonts.css | grep -q 'woff2' \
	    && docker exec $$cid test -f /index/index.sqlite \
	    && mounts=$$(docker inspect -f '{{range .Mounts}}{{.Destination}}={{.RW}} {{end}}' $$cid) \
	    && echo "$$mounts" | grep -q '/data/runs=false' && echo "$$mounts" | grep -q '/data/scenes=false' && echo "$$mounts" | grep -q '/index=true' \
	    && ! docker exec $$cid sh -c 'touch /data/runs/x' 2>/dev/null \
	    && ! docker exec $$cid sh -c 'touch /data/scenes/x' 2>/dev/null \
	    && ! docker exec $$cid sh -c 'rm -rf /data/runs/duck' 2>/dev/null \
	    && test -d $$data/runs/duck \
	    && docker exec $$cid sh -c 'touch /index/probe && rm /index/probe' \
	    && echo "PASS miniview image answers; the data mount is read only, the index volume is writable: $$(cat /tmp/robotics-lab-miniview-health.json)" \
	    || { echo "FAIL miniview image"; cat /tmp/robotics-lab-miniview-health.json 2>/dev/null; docker logs $$cid; exit 1; }
	@echo "test-viewer-image PASS"

# ---- Composite tiers ---------------------------------------------------------

.PHONY: ci-fast
ci-fast: lint test-unit test-duck test-viewer ## What every push must pass (fast feedback): every project's unit tests
	@echo "ci-fast PASS"

.PHONY: ci
ci: ci-fast test-viewer-pages test-run-compat test-integration test-viewer-image nxt-programs docs-lint docs-build ## What every merge must pass (full gate)
	@echo "ci PASS"

# ---- NXT: run and package ----------------------------------------------------

.PHONY: nxt-web
nxt-web: nxt-sync ## Serve the NXT web UI on the real robot (NXT_HOST, NXT_PORT, NXT_LINK=auto|usb|bluetooth)
	cd $(NXT_DIR) && exec .venv/bin/nxt-web --host $(NXT_HOST) --port $(NXT_PORT) --link $(NXT_LINK)

.PHONY: nxt-web-fake
nxt-web-fake: nxt-sync ## Serve the NXT web UI with a simulated brick (no robot needed)
	cd $(NXT_DIR) && exec .venv/bin/nxt-web --fake --host $(NXT_HOST) --port $(NXT_PORT)

.PHONY: nxt-image
nxt-image: ## Build the NXT web UI image (NXT_IMAGE)
	docker build -t $(NXT_IMAGE) $(NXT_DIR)

.PHONY: viewers viewers-down
viewers: viewer-up ## The viewers on loopback: miniview (:8070), Rerun (:9090) and Lichtblick (:8090) (ADR-0002, ADR-0005)
	@scripts/viewers.sh up

viewers-down: viewer-down ## Stop the viewers started by make viewers
	@scripts/viewers.sh down

MINIVIEW_PORT ?= 8070
MINIVIEW_DATA ?= /work/robotics-lab/data
MINIVIEW_ENV   = MINIVIEW_PORT=$(MINIVIEW_PORT) MINIVIEW_DATA=$(MINIVIEW_DATA) MINIVIEW_UID=$$(id -u) MINIVIEW_GID=$$(id -g)

.PHONY: viewer-up viewer-down
viewer-up: ## miniview's service in Docker on 127.0.0.1:$(MINIVIEW_PORT), data from $(MINIVIEW_DATA) (RFC-0009)
	@mkdir -p $(MINIVIEW_DATA)/runs $(MINIVIEW_DATA)/scenes
	@$(MINIVIEW_ENV) docker compose -f viewer/compose.yml up -d --build --wait \
	  && echo "miniview at http://127.0.0.1:$(MINIVIEW_PORT)/" \
	  || { echo "viewer-up FAIL"; $(MINIVIEW_ENV) docker compose -f viewer/compose.yml logs --tail 40; exit 1; }

viewer-down: ## Stop miniview's service
	@$(MINIVIEW_ENV) docker compose -f viewer/compose.yml down

.PHONY: nxt-image-run
nxt-image-run: nxt-image ## Run the image on this machine with the robot's USB/Bluetooth devices, port on 127.0.0.1 only
	docker run --rm -it -p 127.0.0.1:$(NXT_PORT):8000 -v $(NXT_DATA):/data \
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
