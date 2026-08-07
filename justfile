# tokennet task runner — `just <recipe>`; `just` or `just --list` shows everything.

# One pin site for the hooks + recipes; the source of truth is
# `required-version` in pyproject.toml — keep them in sync.
ruff := "ruff@0.15.18"

# The shared test gate — it reads test-gate.toml and the diff, and decides
# whether the suite can be affected by this change. Absolute via
# home_directory(): a git worktree lives several levels under the repo root, so
# a path relative to this justfile would not find it.
gate := "python3 " + home_directory() + "/src/software-factory/scripts/test-gate.py"

# List the available recipes
default:
    @just --list

# Lint + format check + typecheck (same as the pre-commit hook)
check:
    uvx {{ ruff }} check .
    uvx {{ ruff }} format --check .
    uv run mypy

# Auto-format and auto-fix what Ruff can, then typecheck
fix:
    uvx {{ ruff }} format .
    uvx {{ ruff }} check --fix .
    uv run mypy

# Unit tests, fully offline, unless nothing changed that could affect them.
# Pass pytest args, e.g. `just test -k stream`; `--force` runs regardless and
# `--explain` shows the gate's reasoning without running anything.
test *args:
    @{{ gate }} {{ args }} -- uv run pytest -m "not live"

# The live suite: real requests to a real deployment, skipped without a
# credential. Targets next.tokennet.dev unless TOKENNET_TEST_DOMAIN says otherwise.
test-live *args:
    uv run pytest -m live {{ args }}
