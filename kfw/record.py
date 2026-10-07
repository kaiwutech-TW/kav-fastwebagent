"""Demo recorder (design docs/design/demo-recording.md v3.2, WP1): the in-page recorder, the recording state machine,
payload validation, the on-disk format and the one-recording-at-a-time manager behind start_recording / stop_recording.

WP2: stop also runs the live check (design 7.3) while the page is still there and builds the draft with kfw/draft.py
(pure conversion); dry_run's demonstration comparison lives in kfw/recipes.py and reads a recording through read_recording().

Facts this file is built on (docs/design/demo-recording.spike.md, TRAPS pagehide-binding-call-not-delivered):
  * the binding __kfwRec exists only in the world named kfw_rec; the page cannot call it;
  * pagehide/visibilitychange calls never arrive, beforeunload does: groups are announced when they open
    (group_open) and closed when stable or on beforeunload, never on pagehide;
  * BFCache restore re-fires pageshow(persisted) in the old JS: the old token is void and a new hello is sent;
  * CSP: the bar uses createElement + textContent + CSSOM only (no innerHTML, no <style>, no setAttribute('style')).
"""

import base64
import hashlib
import json
import logging
import os
import queue
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from urllib.parse import urlsplit

from . import compare, draft as draftmod
from .cdp import Browser
from .form import OBSERVE_JS, PICK_GROUPS_JS

# =====================================================================================================
# The recorder that runs inside the page (design 3.2, 3.3). It is built from form.OBSERVE_JS (labels, snapshots, groups,
# the sensitive-field rules and the injected KFW_RULES), so recording and replay observe pages with the same code.
# =====================================================================================================

_GUARD = r"""
if (window.top !== window) return;            // main frame only: an iframe never says hello
const B = globalThis.__kfwRec;                // exists only in the world named kfw_rec
if (typeof B !== 'function') return;
if (globalThis.__kfwInstalled) return;
globalThis.__kfwInstalled = true;
"""

_BODY = r"""
const CFG = {unarmedMs: __UNARMED_MS__, pollMs: 150, capMs: 1500, baselineCapMs: 3000, snapBudget: 50000, markBudget: 50000};
const S = {token: null, seq: 0, torn: false, halted: false, preArm: 0, preKinds: [], docId: Math.random().toString(36).slice(2),
  group: null, gidN: 0, lastSnap: null, sent: new Set(), baselineDone: false, baselineTimer: null, unarmedTimer: null,
  marking: null, lastErr: null, testNoUnload: false, pageshows: 0, sends: 0, flagged: new Set()};
const rawSend = o => { try { B(JSON.stringify(o)); S.sends++; return true; } catch (e) { S.lastErr = String(e); return false; } };
// every message after arm carries the epoch token and the next seq; nothing is sent without a token
const emit = o => { if (!S.token || S.torn || S.halted) return false; o.token = S.token; o.seq = ++S.seq; return rawSend(o); };
const now = () => performance.now();
const bytes = s => new TextEncoder().encode(s).length;
const norm = O.norm;
const navType = () => { try { return performance.getEntriesByType('navigation')[0].type; } catch (_) { return null; } };
const hello = (restored, persisted) => {
  rawSend({type: 'hello', doc_id: S.docId, href: location.href, restored, persisted, nav_type: navType(), ready_state: document.readyState});
  clearTimeout(S.unarmedTimer);
  // a document nobody arms (a BFCache page of a finished recording) switches itself off for good
  S.unarmedTimer = setTimeout(() => { if (!S.token) teardown(); }, CFG.unarmedMs);
};
const flag = reason => { if (S.flagged.has(reason)) return; S.flagged.add(reason); emit({type: 'flag', reason}); };
const block = reason => { if (S.halted) return; emit({type: 'blocked', reason}); S.halted = true; syncUI(); };

// ---- result-group observation (WP2b, steps drafts): what repeating groups a page shows, and the row a clicked control sits in.
// One O.groups() pass (the same one replay uses); the DOM marks it writes are removed again before anything else runs. ----
const CELL_MAX = 80, ROW_CELLS = 12, ROW_SAMPLE = 25, ROW_BYTES = 30000;
const clipCells = cs => cs.slice(0, ROW_CELLS).map(c => c.slice(0, CELL_MAX));
const headsOf = () => {
  const out = [], add = t => { t = norm(t || '').slice(0, 60); if (t && !out.includes(t) && out.length < 8) out.push(t); };
  for (const e of document.querySelectorAll('h1, h2, h3, h4, [role=heading]')) if (O.visible(e)) add(e.innerText);
  return out;
};
const resFrom = gs => {
  const rows = [];
  for (const g of gs) {
    if (g.total < 2 || !g.rows.length) continue;
    rows.push({sc: g.rows.reduce((a, r) => a + r.text.length, 0), fp: g.fingerprint, n: g.total, cols: g.rows[0].cells.length, sig: groupSig(g) || ''});
  }
  rows.sort((a, b) => b.sc - a.sc);
  return {groups: rows.slice(0, 8).map(({fp, n, cols, sig}) => ({fp, n, cols, sig: sig.slice(0, 120)})), heads: headsOf()};
};
const rowFrom = (gs, ctl) => {
  let best = null;
  const byId = new Map(gs.map(g => [g.group_id, g]));
  for (let n = ctl.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    const g = n.dataset && n.dataset.kfwGroup && byId.get(n.dataset.kfwGroup);
    if (!g || g.total < 2) continue;
    const sc = g.rows.reduce((a, r) => a + r.text.length, 0);
    if (!best || sc > best.sc) best = {g, sc, rid: n.dataset.kfwRow};
  }
  if (!best) return null;
  const idx = best.g.rows.findIndex(r => r.row_id === best.rid);
  if (idx < 0) return null;
  let take = ROW_SAMPLE, out = null;
  while (take >= 2) {          // the clicked row is always in the sample; the sample shrinks to fit the payload budget
    const start = idx < take ? 0 : idx - take + 1, part = best.g.rows.slice(start, start + take);
    out = {cells: clipCells(best.g.rows[idx].cells), text: best.g.rows[idx].text.slice(0, 200), rows: part.map(r => clipCells(r.cells)),
      texts: part.map(r => r.text.slice(0, 200)), total: best.g.total, index: idx - start};
    if (bytes(JSON.stringify(out)) <= ROW_BYTES) return out;
    take = Math.floor(take / 2);
  }
  return null;
};
const observeAtClick = ctl => {
  try {
    const gs = O.groups(null, null, null, false);
    return {res: resFrom(gs), row: ctl ? rowFrom(gs, ctl) : null};
  } catch (_) { return {res: null, row: null}; } finally { clearMarks(); }
};

// ---- snapshots (committed, hash-deduplicated) ----
const fit = ctl => {
  const LIM = CFG.snapBudget, size = c => bytes(JSON.stringify(c));
  if (size(ctl) <= LIM) return {controls: ctl, dropped: 0};
  const links = ctl.filter(c => c.kind === 'link');
  let k = links.length;
  while (k > 0 && size(ctl.filter(c => c.kind !== 'link' || links.indexOf(c) < k)) > LIM) k = Math.floor(k / 2);
  let out = ctl.filter(c => c.kind !== 'link' || links.indexOf(c) < k);
  while (out.length > 1 && size(out) > LIM) out = out.slice(0, Math.floor(out.length * 0.8));
  return {controls: out, dropped: ctl.length - out.length};
};
const sensitiveValue = ctl => ctl.some(c => c.sensitive && (c.has_value || c.value));
const commit = () => {
  const ctl = O.snapshot(document);
  if (sensitiveValue(ctl)) { block('sensitive_value'); return null; }
  const f = fit(ctl), id = O.fingerprint(f.controls);
  if (!S.sent.has(id)) { S.sent.add(id); emit({type: 'snapshot', id, controls: f.controls, links_dropped: f.dropped}); }
  S.lastSnap = id;
  return id;
};
const hashNow = () => { try { return O.fingerprint(O.snapshot(document)); } catch (_) { return null; } };
const commitBaseline = () => {
  if (S.baselineDone) return;
  S.baselineDone = true; clearTimeout(S.baselineTimer);
  const id = commit();
  if (id) { const res = observeAtClick(null).res; emit(res ? {type: 'baseline', snap: id, res} : {type: 'baseline', snap: id}); }
};
const startBaseline = () => {
  let last = null; const t0 = now();
  const step = () => {
    if (S.torn || S.halted || !S.token || S.baselineDone) return;
    const h = hashNow();
    if ((h !== null && h === last && document.readyState !== 'loading') || now() - t0 >= CFG.baselineCapMs) { commitBaseline(); return; }
    last = h; S.baselineTimer = setTimeout(step, CFG.pollMs);
  };
  S.baselineTimer = setTimeout(step, CFG.pollMs);
};

// ---- action groups ----
const CTL = 'select, input, textarea, button, [role=button], a[href]';
const MODIFIERS = new Set(['Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'Fn', 'NumLock', 'ScrollLock', 'AltGraph']);
const OPENERS = new Set(['pointerdown', 'keydown', 'beforeinput', 'paste', 'compositionstart']);
const RANK = {pointer: 0, keyboard: 1, text_input: 2, paste: 3, ime: 4};
const KEYS = new Set(['Enter', 'Escape', 'Tab']);
let host = null;
const isOurs = e => { try { return !!host && e.composedPath().includes(host); } catch (_) { return false; } };
const nodeOf = e => { const p = e.composedPath && e.composedPath()[0];
  return p && p.nodeType === 1 ? p : (e.target && e.target.nodeType === 1 ? e.target : null); };
const ctlOf = n => (n && n.closest) ? (n.closest(CTL) || n) : n;
const buttonLike = el => !!el && (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button' || (el.tagName === 'A' && el.hasAttribute('href')) ||
  (el.tagName === 'INPUT' && ['button', 'submit', 'reset', 'image'].includes((el.type || '').toLowerCase())));
const targetInfo = e => {
  const path = e.composedPath ? e.composedPath() : [];
  const node = nodeOf(e) || document.body;
  const inShadow = path.some(n => typeof ShadowRoot !== 'undefined' && n instanceof ShadowRoot);
  const custom = (node.localName || '').includes('-') || !!node.shadowRoot || inShadow;
  const ctl = node.closest ? node.closest(CTL) : null;
  if (ctl && !ctl.dataset.kfwId) O.snapshot(document);       // assigns data-kfw-id to what is visible
  const el = ctl || node, isField = ['SELECT', 'INPUT', 'TEXTAREA'].includes(el.tagName), bl = buttonLike(el);
  const text = isField && !bl ? '' : norm(el.innerText || el.value || el.getAttribute('aria-label') || '').slice(0, 80);
  return {tag: el.tagName, native: isField, in_controls: !!(ctl && ctl.dataset.kfwId), id: (ctl && ctl.dataset.kfwId) || null,
    label: bl ? text : (ctl ? O.labelOf(ctl) : ''), text, is_button_like: bl, custom_element: custom,
    iframe: node.tagName === 'IFRAME' || node.tagName === 'FRAME'};
};
const newTabCheck = e => {
  const n = nodeOf(e), a = n && n.closest ? n.closest('a[href]') : null;
  if (!a) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1 || (a.target && a.target !== '_self' && e.type === 'click')) flag('new_tab');
};
const pollGroup = () => {
  const g = S.group;
  if (!g || S.torn) return;
  const t = now(), h = hashNow();
  if ((h === g.lastHash && t - g.lastAct >= CFG.pollMs) || t - g.lastAct >= CFG.capMs) { closeGroup(false); return; }
  g.lastHash = h; g.timer = setTimeout(pollGroup, CFG.pollMs);
};
const closeGroup = unloading => {
  const g = S.group;
  if (!g) return;
  S.group = null; clearTimeout(g.timer);
  const snap = commit();
  if (snap === null) return;
  const o = {type: 'group_close', gid: g.gid, kind: g.kind, snap, keys: g.keys.slice()};
  if (unloading) o.unloading = true;
  emit(o);
};
const openGroup = (e, kind) => {
  if (S.group) closeGroup(false);
  if (S.halted) return null;
  if (!S.baselineDone) commitBaseline();
  const info = targetInfo(e);
  const tnode = ctlOf(nodeOf(e));
  const obs = info.is_button_like ? observeAtClick(tnode) : null;       // the result groups just before the click, and the list row it sits in
  if (obs && obs.row) info.row = obs.row;
  const g = S.group = {gid: 'g' + (++S.gidN), kind, tnode, keys: [], lastAct: now(), lastHash: null, timer: null};
  const open = {type: 'group_open', gid: g.gid, kind, target: info, prev_snap: S.lastSnap};
  if (obs && obs.res) open.res = obs.res;
  emit(open);
  g.timer = setTimeout(pollGroup, CFG.pollMs);
  return g;
};
const touch = g => { g.lastAct = now(); g.lastHash = null; };
// typing continues one group; a pointer group is never extended by the keyboard
const joinOrOpen = (e, kind) => {
  const g = S.group;
  if (g && g.kind !== 'pointer' && g.tnode === ctlOf(nodeOf(e))) {
    if (RANK[kind] > RANK[g.kind]) g.kind = kind;
    touch(g); return g;
  }
  return openGroup(e, kind);
};
const sensitiveTarget = e => { const n = ctlOf(nodeOf(e)); try { return !!n && n.nodeType === 1 && O.isSensitive(n); } catch (_) { return false; } };
const onEvent = e => {
  if (!e.isTrusted || S.torn || S.halted || S.marking || isOurs(e)) return;
  const type = e.type;
  if (!S.token) {                                            // before arm: count, never drop silently
    if (OPENERS.has(type)) { S.preArm++; if (S.preKinds.length < 10) S.preKinds.push(type); }
    return;
  }
  if (!nodeOf(e)) return;
  if (['keydown', 'beforeinput', 'input', 'paste', 'compositionstart'].includes(type) && sensitiveTarget(e)) { block('sensitive_focus'); return; }
  let g = null;
  switch (type) {
    case 'pointerdown': newTabCheck(e); if (targetInfoIsFrame(e)) flag('iframe_interaction'); openGroup(e, 'pointer'); break;
    case 'auxclick': newTabCheck(e); break;
    case 'click': newTabCheck(e); if (S.group) touch(S.group); else openGroup(e, 'pointer'); break;
    case 'keydown':
      if (MODIFIERS.has(e.key)) break;
      g = joinOrOpen(e, 'keyboard');
      if (g && KEYS.has(e.key) && g.keys.length < 20) g.keys.push(e.key);
      break;
    case 'beforeinput': case 'input': {
      const it = e.inputType;
      const kind = !it ? 'keyboard' : /^insertFrom(Paste|Drop|Yank)/.test(it) ? 'paste' : /Composition/.test(it) ? 'ime' : 'text_input';
      joinOrOpen(e, kind); break; }
    case 'paste': joinOrOpen(e, 'paste'); break;
    case 'compositionstart': case 'compositionupdate': case 'compositionend': joinOrOpen(e, 'ime'); break;
    case 'change': if (S.group) touch(S.group); else joinOrOpen(e, 'keyboard'); break;
    default: if (S.group) touch(S.group);
  }
};
const targetInfoIsFrame = e => { const n = nodeOf(e); return !!n && (n.tagName === 'IFRAME' || n.tagName === 'FRAME'); };

// ---- bar (closed shadow root; createElement + textContent + CSSOM only) ----
let root = null, bar = null, btnMark = null, btnDone = null, statusEl = null, mo = null;
const st = (el, o) => { for (const k in o) el.style.setProperty(k, o[k]); };
const mkBtn = (label, color, onClick) => {
  const b = document.createElement('button');
  b.textContent = label;
  st(b, {background: color, color: 'rgb(255, 255, 255)', border: 'none', padding: '6px 14px', 'border-radius': '6px',
    cursor: 'pointer', font: '14px sans-serif'});
  const keep = e => e.preventDefault();                       // keep the page's focus where it is
  b.addEventListener('pointerdown', keep); b.addEventListener('mousedown', keep);
  b.addEventListener('click', e => { if (e.isTrusted) onClick(e); });
  return b;
};
const build = () => {
  host = document.createElement('div');
  st(host, {all: 'initial', position: 'fixed', right: '16px', bottom: '16px', 'z-index': '2147483647', display: 'none'});
  root = host.attachShadow({mode: 'closed'});
  bar = document.createElement('div');
  st(bar, {display: 'flex', 'align-items': 'center', gap: '8px', background: 'rgb(30, 30, 30)', color: 'rgb(255, 255, 255)',
    padding: '8px 12px', 'border-radius': '8px', font: '14px sans-serif', position: 'relative', 'z-index': '2',
    'box-shadow': '0 2px 10px rgba(0, 0, 0, 0.45)'});
  const dot = document.createElement('span');
  st(dot, {display: 'inline-block', width: '10px', height: '10px', 'border-radius': '50%', background: 'rgb(230, 50, 50)'});
  statusEl = document.createElement('span');
  statusEl.textContent = 'Kav 錄製中';
  btnMark = mkBtn('標記結果', 'rgb(52, 110, 200)', () => (S.marking ? cancelMark() : enterMark()));
  btnDone = mkBtn('完成', 'rgb(0, 150, 105)', () => { if (S.marking) cancelMark(); emit({type: 'done'}); });
  bar.appendChild(dot); bar.appendChild(statusEl); bar.appendChild(btnMark); bar.appendChild(btnDone);
  root.appendChild(bar);
};
const syncUI = () => { if (host) host.style.setProperty('display', S.token && !S.halted && !S.torn ? 'block' : 'none'); };
const setStatus = t => { if (statusEl) statusEl.textContent = t; };
const mount = () => {
  if (S.torn || !document.body) return;
  if (host && host.isConnected) return;
  if (!host) build();
  document.body.appendChild(host);
  syncUI();
};

// ---- mark mode ----
const SWALLOW = ['pointerdown', 'pointerup', 'pointermove', 'pointerover', 'pointerout', 'pointerenter', 'pointerleave',
  'mousedown', 'mouseup', 'mousemove', 'mouseover', 'mouseout', 'mouseenter', 'mouseleave', 'click', 'dblclick', 'auxclick',
  'contextmenu', 'keydown', 'keyup', 'keypress', 'wheel', 'touchstart', 'touchmove', 'touchend', 'dragstart', 'selectstart',
  'beforeinput', 'input', 'paste', 'copy', 'cut', 'compositionstart'];
const enterMark = () => {
  if (S.marking || S.torn || S.halted || !S.token || !root) return;
  if (S.group) closeGroup(false);
  const prev = document.activeElement;
  if (prev && prev !== document.body && typeof prev.blur === 'function') prev.blur();
  const overlay = document.createElement('div');
  st(overlay, {position: 'fixed', left: '0', top: '0', right: '0', bottom: '0', cursor: 'crosshair', 'z-index': '1',
    background: 'rgba(0, 0, 0, 0.03)', outline: 'none'});
  overlay.tabIndex = -1;
  const outline = document.createElement('div');
  st(outline, {position: 'fixed', border: '2px solid rgb(0, 170, 119)', 'pointer-events': 'none', 'z-index': '1', display: 'none',
    'box-sizing': 'border-box', background: 'rgba(0, 170, 119, 0.12)'});
  root.appendChild(overlay); root.appendChild(outline);
  S.marking = {prev, overlay, outline, el: null, stack: []};
  try { overlay.focus({preventScroll: true}); } catch (_) {}
  setTimeout(() => { if (S.marking && S.marking.overlay === overlay) { try { overlay.focus({preventScroll: true}); } catch (_) {} } }, 0);
  btnMark.textContent = '取消標記';
  setStatus('點選要標記的結果區域(↑ 放大,Esc 取消)');
};
const exitMark = restore => {
  const m = S.marking;
  if (!m) return;
  S.marking = null;
  m.overlay.remove(); m.outline.remove();
  if (btnMark) btnMark.textContent = '標記結果';
  if (restore && m.prev && m.prev.isConnected && typeof m.prev.focus === 'function') { try { m.prev.focus({preventScroll: true}); } catch (_) {} }
};
const cancelMark = () => { exitMark(true); setStatus('Kav 錄製中'); };
const drawOutline = () => {
  const m = S.marking;
  if (!m) return;
  if (!m.el) { m.outline.style.setProperty('display', 'none'); return; }
  const r = m.el.getBoundingClientRect();
  st(m.outline, {display: 'block', left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px'});
};
const hover = (x, y) => {
  const m = S.marking;
  if (!m) return;
  const el = document.elementsFromPoint(x, y).find(n => n !== host && n.nodeType === 1);
  if (el !== m.el) { m.el = el || null; m.stack = []; }
  drawOutline();
};
const clearMarks = () => { for (const e of document.querySelectorAll('[data-kfw-row], [data-kfw-group]')) { delete e.dataset.kfwRow; delete e.dataset.kfwGroup; } };
const rowSigOf = rid => { const el = document.querySelector('[data-kfw-row="' + rid + '"]'); return el ? O.sig(el) : null; };
const groupSig = g => g.rows.length ? rowSigOf(g.rows[0].row_id) + '|' + g.rows[0].cells.length : null;
const pickBest = gs => {
  let b = null;
  for (const g of gs) { const sc = g.rows.reduce((a, r) => a + r.text.length, 0);
    if (!b || g.total > b.g.total || (g.total === b.g.total && sc > b.sc)) b = {g, sc}; }
  return b && b.g;
};
const doMark = () => {
  const m = S.marking, el = m && m.el;
  if (!el) { setStatus('請先把滑鼠移到要標記的區域'); return; }
  const full = norm(el.innerText || el.textContent || '');
  if (!full) { setStatus('這個區域沒有文字,請換一個'); return; }
  let group = null;
  const best = pickBest(O.groups(el, null, null, false));
  if (best) {
    const sig = groupSig(best), first = document.querySelector('[data-kfw-row="' + best.rows[0].row_id + '"]');
    const table = first && first.closest ? first.closest('table') : null;
    const hasTh = !!(first && (first.querySelector('th') || (table && table.querySelector('th'))));
    let same = 0;
    for (const g of O.groups(null, null, null, false)) if (groupSig(g) === sig) same++;
    let cells = best.rows.map(r => r.cells);
    let sent = cells.length;
    while (sent > 1 && bytes(JSON.stringify(cells.slice(0, sent))) > CFG.markBudget) sent = Math.floor(sent / 2);
    // th header texts (WP2: rows.columns is filled only when they are certain): the table's first row made only of th cells
    let headers = null;
    if (table && table.rows) {
      const hr = [...table.rows].find(r => r.cells.length && [...r.cells].every(c => c.tagName === 'TH'));
      if (hr) headers = [...hr.cells].map(c => norm(c.innerText).slice(0, 200)).slice(0, 60);
    }
    group = {rows: cells.slice(0, sent), rows_sent: sent, total: best.total, truncated: best.total > best.rows.length,
      fingerprint: best.fingerprint, has_th: hasTh, same_signature_groups: Math.max(same, 1), headers, sig: (sig || '').slice(0, 120)};
  }
  clearMarks();
  emit({type: 'mark', tag: el.tagName, text: full.slice(0, 2000), text_truncated: full.length > 2000, href: location.href, group});
  exitMark(true);
  setStatus(group ? '已標記(' + group.total + ' 列),可再標記或按完成' : '已標記文字,可再標記或按完成');
};
// composedPath() from a listener outside a CLOSED shadow root never lists nodes inside it, so "the overlay vs the bar" cannot be
// told from the path: mouse events are told apart by position, key events by the shadow root's own activeElement.
const inBar = e => {
  if (!bar || typeof e.clientX !== 'number') return false;
  const r = bar.getBoundingClientRect();
  return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
};
const markHandler = e => {
  const m = S.marking;
  if (!m || S.torn) return;
  const isKey = e.type === 'keydown' || e.type === 'keyup' || e.type === 'keypress';
  if (isKey) {
    const fe = root ? root.activeElement : null;               // Enter/Space on a focused bar button keeps working
    if ((e.key === 'Enter' || e.key === ' ') && fe && (fe === btnMark || fe === btnDone)) return;
  } else if (inBar(e)) return;                                 // the bar's own buttons keep working
  e.preventDefault(); e.stopImmediatePropagation();           // first listener on window: the site never sees it
  if (e.type === 'keydown') {
    if (e.key === 'Escape') cancelMark();
    else if (e.key === 'ArrowUp' && m.el && m.el.parentElement && m.el.parentElement !== document.documentElement) { m.stack.push(m.el); m.el = m.el.parentElement; drawOutline(); }
    else if (e.key === 'ArrowDown' && m.stack.length) { m.el = m.stack.pop(); drawOutline(); }
    return;
  }
  if (e.type === 'pointermove' || e.type === 'mousemove') hover(e.clientX, e.clientY);
  else if (e.type === 'click' && e.isTrusted) { if (!m.el) hover(e.clientX, e.clientY); doMark(); }   // keep an ↑-enlarged pick
};

// ---- listeners ----
const ls = [];
const add = (target, type, fn, opts) => { target.addEventListener(type, fn, opts === undefined ? true : opts); ls.push([target, type, fn, opts === undefined ? true : opts]); };
for (const t of SWALLOW) add(window, t, markHandler, {capture: true, passive: false});   // registered first: sees events first
for (const t of ['pointerdown', 'pointerup', 'click', 'auxclick', 'keydown', 'keyup', 'beforeinput', 'input', 'change', 'paste',
  'compositionstart', 'compositionupdate', 'compositionend']) add(window, t, onEvent);
add(window, 'focusin', e => {
  if (!S.token || S.torn || S.halted || isOurs(e)) return;
  const n = e.target && e.target.nodeType === 1 ? e.target : null;
  try { if (n && O.isSensitive(n)) block('sensitive_focus'); } catch (_) {}
});
add(window, 'blur', e => {
  if (e.target !== window || !S.token || S.torn || S.halted) return;
  const a = document.activeElement;
  if (a && (a.tagName === 'IFRAME' || a.tagName === 'FRAME')) flag('iframe_interaction');
});
add(window, 'beforeunload', () => { if (S.token && !S.torn && !S.halted && !S.testNoUnload && S.group) closeGroup(true); });
add(window, 'pageshow', e => {
  S.pageshows++;
  if (!e.persisted || S.torn) return;
  // BFCache restore: the old token is void; a new epoch is Python's to grant
  if (S.marking) exitMark(false);
  if (S.group) { clearTimeout(S.group.timer); S.group = null; }
  clearTimeout(S.baselineTimer);
  S.token = null; S.seq = 0; S.baselineDone = false; S.lastSnap = null; S.sent.clear(); S.flagged.clear();
  syncUI();
  hello(true, true);
});
mo = new MutationObserver(() => { if (!S.torn && host && !host.isConnected) mount(); });
mo.observe(document, {childList: true, subtree: true});
mount();
if (document.readyState === 'loading') add(document, 'DOMContentLoaded', mount);

// ---- Python's handles (isolated world only) ----
globalThis.__kfwArm = token => {
  if (S.torn) return 'torn';
  clearTimeout(S.unarmedTimer);
  S.token = token; S.seq = 0; S.sent.clear(); S.lastSnap = null; S.baselineDone = false; S.flagged.clear();
  rawSend({type: 'armed', token, pre_arm_inputs: S.preArm, pre_kinds: S.preKinds.slice()});
  S.preArm = 0; S.preKinds = [];
  mount(); syncUI(); setStatus('Kav 錄製中');
  const a = document.activeElement;
  try { if (a && a.nodeType === 1 && O.isSensitive(a)) block('sensitive_focus'); } catch (_) {}
  startBaseline();
  return 'armed';
};
globalThis.__kfwFlush = () => {
  if (S.torn) return {ok: false, why: 'torn'};
  if (S.halted) return {ok: false, why: 'halted'};
  if (!S.token) return {ok: false, why: 'unarmed'};
  if (S.marking) cancelMark();
  if (S.group) closeGroup(false);
  if (!S.baselineDone) commitBaseline();
  if (S.halted) return {ok: false, why: 'halted'};
  return {ok: true, token: S.token, last_seq: S.seq};
};
const teardown = () => {
  S.torn = true; S.token = null;                              // permanent: pageshow(persisted) checks it, BFCache cannot revive it
  clearTimeout(S.unarmedTimer); clearTimeout(S.baselineTimer);
  if (S.group) { clearTimeout(S.group.timer); S.group = null; }
  if (S.marking) exitMark(true);
  for (const [t, ty, fn, o] of ls) t.removeEventListener(ty, fn, o);
  ls.length = 0;
  if (mo) mo.disconnect();
  if (host) host.remove();
  return 'torn-down';
};
globalThis.__kfwTeardown = teardown;
// read-only introspection for tests and debugging (only reachable from the kfw_rec world)
globalThis.__kfwInfo = () => {
  const r2 = x => x && [Math.round(x.x), Math.round(x.y), Math.round(x.width), Math.round(x.height)];
  const vis = !!host && host.isConnected && getComputedStyle(host).display !== 'none';
  return {torn: S.torn, halted: S.halted, connected: !!host && host.isConnected, visible: vis,
    hostRect: host ? r2(host.getBoundingClientRect()) : null,
    markBtn: btnMark ? r2(btnMark.getBoundingClientRect()) : null, doneBtn: btnDone ? r2(btnDone.getBoundingClientRect()) : null,
    hit: (btnDone && vis) ? document.elementFromPoint(btnDone.getBoundingClientRect().x + 5, btnDone.getBoundingClientRect().y + 5) === host : null,
    marking: !!S.marking, token: S.token, seq: S.seq, group: S.group ? S.group.gid : null, preArm: S.preArm, lastErr: S.lastErr,
    docId: S.docId, pageshows: S.pageshows, sends: S.sends, status: statusEl ? statusEl.textContent : null,
    bodyChildren: document.body ? document.body.childElementCount : null};
};
globalThis.__kfwTestHook = (name, value) => { if (name === 'noUnloadClose') S.testNoUnload = !!value; return true; };

hello(false, false);
"""


def build_recorder_js(unarmed_ms=8000):
    """The full injected source: guards, then the shared observation code, then the recorder."""
    body = _BODY.replace("__UNARMED_MS__", str(int(unarmed_ms)))
    return "(() => {\n" + _GUARD + OBSERVE_JS + body + "\n})();\n"


RECORDER_JS = build_recorder_js()


# =====================================================================================================
# Python side
# =====================================================================================================

log = logging.getLogger(__name__)

MAX_PAYLOAD = 64 * 1024          # one binding payload, bytes (design 2.2)
MAX_RECORDS = 5000               # records per recording (design 7.1)
MAX_BYTES = 5 * 1024 * 1024      # log + snapshots on disk
GAP_S = 3.0                      # a new document must be armed within this long
IDLE_S = 15 * 60                 # no event for this long: barrier, then completed
MAX_S = 30 * 60                  # total length: barrier, then incomplete: too_long
START_TIMEOUT_S = 20.0
BARRIER_S = 5.0
RETENTION_DAYS = 30
NAV_WINDOW_S = 2.0               # a group that ended this close to a document change counts as "navigated after"
ID_RE = re.compile(r"^[0-9a-f]{12}$")

TERMINAL = ("completed", "incomplete", "discarded")
TRANSITIONS = {
    "starting": {"recording", "incomplete"},
    "recording": {"stopping", "incomplete", "discarded"},
    "stopping": {"completed", "incomplete", "discarded"},
    "completed": {"discarded"},
    "incomplete": {"discarded"},
    "discarded": set(),
}

REASON_HINTS = {
    "blocked": "偵測到敏感欄位(密碼、卡號、驗證碼等),錄製已刪除,只留一筆紀錄。請避開這類欄位,或改用手寫流程。",
    "new_tab": "示範中開了新分頁,錄製 v1 不支援新分頁。請改在同一個分頁完成後重錄。",
    "iframe_interaction": "示範中操作了頁面裡的內嵌框(iframe),錄製看不到裡面。這個網站可能錄不了。",
    "custom_element_interaction": "示範中操作了網站自訂的元件,錄製無法確定它改了什麼。",
    "pre_arm_input": "錄製準備好之前就有操作(輸入或點擊),可能漏錄。請重錄。",
    "unclosed_input_group": "離開頁面時最後一次輸入還沒完成記錄,請在輸入後等一下再離開頁面,重錄。",
    "gap": "換頁後錄製沒有在 3 秒內接上,中間可能漏錄。",
    "seq_gap": "收到的紀錄有缺號,可能漏錄。",
    "bad_payload": "收到不合格式的紀錄,已丟棄,錄製不完整。",
    "unflushed": "結束時沒能確認所有紀錄都收齊。",
    "page_closed": "錄製中的分頁被關掉了。",
    "reattached": "錄製分頁的連線中斷後重接,中間可能漏錄。",
    "truncated": "紀錄超過上限(5000 筆或 5MB),後面的沒有記下來。",
    "too_long": "錄製超過 30 分鐘。",
    "start_failed": "沒能開始錄製(分頁沒載入或錄製程式沒接上)。",
    "server_restarted": "錄製途中 Kav 重新啟動,這份錄製不完整。",
    "browser_disconnected": "和瀏覽器的連線中斷了。",
    "page_crashed": "錄製分頁當掉了。",
}

KINDS = ("pointer", "keyboard", "text_input", "paste", "ime")


# ---------------------------------------------------------------------------------------------------
# payload validation (pure)
# ---------------------------------------------------------------------------------------------------

class BadPayload(Exception):
    """A binding payload that must be dropped; str(e) is the short why."""


def _str(n):
    return lambda v: isinstance(v, str) and len(v) <= n


def _bool(v):
    return isinstance(v, bool)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10**9


def _opt(f):
    return lambda v: v is None or f(v)


def _in(*vals):
    return lambda v: isinstance(v, str) and v in vals


def _list(f, n):
    return lambda v: isinstance(v, list) and len(v) <= n and all(f(x) for x in v)


def _shape(spec):
    return lambda v: isinstance(v, dict) and all(k in v and f(v[k]) for k, f in spec.items())


_TARGET = {"tag": _str(24), "native": _bool, "in_controls": _bool, "id": _opt(_str(32)), "label": _str(300), "text": _str(300),
           "is_button_like": _bool, "custom_element": _bool, "iframe": _bool}
_MARK_GROUP = _opt(lambda v: isinstance(v, dict) and _shape({
    "rows": _list(_list(_str(4000), 400), 400), "rows_sent": _int, "total": _int, "truncated": _bool,
    "fingerprint": _str(64), "has_th": _bool, "same_signature_groups": _int})(v)
    and (v.get("headers") is None or _list(_str(200), 60)(v.get("headers")))
    and (v.get("sig") is None or _str(200)(v.get("sig"))))
# steps drafts (WP2b): what result groups a page showed (before a click / at baseline) and the list row a clicked control sat in
_RES = _opt(lambda v: isinstance(v, dict) and _shape({
    "groups": _list(_shape({"fp": _str(64), "n": _int, "cols": _int, "sig": _str(200)}), 8), "heads": _list(_str(80), 8)})(v))
_ROW = _opt(lambda v: isinstance(v, dict) and _shape({
    "cells": _list(_str(200), 12), "text": _str(400), "rows": _list(_list(_str(200), 12), 30), "texts": _list(_str(400), 30),
    "total": _int, "index": _int})(v))

SCHEMAS: dict[str, dict] = {
    "hello": {"doc_id": _str(64), "href": _str(4096), "restored": _bool, "persisted": _bool, "nav_type": _opt(_str(32)),
              "ready_state": _str(32)},
    "armed": {"pre_arm_inputs": _int, "pre_kinds": _list(_str(32), 20)},
    "snapshot": {"id": _str(64), "controls": _list(lambda c: isinstance(c, dict), 3000), "links_dropped": _int},
    "baseline": {"snap": _str(64)},
    "group_open": {"gid": _str(32), "kind": _in(*KINDS), "target": lambda v: _shape(_TARGET)(v) and _ROW(v.get("row")),
                   "prev_snap": _opt(_str(64))},
    "group_close": {"gid": _str(32), "kind": _in(*KINDS), "snap": _opt(_str(64)), "keys": _list(_in("Enter", "Escape", "Tab"), 20)},
    "flag": {"reason": _in("new_tab", "iframe_interaction")},
    "blocked": {"reason": _in("sensitive_value", "sensitive_focus")},
    "mark": {"tag": _str(24), "text": _str(2000), "text_truncated": _bool, "href": _str(4096), "group": _MARK_GROUP},
    "done": {},
}
_OPTIONAL = {"group_close": {"unloading": _bool}, "baseline": {"res": _RES}, "group_open": {"res": _RES}}


def parse_payload(raw) -> dict:
    """A binding payload string -> its JSON object, or BadPayload. Size is bytes; the payload must be a str."""
    if not isinstance(raw, str):
        raise BadPayload("not_a_string")
    if len(raw.encode("utf-8", "replace")) > MAX_PAYLOAD:
        raise BadPayload("too_large")
    try:
        msg = json.loads(raw)
    except ValueError:
        raise BadPayload("not_json") from None
    if not isinstance(msg, dict) or msg.get("type") not in SCHEMAS:
        raise BadPayload("unknown_type")
    return msg


def clean_payload(msg: dict) -> dict:
    """Schema check; returns only whitelisted fields (plus type). BadPayload on any mismatch."""
    spec = SCHEMAS[msg["type"]]
    out = {"type": msg["type"]}
    for k, ok in spec.items():
        if k not in msg or not ok(msg[k]):
            raise BadPayload(f"schema:{msg['type']}.{k}")
        out[k] = msg[k]
    for k, ok in _OPTIONAL.get(msg["type"], {}).items():
        if k in msg:
            if not ok(msg[k]):
                raise BadPayload(f"schema:{msg['type']}.{k}")
            out[k] = msg[k]
    return out


def sensitive_present(controls) -> bool:
    """A committed snapshot must never hold a sensitive field's value (V11): presence of a value is enough."""
    return any(isinstance(c, dict) and c.get("sensitive") and (c.get("has_value") or c.get("value")) for c in controls)


def snap_diff(prev, cur):
    """Native field changes between two committed snapshots: [{id, label, kind, before, after}].
    Sensitive fields carry no value and are skipped."""
    old = {c.get("id"): c for c in (prev or []) if isinstance(c, dict) and c.get("id")}
    out = []
    for c in cur or []:
        if not isinstance(c, dict) or c.get("sensitive"):
            continue
        p = old.get(c.get("id"))
        if p is None:
            continue
        kind = c.get("kind")
        key = "checked" if kind in ("checkbox", "radio") else "value" if kind in ("select", "text") else None
        if key and p.get(key) != c.get(key):
            out.append({"id": c["id"], "label": c.get("label", ""), "kind": kind, "before": p.get(key), "after": c.get(key)})
    return out


def origin_of(url: str) -> str:
    try:
        u = urlsplit(url)
        return f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else ""
    except ValueError:
        return ""


# ---------------------------------------------------------------------------------------------------
# disk (one directory per recording)
# ---------------------------------------------------------------------------------------------------

def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


class Store:
    """log.jsonl + snapshots/<id>.json + meta.json (+ result.json, screenshot.jpg) under one recording directory.

    Blocked recordings are sealed: the terminal tombstone is written to meta.json FIRST (atomic replace), then every
    other file is deleted, so a crash in between still reads as terminal and the leftovers are purged on recovery."""

    def __init__(self, path: Path):
        self.dir = path
        self.lock = threading.RLock()
        self._log = None
        self.records = 0
        self.bytes = 0
        self.sealed = False
        self.full = False
        self.snap_ids: set[str] = set()

    def open(self, meta: dict):
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=False)
            (self.dir / "snapshots").mkdir()
            self._log = open(self.dir / "log.jsonl", "ab")
            _atomic_write(self.dir / "meta.json", json.dumps(meta, ensure_ascii=False).encode())

    def append(self, rec: dict) -> bool:
        line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        with self.lock:
            if self.sealed or self._log is None:
                return False
            if self.records >= MAX_RECORDS or self.bytes + len(line) > MAX_BYTES:
                self.full = True
                return False
            self._log.write(line)
            self._log.flush()          # readable by others at once; fsync happens at the barrier
            self.records += 1
            self.bytes += len(line)
            return True

    def put_snapshot(self, sid: str, controls: list) -> bool:
        if not re.fullmatch(r"[0-9a-f]{1,64}", sid):
            return False
        body = json.dumps({"controls": controls}, ensure_ascii=False, separators=(",", ":")).encode()
        with self.lock:
            if self.sealed:
                return False
            if sid in self.snap_ids:
                return True
            if self.records >= MAX_RECORDS or self.bytes + len(body) > MAX_BYTES:
                self.full = True
                return False
            (self.dir / "snapshots" / f"{sid}.json").write_bytes(body)
            self.snap_ids.add(sid)
            self.records += 1
            self.bytes += len(body)
            return True

    def sync(self):
        """flush + fsync the log, the snapshots and the directory entries (barrier step 4)."""
        with self.lock:
            if self.sealed or self._log is None:
                return
            self._log.flush()
            os.fsync(self._log.fileno())
            snaps = self.dir / "snapshots"
            for p in snaps.glob("*.json"):
                fd = os.open(p, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            _fsync_dir(snaps)
            _fsync_dir(self.dir)

    def close(self):
        with self.lock:
            if self._log is not None:
                try:
                    self._log.flush()
                    self._log.close()
                except OSError:
                    pass
                self._log = None

    def digest(self) -> str:
        h = hashlib.sha256()
        with self.lock:
            log_path = self.dir / "log.jsonl"
            if log_path.exists():
                h.update(log_path.read_bytes())
            for p in sorted((self.dir / "snapshots").glob("*.json")):
                h.update(p.name.encode())
                h.update(p.read_bytes())
        return h.hexdigest()

    def write_meta(self, meta: dict) -> bool:
        with self.lock:
            if self.sealed:
                return False
            _atomic_write(self.dir / "meta.json", json.dumps(meta, ensure_ascii=False).encode())
            return True

    def write_final(self, meta: dict, result: dict) -> bool:
        """The terminal meta + result, unless a block sealed the recording in the meantime."""
        with self.lock:
            if self.sealed:
                return False
            _atomic_write(self.dir / "result.json", json.dumps(result, ensure_ascii=False).encode())
            _atomic_write(self.dir / "meta.json", json.dumps(meta, ensure_ascii=False).encode())
            return True

    def _purge(self):
        for p in list(self.dir.iterdir()):
            if p.name == "meta.json":
                continue
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except OSError:
                    pass

    def seal(self, tombstone: dict):
        """Terminal tombstone first, then delete everything else. Nothing is written afterwards."""
        with self.lock:
            self.sealed = True
            self.close()
            _atomic_write(self.dir / "meta.json", json.dumps(tombstone, ensure_ascii=False).encode())
            self._purge()
            _fsync_dir(self.dir)


def read_log(path: Path) -> list[dict]:
    """log.jsonl of a recording directory as a list of records (a torn last line is ignored)."""
    out = []
    p = Path(path) / "log.jsonl"
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            break
    return out


def read_snapshots(path: Path) -> dict[str, list]:
    out = {}
    for p in sorted((Path(path) / "snapshots").glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))["controls"]
    return out


# ---------------------------------------------------------------------------------------------------
# one recording
# ---------------------------------------------------------------------------------------------------

class InvalidTransition(RuntimeError):
    pass


class Epoch:
    """One document generation. Python grants it (a fresh token per hello); a context only proves the source."""

    def __init__(self, n, token, ctx, uid, doc_id, href, restored):
        self.n, self.token, self.ctx, self.uid = n, token, ctx, uid
        self.doc_id, self.href, self.restored = doc_id, href, restored
        self.armed = False
        self.retired = False
        self.last_seq = 0
        self.open_groups: set[str] = set()
        self.last_group: tuple[str, float] | None = None   # (gid, closed_at) of the most recent group


class Recording:
    def __init__(self, rid: str, url: str, browser, store: Store, on_finished=None):
        self.id, self.url, self.browser, self.store = rid, url, browser, store
        self.on_finished = on_finished
        self.state = "starting"
        self.reasons: list[str] = []
        self._flag_counts: dict[str, int] = {}
        self.result: dict | None = None
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._fin_lock = threading.Lock()
        self.target_id: str | None = None
        self.session: str | None = None
        self.main_frame_id: str | None = None
        self.script_id: str | None = None
        self._ctx: dict[int, str] = {}                 # executionContextId -> uniqueId, main-frame kfw_rec contexts only
        self.epoch: Epoch | None = None
        self.epoch_n = 0
        self._retired: set[str] = set()
        self._groups: dict[tuple[int, str], dict] = {}
        self._timeline: list[tuple] = []
        self.snaps: dict[str, list] = {}
        self.marks: list[dict] = []
        self._mark_epochs: list[int] = []              # the document generation each mark was made in (live check, 7.3)
        self.stale_dropped = 0
        self._gap_start: float | None = None
        self._t0 = time.monotonic()
        self._last_event = self._t0
        self._regs: list[tuple] = []
        self._known_targets: set[str] = set()
        self._early_targets: list[dict] = []
        self._blocked = False
        self._refs: set[str] = set()                   # snapshot ids the log points at; the barrier checks they all resolve
        self._block_origin = ""
        self._armed_evt = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self._halt = threading.Event()
        self._threads: list[threading.Thread] = []
        self._auto_finish = False

    # ---- state machine ----
    def _set_state(self, new: str):
        with self._lock:
            old = self.state
            if new == old:
                return
            if new not in TRANSITIONS[old]:
                raise InvalidTransition(f"{old} -> {new}")
            self.state = new
            self._cond.notify_all()

    @property
    def finished(self) -> bool:
        return self.result is not None

    def _live(self) -> bool:
        return not self._blocked and self.state in ("starting", "recording", "stopping")

    # ---- logging / flags ----
    def _log(self, rec: dict):
        if self._blocked:
            return
        ep = self.epoch
        full = {"t": round(time.monotonic() - self._t0, 3), "epoch": ep.n if ep else 0, **rec}
        if not self.store.append(full) and self.store.full and "truncated" not in self.reasons:
            self.reasons.append("truncated")

    def flag(self, reason: str, **detail):
        """Mark the recording incomplete (sticky). Collection continues so the user can finish; blocked is different."""
        with self._lock:
            if self._blocked or self.state in TERMINAL:
                return
            if reason not in self.reasons:
                self.reasons.append(reason)
            n = self._flag_counts[reason] = self._flag_counts.get(reason, 0) + 1
            if n > 20:      # every occurrence is logged (its detail is evidence), but a flood is not
                return
        self._log({"type": "incomplete", "reason": reason, **detail})

    # ---- worker (all CDP calls on the recording tab are serialised here) ----
    def _worker_loop(self):
        while True:
            item = self._jobs.get()
            if item is None:
                return
            fn, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn())
            except BaseException as e:  # noqa: BLE001 - handed to whoever waits on the future
                fut.set_exception(e)

    def _submit(self, fn) -> Future:
        fut: Future = Future()
        self._jobs.put((fn, fut))
        return fut

    def _run(self, fn, timeout=30):
        return self._submit(fn).result(timeout)

    def _send(self, method, timeout=30, **params):
        return self.browser.send(method, session_id=self.session, timeout=timeout, **params)

    def _boot_threads(self):
        for target, name in ((self._worker_loop, "rec-worker"), (self._monitor, "rec-monitor")):
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            self._threads.append(t)

    # ---- listeners ----
    def _reg(self, session, method, cb):
        self.browser.on(session, method, cb)
        self._regs.append((session, method, cb))

    def _register_session_listeners(self):
        s = self.session
        self._reg(s, "Runtime.bindingCalled", self.on_binding)
        self._reg(s, "Runtime.executionContextCreated", self._on_ctx_created)
        self._reg(s, "Runtime.executionContextsCleared", self._on_ctx_cleared)
        self._reg(s, "Page.frameNavigated", self._on_frame_navigated)
        self._reg(s, "Page.navigatedWithinDocument", self._on_same_document)

    # ---- start (design 2.2, order fixed) ----
    def start(self) -> None:
        """Blocks until armed (state recording). Any failure -> incomplete: start_failed, and the exception is re-raised
        as RuntimeError for the manager."""
        try:
            b = self.browser
            self._boot_threads()
            self._known_targets = {t["targetId"] for t in b.send("Target.getTargets").get("targetInfos", [])}
            for method, cb in (("Target.targetCreated", self._on_target_created), ("Target.targetDestroyed", self._on_target_destroyed),
                               ("Target.detachedFromTarget", self._on_detached), ("Target.targetCrashed", self._on_target_crashed)):
                self._reg(None, method, cb)
            b.on_disconnect(self._on_disconnect)
            b.send("Target.setDiscoverTargets", discover=True)
            tid = b.send("Target.createTarget", url="about:blank", background=False)["targetId"]
            with self._lock:
                self.target_id = tid
                early, self._early_targets = self._early_targets, []
            for ti in early:
                self._on_target_created({"targetInfo": ti})
            self.session = b.send("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
            self._register_session_listeners()
            self._send("Page.enable")
            self._send("Runtime.enable")
            try:  # a prerendered page activated from the omnibox replaces the tab's target: the recording would lose it
                self._send("Page.setPrerenderingAllowed", isAllowed=False)
            except Exception:  # noqa: BLE001 - experimental command; older Chrome
                pass
            try:
                self._send("Page.bringToFront")
            except Exception:  # noqa: BLE001 - cosmetic
                pass
            self._send("Runtime.addBinding", name="__kfwRec", executionContextName="kfw_rec")
            self.script_id = self._send("Page.addScriptToEvaluateOnNewDocument", source=RECORDER_JS, worldName="kfw_rec")["identifier"]
            self.main_frame_id = self._send("Page.getFrameTree")["frameTree"]["frame"]["id"]
            nav = self._send("Page.navigate", url=self.url)
            if nav.get("errorText"):
                raise RuntimeError(f"navigate: {nav['errorText']}")
            if not self._armed_evt.wait(START_TIMEOUT_S):
                raise RuntimeError("recorder did not arm (no hello/armed from the page)")
            if self._blocked:
                raise RuntimeError("blocked during start")
            self._set_state("recording")
            self.store.write_meta({"id": self.id, "state": "recording", "url": self.url, "started": time.time()})
        except BaseException as e:
            self._fail_start(e)
            raise RuntimeError(f"start_failed: {e}") from e

    def _fail_start(self, err):
        log.warning("recording start failed: %s", err)
        with self._lock:
            if self._blocked:
                return
            if "start_failed" not in self.reasons:
                self.reasons.append("start_failed")
        self.finish(trigger="start_failed", hint=str(err))

    # ---- targets ----
    def _on_target_created(self, p):
        ti = p.get("targetInfo", {})
        if ti.get("type") != "page":
            return
        tid = ti.get("targetId")
        with self._lock:
            if tid in self._known_targets or not self._live():
                return
            if self.target_id is None:
                self._early_targets.append(ti)
                return
            if tid == self.target_id:
                return
            self._known_targets.add(tid)
        self.flag("new_tab", opener=(ti.get("openerId") == self.target_id))

    def _on_target_destroyed(self, p):
        if p.get("targetId") == self.target_id and self._live() and self.state != "stopping":
            self._auto(self._page_gone)

    def _on_target_crashed(self, p):
        if p.get("targetId") == self.target_id and self._live():
            self.flag("page_crashed")

    def _on_detached(self, p):
        if p.get("sessionId") != self.session or not self._live():
            return
        self._submit(self._handle_detach)

    def _handle_detach(self):
        if self._target_gone():
            self._page_gone()
            return
        try:  # serialised on the worker; the new session gets no new-document script for the current document
            for s, m, cb in [r for r in self._regs if r[0] == self.session]:
                self.browser.off(s, m, cb)
            self._regs = [r for r in self._regs if r[0] != self.session]
            self.session = self.browser.send("Target.attachToTarget", targetId=self.target_id, flatten=True)["sessionId"]
            self._register_session_listeners()
            self._send("Page.enable")
            self._send("Runtime.enable")
            self._send("Runtime.addBinding", name="__kfwRec", executionContextName="kfw_rec")
            self.script_id = self._send("Page.addScriptToEvaluateOnNewDocument", source=RECORDER_JS, worldName="kfw_rec")["identifier"]
        except Exception as e:  # noqa: BLE001
            log.warning("reattach failed: %s", e)
        self.flag("reattached")

    def _target_gone(self) -> bool:
        try:
            infos = self.browser.send("Target.getTargets").get("targetInfos", [])
        except Exception:  # noqa: BLE001
            return False
        return not any(t.get("targetId") == self.target_id for t in infos)

    def _page_gone(self):
        try:  # evidence for "the tab is still there": was it replaced by another target (prerender, process swap)?
            pages = [{"id": t.get("targetId"), "url": (t.get("url") or "")[:120], "subtype": t.get("subtype")}
                     for t in self.browser.send("Target.getTargets").get("targetInfos", []) if t.get("type") == "page"]
        except Exception:  # noqa: BLE001
            pages = None
        self.flag("page_closed", target_id=self.target_id, pages_now=pages)
        self.finish(trigger="page_closed")

    def _on_disconnect(self):
        if self._live():
            self.flag("browser_disconnected")
            self._auto(lambda: self.finish(trigger="disconnect"))

    def _auto(self, fn):
        threading.Thread(target=fn, daemon=True, name="rec-auto").start()

    # ---- page events ----
    def _on_ctx_created(self, p):
        c = p.get("context", {})
        aux = c.get("auxData", {}) or {}
        if c.get("name") != "kfw_rec" or aux.get("frameId") != self.main_frame_id:
            return  # a non-main-frame kfw_rec world (same-site iframe) is ignored (spike 7)
        with self._lock:
            self._ctx[c["id"]] = c.get("uniqueId", "")

    def _on_ctx_cleared(self, _p):
        with self._lock:
            self._ctx.clear()
            if self.epoch is not None and not self.epoch.retired:
                self._retire(self.epoch)
            if self.state == "recording" and self._gap_start is None:
                self._gap_start = time.monotonic()

    def _on_frame_navigated(self, p):
        fr = p.get("frame", {})
        if fr.get("parentId"):
            return
        typ = p.get("type")
        with self._lock:
            self.main_frame_id = fr.get("id", self.main_frame_id)
            if typ == "BackForwardCacheRestore":
                # hello{restored} normally arrives BEFORE this event (spike 7): nothing to do here
                self._log({"type": "nav", "how": "bfcache_restore", "url": fr.get("url", "")[:2048]})
                return
            self._log({"type": "nav", "how": typ or "navigation", "url": fr.get("url", "")[:2048]})
            if self.epoch is not None and not self.epoch.retired:
                self._retire(self.epoch)
            if self.state == "recording" and self._gap_start is None:
                self._gap_start = time.monotonic()

    def _on_same_document(self, p):
        self._log({"type": "nav", "how": "same_document", "url": (p.get("url") or "")[:2048]})

    # ---- epochs ----
    def _retire(self, ep: Epoch):
        """The document is gone. Resolve its open groups; late messages with its token are dropped from now on."""
        ep.retired = True
        self._retired.add(ep.token)
        if not ep.armed and self.state == "recording":
            # the document went away before it was ever armed: whatever the user did in it (and the input count the
            # page would have reported at arm) is lost
            self.flag("gap", detail="document left before it was armed")
        for gid in sorted(ep.open_groups):
            g = self._groups.get((ep.n, gid))
            if not g or g["closed"]:
                continue
            g.update(closed=True, snap=None, synthetic=True)
            self._log({"type": "group_close", "gid": gid, "synthetic": True, "snap": None, "doc_navigated_after": True})
            if g["kind"] != "pointer" and not g["target"].get("is_button_like"):
                self.flag("unclosed_input_group", gid=gid)
        ep.open_groups.clear()
        if ep.last_group and time.monotonic() - ep.last_group[1] <= NAV_WINDOW_S:
            self._log({"type": "group_nav", "gid": ep.last_group[0], "doc_navigated_after": True})

    def _on_hello(self, cid: int, uid: str, m: dict):
        with self._lock:
            if self.epoch is not None and not self.epoch.retired:
                self._retire(self.epoch)
            self.epoch_n += 1
            ep = Epoch(self.epoch_n, secrets.token_hex(8), cid, uid, m["doc_id"], m["href"], m["restored"])
            self.epoch = ep
            if self.state == "recording" and self._gap_start is None:
                self._gap_start = time.monotonic()
            self._log({"type": "hello", "doc_id": m["doc_id"], "href": m["href"], "restored": m["restored"],
                       "persisted": m["persisted"], "nav_type": m["nav_type"]})
            self._timeline.append(("doc", ep.n, m["href"], m["restored"]))
            self._last_event = time.monotonic()
        self._submit(lambda: self._arm(ep))

    def _arm(self, ep: Epoch):
        if ep.retired:
            return
        try:
            r = self._send("Runtime.evaluate", timeout=10, expression=f"__kfwArm({json.dumps(ep.token)})", contextId=ep.ctx,
                           returnByValue=True)
            val = (r.get("result") or {}).get("value")
            if val != "armed" and not ep.retired:
                self.flag("gap", detail=f"arm:{val}")
        except Exception as e:  # noqa: BLE001
            if not ep.retired:
                self.flag("gap", detail=f"arm:{e}")

    # ---- bindingCalled: every check of design 2.2 ----
    def on_binding(self, p):
        if p.get("name") != "__kfwRec" or not self._live():
            return
        cid = p.get("executionContextId")
        try:
            msg = parse_payload(p.get("payload"))
        except BadPayload as e:
            self.flag("bad_payload", detail=str(e))
            return
        t = msg["type"]
        with self._lock:
            uid = self._ctx.get(cid) if isinstance(cid, int) else None
            if t == "hello":
                if uid is None:
                    self.flag("bad_payload", detail="hello_from_unknown_context")
                    return
                try:
                    m = clean_payload(msg)
                except BadPayload as e:
                    self.flag("bad_payload", detail=str(e))
                    return
                self._on_hello(cid, uid, m)
                return
            ep = self.epoch
            tok = msg.get("token")
            if ep is None or tok != ep.token:
                if isinstance(tok, str) and tok in self._retired:
                    self.stale_dropped += 1   # late data of a finished document: dropped, not an error
                    return
                self.flag("bad_payload", detail="bad_token")
                return
            if ep.retired:
                self.stale_dropped += 1
                return
            if uid is None or cid != ep.ctx or uid != ep.uid:
                self.flag("bad_payload", detail="wrong_context")
                return
            try:
                m = clean_payload(msg)
            except BadPayload as e:
                self.flag("bad_payload", detail=str(e))
                return
            if t == "armed":
                self._on_armed(ep, m)
                return
            seq = msg.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq != ep.last_seq + 1:
                if isinstance(seq, int) and not isinstance(seq, bool) and seq > ep.last_seq:
                    ep.last_seq = seq
                self.flag("seq_gap", detail=f"got {seq}")
                self._cond.notify_all()
                return
            ep.last_seq = seq
            getattr(self, "_h_" + t)(ep, m)
            self._cond.notify_all()

    def _on_armed(self, ep: Epoch, m: dict):
        ep.armed = True
        self._gap_start = None
        self._log({"type": "armed", "pre_arm_inputs": m["pre_arm_inputs"], "pre_kinds": m["pre_kinds"]})
        if m["pre_arm_inputs"] > 0:
            self.flag("pre_arm_input", count=m["pre_arm_inputs"])
        self._armed_evt.set()
        self._cond.notify_all()

    # ---- per-type handlers (called under the lock, message already validated and in sequence) ----
    def _h_snapshot(self, ep, m):
        if sensitive_present(m["controls"]):
            self._block("sensitive_value")
            return
        self.snaps.setdefault(m["id"], m["controls"])
        self.store.put_snapshot(m["id"], m["controls"])
        self._log({"type": "snapshot", "id": m["id"], "links_dropped": m["links_dropped"]})

    def _h_baseline(self, ep, m):
        self._refs.add(m["snap"])
        self._log({"type": "baseline", "snap": m["snap"], **({"res": m["res"]} if m.get("res") else {})})

    def _h_group_open(self, ep, m):
        g = {"epoch": ep.n, "gid": m["gid"], "kind": m["kind"], "target": m["target"], "prev": m["prev_snap"], "snap": None,
             "keys": [], "closed": False, "opened_at": time.monotonic()}
        self._groups[(ep.n, m["gid"])] = g
        if m["prev_snap"]:
            self._refs.add(m["prev_snap"])
        ep.open_groups.add(m["gid"])
        self._timeline.append(("group", ep.n, m["gid"]))
        self._last_event = time.monotonic()
        self._log({"type": "group_open", "gid": m["gid"], "kind": m["kind"], "target": m["target"], "prev_snap": m["prev_snap"],
                   **({"res": m["res"]} if m.get("res") else {})})
        if m["target"].get("iframe"):
            self.flag("iframe_interaction")

    def _h_group_close(self, ep, m):
        g = self._groups.get((ep.n, m["gid"]))
        if g is None or g["closed"]:
            self.flag("bad_payload", detail="group_close_without_open")
            return
        g.update(closed=True, snap=m["snap"], kind=m["kind"], keys=m["keys"], closed_at=time.monotonic())
        if m["snap"]:
            self._refs.add(m["snap"])
        ep.open_groups.discard(m["gid"])
        ep.last_group = (m["gid"], time.monotonic())
        self._last_event = time.monotonic()
        self._log({"type": "group_close", "gid": m["gid"], "kind": m["kind"], "snap": m["snap"], "keys": m["keys"],
                   **({"unloading": True} if m.get("unloading") else {})})
        if g["target"].get("custom_element"):
            prev, cur = self.snaps.get(g["prev"] or ""), self.snaps.get(m["snap"] or "")
            if not snap_diff(prev, cur):   # custom widget and no native field changed: we cannot tell what it did
                self.flag("custom_element_interaction", gid=m["gid"])

    def _h_flag(self, ep, m):
        self.flag(m["reason"])

    def _h_blocked(self, ep, m):
        self._block(m["reason"])

    def _h_mark(self, ep, m):
        self.marks.append(m)
        self._mark_epochs.append(ep.n)
        self._last_event = time.monotonic()
        self._log({"type": "mark", "tag": m["tag"], "text": m["text"], "text_truncated": m["text_truncated"], "href": m["href"],
                   "group": m["group"]})

    def _h_done(self, ep, m):
        self._last_event = time.monotonic()
        self._log({"type": "done"})
        if not self._auto_finish:
            self._auto_finish = True
            self._auto(lambda: self.finish(trigger="done"))

    # ---- blocked: stop collecting, delete, keep only a tombstone ----
    def _block(self, why: str):
        with self._lock:
            if self._blocked or self.state in TERMINAL:
                return
            self._blocked = True
            self._block_origin = origin_of(self.epoch.href if self.epoch else self.url)
            self.reasons = ["blocked"]
            self._set_state("incomplete")
        self.store.seal({"state": "incomplete", "reason": "blocked", "origin": self._block_origin})
        self.snaps.clear()
        self.marks.clear()
        self._mark_epochs.clear()
        self._groups.clear()
        self._timeline.clear()
        self._armed_evt.set()
        self._auto(lambda: self.finish(trigger="blocked"))

    # ---- timers ----
    def _monitor(self):
        while not self._halt.wait(0.2):
            now = time.monotonic()
            with self._lock:
                st, gs, last, launched = self.state, self._gap_start, self._last_event, self._auto_finish
            if st != "recording":
                continue
            if gs is not None and now - gs > GAP_S:
                self.flag("gap", detail="no arm after navigation")
                with self._lock:
                    self._gap_start = None
            if not launched:
                if now - self._t0 > MAX_S:
                    with self._lock:
                        self._auto_finish = True
                    self._auto(lambda: self.finish(trigger="too_long"))
                elif now - last > IDLE_S:
                    with self._lock:
                        self._auto_finish = True
                    self._auto(lambda: self.finish(trigger="idle"))

    # ---- barrier (design 2.2): flush -> last_seq received -> snapshot refs resolve -> fsync ----
    def _wait_armed(self, timeout: float) -> Epoch | None:
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                ep = self.epoch
                if ep is not None and ep.armed and not ep.retired:
                    return ep
                left = end - time.monotonic()
                if left <= 0 or self._blocked:
                    return None
                self._cond.wait(min(left, 0.1))

    def _barrier(self):
        ep = self._wait_armed(GAP_S + 0.5)
        if ep is None:
            self.flag("page_closed" if self._target_gone() else "unflushed", detail="no armed document at stop")
            return
        try:
            r = self._run(lambda: self._send("Runtime.evaluate", timeout=10, expression="__kfwFlush()", contextId=ep.ctx,
                                             returnByValue=True), timeout=15)
            val = (r.get("result") or {}).get("value") or {}
        except Exception as e:  # noqa: BLE001
            self.flag("page_closed" if self._target_gone() else "unflushed", detail=str(e))
            return
        if not val.get("ok"):
            if val.get("why") != "halted":
                self.flag("unflushed", detail=f"flush:{val.get('why')}")
            return
        end = time.monotonic() + BARRIER_S
        with self._cond:
            while ep.last_seq < val["last_seq"] and not self._blocked:
                left = end - time.monotonic()
                if left <= 0 or ep.retired:
                    break
                self._cond.wait(min(left, 0.1))
            got = ep.last_seq >= val["last_seq"] and val.get("token") == ep.token
        if not got and not self._blocked:
            self.flag("unflushed", detail=f"last_seq {ep.last_seq}/{val['last_seq']}")
            return
        with self._lock:
            missing = [s for s in self._refs if s not in self.snaps]
        if missing and not self._blocked:
            self.flag("unflushed", detail=f"unresolved snapshot refs: {len(missing)}")
        self.store.sync()

    # ---- finish: stop / done / idle / too_long / page gone / disconnect / start failed / blocked ----
    def finish(self, discard: bool = False, trigger: str = "stop", hint: str | None = None) -> dict:
        """Idempotent: the first caller does the work, everyone else gets the same result."""
        with self._fin_lock:
            if self.result is not None:
                return self.result
            try:
                res = self._finish(discard, trigger, hint)
            except BaseException as e:  # noqa: BLE001
                log.exception("recording finish failed")
                res = self._emergency(e)
            self.result = res
            self._halt.set()
            self._jobs.put(None)
            if self.on_finished:
                try:
                    self.on_finished(self)
                except Exception:  # noqa: BLE001
                    log.exception("on_finished raised")
            return res

    def _emergency(self, err) -> dict:
        with self._lock:
            if not self._blocked and self.state not in TERMINAL:
                self._set_state("incomplete")
            if "unflushed" not in self.reasons and not self._blocked:
                self.reasons.append("unflushed")
        return self._result_dict(warnings=[f"結束錄製時發生錯誤:{err}"])

    def _finish(self, discard: bool, trigger: str, hint: str | None) -> dict:
        if self._blocked:
            self._teardown()
            return self._blocked_result()
        if discard:
            self._teardown()
            self._set_state("discarded")
            self.store.close()
            self.store.seal({"state": "discarded"})
            return {"recording_id": self.id, "state": "discarded"}
        if self.state == "starting":
            self._teardown()
            self._set_state("incomplete")
            self.store.close()
            res = self._result_dict(warnings=[hint] if hint else [])
            self.store.write_final(self._meta(), res)
            return res
        self._set_state("stopping")
        if trigger == "too_long":
            self.flag("too_long")
        screenshot, live = None, None
        if trigger not in ("page_closed", "disconnect"):
            self._barrier()
            if not self._blocked:
                live = self._live_checks()          # design 7.1 order: barrier -> live check -> screenshot -> teardown -> to_draft
                screenshot = self._screenshot()
        else:
            self.flag("page_closed" if trigger == "page_closed" else "browser_disconnected")
        if self._blocked:
            self._teardown()
            return self._blocked_result()
        self._teardown()
        self.store.close()
        self._set_state("incomplete" if self.reasons else "completed")
        warnings = []
        if trigger == "page_closed" and screenshot is None:
            warnings.append("分頁已關閉,沒有截圖")
        res = self._result_dict(screenshot=screenshot, warnings=warnings)
        self._add_draft(res, live)
        meta = self._meta()
        meta["target_id"] = self.target_id
        meta["digest"] = self.store.digest()
        if not self.store.write_final(meta, res):     # a block sealed the recording while we were finishing
            self._teardown()
            return self._blocked_result()
        return res

    def _live_checks(self) -> dict | None:
        """Design 7.3 / I3: while the marked page is still the current document, run the candidate row pattern through the
        shared group observation. pattern_specific is true only when exactly ONE group matches and its fingerprint (a hash of
        canonical cells, never DOM ids) equals the marked group's. The page left (other document or URL) -> pending."""
        with self._lock:
            mark = self.marks[-1] if self.marks else None
            mark_ep = self._mark_epochs[-1] if self._mark_epochs else None
            ep = self.epoch
        if mark is None or not mark.get("group"):
            return None
        pattern, _ = draftmod.candidate_pattern(mark["group"])
        if pattern is None:
            return None
        base = {"pattern": pattern}
        if ep is None or ep.retired or ep.n != mark_ep or not ep.armed:
            return {**base, "status": "pending", "reason": "page_left_marked_document"}
        try:
            def ev(expr):
                r = self._run(lambda: self._send("Runtime.evaluate", timeout=15, expression=expr, contextId=ep.ctx, returnByValue=True), timeout=20)
                if r.get("exceptionDetails"):
                    raise RuntimeError(r["exceptionDetails"].get("text", "exception"))
                return (r.get("result") or {}).get("value")
            if ev("location.href") != mark.get("href"):
                return {**base, "status": "pending", "reason": "page_url_changed"}
            got = ev(f"{PICK_GROUPS_JS}({json.dumps(pattern)}, 1)")
            groups = (got or {}).get("groups") or []
        except Exception as e:  # noqa: BLE001
            return {**base, "status": "pending", "reason": f"check_failed:{str(e)[:80]}"}
        equal = len(groups) == 1 and groups[0].get("fingerprint") == mark["group"].get("fingerprint")
        return {**base, "status": "checked", "groups_matched": len(groups), "fingerprint_equal": equal, "pattern_specific": equal}

    def _add_draft(self, res: dict, live: dict | None):
        """Design 7.2: the draft is a pure function of the log + snapshots on disk (store already closed) + the live check."""
        try:
            d = draftmod.to_draft(read_log(self.store.dir), read_snapshots(self.store.dir), live, recording_id=self.id, terminal_state=self.state)
        except Exception as e:  # noqa: BLE001 - a conversion bug must not lose the recording
            log.exception("to_draft failed")
            res["warnings"].append(f"轉換草稿時發生錯誤:{type(e).__name__}: {str(e)[:100]}(錄製本身已保存)")
            return
        apply_draft(res, d)

    def _meta(self) -> dict:
        return {"id": self.id, "state": self.state, "reason": self.reasons[0] if self.reasons else None, "reasons": list(self.reasons),
                "url": self.url, "finished": time.time(), "records": self.store.records, "bytes": self.store.bytes,
                "stale_dropped": self.stale_dropped}

    def _blocked_result(self) -> dict:
        return {"recording_id": self.id, "state": "incomplete", "reason": "blocked", "draft": None, "param_candidates": [],
                "warnings": [REASON_HINTS["blocked"]], "demo_summary": None, "marked_summary": None}

    def _screenshot(self) -> str | None:
        try:
            r = self._run(lambda: self._send("Page.captureScreenshot", timeout=15, format="jpeg", quality=70), timeout=20)
            path = self.store.dir / "screenshot.jpg"
            with self.store.lock:
                if self.store.sealed:
                    return None
                path.write_bytes(base64.b64decode(r["data"]))
            return str(path)
        except Exception as e:  # noqa: BLE001
            log.warning("screenshot failed: %s", e)
            return None

    def _teardown(self):
        """Design 2.2 cleanup: page-side teardown, remove script and binding, off(), close our connection.
        The tab stays for the user."""
        ep = self.epoch
        steps = []
        if self.session:
            if ep is not None and not ep.retired:
                steps.append(("Runtime.evaluate", {"expression": "__kfwTeardown()", "contextId": ep.ctx, "returnByValue": True}))
            if self.script_id:
                steps.append(("Page.removeScriptToEvaluateOnNewDocument", {"identifier": self.script_id}))
            steps.append(("Runtime.removeBinding", {"name": "__kfwRec"}))
            for method, params in steps:
                try:
                    self._send(method, timeout=5, **params)
                except Exception:  # noqa: BLE001 - the page may be gone already
                    pass
        try:
            self.browser.send("Target.setDiscoverTargets", discover=False, timeout=5)
        except Exception:  # noqa: BLE001
            pass
        for s, m, cb in self._regs:
            self.browser.off(s, m, cb)
        self._regs.clear()
        self.browser.close()

    # ---- what stop returns: small, no raw log ----
    def _result_dict(self, screenshot: str | None = None, warnings: list[str] | None = None) -> dict:
        with self._lock:
            state = self.state
            reason = self.reasons[0] if self.reasons else None
            w = list(warnings or [])
            for r in self.reasons:
                if r in REASON_HINTS:
                    w.append(REASON_HINTS[r])
            if not self.marks and state != "discarded":
                w.append(draftmod.W_NO_MARK)
            if len(self.marks) > 1:
                w.append(draftmod.w_multi_mark(len(self.marks)))
            if self.stale_dropped:
                w.append(f"丟棄了 {self.stale_dropped} 筆舊文件遲到的紀錄(正常現象)。")
            res = {"recording_id": self.id, "state": state, "draft": None, "param_candidates": [], "warnings": w,
                   "demo_summary": self._demo_summary(), "marked_summary": self._marked_summary()}
            if reason:
                res["reason"] = reason
                if len(self.reasons) > 1:
                    res["reasons"] = list(self.reasons)
            if screenshot:
                res["screenshot"] = screenshot
            return res

    def _demo_summary(self) -> dict:
        docs, steps, by_kind = [], [], {}
        for item in self._timeline:
            if item[0] == "doc":
                if len(docs) < 10:
                    docs.append({"url": item[2][:200], "restored": item[3]})
            else:
                g = self._groups.get((item[1], item[2]))
                if not g:
                    continue
                by_kind[g["kind"]] = by_kind.get(g["kind"], 0) + 1
                if len(steps) < 30:
                    tgt = g["target"]
                    changes = snap_diff(self.snaps.get(g["prev"] or ""), self.snaps.get(g["snap"] or ""))
                    steps.append({"kind": g["kind"], "target": tgt.get("label") or tgt.get("text") or tgt.get("tag"),
                                  "button": bool(tgt.get("is_button_like")), "keys": g["keys"],
                                  "changes": [{"field": c["label"], "to": str(c["after"])[:60]} for c in changes[:3]]})
        return {"documents": len(docs), "urls": docs, "action_groups": sum(by_kind.values()), "by_kind": by_kind, "steps": steps,
                "steps_shown": len(steps)}

    def _marked_summary(self) -> dict | None:
        if not self.marks:
            return None
        m = self.marks[-1]
        out = {"marks": len(self.marks), "tag": m["tag"], "text": m["text"][:300], "text_chars": len(m["text"]), "url": m["href"][:200]}
        g = m["group"]
        if g:
            out["table"] = {"total_rows": g["total"], "truncated": g["truncated"], "has_th": g["has_th"],
                            "same_signature_groups": g["same_signature_groups"], "fingerprint": g["fingerprint"],
                            "rows": [[c[:60] for c in r[:12]] for r in g["rows"][:20]], "rows_shown": min(20, len(g["rows"]))}
        return out

    # ---- for tests and debugging ----
    def debug(self) -> dict:
        with self._lock:
            ep = self.epoch
            return {"state": self.state, "reasons": list(self.reasons), "epoch": ep.n if ep else 0, "armed": bool(ep and ep.armed),
                    "retired": bool(ep and ep.retired), "last_seq": ep.last_seq if ep else 0, "ctx": dict(self._ctx),
                    "groups": [dict(g) for g in self._groups.values()], "marks": len(self.marks), "snaps": len(self.snaps),
                    "stale_dropped": self.stale_dropped, "records": self.store.records, "target_id": self.target_id,
                    "session": self.session}


def apply_draft(res: dict, d: dict):
    """Merge to_draft's answer into a stop result (warnings are de-duplicated, order kept)."""
    res["draft"] = d["draft"]
    res["param_candidates"] = d["param_candidates"]
    res["live_checks"] = d["live_checks"]
    res["demo"] = d["demo"]
    for k in ("unsupported", "draft_todo", "suggested_expect_text", "then_candidates", "step_suggestions", "needs_review"):
        if d.get(k):
            res[k] = d[k]
    seen = set(res["warnings"])
    res["warnings"] = list(res["warnings"]) + [w for w in d["warnings"] if w not in seen]


def recordings_root() -> Path:
    return Path(compare.HOME) / "recordings"


def read_recording(rid: str, root: Path | None = None) -> dict:
    """What dry_run / save_recipe need from a recording on disk (never used by run_recipe):
    {ok, why?, state, digest, draft (to_draft output), mark}. Only a completed recording that is not expired and whose files
    still hash to the digest written at stop is usable as evidence."""
    if not isinstance(rid, str) or not ID_RE.fullmatch(rid):
        return {"ok": False, "why": "recorded_from 必須是 12 位十六進位的錄製 id"}
    d = (root or recordings_root()) / rid
    meta = Manager._read_meta(d) if d.is_dir() else None
    if meta is None:
        return {"ok": False, "why": f"找不到錄製 {rid}(不存在,或已超過 {RETENTION_DAYS} 天被清掉);請使用者重錄"}
    if meta.get("state") != "completed":
        return {"ok": False, "why": f"錄製 {rid} 的狀態是 {meta.get('state')},只有 completed 的錄製能當示範證據"}
    finished = meta.get("finished") or 0
    if finished and time.time() - finished > RETENTION_DAYS * 86400:
        return {"ok": False, "why": f"錄製 {rid} 已超過 {RETENTION_DAYS} 天保存期限,請使用者重錄", "expired": True}
    digest = meta.get("digest")
    if not digest or Store(d).digest() != digest:
        return {"ok": False, "why": f"錄製 {rid} 的內容和收尾時記下的 digest 不符(檔案被改過或損毀),不能當證據"}
    try:
        live = json.loads((d / "result.json").read_text(encoding="utf-8")).get("live_checks")
    except (OSError, ValueError):
        live = None
    log_, snaps = read_log(d), read_snapshots(d)
    return {"ok": True, "digest": digest, "state": "completed",
            "draft": draftmod.to_draft(log_, snaps, live, recording_id=rid, terminal_state="completed"), "mark": draftmod.mark_reference(log_)}


# ---------------------------------------------------------------------------------------------------
# the manager: one recording at a time, recovery, retention
# ---------------------------------------------------------------------------------------------------

def _default_browser_factory():
    compare.ensure_chrome()
    return Browser(compare.CDP)


class Manager:
    def __init__(self, home: Path | str | None = None, browser_factory=None):
        self.root = Path(home if home is not None else compare.HOME) / "recordings"
        self.factory = browser_factory or _default_browser_factory
        self._lock = threading.RLock()
        self._active: Recording | None = None
        self.root.mkdir(parents=True, exist_ok=True)
        self.recover()
        self.cleanup()

    def _dir(self, rid: str) -> Path:
        assert ID_RE.fullmatch(rid), rid
        return self.root / rid

    # ---- restart recovery: a directory with no terminal record is an incomplete recording ----
    def recover(self):
        for d in sorted(self.root.iterdir()):
            if not d.is_dir() or not ID_RE.fullmatch(d.name):
                continue
            with self._lock:
                if self._active is not None and self._active.id == d.name:
                    continue
            meta = self._read_meta(d)
            if meta is not None and meta.get("state") in TERMINAL:
                if meta.get("reason") == "blocked" or meta.get("state") == "discarded":  # finish an interrupted purge
                    for p in d.iterdir():
                        if p.name == "meta.json":
                            continue
                        if p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            p.unlink(missing_ok=True)
                continue
            tomb = {"id": d.name, "state": "incomplete", "reason": "server_restarted", "reasons": ["server_restarted"],
                    "finished": time.time(), "url": (meta or {}).get("url")}
            res = {"recording_id": d.name, "state": "incomplete", "reason": "server_restarted", "draft": None, "param_candidates": [],
                   "warnings": [REASON_HINTS["server_restarted"]], "demo_summary": None, "marked_summary": None}
            _atomic_write(d / "result.json", json.dumps(res, ensure_ascii=False).encode())
            _atomic_write(d / "meta.json", json.dumps(tomb, ensure_ascii=False).encode())

    @staticmethod
    def _read_meta(d: Path) -> dict | None:
        try:
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            return m if isinstance(m, dict) else None
        except (OSError, ValueError):
            return None

    def cleanup(self, now: float | None = None, days: int = RETENTION_DAYS) -> list[str]:
        """Delete recording directories older than `days` (finished time, else directory mtime). Returns their ids."""
        cutoff = (now if now is not None else time.time()) - days * 86400
        gone = []
        for d in self.root.iterdir():
            if not d.is_dir() or not ID_RE.fullmatch(d.name):
                continue
            with self._lock:
                if self._active is not None and self._active.id == d.name:
                    continue
            meta = self._read_meta(d) or {}
            stamp = meta.get("finished") or meta.get("started") or d.stat().st_mtime
            if stamp < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                gone.append(d.name)
        return gone

    # ---- tools ----
    def start(self, url: str) -> dict:
        u = urlsplit(url or "")
        if u.scheme not in ("http", "https") or not u.netloc:
            return {"state": "error", "reason": "bad_url", "hint": "只接受 http(s) 網址"}
        with self._lock:
            if self._active is not None:
                return {"state": "error", "reason": "recording_in_progress", "recording_id": self._active.id,
                        "hint": "已經有一個錄製在進行,先 stop_recording 它。"}
            self.cleanup()
            rid = secrets.token_hex(6)
            try:
                browser = self.factory()
            except Exception as e:  # noqa: BLE001
                return {"state": "error", "reason": "browser_unavailable", "hint": str(e)}
            store = Store(self._dir(rid))
            store.open({"id": rid, "state": "starting", "url": url, "started": time.time()})
            rec = Recording(rid, url, browser, store, on_finished=self._finished)
            self._active = rec
        try:
            rec.start()
        except RuntimeError as e:
            if rec._blocked:
                return {"recording_id": rid, "state": "incomplete", "reason": "blocked", "hint": REASON_HINTS["blocked"]}
            res = rec.result or {}
            return {"recording_id": rid, "state": res.get("state", "incomplete"), "reason": "start_failed", "hint": str(e)}
        return {"recording_id": rid, "state": rec.state,
                "tell_user": "請在剛開啟的分頁裡照平常的方式操作一次(不要輸入密碼、卡號等個資)。做完後,想當成『結果』的地方"
                             "請按畫面右下角的「標記結果」,再點那個區域;全部做完按「完成」,然後告訴我。"}

    def _finished(self, rec: Recording):
        with self._lock:
            if self._active is rec:
                self._active = None

    def active(self) -> Recording | None:
        with self._lock:
            return self._active

    def stop(self, rid: str, discard: bool = False, compare_to: str | None = None) -> dict:
        if not isinstance(rid, str) or not ID_RE.fullmatch(rid):
            return {"state": "error", "reason": "bad_recording_id"}
        with self._lock:
            rec = self._active if (self._active is not None and self._active.id == rid) else None
        d = self._dir(rid)
        if rec is not None:
            res = rec.finish(discard=discard, trigger="stop")
        elif d.is_dir():
            res = self._stored_result(d, rid)
        else:
            return {"state": "error", "reason": "not_found", "recording_id": rid}
        if discard and res.get("state") in ("completed", "incomplete") and res.get("reason") != "blocked":
            res = self._discard_disk(d, rid)
        res = dict(res)
        if compare_to:
            res["diff"] = self._diff(res, compare_to)
            if res["diff"].get("error"):
                res["warnings"] = list(res.get("warnings", [])) + [f"compare_to 沒有做成:{res['diff']['error']}"]
        return res

    @staticmethod
    def _diff(res: dict, name: str) -> dict:
        """compare_to=<recipe> (7.1): the demonstrated actions and result contract against an existing recipe."""
        from . import recipes  # recipes imports this module for read_recording
        if not res.get("draft"):
            return {"same": False, "error": "這份錄製沒有草稿(" + str((res.get("unsupported") or {}).get("reason") or res.get("state")) + "),沒有東西可比對"}
        try:
            recipe = recipes.get(name)
        except recipes.RecipeError as e:
            return {"same": False, "error": str(e)}
        return {"recipe": name, **draftmod.diff_against_recipe(res["draft"], recipe)}

    def _stored_result(self, d: Path, rid: str) -> dict:
        try:
            return json.loads((d / "result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        meta = self._read_meta(d) or {}
        st = meta.get("state")
        if st not in TERMINAL:          # a directory nobody owns: the server restarted mid-recording
            self.recover()
            return self._stored_result(d, rid)
        if st == "discarded":
            return {"recording_id": rid, "state": "discarded"}
        return {"recording_id": rid, "state": st, "reason": meta.get("reason"), "draft": None, "param_candidates": [],
                "warnings": [REASON_HINTS.get(meta.get("reason") or "", "")], "demo_summary": None, "marked_summary": None}

    def _discard_disk(self, d: Path, rid: str) -> dict:
        st = Store(d)
        st.seal({"state": "discarded"})
        return {"recording_id": rid, "state": "discarded"}


_MANAGER: Manager | None = None
_MANAGER_LOCK = threading.Lock()


def manager() -> Manager:
    """The process-wide manager (created on first use, so tests can point KFW_HOME first)."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = Manager()
        return _MANAGER
