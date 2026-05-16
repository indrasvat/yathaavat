.DEFAULT_GOAL := help

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

PROJECT := yathaavat
PYTHON := python3.14

COLOR_RESET := \033[0m
COLOR_BOLD  := \033[1m
COLOR_DIM   := \033[2m
COLOR_BLUE  := \033[34m
COLOR_CYAN  := \033[36m
COLOR_GREEN := \033[32m
COLOR_YELLOW:= \033[33m
COLOR_RED   := \033[31m

.PHONY: help
help: ## Show this help (default)
	@printf "$(COLOR_BOLD)$(PROJECT)$(COLOR_RESET) — commands\n\n"
	@printf "$(COLOR_DIM)Tip: run \`make sync\` first on a fresh checkout.$(COLOR_RESET)\n\n"
	@awk 'BEGIN {FS = ":.*##"; printf "$(COLOR_BOLD)Usage$(COLOR_RESET): make <target>\n\n"} \
		/^[a-zA-Z0-9_.-]+:.*##/ { \
			printf "  $(COLOR_CYAN)%-22s$(COLOR_RESET) %s\n", $$1, $$2 \
		}' $(MAKEFILE_LIST)

.PHONY: sync
sync: ## Create/update .venv, install deps, install hooks
	@uv sync --python $(PYTHON) --all-extras
	@$(MAKE) hooks || printf "$(COLOR_YELLOW)WARN$(COLOR_RESET) Hooks not installed (lefthook unavailable). Run \`make hooks\` manually.\n"

.PHONY: run
run: ## Launch the TUI
	@uv run --python $(PYTHON) $(PROJECT)

.PHONY: demo-service
demo-service: ## Run the demo HTTP service (debugpy + CPU endpoints)
	@uv run --python $(PYTHON) python -Xfrozen_modules=off examples/demo_service.py

.PHONY: demo-service-nodebug
demo-service-nodebug: ## Run demo HTTP service without debugpy (for safe attach)
	@YATHAAVAT_ENABLE_DEBUGPY=0 uv run --python $(PYTHON) python -Xfrozen_modules=off examples/demo_service.py

.PHONY: vanilla-service
vanilla-service: ## Run vanilla HTTP service (no debugpy in code)
	@uv run --python $(PYTHON) python -Xfrozen_modules=off examples/vanilla_service.py --host $${YATHAAVAT_HTTP_HOST:-127.0.0.1} --port $${YATHAAVAT_HTTP_PORT:-8001}

.PHONY: demo-client
demo-client: ## Drive the demo HTTP service with requests
	@uv run --python $(PYTHON) examples/demo_service_client.py

.PHONY: shux-install
shux-install: ## Install shux binary + Codex/agent skill if missing
	@if ! command -v shux >/dev/null 2>&1; then \
		curl -sSf https://shux.pages.dev/install.sh | sh; \
	fi

.PHONY: shux-smoke
shux-smoke: shux-install ## Drive TUI with shux + capture color screenshot
	@mkdir -p .shux/out
	@session="yathaavat-smoke-$$(date +%s)"; \
		trap 'shux session kill '"'"'$$session'"'"' >/dev/null 2>&1 || true' EXIT; \
		shux --format json session create "$$session" -d -- \
			env -u NO_COLOR TERM=xterm-256color COLORTERM=truecolor FORCE_COLOR=1 \
			uv run --python $(PYTHON) $(PROJECT) >/dev/null; \
		shux pane set-size -s "$$session" --cols 140 --rows 45 >/dev/null; \
		shux pane wait-for -s "$$session" --text yathaavat --timeout-ms 10000 >/dev/null; \
		shux --format json pane snapshot -s "$$session" \
			| $(PYTHON) -c 'import base64,json,sys; sys.stdout.buffer.write(base64.b64decode(json.load(sys.stdin)["png_base64"]))' \
			> .shux/out/yathaavat-smoke.png; \
		printf "$(COLOR_GREEN)OK$(COLOR_RESET) Wrote .shux/out/yathaavat-smoke.png\n"

.PHONY: test
test: ## Run tests (pytest)
	@uv run --python $(PYTHON) pytest

.PHONY: coverage
coverage: ## Run tests with branch coverage and XML report
	@uv run --python $(PYTHON) pytest --cov=src/$(PROJECT) --cov-report=term-missing:skip-covered --cov-report=xml:coverage.xml

.PHONY: coverage-html
coverage-html: ## Run tests with coverage and build htmlcov/
	@uv run --python $(PYTHON) pytest --cov=src/$(PROJECT) --cov-report=term-missing:skip-covered --cov-report=xml:coverage.xml --cov-report=html:htmlcov

.PHONY: lint
lint: ## Lint (ruff)
	@uv run --python $(PYTHON) ruff check

.PHONY: format
format: ## Auto-format (ruff format)
	@uv run --python $(PYTHON) ruff format

.PHONY: format-check
format-check: ## Check formatting (ruff format --check)
	@uv run --python $(PYTHON) ruff format --check

.PHONY: typecheck
typecheck: ## Type-check (mypy)
	@uv run --python $(PYTHON) mypy src tests

.PHONY: check
check: format-check lint typecheck test ## Run all checks (fast fail)
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) All checks passed.\n"

.PHONY: ci
ci: check shellcheck ## Full CI pipeline (check + shellcheck)
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) CI passed.\n"

.PHONY: shellcheck
shellcheck: ## Shellcheck install.sh
	@shellcheck install.sh
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) shellcheck passed.\n"

.PHONY: hooks
hooks: ## Install git hooks via lefthook (pre-commit + pre-push)
	@if ! command -v lefthook >/dev/null 2>&1; then \
		printf "$(COLOR_YELLOW)lefthook not found — installing via brew…$(COLOR_RESET)\n"; \
		brew install lefthook; \
	fi
	@lefthook install
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) Installed lefthook hooks (pre-commit + pre-push).\n"

.PHONY: version
version: ## Show current version (from git tags)
	@uv run --python $(PYTHON) python -c "from yathaavat import __version__; print(__version__)"

.PHONY: build-dist
build-dist: ## Build wheel + sdist into dist/
	@uv build
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) Built dist/\n"

.PHONY: release
release: check ## Tag + push to trigger GH Actions release (usage: make release V=0.2.0)
	@if [ -z "$(V)" ]; then \
		printf "$(COLOR_RED)ERROR$(COLOR_RESET) Usage: make release V=x.y.z\n"; \
		exit 1; \
	fi
	@printf "$(COLOR_BOLD)Releasing v$(V)…$(COLOR_RESET)\n"
	@git diff --quiet || { printf "$(COLOR_RED)ERROR$(COLOR_RESET) Unstaged changes.\n"; exit 1; }
	@git diff --cached --quiet || { printf "$(COLOR_RED)ERROR$(COLOR_RESET) Staged uncommitted changes.\n"; exit 1; }
	@test -z "$$(git ls-files --others --exclude-standard)" || { printf "$(COLOR_YELLOW)WARN$(COLOR_RESET) Untracked files present.\n"; }
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
		if [ "$$branch" != "main" ]; then \
			printf "$(COLOR_YELLOW)WARN$(COLOR_RESET) Releasing from branch '$$branch' (not main).\n"; \
		fi
	@git tag -a "v$(V)" -m "release: v$(V)"
	@git push origin "v$(V)"
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) Tag v$(V) pushed — GitHub Actions will build and create the release.\n"
	@printf "  Track: $(COLOR_CYAN)gh run watch$(COLOR_RESET)\n"
	@printf "  Install: $(COLOR_CYAN)uvx --from git+https://github.com/indrasvat/yathaavat@v$(V) yathaavat$(COLOR_RESET)\n"

.PHONY: clean
clean: ## Remove caches + .venv
	@rm -rf .venv .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info || true
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) Cleaned.\n"
