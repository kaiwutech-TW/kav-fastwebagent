// WP-S spike: minimal recorder, injected into isolated world "kfw_rec" via
// Page.addScriptToEvaluateOnNewDocument(worldName="kfw_rec"). Not product code.
(() => {
  'use strict';
  if (window.top !== window) return;               // main-frame guard (no hello from iframes)
  const B = globalThis.__kfwRec;                   // binding: only exists in the world named kfw_rec
  if (typeof B !== 'function') return;
  if (globalThis.__kfwInstalled) return;
  globalThis.__kfwInstalled = true;

  const S = { token: null, seq: 0, torn: false, preArm: 0, preKinds: [], mountCount: 0,
              mountedAt: null, docId: Math.random().toString(36).slice(2), lastErr: null,
              injectedAt: performance.now(), pageshows: 0 };
  const send = (o) => { try { B(JSON.stringify(o)); return true; } catch (e) { S.lastErr = String(e); return false; } };
  const navType = () => { try { return performance.getEntriesByType('navigation')[0].type; } catch (e) { return null; } };
  const hello = (restored, persisted) => send({
    type: 'hello', docId: S.docId, href: location.href, readyState: document.readyState,
    restored, persisted, navType: navType(), t: performance.now(), timeOrigin: performance.timeOrigin,
    earlyAttr: document.documentElement ? document.documentElement.getAttribute('data-early') : 'no-documentElement',
    hasBody: !!document.body });

  // ---- UI: closed shadow root, createElement + textContent + CSSOM only ----
  let host = null, btn = null, mo = null;
  const build = () => {
    host = document.createElement('div');
    const hs = host.style;
    hs.setProperty('all', 'initial');
    hs.setProperty('position', 'fixed'); hs.setProperty('right', '16px'); hs.setProperty('bottom', '16px');
    hs.setProperty('z-index', '2147483647'); hs.setProperty('display', 'block');
    const root = host.attachShadow({ mode: 'closed' });
    const bar = document.createElement('div');
    const bs = bar.style;
    bs.setProperty('display', 'flex'); bs.setProperty('align-items', 'center');
    bs.setProperty('background', 'rgb(30, 30, 30)'); bs.setProperty('color', 'rgb(255, 255, 255)');
    bs.setProperty('padding', '8px 12px'); bs.setProperty('border-radius', '8px');
    bs.setProperty('font', '14px sans-serif');
    const label = document.createElement('span');
    label.textContent = 'Kav REC';
    label.style.setProperty('margin-right', '10px');
    btn = document.createElement('button');
    btn.textContent = 'Done';
    const ts = btn.style;
    ts.setProperty('background', 'rgb(0, 170, 119)'); ts.setProperty('color', 'rgb(255, 255, 255)');
    ts.setProperty('border', 'none'); ts.setProperty('padding', '6px 16px'); ts.setProperty('cursor', 'pointer');
    btn.addEventListener('click', () => send({ type: 'ui_click', token: S.token, seq: S.token ? ++S.seq : null, t: performance.now() }));
    bar.appendChild(label); bar.appendChild(btn); root.appendChild(bar);
  };
  const mount = () => {
    if (S.torn || !document.body) return;
    if (host && host.isConnected) return;
    if (!host) build();
    document.body.appendChild(host);
    S.mountCount++; S.mountedAt = performance.now();
  };
  mo = new MutationObserver(() => mount());
  mo.observe(document, { childList: true, subtree: true });
  mount();

  // ---- events ----
  const isOurs = (e) => { try { return !!host && e.composedPath().includes(host); } catch (_) { return false; } };
  const mk = (kind) => (e) => {
    if (!e.isTrusted || S.torn || isOurs(e)) return;
    if (!S.token) { S.preArm++; S.preKinds.push(kind); return; }
    const t = e.target;
    send({ type: 'ev', token: S.token, seq: ++S.seq, kind, tag: t && t.tagName, id: t && t.id, key: e.key, t: performance.now() });
  };
  const ls = [];
  const add = (target, type, fn) => { target.addEventListener(type, fn, true); ls.push([target, type, fn]); };
  add(window, 'pointerdown', mk('pointerdown'));
  add(window, 'keydown', mk('keydown'));
  add(window, 'input', mk('input'));
  add(window, 'pagehide', (e) => {
    S.pagehide = (S.pagehide || 0) + 1;
    if (S.token && !S.torn) { const seq = ++S.seq; S.pagehideSent = send({ type: 'pagehide', token: S.token, seq, persisted: e.persisted, t: performance.now() }); }
  });
  add(window, 'beforeunload', () => {
    S.bu = (S.bu || 0) + 1;
    if (S.token && !S.torn) { const seq = ++S.seq; S.buSent = send({ type: 'beforeunload', token: S.token, seq, t: performance.now() }); }
  });
  add(document, 'visibilitychange', () => {
    S.vis = (S.vis || 0) + 1;
    if (S.token && !S.torn) { const seq = ++S.seq; S.visSent = send({ type: 'vis', state: document.visibilityState, token: S.token, seq, t: performance.now() }); }
  });
  add(window, 'pageshow', (e) => {
    S.pageshows++;
    if (e.persisted && !S.torn) { S.token = null; S.seq = 0; hello(true, true); }   // BFCache: old token void, ask to re-arm
  });

  window.__kfwArm = (token) => {
    if (S.torn) return 'torn';
    S.token = token; S.seq = 0;
    send({ type: 'armed', token, preArm: S.preArm, preKinds: S.preKinds.slice(), t: performance.now() });
    S.preArm = 0; S.preKinds = [];
    return 'armed';
  };
  window.__kfwTeardown = () => {
    S.torn = true; S.token = null;
    for (const [t, ty, fn] of ls) t.removeEventListener(ty, fn, true);
    if (mo) mo.disconnect();
    if (host) host.remove();
    return 'torn-down';
  };
  window.__kfwInfo = () => {
    const r = host ? host.getBoundingClientRect() : null;
    const b = btn ? btn.getBoundingClientRect() : null;
    let hit = null;
    if (b && host && host.isConnected) { const el = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); hit = el === host; }
    const cs = host ? getComputedStyle(host) : null;
    const r2 = (x) => x && [Math.round(x.x), Math.round(x.y), Math.round(x.width), Math.round(x.height)];
    return { torn: S.torn, connected: !!host && host.isConnected, hostRect: r2(r), btnRect: r2(b), hit,
      display: cs && cs.display, position: cs && cs.position, visibility: cs && cs.visibility, opacity: cs && cs.opacity,
      mountCount: S.mountCount, mountedAt: S.mountedAt, bodyChildren: document.body ? document.body.childElementCount : null,
      token: S.token, seq: S.seq, preArm: S.preArm, lastErr: S.lastErr, pageshows: S.pageshows, docId: S.docId, pagehideCount: S.pagehide || 0, pagehideSent: S.pagehideSent, buCount: S.bu || 0, buSent: S.buSent, visCount: S.vis || 0, visSent: S.visSent, seqNow: S.seq };
  };
  window.__kfwProbe = () => {
    const out = {};
    const red = (d) => { document.body.appendChild(d); const ok = getComputedStyle(d).color === 'rgb(255, 0, 0)'; d.remove(); return ok; };
    const t = (n, f) => { try { const v = f(); out[n] = v === undefined ? 'ok' : v; } catch (e) { out[n] = 'ERR ' + e.name + ': ' + String(e.message).slice(0, 90); } };
    t('innerHTML', () => { const d = document.createElement('div'); d.innerHTML = '<b>x</b>'; });
    t('setAttribute_style_effective', () => { const d = document.createElement('div'); d.setAttribute('style', 'color:red'); return red(d); });
    t('cssText_effective', () => { const d = document.createElement('div'); d.style.cssText = 'color:red'; return red(d); });
    t('styleProp_effective', () => { const d = document.createElement('div'); d.style.setProperty('color', 'red'); return red(d); });
    t('styleElement_effective', () => { const s = document.createElement('style'); s.textContent = '.kfwz{color:red}'; document.head.appendChild(s); const d = document.createElement('div'); d.className = 'kfwz'; const ok = red(d); s.remove(); return ok; });
    t('constructableSheet_effective', () => { const sh = new CSSStyleSheet(); sh.replaceSync('.kfwy{color:red}'); document.adoptedStyleSheets = [...document.adoptedStyleSheets, sh]; const d = document.createElement('div'); d.className = 'kfwy'; const ok = red(d); document.adoptedStyleSheets = document.adoptedStyleSheets.filter(x => x !== sh); return ok; });
    t('eval', () => eval('1+1'));
    return out;
  };

  hello(false, false);
})();
