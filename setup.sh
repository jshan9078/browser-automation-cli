#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
  DEFAULT_PACKAGE_SPEC="$SCRIPT_DIR"
else
  DEFAULT_PACKAGE_SPEC="browser-automation-cli"
fi

PACKAGE_SPEC="${1:-$DEFAULT_PACKAGE_SPEC}"

echo "Installing Browser CLI with uv..."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

uv tool install --force "$PACKAGE_SPEC"

echo "Installing Chromium runtime..."
browser install

echo ""
echo "Done! Next steps:"
echo "  1. browser-daemon"
echo "  2. browser create"
echo ""
echo "Tip: pass a package spec to install from remote:"
echo "  ./setup.sh 'git+https://github.com/<your-org>/<your-repo>.git'"
