"""Pre-WP0b observation JS, frozen verbatim from kfw/form.py at c727fab: the reference for equivalence tests."""

OLD_CONTROLS_JS = r"""(() => {
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
  let seq = window.__kfwSeq || 0; const out = [];
  for (const e of document.querySelectorAll('select, input, textarea, button, [role=button], a[href]')) {
    if (!visible(e) || e.disabled || e.type === 'hidden') continue;
    if (!e.dataset.kfwId) e.dataset.kfwId = 'k' + (++seq);
    const base = {id: e.dataset.kfwId, label: labelOf(e)};
    if (e.tagName === 'SELECT') out.push({...base, kind: 'select', value: e.selectedOptions[0]?.text.trim() || '',
        options: [...e.options].filter(o => !o.disabled).map(o => o.text.trim()).slice(0, 60)});
    else if (e.tagName === 'INPUT' && ['checkbox', 'radio'].includes(e.type)) out.push({...base, kind: e.type, checked: e.checked});
    else if (e.tagName === 'INPUT' || e.tagName === 'TEXTAREA')
      out.push({...base, kind: 'text', value: e.value, readonly: e.readOnly, input_type: e.type, placeholder: e.placeholder || undefined});
    else { const t = norm(e.innerText || e.value || e.getAttribute('aria-label')); if (!t || t.length > 40) continue;
      out.push({...base, kind: e.tagName === 'A' ? 'link' : 'button', label: t}); }
  }
  window.__kfwSeq = seq;
  return out;
})()"""

OLD_ROWS_JS = r"""((pattern, minRows) => {
  const re = new RegExp(pattern);
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const sig = e => e.tagName + '.' + [...e.classList].filter(c => !/\d{3,}/.test(c)).slice(0, 3).sort().join('.');
  let best = null;
  for (const parent of document.querySelectorAll('body *')) {
    const groups = {};
    for (const k of parent.children) (groups[sig(k)] ||= []).push(k);
    for (const items of Object.values(groups)) {
      const good = items.filter(k => re.test(norm(k.innerText)));
      if (good.length < minRows || good.length < 0.6 * items.length) continue;
      const score = good.reduce((a, k) => a + norm(k.innerText).length, 0);
      if (!best || good.length > best.length || (good.length === best.length && score > best.score)) best = Object.assign(good, {score});
    }
  }
  if (!best) return [];
  return best.slice(0, 200).map(k => {
    const cells = [...k.children].map(c => norm(c.innerText)).filter(Boolean);
    return cells.length > 1 ? cells : norm(k.innerText).split(/\s*\n\s*|\s{2,}/).filter(Boolean);
  });
})"""
