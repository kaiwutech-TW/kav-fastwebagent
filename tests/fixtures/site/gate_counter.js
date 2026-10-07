// Counts every input-ish event the page receives (capture phase) into localStorage, so a test can read the
// totals from another tab after the engine has closed its own. Continues across page loads until cleared.
(() => {
  const names = ['pointerdown', 'mousedown', 'click', 'keydown', 'input', 'beforeinput'];
  let counts = {};
  try { counts = JSON.parse(localStorage.getItem('kfw_ev') || '{}'); } catch (e) {}
  for (const n of names) window.addEventListener(n, () => {
    counts[n] = (counts[n] || 0) + 1;
    try { localStorage.setItem('kfw_ev', JSON.stringify(counts)); } catch (e) {}
  }, true);
})();
