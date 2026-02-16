# x-unfurls development commands
# Run `just` to see available recipes

# ─── Dependencies ────────────────────────────────────────────

# Install all dependencies (including dev)
install:
    uv sync --all-extras

# ─── Quality ─────────────────────────────────────────────────

# Run all quality checks (CI-equivalent)
check: format-check lint typecheck test

# Format code
format:
    uv run ruff format src/ tests/

# Check formatting without modifying (CI mode)
format-check:
    uv run ruff format --check src/ tests/

# Lint code
lint:
    uv run ruff check src/ tests/

# Lint and auto-fix
lint-fix:
    uv run ruff check --fix src/ tests/

# Type-check with mypy
typecheck:
    uv run mypy src/

# ─── Testing ─────────────────────────────────────────────────

# Run tests with coverage
test *ARGS:
    uv run pytest {{ ARGS }}

# Run tests quietly (CI mode)
test-quiet:
    uv run pytest -q

# ─── Cleanup ─────────────────────────────────────────────────

# Remove build artifacts and caches
clean:
    find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
    rm -rf .mypy_cache src/.mypy_cache .pytest_cache .ruff_cache
    rm -rf htmlcov .coverage
    rm -rf dist build *.egg-info

# ─── Local Dev ───────────────────────────────────────────────

# Run webhook service locally
run-webhook:
    uv run uvicorn xunfurls.infrastructure.gcp.webhook_app:app --reload --port 8080

# Run worker service locally
run-worker:
    uv run uvicorn xunfurls.infrastructure.gcp.worker_app:app --reload --port 8081
