"""Forms and result rows, site-agnostic.

Controls get a code-owned id (data-kfw-id) when observed; every action names that id, never a
selector the model wrote. Each action is verified by reading the value back (thsrc.com.tw's date
widget swallowed Cmd+A and produced "2026/02026/10/059/29": TRAPS web-agent-false-done-before-async-results).
"""

import json
import time

from . import safety

# Shared observation code. One JS body that defines `O`; every observation entry point below is this body
# plus one return statement, so recording and execution cannot drift apart (design 3.1, principle 5).
OBSERVE_JS = "const KFW_RULES = " + json.dumps(safety.js_rules(), ensure_ascii=False) + ";\n" + r"""
const O = (() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = e => { const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const labelOf = e => {
    if (e.getAttribute('aria-label')) return norm(e.getAttribute('aria-label'));
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) return norm(l.innerText); }
    const wrap = e.closest('label'); if (wrap) return norm(wrap.innerText).slice(0, 40);
    // nearest preceding text in the same form group
    let n = e, hops = 0;
    while (n && hops++ < 4) { let p = n.previousElementSibling;
      while (p) { const t = norm(p.innerText); if (t && t.length <= 20) return t; p = p.previousElementSibling; }
      n = n.parentElement; }
    return norm(e.placeholder || e.name || e.id || '');
  };

  // Safety vocabulary comes from kfw/safety_rules.json (injected as KFW_RULES), never hand-written here.
  // Same matching as kfw/safety.py: zh = normalized containment; en = lowercase with ASCII word boundaries.
  const R = KFW_RULES;
  const zhNorm = s => (s || '').normalize('NFKC').toLowerCase().replace(/ /g, '');
  const enNorm = s => (s || '').normalize('NFKC').toLowerCase();
  const compile = r => ({zh: r.zh, en: r.en.map(p => new RegExp(p))});
  const RULE = {forbidden: compile(R.forbidden_click), stateful: compile(R.stateful_click), label: compile(R.sensitive_label)};
  const hits = (rule, s) => { const z = zhNorm(s), e = enNorm(s); return rule.zh.some(t => z.includes(t)) || rule.en.some(re => re.test(e)); };
  const classify = s => ({forbidden: hits(RULE.forbidden, s), stateful: hits(RULE.stateful, s), sensitive_label: hits(RULE.label, s)});
  const acSensitive = v => (v || '').toLowerCase().split(/[ \t\r\n]+/).filter(Boolean).some(tok => R.sensitive_autocomplete.some(p =>
    p.endsWith('*') ? tok.length > p.length - 1 && tok.startsWith(p.slice(0, -1)) : tok === p));
  const TEXTLESS = ['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'hidden', 'file', 'range', 'color'];
  // Sensitive fields: their value is never read into the snapshot, only `sensitive` and `has_value`.
  const sensitiveFor = (tag, type, autocomplete, label) => {
    if (tag !== 'INPUT' && tag !== 'TEXTAREA') return false;
    const t = (type || '').toLowerCase();
    if (R.sensitive_input_types.includes(t) || acSensitive(autocomplete)) return true;
    if (TEXTLESS.includes(t)) return false;
    return hits(RULE.label, typeof label === 'function' ? label() : label);
  };
  const isSensitive = e => sensitiveFor(e.tagName, e.type, e.getAttribute('autocomplete'), () => labelOf(e));
  const formOf = e => e.form || e.closest('form') || null;  // e.form also follows the form= attribute
  const formHasSensitive = (f, cache) => {
    if (!f) return false;
    if (cache && cache.has(f)) return cache.get(f);
    const v = [...f.elements].some(isSensitive);
    if (cache) cache.set(f, v);
    return v;
  };
  const nextSeq = name => (window[name] = (window[name] || 0) + 1);
  const formId = f => { if (!f) return null; if (!f.dataset.kfwForm) f.dataset.kfwForm = 'f' + nextSeq('__kfwFormSeq'); return f.dataset.kfwForm; };

  const snapshot = root => {
    let seq = window.__kfwSeq || 0; const out = [], fcache = new Map();
    for (const e of root.querySelectorAll('select, input, textarea, button, [role=button], a[href]')) {
      if (!visible(e) || e.disabled || e.type === 'hidden') continue;
      if (!e.dataset.kfwId) e.dataset.kfwId = 'k' + (++seq);
      const sensitive = isSensitive(e), f = formOf(e);
      const base = {id: e.dataset.kfwId, label: labelOf(e)};
      const extra = {name: e.getAttribute('name') || '', autocomplete: e.getAttribute('autocomplete') || '',
        form_id: formId(f), form_has_sensitive: formHasSensitive(f, fcache), sensitive,
        native: ['SELECT', 'INPUT', 'TEXTAREA'].includes(e.tagName)};
      if (e.tagName === 'SELECT') out.push({...base, kind: 'select', value: e.selectedOptions[0]?.text.trim() || '',
          options: [...e.options].filter(o => !o.disabled).map(o => o.text.trim()).slice(0, 60),
          ...extra, has_value: !!(e.selectedOptions[0]?.text.trim())});
      else if (e.tagName === 'INPUT' && ['checkbox', 'radio'].includes(e.type))
        out.push({...base, kind: e.type, checked: e.checked, ...extra, has_value: e.checked});
      else if (e.tagName === 'INPUT' && ['submit', 'button', 'reset', 'image'].includes(e.type)) {
        // <input type=submit value="查詢"> is a button, not a text box: many real forms submit this way
        const t = norm(e.value || e.getAttribute('aria-label') || e.alt);
        if (!t || t.length > 40) continue;
        out.push({...base, kind: 'button', label: t, native: false, ...extra, has_value: false}); }
      else if (e.tagName === 'INPUT' || e.tagName === 'TEXTAREA')
        out.push({...base, kind: 'text', value: sensitive ? '' : e.value, readonly: e.readOnly, input_type: e.type,
          placeholder: e.placeholder || undefined, ...extra, has_value: e.value !== ''});
      else { const t = norm(e.innerText || e.value || e.getAttribute('aria-label')); if (!t || t.length > 40) continue;
        out.push({...base, kind: e.tagName === 'A' ? 'link' : 'button', label: t, ...extra, has_value: false}); }
    }
    window.__kfwSeq = seq;
    return out;
  };

  // Repeating groups: same-signature siblings, >= 60% of them matching, at least minRows matches.
  const sig = e => e.tagName + '.' + [...e.classList].filter(c => !/\d{3,}/.test(c)).slice(0, 3).sort().join('.');
  const collect = (root, pattern, minRows) => {
    const re = pattern == null ? null : new RegExp(pattern);
    const found = [];
    // a user's mark (no pattern): the marked container itself is a candidate parent, its direct children are the rows.
    // With a pattern (the engines) the scan stays exactly as before (equivalence tests).
    for (const parent of (re ? [...root.querySelectorAll('*')] : [root, ...root.querySelectorAll('*')])) {
      const by = {};
      for (const k of parent.children) (by[sig(k)] ||= []).push(k);
      for (const items of Object.values(by)) {
        // no pattern (a user's mark): hidden rows (innerText of an unrendered node is its full textContent!) are not what they saw (e.g. collapsed per-train stop lists), and a table row has at least two parts (paragraphs are a text block, not a table)
        const good = re ? items.filter(k => re.test(norm(k.innerText))) : items.filter(k => visible(k) && k.children.length >= 2 && norm(k.innerText) !== '');
        if (good.length < minRows || good.length < 0.6 * items.length) continue;
        // skipped: same-signature siblings the pattern did NOT match (a too-narrow pattern drops rows silently otherwise)
        found.push({good, score: good.reduce((a, k) => a + norm(k.innerText).length, 0), skipped: items.length - good.length});
      }
    }
    return found;
  };
  const best = found => {
    let b = null;
    for (const g of found)
      if (!b || g.good.length > b.good.length || (g.good.length === b.good.length && g.score > b.score)) b = g;
    return b;
  };
  const cellsOf = k => {
    const cells = [...k.children].map(c => norm(c.innerText)).filter(Boolean);
    return cells.length > 1 ? cells : norm(k.innerText).split(/\s*\n\s*|\s{2,}/).filter(Boolean);
  };
  // Fingerprint of a group = hash of its canonical cells (never DOM ids), so recording and replay agree.
  const fingerprint = cellsList => {
    const s = JSON.stringify(cellsList); let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i);
      h1 = Math.imul(h1 ^ c, 2654435761); h2 = Math.imul(h2 ^ c, 1597334677); }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16);
  };
  const LIMIT = 200;

  // Every qualifying group, marked in the DOM (data-kfw-group / data-kfw-row; valid until the next call).
  const groups = (rootSelector, pattern, minRows, withControls) => {
    // rootSelector: a CSS selector string, or (recorder mark) an Element; falsy = the whole body
    const root = rootSelector ? (typeof rootSelector === 'string' ? document.querySelector(rootSelector) : rootSelector) : document.body;
    if (!root) return [];
    if (minRows == null) minRows = pattern == null ? 2 : 1;
    for (const e of document.querySelectorAll('[data-kfw-row], [data-kfw-group]')) { delete e.dataset.kfwRow; delete e.dataset.kfwGroup; }
    return collect(root, pattern, minRows).map(g => {
      const gid = 'g' + nextSeq('__kfwGroupSeq');
      const rows = g.good.slice(0, LIMIT).map(k => {
        const rid = 'r' + nextSeq('__kfwRowSeq');
        k.dataset.kfwRow = rid; k.dataset.kfwGroup = gid;
        return {row_id: rid, cells: cellsOf(k), text: norm(k.innerText), controls: withControls ? snapshot(k) : []};
      });
      return {group_id: gid, fingerprint: fingerprint(rows.map(r => r.cells)), rows, total: g.good.length, skipped: g.skipped};
    });
  };

  // legacy rows(): the best group's cells, exactly what ROWS_JS returned before WP0b. No DOM writes.
  const legacyRows = (pattern, minRows) => {
    const b = best(collect(document.body, pattern, minRows));
    return b ? b.good.slice(0, LIMIT).map(cellsOf) : [];
  };
  // Best group plus how many *other* groups also qualify. A group nested in / around the chosen one (a lone
  // <tbody> wrapping the rows, cells inside a row) is the same table seen at another level, not a rival.
  const rowsDetail = (pattern, minRows) => {
    const found = collect(document.body, pattern, minRows), b = best(found);
    if (!b) return {rows: [], group_fingerprint: null, other_qualifying_groups: 0, rows_skipped: 0};
    const rows = b.good.slice(0, LIMIT).map(cellsOf);
    const overlap = (g, h) => g === h || g.good.some(x => h.good.some(y => x.contains(y) || y.contains(x)));
    // rivals are counted once per region: a rival table's rows and its wrapping <tbody> are one rival
    const kept = [];
    for (const g of found.filter(g => !overlap(g, b)).sort((p, q) => q.good.length - p.good.length || q.score - p.score))
      if (!kept.some(k => overlap(g, k))) kept.push(g);
    return {rows, group_fingerprint: fingerprint(rows), other_qualifying_groups: kept.length, rows_skipped: b.skipped};
  };
  // One node, read fresh for the safety gate (kfw/safety.py gate). Never returns a field's value.
  const describe = id => {
    const e = document.querySelector(`[data-kfw-id="${CSS.escape(id)}"]`);
    if (!e || !e.isConnected) return {ok: false, why: 'gone'};
    const t = (e.type || '').toLowerCase();
    const valueText = e.tagName === 'BUTTON' || (e.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(t));
    return {ok: true, tag: e.tagName, type: t, text: norm(e.innerText || (valueText ? e.value : '')),
      aria_label: norm(e.getAttribute('aria-label')), label: labelOf(e), name: e.getAttribute('name') || '',
      autocomplete: e.getAttribute('autocomplete') || '', sensitive: isSensitive(e),
      form_has_sensitive: formHasSensitive(formOf(e))};
  };
  return {norm, visible, labelOf, snapshot, groups, legacyRows, rowsDetail, isSensitive, describe, classify, acSensitive, sensitiveFor,
    sig, fingerprint};
})();
"""

CONTROLS_JS = "(() => {" + OBSERVE_JS + "\n  return O.snapshot(document);\n})()"
ROWS_JS = "((pattern, minRows) => {" + OBSERVE_JS + "\n  return O.legacyRows(pattern, minRows);\n})"
ROWS_DETAIL_JS = "((pattern, minRows) => {" + OBSERVE_JS + "\n  return O.rowsDetail(pattern, minRows);\n})"
CLICKABLES_JS = "(() => {" + OBSERVE_JS + r"""
  let seq = window.__kfwSeq || 0; const out = [];
  for (const e of document.querySelectorAll('button, [role=button], a[href]')) {
    if (!O.visible(e)) continue;
    const t = O.norm(e.innerText || e.value || e.getAttribute('aria-label'));
    if (!t || t.length > 40) continue;
    if (!e.dataset.kfwId) e.dataset.kfwId = 'k' + (++seq);
    out.push({id: e.dataset.kfwId, label: t, kind: e.tagName === 'A' ? 'link' : 'button',
      disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true'});
  }
  window.__kfwSeq = seq;
  return out;
})()"""
DESCRIBE_JS = "((id) => {" + OBSERVE_JS + "\n  return O.describe(id);\n})"
CLASSIFY_JS = "((s) => {" + OBSERVE_JS + "\n  return O.classify(s);\n})"
SENSITIVE_FOR_JS = "((tag, type, ac, label) => {" + OBSERVE_JS + "\n  return O.sensitiveFor(tag, type, ac, label);\n})"
GROUPS_JS ="((root, pattern, minRows, withControls) => {" + OBSERVE_JS + "\n  return O.groups(root, pattern, minRows, withControls);\n})"


def controls(tab):
    return tab.evaluate(CONTROLS_JS)


def find_clickable(tab, text, include_disabled=True):
    """Look for one visible button/link by its text (exact, then contains: same matching as recipes._find_control),
    seeing disabled ones too (controls() filters them out; the last page of a pager is disabled, not absent).
    Returns {state: "enabled"|"disabled"|"absent"|"ambiguous", control?: {id, label, kind, disabled}, candidates: n}.
    include_disabled=False treats disabled controls as absent."""
    from .judge import normalize
    cands = [c for c in tab.evaluate(CLICKABLES_JS) if include_disabled or not c["disabled"]]
    n = normalize(text)
    found = [c for c in cands if normalize(c["label"]) == n] or [c for c in cands if n in normalize(c["label"])]
    if not found:
        return {"state": "absent", "candidates": 0}
    if len(found) > 1:
        return {"state": "ambiguous", "candidates": len(found)}
    c = found[0]
    return {"state": "disabled" if c["disabled"] else "enabled", "control": c, "candidates": 1}


def _node(tab, cid, body):
    """Run fixed JS against one observed control. cid is always a code-issued id."""
    return tab.evaluate(f"""(id => {{ const e = document.querySelector(`[data-kfw-id="${{id}}"]`);
      if (!e || !e.isConnected) return {{ok: false, why: 'gone'}}; {body} }})({json.dumps(cid)})""")


def describe(tab, cid):
    """The node behind a code-issued id, read now with the same JS rules as the snapshot (the gate's target):
    {ok, tag, type, text, aria_label, label, name, autocomplete, sensitive, form_has_sensitive} or
    {ok: False, why: 'gone'}. Never includes a field's value."""
    return tab.evaluate(f"{DESCRIBE_JS}({json.dumps(cid)})")


def select_option(tab, cid, option_text):
    r = _node(tab, cid, """const o = [...e.options].find(o => o.text.trim() === %s);
      if (!o) return {ok: false, why: 'no such option'};
      e.value = o.value; e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
      return {ok: e.selectedOptions[0]?.text.trim() === %s, now: e.selectedOptions[0]?.text.trim()};"""
              % (json.dumps(option_text), json.dumps(option_text)))
    return r


def fill(tab, cid, text):
    ok = _node(tab, cid, "if (e.readOnly) return {ok: false, why: 'readonly'}; e.scrollIntoView({block: 'center'}); "
                         "e.focus(); e.select?.(); return {ok: true};")
    if not ok.get("ok"):
        return ok
    tab.call("Input.insertText", text=text)
    r = _node(tab, cid, "e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); "
                        "e.blur(); return {ok: true, now: e.value};")
    for t in ("keyDown", "keyUp"):  # close a picker the focus opened
        tab.call("Input.dispatchKeyEvent", type=t, key="Escape", code="Escape")
    r["ok"] = r.get("now") == text
    return r


def click(tab, cid):
    r = _node(tab, cid, """e.scrollIntoView({block: 'center'}); const b = e.getBoundingClientRect();
      const x = b.x + b.width / 2, y = b.y + b.height / 2; const top = document.elementFromPoint(x, y);
      if (!top || !(e === top || e.contains(top) || top.contains(e))) return {ok: false, why: 'covered'};
      window.__kfwClickAt = performance.now(); return {ok: true, x, y, href: location.href};""")
    if not r.get("ok"):
        return r
    at = time.perf_counter()
    for ev in ("mousePressed", "mouseReleased"):
        tab.call("Input.dispatchMouseEvent", type=ev, x=r["x"], y=r["y"], button="left", clickCount=1)
    return {"ok": True, "_href": r["href"], "_at": at}


def checked(tab, cid):
    """The read-back of a checkbox/radio: its current `checked` state, or None when the node is gone."""
    r = _node(tab, cid, "return {ok: true, checked: !!e.checked};")
    return r.get("checked") if r.get("ok") else None


def settle_controls(tab, poll_s=0.25, cap_s=3.0):
    """Wait until the visible controls stop changing (two equal snapshots in a row). Widgets that JS
    enhances after load re-render or re-default the form; filling before that is lost or ignored
    (TRAPS form-submit-fills-half-initialized-page). Returns the last snapshot and whether it settled."""
    t0, last = time.perf_counter(), None
    while True:
        snap = controls(tab)
        ms = round((time.perf_counter() - t0) * 1000)
        if snap == last:
            return snap, {"ok": True, "ms": ms}
        if ms >= cap_s * 1000:
            return snap, {"ok": False, "ms": ms}
        last = snap
        time.sleep(poll_s)


EFFECT_JS = "[location.href, window.__kfwClickAt ?? null, window.__kfwMut?.last ?? 0]"


def submit_effect(href_before, clicked_at, last_req, probe):
    """What proves a click did something: navigation, a request started after it, or a DOM change after it.
    probe is EFFECT_JS evaluated after the click (None while the page is navigating). None = no evidence yet."""
    if probe is None:
        return "navigating"
    href, click_mark, mut_last = probe
    if href != href_before or click_mark is None:  # new document: the mark set before the click is gone
        return "navigated"
    if last_req > clicked_at:
        return "request"
    if mut_last > click_mark:
        return "dom"
    return None


def wait_submit_effect(tab, click_result, cap_s=2.0, poll_s=0.1):
    """After form.click: wait briefly for evidence the click took effect. Returns (how | None, ms)."""
    t0 = time.perf_counter()
    while True:
        try:
            probe = tab.evaluate(EFFECT_JS)
        except Exception:
            probe = None
        how = submit_effect(click_result["_href"], click_result["_at"], tab.last_req, probe)
        ms = round((time.perf_counter() - t0) * 1000)
        if how or ms >= cap_s * 1000:
            return how, ms
        time.sleep(poll_s)


def rows(tab, pattern, min_rows=1):
    """Legacy shape: the best group's rows as lists of cells."""
    return tab.evaluate(f"{ROWS_JS}({json.dumps(pattern)}, {int(min_rows)})")


def rows_detail(tab, pattern, min_rows=1):
    """{rows, group_fingerprint, other_qualifying_groups}: the same best group rows() returns, plus how many
    other, unrelated groups also satisfy pattern and min_rows (>0 means the result table is ambiguous)."""
    return tab.evaluate(f"{ROWS_DETAIL_JS}({json.dumps(pattern)}, {int(min_rows)})")


def groups(tab, pattern=None, min_rows=None, root=None, with_controls=True):
    """All repeating-row groups under `root` (CSS selector, default body) that match `pattern` (None = any).
    Marks them in the DOM (data-kfw-group / data-kfw-row); ids are valid until the next call."""
    return tab.evaluate(f"{GROUPS_JS}({json.dumps(root)}, {json.dumps(pattern)}, {json.dumps(min_rows)}, "
                        f"{json.dumps(bool(with_controls))})")


def wait_rows(tab, pattern, min_rows=1, stable_polls=2, poll_s=0.3, cap_s=12.0):
    """Completion is proven by code: at least min_rows rows matching `pattern`, stable across polls."""
    t0, last, same = time.perf_counter(), None, 0
    while time.perf_counter() - t0 < cap_s:
        try:
            got = rows(tab, pattern, min_rows)
        except Exception:
            got = []
        n = len(got)
        if n >= min_rows and n == last:
            same += 1
            if same >= stable_polls:
                return got, round((time.perf_counter() - t0) * 1000)
        else:
            same = 0
        last = n
        time.sleep(poll_s)
    return [], round((time.perf_counter() - t0) * 1000)


# ---------- pick (design 6.4) ----------
# One observation of the candidate list, and the check made just before the click. Both reuse the shared OBSERVE_JS.

PICK_GROUPS_JS = "((pattern, minRows) => {" + OBSERVE_JS + r"""
  const gs = O.groups(null, pattern, minRows, true);
  const nodes = gs.map(g => [...document.querySelectorAll(`[data-kfw-group="${g.group_id}"]`)]);
  const overlap = (i, j) => nodes[i].some(x => nodes[j].some(y => x.contains(y) || y.contains(x)));
  // groups that wrap / sit inside each other (a lone <tbody>, cells inside a row) are one region seen at several levels
  const parent = gs.map((_, i) => i), find = i => parent[i] === i ? i : (parent[i] = find(parent[i]));
  for (let i = 0; i < gs.length; i++) for (let j = i + 1; j < gs.length; j++) if (overlap(i, j)) parent[find(j)] = find(i);
  const score = g => g.rows.reduce((a, r) => a + r.text.length, 0);
  const best = new Map();
  gs.forEach((g, i) => { const r = find(i), b = best.get(r);
    if (!b || g.total > b.total || (g.total === b.total && score(g) > score(b))) best.set(r, g); });
  return {generation: window.__kfwGroupSeq || 0, groups: [...best.values()]};
})"""

VERIFY_PICK_JS = "((rid, gid, text, gen, cid) => {" + OBSERVE_JS + r"""
  const row = document.querySelector(`[data-kfw-row="${CSS.escape(rid)}"]`);
  if (!row || !row.isConnected) return {ok: false, why: 'row_gone'};
  if (row.dataset.kfwGroup !== gid) return {ok: false, why: 'group_changed'};
  if ((window.__kfwGroupSeq || 0) !== gen) return {ok: false, why: 'generation_changed'};
  if (O.norm(row.innerText) !== text) return {ok: false, why: 'row_text_changed'};
  const c = document.querySelector(`[data-kfw-id="${CSS.escape(cid)}"]`);
  if (!c || !c.isConnected || !row.contains(c)) return {ok: false, why: 'control_moved'};
  return {ok: true};
})"""


def pick_groups(tab, pattern, min_rows=1):
    """One groups() observation (marks data-kfw-row / data-kfw-group, rows carry their own `controls`), reduced to one
    group per region: {generation, groups: [{group_id, fingerprint, rows: [{row_id, cells, text, controls}], total}]}.
    More than one entry in `groups` means the page has several unrelated matching lists."""
    return tab.evaluate(f"{PICK_GROUPS_JS}({json.dumps(pattern)}, {int(min_rows)})")


def verify_pick(tab, row_id, group_id, text, generation, control_id):
    """Just before a pick click: the observed row node is still connected and still in the same group, its text
    is unchanged, no newer observation replaced the marks, and the control is still inside that row.
    {ok: True} or {ok: False, why}."""
    return tab.evaluate(f"{VERIFY_PICK_JS}({json.dumps(row_id)}, {json.dumps(group_id)}, {json.dumps(text)}, "
                        f"{json.dumps(generation)}, {json.dumps(control_id)})")
