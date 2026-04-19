# Release Checklist

Complete guide for publishing browser-cli to PyPI.

## Pre-Release: Test Locally

```bash
cd ~/Desktop/browser-cli

# Install build tools
python3 -m pip install --upgrade build twine

# Build the package
python3 -m build

# Verify dist files exist
ls dist/
# Expected: browser_cli-0.1.0-py3-none-any.whl and browser_cli-0.1.0.tar.gz

# Test install from local wheel (no PyPI needed)
pipx install ./dist/browser_cli-0.1.0-py3-none-any.whl

# If commands not found, add pipx to PATH:
# export PATH="$HOME/.local/bin:$PATH"

# Verify commands work
browser --help

# Test standalone capture (no daemon needed)
browser capture https://example.com
browser capture https://example.com -f
browser capture https://example.com -o ./my-screenshot.jpg

# Test daemon workflow
browser-daemon &
browser create
# (manually log in to sites in the opened browser)
browser <session_id> navigate https://example.com
browser <session_id> snapshot
browser <session_id> click "a"
browser <session_id> screenshot
browser list
browser delete <session_id>

# Clean up stale Chrome processes (if needed)
browser cleanup

# Clean up local install
pipx uninstall browser-cli
```

## Optional: Create GitHub Repo

Not required for PyPI, but recommended:

```bash
cd ~/Desktop/browser-cli
git init
git add .
git commit -m "Initial browser-cli package"

# Using GitHub CLI
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main

# Or create repo via web and push
```

**Update pyproject.toml with your repo URL:**
```toml
[project.urls]
Homepage = "https://github.com/<your-username>/<your-repo>"
Repository = "https://github.com/<your-username>/<your-repo>"
```

## Step 1: Create PyPI Accounts

1. **Create TestPyPI account:** https://test.pypi.org/account/register/
2. **Create PyPI account:** https://pypi.org/account/register/
3. **Generate API tokens on both sites:**
   - Go to Account Settings → API Tokens → Add API Token
   - Name: "browser-cli upload"
   - Scope: "Entire account"
   - Copy the token (starts with `pypi-`)

## Step 2: Configure Twine

Create `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-YOUR_PYPI_TOKEN_HERE

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-YOUR_TESTPYPI_TOKEN_HERE
```

**Security:**
- Never commit this file
- Set permissions: `chmod 600 ~/.pypirc`

## Step 3: Test Upload to TestPyPI

```bash
cd ~/Desktop/browser-cli

# Rebuild if you made changes
python3 -m build

# Upload to TestPyPI
python3 -m twine upload --repository testpypi dist/*

# If you didn't configure .pypirc, use:
# python3 -m twine upload --repository-url https://test.pypi.org/legacy/ dist/*
```

## Step 4: Verify TestPyPI Install

```bash
# Install from TestPyPI
pipx install --index-url https://test.pypi.org/simple/ browser-cli

# Test it
browser capture https://example.com

# Clean up
pipx uninstall browser-cli
```

## Step 5: Publish to Real PyPI

```bash
cd ~/Desktop/browser-cli

# Final build
python3 -m build

# Upload to PyPI
python3 -m twine upload dist/*

# Or if you didn't configure .pypirc:
# python3 -m twine upload --username __token__ --password YOUR_PYPI_TOKEN dist/*
```

## Step 6: Verify Production Install

```bash
# Clean install from PyPI
pipx install browser-cli

# Test all commands
browser --help
browser capture https://example.com

# If you need the full daemon functionality:
browser install        # Install Chromium
browser-daemon         # Start daemon
browser create         # Create session
```

## Troubleshooting

**"File already exists" on upload:**
```bash
# Bump version in pyproject.toml
# Edit version = "0.1.1"  # increment
python3 -m build
python3 -m twine upload dist/*
```

**Package name already taken:**
- Choose a different name in `pyproject.toml`
- Or request transfer if name is squatting

**Build errors:**
```bash
# Clean and rebuild
rm -rf dist/ build/ *.egg-info
python3 -m build
```

**Authentication errors:**
- Verify token hasn't expired
- Check `~/.pypirc` permissions (should be 600)
- Ensure you're using `__token__` as username, not your PyPI username

## Post-Release

- Tag the release on GitHub: `git tag v0.1.0 && git push origin v0.1.0`
- Update documentation with install instructions
- Announce if applicable

## One-Liner Test

Quick validation that everything works:

```bash
pipx install browser-cli && \
browser capture https://example.com && \
pipx uninstall browser-cli && \
echo "Success!"
```
