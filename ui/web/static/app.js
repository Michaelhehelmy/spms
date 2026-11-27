(function () {
  function typewrite(el) {
    if (!el || el.dataset.typed === '1') return;
    const full = el.getAttribute('data-fulltext');
    if (full == null) return;
    el.dataset.typed = '1';
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || full.length === 0) {
      el.textContent = full;
      el.classList.remove('typing');
      return;
    }
    let i = 0;
    const speed = full.length > 600 ? 2 : (full.length > 200 ? 4 : 12);
    const step = full.length > 600 ? 4 : (full.length > 200 ? 2 : 1);
    el.textContent = '';
    el.classList.add('typing');
    function tick() {
      if (!el.isConnected) return;
      i = Math.min(full.length, i + step);
      el.textContent = full.slice(0, i);
      const container = document.getElementById('assistant-messages');
      if (container) container.scrollTop = container.scrollHeight;
      if (i < full.length) {
        setTimeout(tick, speed);
      } else {
        el.classList.remove('typing');
      }
    }
    tick();
  }

  function runTypewriter(root) {
    const scope = root || document;
    const nodes = scope.querySelectorAll ? scope.querySelectorAll('[data-animate="1"] .assistant-content[data-fulltext]') : [];
    nodes.forEach(typewrite);
    // also handle if root itself is container
    if (scope.querySelectorAll) {
      scope.querySelectorAll('.assistant-content[data-animate-self="1"][data-fulltext]').forEach(typewrite);
    }
  }

  function setActiveNav() {
    const path = window.location.pathname.replace(/\/$/, '') || '/';
    document.querySelectorAll('nav a.nav-link').forEach(a => {
      const href = (a.getAttribute('href') || '').replace(/\/$/, '') || '/';
      const active = href === '/' ? path === '/' : (path === href || path.startsWith(href + '/'));
      a.classList.toggle('active', active);
      if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }

  function setupNavDrawer() {
    const btn = document.getElementById('nav-toggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (!btn || !sidebar) return;
    function closeNav() {
      document.body.classList.remove('nav-open');
      btn.setAttribute('aria-expanded', 'false');
    }
    function openNav() {
      document.body.classList.add('nav-open');
      btn.setAttribute('aria-expanded', 'true');
    }
    btn.addEventListener('click', function () {
      document.body.classList.contains('nav-open') ? closeNav() : openNav();
    });
    if (overlay) overlay.addEventListener('click', closeNav);
    sidebar.querySelectorAll('a.nav-link').forEach(a => a.addEventListener('click', closeNav));
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeNav();
    });
    window.addEventListener('resize', function () {
      if (window.innerWidth > 900) closeNav();
    });
  }

  function markLoading(on) {
    document.body.classList.toggle('htmx-loading', !!on);
    const bar = document.getElementById('top-progress');
    if (bar) bar.classList.toggle('active', !!on);
  }

  document.addEventListener('DOMContentLoaded', function () {
    setActiveNav();
    setupNavDrawer();
    runTypewriter(document);
  });

  document.body.addEventListener('htmx:beforeRequest', function () { markLoading(true); });
  document.body.addEventListener('htmx:afterSwap', function (e) {
    markLoading(false);
    runTypewriter(e.target);
  });
  document.body.addEventListener('htmx:afterRequest', function () { markLoading(false); });
  document.body.addEventListener('htmx:responseError', function () { markLoading(false); });
  window.addEventListener('pageshow', setActiveNav);

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/static/sw.js', { scope: '/' }).catch(function () {
        // Ignore registration failures (e.g. non-HTTPS contexts where SW is unsupported)
      });
    });
  }
})();
