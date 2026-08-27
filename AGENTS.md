# Working on this repository

This file is for coding agents (and humans) developing browser-automation-cli itself.
**If you want to *use* the tool from an agent, read [SKILL.md](SKILL.md) instead**, it is embedded in
the binary (`browser install skill` installs it into Claude Code / Codex / OpenCode).

The whole project is Rust: one binary (`browser`, with a `daemon` subcommand) plus a `browser-daemon`
compat shim, driving Chrome over raw CDP via a websocket, no Python, Playwright, or Node at runtime.

## Layout

| path | what it is |
|---|---|
| `src/` | the Rust client + daemon (`Cargo.toml` at the repo root) |
| `src/js.rs` | all injected JavaScript: snapshot (iframe/shadow-DOM aware, `@eN` refs), target resolution (strict mode), settle. Snapshot and targeting share one role/name definition, keep it that way |
| `pyproject.toml` | maturin packaging (`bindings = "bin"`), builds the two binaries into the `browser-automation-cli` wheel |
| `install.sh` | installs prebuilt binaries from the GitHub release |
| `tests/test_cli.py` | 18 end-to-end tests that drive the real daemon through the real CLI (Python is only the test runner + the local test-site fixture; stdlib only) |
| `benchmarks/performance-test/` | tool benchmark (latency, tokens, idle CPU/RSS) and one-off probes |
| `benchmarks/development-bench/` | agent benchmark: 17 verifier-judged tasks run by fresh LLM subagents |

## Build and test

```bash
cargo build --release
BROWSER_CLI=$PWD/target/release/browser \
BROWSER_DAEMON=$PWD/target/release/browser-daemon \
  python3 -m unittest -v tests/test_cli.py
```

The test suite needs a `python3` on PATH (stdlib only, it's the test runner and serves the local test
site) and a Chromium for the daemon (`target/release/browser install`). `BROWSER_CLI` / `BROWSER_DAEMON`
default to `target/release/…` when unset.

CI (`.github/workflows/rust-wheels.yml`) runs the suite on Linux twice (managed build and
`engine=system`), builds wheels for 4 platforms, and on `v*` tags publishes to PyPI and attaches
release assets. Chromium system libs come from an ephemeral `uvx playwright install-deps` (no project
dependency). Lint workflow changes with `actionlint` before pushing.

## Non-negotiables

- **Measure before and after.** Any performance/resource claim goes through `benchmarks/performance-test/run.py`
  (before → change → after) or the agent benchmark; results belong in the relevant benchmark's README / RESULTS.md. macOS `ps pcpu`
  is a lifetime average, the harness uses `ps -o time` deltas for a reason.
- **The test suite is the protocol contract.** Don't change request/response shapes without updating
  the tests (or documenting a legacy shim, as done for `type {selector, text}`).
- **Agent benchmark subagents run on Claude Sonnet** (`model: "sonnet"`) unless explicitly comparing
  models; two attempts per task (pass@2) is the minimum for judging a change.
- **Docs ship with the binary**: `README.md` becomes the PyPI description (maturin reads it at build)
  and `SKILL.md` is embedded in the binary, both live at the repo root.
- **Releases**: bump `Cargo.toml` + `pyproject.toml` + `install.sh` together, tag `v<version>`, and
  let CI publish. PyPI descriptions are frozen per release.
