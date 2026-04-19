.PHONY: install daemon cli help

help:
	@echo "Browser CLI - Usage"
	@echo ""
	@echo "  make install          Install dependencies and commands"
	@echo "  make daemon          Start the browser daemon (background)"
	@echo "  browser create       Create new session"
	@echo "  browser list         List sessions"
	@echo "  browser <id> <cmd>   Run command on session"

install:
	@pip install playwright
	@playwright install chromium
	@pip install -e .

daemon:
	@browser-daemon

start-daemon:
	@browser-daemon &
	@echo "Daemon started in background"
