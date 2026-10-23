/* Apply before paint; appearance is local to this browser, never a database setting. */
(() => {
  const key = 'courtside-theme';
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const saved = () => { try { return localStorage.getItem(key); } catch { return null; } };
  const valid = value => value === 'light' || value === 'dark';
  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0b1220' : '#f4f7fb');
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    const dark = theme === 'dark';
    button.setAttribute('aria-pressed', String(dark));
    button.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} mode`);
    button.title = `Switch to ${dark ? 'light' : 'dark'} mode`;
    button.querySelector('.theme-icon').textContent = dark ? '☀' : '☾';
    button.querySelector('.theme-label').textContent = dark ? 'Light' : 'Dark';
  }
  const preference = saved();
  apply(valid(preference) ? preference : system.matches ? 'dark' : 'light');
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.getElementById('theme-toggle').addEventListener('click', () => {
      const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(key, theme); } catch { /* Still works for this session. */ }
      apply(theme);
    });
  });
  system.addEventListener('change', () => { if (!valid(saved())) apply(system.matches ? 'dark' : 'light'); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) {
      const theme = saved();
      apply(valid(theme) ? theme : system.matches ? 'dark' : 'light');
    }
  });
})();
