# browser-automation-cli (Rust implementation)

`browser` + `browser-daemon`: persistent, authenticated browser automation for coding agents over a
Unix socket — the same CLI and protocol as the 0.3 Python package, with no Python/Playwright/Node.
`browser install` downloads Chrome for Testing (the build Playwright pins) into Playwright's cache layout;
or point `BROWSER_CHROME_PATH` at any Chromium.

Docs, benchmarks and the agent-level evaluation: https://github.com/jshan9078/browser-automation-cli
