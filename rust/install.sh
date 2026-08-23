#!/bin/sh
# Install the Rust browser/browser-daemon binaries from the GitHub release into ~/.local/bin.
set -e
V="${BROWSER_CLI_VERSION:-0.4.0-alpha.1}"; OS=$(uname -s | tr A-Z a-z); ARCH=$(uname -m)
URL="https://github.com/jshan9078/browser-automation-cli/releases/download/v$V/browser-cli-$V-$OS-$ARCH.tar.gz"
DEST="${BROWSER_CLI_BIN:-$HOME/.local/bin}"; mkdir -p "$DEST"
echo "Downloading $URL"; curl -fsSL "$URL" | tar -C "$DEST" -xzf -
chmod +x "$DEST/browser" "$DEST/browser-daemon"
echo "Installed browser and browser-daemon to $DEST (Rust $V). Chromium: run 'browser install' (needs the Python package) or set BROWSER_CHROME_PATH."
