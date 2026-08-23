"""Per-session page actions. Every handler takes the Session and returns a JSON-able dict."""
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import Page

from .session import Session

logger = logging.getLogger(__name__)

SHOTS_DIR = Path.home() / ".browser-daemon" / "shots"
ACTION_TIMEOUT = 10000

# ---------------------------------------------------------------------------
# Snapshot: interactive + landmark elements only, visibility-filtered, flat text.
# Refs (@eN) are stored on the DOM node itself (like Playwright MCP's aria-ref), so
# they stay stable across snapshots until the page navigates.
# ---------------------------------------------------------------------------
SNAPSHOT_JS = r"""
(args) => {
  const {scope, all, max} = args;
  const root = scope ? document.querySelector(scope) : document.body;
  if (!root) return {error: 'scope not found: ' + scope};
  const W = window;
  if (!W.__brefs) { W.__brefs = new WeakMap(); W.__brefmap = new Map(); W.__brefn = 0; }

  const INTERACTIVE = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=menuitemcheckbox],[role=menuitemradio],[role=option],[role=checkbox],[role=radio],[role=switch],[role=combobox],[role=textbox],[role=searchbox],[role=slider],[role=spinbutton],[contenteditable=true],[contenteditable=""],[tabindex]:not([tabindex="-1"])';
  const LANDMARK = 'h1,h2,h3,[role=dialog],[role=alertdialog],[role=alert],[role=status],[aria-live]:not([aria-live=off]),[role=heading]';
  const TEXTY = 'p,li,td,th,dt,dd,label,legend,figcaption,blockquote,pre,h4,h5,h6';

  const vh = W.innerHeight, vw = W.innerWidth;
  function visible(el) {
    if (el.closest('[aria-hidden="true"]')) return false;
    if (typeof el.checkVisibility === 'function' && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return false;
    return true;
  }
  function where(r) {
    if (r.bottom < 0) return 'above';
    if (r.top > vh) return 'below';
    if (r.right < 0 || r.left > vw) return 'offside';
    return '';
  }
  function txt(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
  function ownText(el) {
    const t = txt(el.innerText);
    return t.length > 120 ? t.slice(0, 117) + '...' : t;
  }
  function labelFor(el) {
    if (el.labels && el.labels.length) return txt(el.labels[0].innerText);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const n = lb.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(e => txt(e.innerText)).join(' '); if (n) return n; }
    return '';
  }
  function role(el) {
    const r = el.getAttribute('role'); if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === 'a') return el.hasAttribute('href') ? 'link' : 'generic';
    if (t === 'button' || t === 'summary') return 'button';
    if (t === 'select') return 'select';
    if (t === 'textarea') return 'textbox';
    if (t === 'input') {
      const ty = (el.type || 'text').toLowerCase();
      return {checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button', reset: 'button', image: 'button',
              range: 'slider', number: 'spinbutton', search: 'searchbox', file: 'file', hidden: 'hidden'}[ty] || 'textbox';
    }
    if (/^h[1-6]$/.test(t)) return 'heading';
    if (el.isContentEditable) return 'textbox';
    return t;
  }
  function name(el, r) {
    const al = txt(el.getAttribute('aria-label')); if (al) return al;
    const lf = labelFor(el); if (lf) return lf;
    if (['textbox', 'searchbox', 'combobox', 'spinbutton', 'select', 'checkbox', 'radio', 'slider', 'file'].includes(r)) {
      return txt(el.placeholder) || txt(el.getAttribute('title')) || txt(el.name) || '';
    }
    if (el.tagName === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type)) return txt(el.value);
    if (el.tagName === 'IMG') return txt(el.alt);
    let t = ownText(el);
    if (!t) { const img = el.querySelector('img[alt],svg[aria-label],[aria-label]'); if (img) t = txt(img.getAttribute('alt') || img.getAttribute('aria-label')); }
    return t || txt(el.getAttribute('title'));
  }
  function ref(el) {
    let r = W.__brefs.get(el);
    if (!r) { r = 'e' + (++W.__brefn); W.__brefs.set(el, r); }
    W.__brefmap.set(r, el);
    return r;
  }
  function uniqueSelector(el) {
    if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) return '#' + CSS.escape(el.id);
    for (const a of ['data-testid', 'data-test', 'data-cy', 'name', 'aria-label']) {
      const v = el.getAttribute(a);
      if (v) { const s = el.tagName.toLowerCase() + '[' + a + '="' + v.replace(/"/g, '\\"') + '"]'; if (document.querySelectorAll(s).length === 1) return s; }
    }
    const parts = []; let cur = el;
    while (cur && cur !== document.body) {
      if (cur.id) { parts.unshift('#' + CSS.escape(cur.id)); break; }
      const par = cur.parentElement; if (!par) break;
      parts.unshift(cur.tagName.toLowerCase() + ':nth-child(' + (Array.from(par.children).indexOf(cur) + 1) + ')'); cur = par;
    }
    return parts.join(' > ');
  }

  const sel = all ? INTERACTIVE + ',' + LANDMARK + ',' + TEXTY : INTERACTIVE + ',' + LANDMARK;
  const nodes = Array.from(root.querySelectorAll(sel));
  if (root !== document.body && root.matches(sel)) nodes.unshift(root);
  const out = []; let truncated = 0; const seenText = new Set();
  for (const el of nodes) {
    if (!visible(el)) continue;
    const r = role(el);
    if (r === 'hidden') continue;
    const isInter = el.matches(INTERACTIVE);
    // skip wrappers whose only content is one interactive child (a > button, label > input)
    if (isInter && el.children.length === 1 && el.children[0].matches(INTERACTIVE) && !txt(el.childNodes[0].nodeType === 3 ? el.childNodes[0].textContent : '')) continue;
    const rect = el.getBoundingClientRect();
    const n = name(el, r);
    if (!isInter) {
      if (!n) continue;
      const key = r + '|' + n; if (seenText.has(key)) continue; seenText.add(key);
    }
    if (out.length >= max) { truncated++; continue; }
    const item = {role: r, name: n, pos: where(rect)};
    if (isInter) {
      item.ref = ref(el);
      item.box = [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)];
      if (el.tagName === 'A' && el.getAttribute('href')) item.href = el.getAttribute('href').slice(0, 200);
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.value && el.type !== 'password') item.value = String(el.value).slice(0, 80);
        if (el.placeholder && el.placeholder !== n) item.placeholder = el.placeholder;
        if (el.type === 'checkbox' || el.type === 'radio') item.checked = el.checked;
        if (el.type === 'password') item.type = 'password';
        if (el.required) item.required = true;
      }
      if (el.tagName === 'SELECT') {
        item.options = Array.from(el.options).slice(0, 20).map(o => o.text.trim());
        item.value = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : '';
      }
      if (el.hasAttribute('aria-expanded')) item.expanded = el.getAttribute('aria-expanded') === 'true';
      if (el.getAttribute('aria-selected') === 'true' || el.hasAttribute('aria-current')) item.selected = true;
      if (el.disabled || el.getAttribute('aria-disabled') === 'true') item.disabled = true;
      if (all) item.selector = uniqueSelector(el);
    } else if (r === 'heading') {
      item.level = /^H[1-6]$/.test(el.tagName) ? Number(el.tagName[1]) : Number(el.getAttribute('aria-level') || 2);
    }
    out.push(item);
  }
  return {
    elements: out, truncated,
    scrollY: Math.round(W.scrollY), viewportHeight: vh, viewportWidth: vw,
    documentHeight: document.documentElement.scrollHeight,
  };
}
"""


def _fmt_line(e: dict) -> str:
    parts = []
    if e.get("ref"):
        parts.append("@" + e["ref"])
    parts.append(f"h{e.get('level', 2)}" if e["role"] == "heading" else e["role"])
    if e.get("name"):
        parts.append('"' + e["name"].replace('"', '\\"') + '"')
    for k in ("href", "placeholder", "value", "type"):
        if e.get(k):
            parts.append(f'{k}="{e[k]}"')
    if e.get("options"):
        parts.append("[" + " | ".join(e["options"]) + "]")
    for flag in ("checked", "expanded"):
        if flag in e:
            parts.append(f"[{flag}={str(e[flag]).lower()}]")
    for flag in ("selected", "disabled", "required"):
        if e.get(flag):
            parts.append(f"[{flag}]")
    if e.get("pos"):
        parts.append(f"[{e['pos']}]")
    return " ".join(parts)


def format_snapshot(res: dict) -> str:
    head = [f"url: {res['url']}", f"title: {res['title']}"]
    dh, vh, sy = res["documentHeight"], res["viewportHeight"], res["scrollY"]
    if dh > vh + 10:
        head.append(f"scroll: {sy}/{dh - vh} (viewport {res['viewportWidth']}x{vh}; [below]/[above] = outside viewport)")
    lines = [_fmt_line(e) for e in res["elements"]]
    if res.get("truncated"):
        lines.append(f"... {res['truncated']} more element(s) truncated; scope with a selector or raise --max")
    return "\n".join(head + lines)


async def snapshot(s: Session, selector: Optional[str] = None, all: bool = False, max: int = 300,
                   format: str = "text") -> dict[str, Any]:
    page = s.page
    try:
        res = await page.evaluate(SNAPSHOT_JS, {"scope": selector, "all": all, "max": max})
        if "error" in res:
            return {"success": False, "error": res["error"]}
        res["url"], res["title"] = page.url, await page.title()
        if format == "json":
            return {"success": True, **res}
        return {"success": True, "snapshot": format_snapshot(res)}
    except Exception as e:
        logger.error(f"Snapshot failed: {e}")
        return {"success": False, "error": _short(e)}


# ---------------------------------------------------------------------------
# Targeting: @eN ref | text=... | role=button[name=...] | label=... | placeholder=... | CSS/Playwright selector
# ---------------------------------------------------------------------------
_REF = re.compile(r"^@?(e\d+)$")


class _ElementLocator:
    """Minimal Locator-shaped wrapper over an ElementHandle so refs and selectors share one code path."""

    def __init__(self, el):
        self.el = el

    async def click(self, **kw): await self.el.click(**kw)
    async def dblclick(self, **kw): await self.el.dblclick(**kw)
    async def hover(self, **kw): await self.el.hover(**kw)
    async def fill(self, v, **kw): await self.el.fill(v, **kw)
    async def press_sequentially(self, v, **kw): await self.el.type(v, **kw)
    async def press(self, k, **kw): await self.el.press(k, **kw)
    async def select_option(self, *a, **kw): return await self.el.select_option(*a, **kw)
    async def screenshot(self, **kw): return await self.el.screenshot(**kw)
    async def scroll_into_view_if_needed(self, **kw): await self.el.scroll_into_view_if_needed(**kw)


async def resolve(s: Session, target: str = "", *, text: Optional[str] = None, role: Optional[str] = None,
                  name: Optional[str] = None, label: Optional[str] = None, placeholder: Optional[str] = None):
    page = s.page
    if role:
        return page.get_by_role(role, name=name or text, exact=bool(name or text))
    if label:
        return page.get_by_label(label)
    if placeholder:
        return page.get_by_placeholder(placeholder)
    if text:
        return page.get_by_text(text, exact=True)
    if not target:
        raise ValueError("no target given (use @ref, a selector, or --text/--role/--label/--placeholder)")
    m = _REF.match(target)
    if m:
        handle = await page.evaluate_handle("(r) => (window.__brefmap && window.__brefmap.get(r)) || null", m.group(1))
        el = handle.as_element()
        if el is None:
            raise ValueError(f"ref @{m.group(1)} is unknown or stale (page changed); run snapshot again")
        return _ElementLocator(el)
    if target.startswith("text="):
        return page.get_by_text(target[5:], exact=True)
    if target.startswith("label="):
        return page.get_by_label(target[6:])
    if target.startswith("placeholder="):
        return page.get_by_placeholder(target[12:])
    rm = re.match(r"^role=(\w+)(?:\[name=(.+)\])?$", target)
    if rm:
        return page.get_by_role(rm.group(1), name=rm.group(2), exact=bool(rm.group(2)))
    return page.locator(target)


SETTLE_JS = """
([quietMs, maxMs]) => new Promise(resolve => {
  let last = performance.now(); const start = last;
  const obs = new MutationObserver(() => { last = performance.now(); });
  obs.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  const tick = () => {
    const now = performance.now();
    if (now - last >= quietMs || now - start >= maxMs) { obs.disconnect(); resolve(Math.round(now - start)); }
    else setTimeout(tick, 15);
  };
  setTimeout(tick, 15);
})
"""


async def settle(page: Page, quiet_ms: int = 60, max_ms: int = 500):
    """Wait until the DOM has been quiet for `quiet_ms` (bounded by `max_ms`), so a following
    snapshot sees the post-action state without the agent adding sleeps by hand."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
        await page.evaluate(SETTLE_JS, [quiet_ms, max_ms])
    except Exception:
        pass


async def _after(s: Session, result: dict, snap: bool, do_settle: bool = True) -> dict:
    page = s.page
    if do_settle or snap:
        await settle(page)
    result.update({"url": page.url, "title": await page.title()})
    if snap:
        sn = await snapshot(s)
        result["snapshot"] = sn.get("snapshot") or sn.get("error")
    return result


def _targeting(kw: dict) -> dict:
    return {k: kw.get(k) for k in ("text", "role", "name", "label", "placeholder")}


def _short(e: Exception) -> str:
    """Playwright errors carry a multi-line call log; keep the informative lines only."""
    lines = [l for l in str(e).splitlines() if l.strip() and not l.startswith("=")]
    return "\n".join(lines[:4])


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
async def navigate(s: Session, url: str, wait: str = "load", timeout: float = 30000, snap: bool = False) -> dict[str, Any]:
    """`wait`: commit | domcontentloaded | load (default) | networkidle (never fatal: SPAs with
    long-polling never go idle, so a timeout after the page has a URL is `settled: false`)."""
    page = s.page
    settled = True
    try:
        if wait == "networkidle":
            await page.goto(url, wait_until="load", timeout=timeout)
            try:
                await page.wait_for_load_state("networkidle", timeout=min(timeout, 5000))
            except Exception:
                settled = False
        else:
            await page.goto(url, wait_until=wait, timeout=timeout)
        return await _after(s, {"success": True, "settled": settled}, snap)
    except Exception as e:
        if page.url and page.url != "about:blank" and "Timeout" in str(e):
            return await _after(s, {"success": True, "settled": False, "warning": str(e).splitlines()[0]}, snap)
        logger.error(f"Navigation failed: {e}")
        return {"success": False, "error": _short(e)}


async def click(s: Session, selector: str = "", snap: bool = False, double: bool = False, **kw) -> dict[str, Any]:
    try:
        loc = await resolve(s, selector, **_targeting(kw))
        if double:
            await loc.dblclick(timeout=ACTION_TIMEOUT)
        else:
            await loc.click(timeout=ACTION_TIMEOUT)
        return await _after(s, {"success": True}, snap)
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def type_text(s: Session, selector: str = "", text_value: str = "", snap: bool = False, sequential: bool = False,
                    submit: bool = False, **kw) -> dict[str, Any]:
    """fill() by default (instant); `sequential` sends real key events for comboboxes/autocomplete."""
    try:
        loc = await resolve(s, selector, **_targeting(kw))
        if sequential:
            await loc.fill("", timeout=ACTION_TIMEOUT)
            await loc.press_sequentially(text_value, timeout=ACTION_TIMEOUT)
        else:
            await loc.fill(text_value, timeout=ACTION_TIMEOUT)
        if submit:
            await loc.press("Enter")
        return await _after(s, {"success": True}, snap, do_settle=submit)
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def hover(s: Session, selector: str = "", snap: bool = False, **kw) -> dict[str, Any]:
    try:
        loc = await resolve(s, selector, **_targeting(kw))
        await loc.hover(timeout=ACTION_TIMEOUT)
        return await _after(s, {"success": True}, snap)
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def select_option(s: Session, selector: str = "", value: str = "", snap: bool = False, **kw) -> dict[str, Any]:
    try:
        loc = await resolve(s, selector, **_targeting(kw))
        try:
            await loc.select_option(value, timeout=ACTION_TIMEOUT)
        except Exception:
            await loc.select_option(label=value, timeout=ACTION_TIMEOUT)
        return await _after(s, {"success": True}, snap)
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def press_key(s: Session, key: str, selector: str = "", snap: bool = False, **kw) -> dict[str, Any]:
    try:
        if selector or any(_targeting(kw).values()):
            loc = await resolve(s, selector, **_targeting(kw))
            await loc.press(key, timeout=ACTION_TIMEOUT)
        else:
            await s.page.keyboard.press(key)
        return await _after(s, {"success": True}, snap)
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def scroll(s: Session, direction: str = "down", amount: Optional[int] = None, selector: str = "",
                 snap: bool = False, **kw) -> dict[str, Any]:
    page = s.page
    try:
        if selector or any(_targeting(kw).values()):
            loc = await resolve(s, selector, **_targeting(kw))
            await loc.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT)
        else:
            vh = page.viewport_size["height"] if page.viewport_size else 800
            dy = amount if amount is not None else int(vh * 0.8)
            await page.mouse.wheel(0, -dy if direction == "up" else dy)
        return await _after(s, {"success": True}, snap)
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def get_text(s: Session, selector: str = "body", max: int = 20000) -> dict[str, Any]:
    """Readable text of the page (or one element): for extraction, far cheaper than snapshot --all."""
    try:
        t = await s.page.locator(selector).first.inner_text(timeout=ACTION_TIMEOUT)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t).strip()
        return {"success": True, "text": t[:max], "truncated": len(t) > max}
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def evaluate(s: Session, expression: str) -> dict[str, Any]:
    try:
        return {"success": True, "result": await s.page.evaluate(expression)}
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def wait_for(s: Session, text: Optional[str] = None, selector: Optional[str] = None, gone: bool = False,
                   timeout: float = 10000) -> dict[str, Any]:
    page = s.page
    try:
        state = "hidden" if gone else "visible"
        if text:
            await page.get_by_text(text).first.wait_for(state=state, timeout=timeout)
        elif selector:
            await page.locator(selector).first.wait_for(state=state, timeout=timeout)
        else:
            await page.wait_for_timeout(min(timeout, 30000))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def screenshot(s: Session, selector: Optional[str] = None, output: Optional[str] = None, full_page: bool = False,
                     quality: int = 70, **kw) -> dict[str, Any]:
    page = s.page
    try:
        opts = {"type": "jpeg", "quality": quality}
        if selector or any(_targeting(kw).values()):
            loc = await resolve(s, selector or "", **_targeting(kw))
            image = await loc.screenshot(**opts)
        else:
            image = await page.screenshot(full_page=full_page, **opts)
        if output:
            path = Path(output).expanduser()
        else:
            SHOTS_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(SHOTS_DIR, 0o700)
            path = SHOTS_DIR / f"{s.id}_{int(time.time() * 1000)}.jpg"
        path.write_bytes(image)
        os.chmod(path, 0o600)
        return {"success": True, "path": str(path), "bytes": len(image), "format": "jpeg"}
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def console_logs(s: Session, clear: bool = False) -> dict[str, Any]:
    logs = list(s.console)
    if clear:
        s.console.clear()
    return {"success": True, "logs": logs}


async def go_back(s: Session, snap: bool = False) -> dict[str, Any]:
    try:
        await s.page.go_back(wait_until="domcontentloaded", timeout=15000)
        return await _after(s, {"success": True}, snap)
    except Exception as e:
        return {"success": False, "error": _short(e)}


async def go_forward(s: Session, snap: bool = False) -> dict[str, Any]:
    try:
        await s.page.go_forward(wait_until="domcontentloaded", timeout=15000)
        return await _after(s, {"success": True}, snap)
    except Exception as e:
        return {"success": False, "error": _short(e)}


ACTIONS = {
    "navigate": navigate,
    "snapshot": snapshot,
    "click": click,
    "type": type_text,
    "hover": hover,
    "select_option": select_option,
    "press_key": press_key,
    "scroll": scroll,
    "text": get_text,
    "eval": evaluate,
    "wait": wait_for,
    "screenshot": screenshot,
    "console_logs": console_logs,
    "go_back": go_back,
    "go_forward": go_forward,
}
