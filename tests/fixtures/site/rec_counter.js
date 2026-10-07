// Counts what the SITE receives (main world, capture phase on window and document) into window.__ev.
(() => {
  const names = ['pointerdown', 'pointerup', 'pointermove', 'mousedown', 'mouseup', 'mousemove', 'click', 'keydown', 'keyup',
    'input', 'beforeinput', 'wheel', 'contextmenu', 'submit'];
  window.__ev = {};
  for (const target of [window, document]) for (const n of names) target.addEventListener(n, () => { window.__ev[n] = (window.__ev[n] || 0) + 1; }, true);
  window.__evReset = () => { window.__ev = {}; };
})();
