.PHONY: build install wheel daemon help

help:
	@echo "Browser CLI (Rust) - Usage"
	@echo ""
	@echo "  make build            cargo build --release"
	@echo "  make install          build + download Chromium"
	@echo "  make wheel            build the PyPI wheel via maturin"
	@echo "  make daemon           start the browser daemon (foreground)"
	@echo "  browser create        create a new session"
	@echo "  browser list          list sessions"
	@echo "  browser <id> <cmd>    run a command on a session"

build:
	@cargo build --release

install: build
	@./target/release/browser install

wheel:
	@uvx maturin build --release

daemon:
	@./target/release/browser daemon
