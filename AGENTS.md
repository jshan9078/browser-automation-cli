# Working on this repository

This file is for coding agents (and humans) developing browser-automation-cli itself.
**If you want to *use* the tool from an agent, read [SKILL.md](SKILL.md) instead** — it is embedded in
the binary (`browser install skill` installs it into Claude Code / Codex / OpenCode).

## Layout

| path | what it is |
|---|---|
| `rust/` | the shipped implementation: one binary (`browser`, with a `daemon` subcommand) + a `browser-daemon` compat shim. Raw CDP over a websocket; no Playwright/Node at runtime |
| `rust/src/js.rs` | all injected JavaScript: snapshot (iframe/shadow-DOM aware, `@eN` refs), target resolution (strict mode), settle. Snapshot and targeting share one role/name definition — keep it that way |
| `cli/`, `daemon/` | the original Python implementation, kept as a reference and protocol oracle. Same JSON-over-Unix-socket protocol |
| `tests/test_cli.py` | 20 end-to-end tests that drive a real daemon through the real CLI. They run against either implementation |
| `scratch/bench/` | tool benchmark (latency, tokens, idle CPU/RSS) and one-off probes |
| `scratch/agentbench/` | agent benchmark: 17 verifier-judged tasks run by fresh LLM subagents |
| `AGENTBENCH.md` | all measured results; update it when numbers change |

## Build and test

```bash
cd rust && cargo build --release
.venv/bin/python -m unittest -v tests/test_cli.py                          # Python daemon (needs `uv sync` + playwright browsers)
BROWSER_CLI=$PWD/rust/target/release/browser \
BROWSER_DAEMON=$PWD/rust/target/release/browser-daemon \
  .venv/bin/python -m unittest -v tests/test_cli.py                        # Rust daemon (the one that ships)
```

CI (`.github/workflows/rust-wheels.yml`) runs the Rust suite on Linux twice (managed build and
`engine=system`), builds wheels for 4 platforms, and on `v*` tags publishes to PyPI and attaches
release assets. Lint workflow changes with `actionlint` before pushing.

## Non-negotiables

- **Measure before and after.** Any performance/resource claim goes through `scratch/bench/run.py`
  (before → change → after) or the agent benchmark; results belong in AGENTBENCH.md. macOS `ps pcpu`
  is a lifetime average — the harness uses `ps -o time` deltas for a reason.
- **The protocol is shared.** The Rust and Python daemons speak the same JSON protocol; the test
  suite is the contract. Don't change request/response shapes without updating both (or documenting
  a legacy shim, as done for `type {selector, text}`).
- **Agent benchmark subagents run on Claude Sonnet** (`model: "sonnet"`) unless explicitly comparing
  models; two attempts per task (pass@2) is the minimum for judging a change.
- **Docs ship with the binary**: `rust/README.md`, `rust/SKILL.md` are synced copies (CI overwrites
  them from the repo root at build). Edit the root files only.
- **Releases**: bump `rust/Cargo.toml` + `rust/pyproject.toml` + `rust/install.sh` together, tag
  `v<version>`, and let CI publish. PyPI descriptions are frozen per release.
