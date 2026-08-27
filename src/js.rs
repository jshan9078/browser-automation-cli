//! JavaScript injected into pages. Everything that needs DOM knowledge lives here so that the
//! snapshot and the targeting share one definition of role/name/visibility. Walks same-origin
//! iframes and open shadow roots; boxes are reported in top-page viewport coordinates so CDP input
//! events (which are page-global) work for elements inside frames.

/// Shared helpers: visibility, role, accessible name, deep DOM walk, ref bookkeeping.
pub const LIB: &str = r##"
(() => {
  const W = window;
  if (W.__blib) return;
  if (!W.__brefs) { W.__brefs = new WeakMap(); W.__brefmap = new Map(); W.__brefn = 0; }
  const INTERACTIVE = 'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=menuitemcheckbox],[role=menuitemradio],[role=option],[role=checkbox],[role=radio],[role=switch],[role=combobox],[role=textbox],[role=searchbox],[role=slider],[role=spinbutton],[role=gridcell],[contenteditable=true],[contenteditable=""],[tabindex]:not([tabindex="-1"])';
  const LANDMARK = 'h1,h2,h3,[role=dialog],[role=alertdialog],[role=alert],[role=status],[aria-live]:not([aria-live=off]),[role=heading]';
  const TEXTY = 'p,li,td,th,dt,dd,label,legend,figcaption,blockquote,pre,h4,h5,h6';
  const txt = s => (s || '').replace(/\s+/g, ' ').trim();
  function visible(el) {
    if (el.closest('[aria-hidden="true"]')) return false;
    if (typeof el.checkVisibility === 'function' && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    const r = el.getBoundingClientRect();
    return !(r.width < 1 && r.height < 1);
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
  function labelFor(el) {
    if (el.labels && el.labels.length) return txt(el.labels[0].innerText);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const d = el.ownerDocument; const n = lb.split(/\s+/).map(id => d.getElementById(id)).filter(Boolean).map(e => txt(e.innerText)).join(' '); if (n) return n; }
    return '';
  }
  function ownText(el) { const t = txt(el.innerText); return t.length > 120 ? t.slice(0, 117) + '...' : t; }
  function name(el, r) {
    const al = txt(el.getAttribute('aria-label')); if (al) return al;
    const lf = labelFor(el); if (lf) return lf;
    if (['textbox', 'searchbox', 'combobox', 'spinbutton', 'select', 'checkbox', 'radio', 'slider', 'file'].includes(r))
      return txt(el.placeholder) || txt(el.getAttribute('title')) || txt(el.name) || '';
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
  // Deep walk: yields {el, off:{x,y}, frame} for every element in the document, open shadow roots,
  // and same-origin iframes (offset = iframe position in top-page coordinates).
  function* walk(root, off, depth) {
    const it = root.ownerDocument ? root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_ELEMENT) : document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let n = root.nodeType === 1 ? root : it.nextNode();
    while (n) {
      yield {el: n, off};
      if (n.shadowRoot && depth < 8) { for (const x of walk(n.shadowRoot, off, depth + 1)) yield x; }
      if (n.tagName === 'IFRAME' && depth < 4) {
        let d = null; try { d = n.contentDocument; } catch (e) {}
        if (d && d.body) { const r = n.getBoundingClientRect(); for (const x of walk(d.body, {x: off.x + r.x, y: off.y + r.y}, depth + 1)) yield x; }
      }
      n = it.nextNode();
    }
  }
  function deepQuery(sel) {
    const out = [];
    for (const {el, off} of walk(document.body, {x: 0, y: 0}, 0)) { try { if (el.matches(sel)) out.push({el, off}); } catch (e) { throw new Error('invalid selector: ' + sel); } }
    return out;
  }
  function box(el, off) { const r = el.getBoundingClientRect(); return [Math.round(r.x + off.x), Math.round(r.y + off.y), Math.round(r.width), Math.round(r.height)]; }
  function where(b) {
    const vh = W.innerHeight, vw = W.innerWidth;
    if (b[1] + b[3] < 0) return 'above'; if (b[1] > vh) return 'below'; if (b[0] + b[2] < 0 || b[0] > vw) return 'offside'; return '';
  }
  W.__blib = {INTERACTIVE, LANDMARK, TEXTY, txt, visible, role, name, ref, walk, deepQuery, box, where};
})();
"##;

/// (args: {scope, all, max}) -> snapshot data
pub const SNAPSHOT: &str = r##"
(args) => {
  const L = window.__blib; const {scope, all, max} = args;
  let roots = [{el: document.body, off: {x: 0, y: 0}}];
  if (scope) { roots = L.deepQuery(scope).slice(0, 1); if (!roots.length) return {error: 'scope not found: ' + scope}; }
  const sel = all ? L.INTERACTIVE + ',' + L.LANDMARK + ',' + L.TEXTY : L.INTERACTIVE + ',' + L.LANDMARK;
  const out = []; let truncated = 0; const seen = new Set();
  for (const root of roots) for (const {el, off} of L.walk(root.el, root.off, 0)) {
    if (!el.matches(sel) || !L.visible(el)) continue;
    const r = L.role(el); if (r === 'hidden') continue;
    const isInter = el.matches(L.INTERACTIVE);
    if (isInter && el.children.length === 1 && el.children[0].matches(L.INTERACTIVE) && !L.txt(el.childNodes[0].nodeType === 3 ? el.childNodes[0].textContent : '')) continue;
    const n = L.name(el, r);
    if (!isInter) { if (!n) continue; const k = r + '|' + n; if (seen.has(k)) continue; seen.add(k); }
    if (out.length >= max) { truncated++; continue; }
    const b = L.box(el, off);
    const item = {role: r, name: n, pos: L.where(b)};
    if (isInter) {
      item.ref = L.ref(el); item.box = b;
      if (el.tagName === 'A' && el.getAttribute('href')) item.href = el.getAttribute('href').slice(0, 200);
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.value && el.type !== 'password') item.value = String(el.value).slice(0, 80);
        if (el.placeholder && el.placeholder !== n) item.placeholder = el.placeholder;
        if (el.type === 'checkbox' || el.type === 'radio') item.checked = el.checked;
        if (el.type === 'password') item.type = 'password';
        if (el.required) item.required = true;
      }
      if (el.tagName === 'SELECT') { item.options = Array.from(el.options).slice(0, 20).map(o => o.text.trim()); item.value = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : ''; }
      if (el.hasAttribute('aria-expanded')) item.expanded = el.getAttribute('aria-expanded') === 'true';
      if (el.getAttribute('aria-selected') === 'true' || el.hasAttribute('aria-current')) item.selected = true;
      if (el.disabled || el.getAttribute('aria-disabled') === 'true') item.disabled = true;
      if (el.ownerDocument !== document) item.frame = true;
    } else if (r === 'heading') item.level = /^H[1-6]$/.test(el.tagName) ? Number(el.tagName[1]) : Number(el.getAttribute('aria-level') || 2);
    out.push(item);
  }
  return {elements: out, truncated, scrollY: Math.round(window.scrollY), viewportHeight: window.innerHeight, viewportWidth: window.innerWidth, documentHeight: document.documentElement.scrollHeight, title: document.title, url: location.href};
}
"##;

/// (t: {target, text, role, name, label, placeholder}) -> {ok, box, tag, type, reason} and sets window.__btarget.
/// Strict: more than one match is an error, like Playwright locators.
pub const RESOLVE: &str = r##"
(function resolve(t) {
  const L = window.__blib;
  const all = () => Array.from(L.walk(document.body, {x: 0, y: 0}, 0));
  const byPred = (pred) => all().filter(x => { try { return L.visible(x.el) && pred(x.el); } catch (e) { return false; } });
  let matches = null, desc = '';
  const eq = (a, b) => L.txt(a).toLowerCase() === L.txt(b).toLowerCase();
  if (t.role) { const want = t.name || t.text; matches = byPred(el => L.role(el) === t.role && (!want || eq(L.name(el, t.role), want))); desc = `role=${t.role}` + (want ? `[name=${want}]` : ''); }
  else if (t.label) { matches = byPred(el => el.matches(L.INTERACTIVE) && (eq(L.name(el, L.role(el)), t.label) || L.txt(L.name(el, L.role(el))).toLowerCase().startsWith(L.txt(t.label).toLowerCase()))); desc = 'label=' + t.label; }
  else if (t.placeholder) { matches = byPred(el => el.placeholder && eq(el.placeholder, t.placeholder)); desc = 'placeholder=' + t.placeholder; }
  else if (t.text) {
    const want = L.txt(t.text).toLowerCase();
    // innermost elements whose own text equals the wanted text; prefer interactive ancestors
    let m = byPred(el => { const tx = L.txt(el.innerText).toLowerCase(); if (tx !== want) return false; return !Array.from(el.children).some(c => L.txt(c.innerText).toLowerCase() === want); });
    m = m.map(x => { const a = x.el.closest(L.INTERACTIVE); return a && L.visible(a) ? {el: a, off: x.off} : x; });
    const seen = new Set(); matches = m.filter(x => { if (seen.has(x.el)) return false; seen.add(x.el); return true; }); desc = 'text=' + t.text;
  } else {
    const s = t.target || '';
    const m = /^@?(e\d+)$/.exec(s);
    if (m) { const el = window.__brefmap && window.__brefmap.get(m[1]); if (!el || !el.isConnected) return {ok: false, reason: 'ref @' + m[1] + ' is unknown or stale (page changed); run snapshot again', fatal: true};
      return finish([{el, off: offsetOf(el)}], '@' + m[1]); }
    if (s.startsWith('text=')) return resolve({text: s.slice(5)});
    if (s.startsWith('label=')) return resolve({label: s.slice(6)});
    if (s.startsWith('placeholder=')) return resolve({placeholder: s.slice(12)});
    const rm = /^role=(\w+)(?:\[name=(.+)\])?$/.exec(s); if (rm) return resolve({role: rm[1], name: rm[2]});
    if (!s) return {ok: false, reason: 'no target given (use @ref, a selector, or --text/--role/--label/--placeholder)', fatal: true};
    let q; try { q = L.deepQuery(s); } catch (e) { return {ok: false, reason: e.message, fatal: true}; }
    matches = q; desc = s;
  }
  return finish(matches, desc);
  function offsetOf(el) { let d = el.ownerDocument, off = {x: 0, y: 0}; while (d !== document) { const f = d.defaultView && d.defaultView.frameElement; if (!f) break; const r = f.getBoundingClientRect(); off = {x: off.x + r.x, y: off.y + r.y}; d = f.ownerDocument; } return off; }
  function finish(ms, desc) {
    if (!ms.length) return {ok: false, reason: 'no element matches ' + desc};
    if (ms.length > 1) return {ok: false, reason: 'strict mode violation: ' + desc + ' resolved to ' + ms.length + ' elements; use an @ref from snapshot or a more specific target', fatal: true};
    const el = ms[0].el; window.__btarget = el;
    if (!L.visible(el)) return {ok: false, reason: desc + ' is not visible'};
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return {ok: false, reason: desc + ' is disabled'};
    try { el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'}); } catch (e) {}
    const b = L.box(el, ms[0].off);
    const cx = b[0] + b[2] / 2, cy = b[1] + b[3] / 2;
    // hit test: the element (or a descendant / shadow host chain) must be what is at the point
    let hit = document.elementFromPoint(cx, cy); let ok = false; let guard = 0;
    while (hit && guard++ < 10) { if (hit === el || el.contains(hit) || (hit.shadowRoot && hit.shadowRoot.contains(el))) { ok = true; break; } if (hit.tagName === 'IFRAME') { try { const r = hit.getBoundingClientRect(); hit = hit.contentDocument.elementFromPoint(cx - r.x, cy - r.y); continue; } catch (e) { break; } } if (hit.shadowRoot) { hit = hit.shadowRoot.elementFromPoint(cx, cy); continue; } break; }
    if (!ok) { const h = document.elementFromPoint(cx, cy); return {ok: false, reason: desc + ' is covered by ' + (h ? '<' + h.tagName.toLowerCase() + (h.id ? '#' + h.id : '') + '>' : 'another element') + ' at its center; dismiss the overlay first', box: b}; }
    return {ok: true, box: b, x: cx, y: cy, tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(), editable: !!(el.isContentEditable || ['INPUT', 'TEXTAREA'].includes(el.tagName))};
  }
})
"##;

/// Prepare window.__btarget for typing: focus and select its contents; returns whether it is a file/select input.
pub const FOCUS_SELECT_ALL: &str = r##"
() => { const el = window.__btarget; if (!el) return {ok: false};
  el.focus();
  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') { try { el.select(); } catch (e) {} if (el.type === 'file') return {ok: false, reason: 'file inputs are not supported'}; }
  else if (el.isContentEditable) { const s = el.ownerDocument.getSelection(); const r = el.ownerDocument.createRange(); r.selectNodeContents(el); s.removeAllRanges(); s.addRange(r); }
  return {ok: true, tag: el.tagName.toLowerCase()}; }
"##;

/// Clear the focused editable (used before insertText so that `fill` replaces rather than appends).
pub const CLEAR: &str = r##"
() => { const el = window.__btarget; if (!el) return false;
  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
    const proto = el.tagName === 'INPUT' ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
    const set = Object.getOwnPropertyDescriptor(proto, 'value').set; set.call(el, '');
    el.dispatchEvent(new Event('input', {bubbles: true}));
  } else if (el.isContentEditable) { el.textContent = ''; el.dispatchEvent(new Event('input', {bubbles: true})); }
  return true; }
"##;

/// (value) -> select an <option> on window.__btarget by value or label; dispatch input/change.
pub const SELECT_OPTION: &str = r##"
(v) => { const el = window.__btarget; if (!el || el.tagName !== 'SELECT') return {ok: false, reason: 'target is not a <select>'};
  let o = Array.from(el.options).find(o => o.value === v) || Array.from(el.options).find(o => o.text.trim() === v) || Array.from(el.options).find(o => o.text.trim().toLowerCase() === v.toLowerCase());
  if (!o) return {ok: false, reason: 'no option "' + v + '" (have: ' + Array.from(el.options).map(o => o.text.trim()).join(', ') + ')'};
  el.value = o.value; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); return {ok: true}; }
"##;

/// ([quietMs, maxMs]) -> resolves when the DOM has been quiet for quietMs (bounded by maxMs).
pub const SETTLE: &str = r##"
([quietMs, maxMs]) => new Promise(resolve => {
  let last = performance.now(); const start = last;
  const obs = new MutationObserver(() => { last = performance.now(); });
  obs.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  const tick = () => { const now = performance.now();
    if (now - last >= quietMs || now - start >= maxMs) { obs.disconnect(); resolve(Math.round(now - start)); } else setTimeout(tick, 15); };
  setTimeout(tick, 15);
})
"##;

/// (selector, max) -> readable text
pub const TEXT: &str = r##"
(sel, max) => { const L = window.__blib; const m = sel === 'body' ? [{el: document.body}] : L.deepQuery(sel); if (!m.length) return {error: 'no element matches ' + sel};
  let t = (m[0].el.innerText || '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim(); return {text: t.slice(0, max), truncated: t.length > max}; }
"##;

/// (text, selector, gone) -> bool: condition currently satisfied
pub const WAIT_CHECK: &str = r##"
(text, sel, gone) => { const L = window.__blib; let found = false;
  if (text) { const w = L.txt(text).toLowerCase(); for (const {el} of L.walk(document.body, {x: 0, y: 0}, 0)) { if (L.visible(el) && L.txt(el.innerText).toLowerCase().includes(w)) { found = true; break; } } }
  else if (sel) { found = L.deepQuery(sel).some(x => L.visible(x.el)); }
  return gone ? !found : found; }
"##;

pub const LOCAL_STORAGE_DUMP: &str = r##"() => { try { return {origin: location.origin, items: Object.assign({}, localStorage)}; } catch (e) { return null; } }"##;

pub const STEALTH: &str = r##"Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});"##;
