# robotics-lab — Makefile
#
# Layered tiers, as in the operator's other projects (flotilla, eval-harness):
#   - lint / test-unit / test-integration → atomic
#   - ci-fast                             → what every push must pass (fast feedback)
#   - ci                                  → what every merge must pass (full gate)
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

.PHONY: lint
lint: ## Byte-compile every Python file
	@$(PYTHON) -m compileall -q $(NXT_DIR)/src $(NXT_DIR)/scripts $(NXT_DIR)/tests >/dev/null || { echo "lint FAIL: Python does not compile"; exit 1; }
	@echo "lint PASS"

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

# ---- Composite tiers ---------------------------------------------------------

.PHONY: ci-fast
ci-fast: lint test-unit ## What every push must pass (fast feedback)
	@echo "ci-fast PASS"

.PHONY: ci
ci: ci-fast test-integration nxt-programs docs-lint docs-build ## What every merge must pass (full gate)
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
viewers: ## Both viewers on loopback with every recorded run: Rerun (:9090) and Lichtblick (:8090) (ADR-0002)
	@scripts/viewers.sh up

viewers-down: ## Stop the viewers started by make viewers
	@scripts/viewers.sh down

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
