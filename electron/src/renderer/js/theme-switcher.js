/* Aerie · 云栖 — Theme switcher */
(function () {
  'use strict';
  const THEMES = ['yita-pink', 'midnight-purple', 'sakura-white', 'ocean-blue', 'forest-green'];
  function apply(theme) {
    if (!THEMES.includes(theme)) theme = 'yita-pink';
    const link = document.getElementById('theme-css');
    if (link) link.setAttribute('href', `styles/themes/${theme}.css`);
    try { localStorage.setItem('aerie-theme', theme); } catch (_) {}
    if (window.aerie && window.aerie.config) {
      window.aerie.config.set({ theme }).catch(() => {});
    }
  }
  function current() {
    try { return localStorage.getItem('aerie-theme') || 'yita-pink'; }
    catch (_) { return 'yita-pink'; }
  }
  window.AerieTheme = { apply, current, THEMES };
  document.addEventListener('DOMContentLoaded', () => apply(current()));
})();
