.PHONY: install daemon cli help sync build

help:
	@echo "Browser CLI - Usage"
	@echo ""
	@echo "  make install          Install dependencies and commands"
	@echo "  make sync             Sync dependencies with uv"
	@echo "  make build            Build distribution packages"
	@echo "  make daemon          Start the browser daemon (background)"
	@echo "  browser create       Create new session"
	@echo "  browser list         List sessions"
	@echo "  browser <id> <cmd>   Run command on session"

install:
	@uv tool install .
	@uv run playwright install chromium

sync:
	@uv sync

build:
	@uv build

daemon:
	@browser-daemon

start-daemon:
	@browser-daemon &
	@echo "Daemon started in background"
