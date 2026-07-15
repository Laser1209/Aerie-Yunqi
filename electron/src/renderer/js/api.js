/* Aerie · 云栖 — API client wrapper for renderer */
(function () {
  'use strict';
  const base = window.aerie;
  if (!base || !base.api) {
    console.warn('aerie API bridge not available');
    return;
  }
  async function get(path) {
    const r = await base.api.get(path);
    if (r && typeof r === 'object' && 'data' in r) return r.data;
    return r;
  }
  async function post(path, body) {
    const r = await base.api.post(path, body || {});
    if (r && typeof r === 'object' && 'data' in r) return r.data;
    return r;
  }
  window.AerieAPI = { get, post };
})();
