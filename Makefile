UV      := uv
BINARY  := bdr
DIST    := dist

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------

.PHONY: dev
dev: check-uv ## Set up a local development environment
	$(UV) sync
	$(UV) run bdr setup
	@echo ""
	@echo "Dev environment ready. Use 'uv run bdr <command>' to run locally."

.PHONY: test
test: check-uv ## Run the test suite
	$(UV) run pytest

# ---------------------------------------------------------------------------
# Installation (global tool, available as 'bdr' on PATH)
# ---------------------------------------------------------------------------

.PHONY: install
install: check-uv ## Install bdr as a global uv tool, then run setup
	$(UV) tool install --force --no-cache .
	bdr setup
	@echo ""
	@echo "bdr installed. Try: bdr run examples/login.bdr"

.PHONY: uninstall
uninstall: check-uv ## Remove the globally installed bdr tool
	$(UV) tool uninstall $(BINARY)

.PHONY: upgrade
upgrade: check-uv ## Upgrade the globally installed bdr tool in-place
	$(UV) tool upgrade $(BINARY)

# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

.PHONY: build
build: check-uv ## Build wheel + sdist for PyPI distribution
	$(UV) build
	@echo ""
	@ls -lh $(DIST)/

.PHONY: bundle
bundle: check-uv ## Build a self-contained single-file binary via PyInstaller
	@echo "Building standalone binary..."
	$(UV) run pyinstaller \
		--onefile \
		--name $(BINARY) \
		--collect-all playwright \
		--hidden-import playwright.sync_api \
		bdr/__main__.py
	@echo ""
	@echo "Binary: $(DIST)/$(BINARY)"
	@echo "Copy it to any machine, then run once to install browsers:"
	@echo "  $(DIST)/$(BINARY) setup"

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

.PHONY: clean
clean: ## Remove all build artifacts and caches
	rm -rf $(DIST)/ build/ *.egg-info .pytest_cache *.spec
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean."

# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

.PHONY: check-uv
check-uv:
	@command -v $(UV) >/dev/null 2>&1 || { \
		echo "uv not found. Install it with:"; \
		echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		exit 1; \
	}
