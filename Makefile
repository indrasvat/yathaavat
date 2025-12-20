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
sync: ## Create/update .venv and install deps (uv sync)
	@uv sync --python $(PYTHON) --all-extras

.PHONY: run
run: ## Launch the TUI
	@uv run --python $(PYTHON) $(PROJECT)

.PHONY: iterm2
iterm2: ## Drive TUI in iTerm2 + capture screenshots
	@uv run --python $(PYTHON) .claude/automations/iterm2_capture_tui.py

.PHONY: iterm2-safe
iterm2-safe: ## Drive safe-attach in iTerm2
	@uv run --python $(PYTHON) .claude/automations/iterm2_capture_safe_attach.py

.PHONY: test
test: ## Run tests (pytest)
	@uv run --python $(PYTHON) pytest

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

.PHONY: hooks
hooks: ## Install git hooks (pre-push runs make check)
	@uv run --python $(PYTHON) pre-commit install --hook-type pre-push
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) Installed pre-push hook.\n"

.PHONY: clean
clean: ## Remove caches + .venv
	@rm -rf .venv .pytest_cache .ruff_cache .mypy_cache dist build *.egg-info || true
	@printf "$(COLOR_GREEN)OK$(COLOR_RESET) Cleaned.\n"
