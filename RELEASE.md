# Release Checklist (browser-automation-cli)

Package name on PyPI: **browser-automation-cli** (commands `browser`, `browser-daemon`). Tooling is `uv` end to end; no pip/pipx/twine.

## 1. Prepare
```bash
cd ~/Desktop/browser-cli
# bump version in pyproject.toml (e.g. 0.2.1 -> 0.2.2), then:
uv lock                      # refresh uv.lock for the new version
uv sync
```

## 2. Test locally from source
```bash
uv tool install --force --reinstall --no-cache .   # from this tree; --no-cache matters: uv caches builds by version, so edits without a version bump are otherwise ignored
browser install              # Chromium for the Playwright version in uv.lock (re-run after any Playwright bump)
browser --help
browser capture https://example.com                     # viewport screenshot -> /tmp/browser_capture_<ts>.jpg
browser capture https://example.com -f -o ./full.jpg    # full page
browser-daemon &             # visible Chromium window opens
browser create               # log in manually in the window; prints <session_id>
browser <session_id> navigate https://example.com
browser <session_id> snapshot
browser <session_id> screenshot
browser <session_id> delete
kill %1                      # stop the daemon
```

## 3. Build
```bash
rm -rf dist/
uv build                     # dist/browser_automation_cli-<ver>-py3-none-any.whl and .tar.gz
```

## 4. Publish
Tokens: PyPI (and optionally TestPyPI) API tokens, scope "project: browser-automation-cli". Keep them in your shell env or a password manager — never in the repo.
```bash
# optional dry run against TestPyPI
UV_PUBLISH_TOKEN=pypi-... uv publish --publish-url https://test.pypi.org/legacy/
uv tool install --force --index-url https://test.pypi.org/simple/ browser-automation-cli && browser --help

# real release
UV_PUBLISH_TOKEN=pypi-... uv publish
```

## 5. Verify the published package
```bash
uv tool install --force browser-automation-cli   # from PyPI
browser install
browser capture https://example.com
```

## 6. Post-release
```bash
git tag v<ver> && git push origin main --tags
```
Then confirm https://pypi.org/project/browser-automation-cli/ shows the new version.

## Troubleshooting
- **"File already exists"** on publish: the version was already uploaded — bump `pyproject.toml`, `uv lock`, rebuild.
- **Source edits don't show up after `uv tool install .`**: uv reused a cached wheel for the same version. Use `--reinstall --no-cache`, or bump the version.
- **`browser` runs an old version**: a leftover pipx install shadows the uv one. `pipx uninstall browser-automation-cli` then `uv tool install --force .` (`ls -la ~/.local/bin/browser` should point into `~/.local/share/uv/tools/`).
- **Playwright prompts to run `playwright install`**: the Chromium build for the locked Playwright version is missing — `browser install`.
