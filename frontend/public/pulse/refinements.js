(() => {
  const names = { studio: 'Studio', pulse: 'Pulse', atlas: 'Atlas' };
  const aliases = { signal: 'pulse', platinum: 'atlas' };
  const screens = ['feed', 'discover', 'inbox', 'profile', 'settings', 'collider'];
  const params = new URLSearchParams(location.search);
  let view = screens.includes(params.get('view')) ? params.get('view') : 'feed';
  const requested = aliases[params.get('direction')] || params.get('direction');
  let selection = Object.hasOwn(names, requested) ? requested : 'studio';
  let picks = [];
  try {
    const stored = JSON.parse(localStorage.getItem('fynd-refinement-shortlist') || '[]');
    if (Array.isArray(stored)) picks = [...new Set(stored.map(x => aliases[x] || x).filter(x => Object.hasOwn(names, x)))];
  } catch {}
  const frames = [...document.querySelectorAll('[data-frame]')];
  function sendView(frame) {
    frame.contentWindow?.postMessage({ type: 'fynd-refinement-view', screen: view }, location.origin);
  }
  function updateAddress() {
    const address = new URL(location.href);
    address.searchParams.set('direction', selection);
    address.searchParams.set('view', view);
    history.replaceState(null, '', address);
  }
  function selectScreen(next) {
    if (!screens.includes(next)) return;
    view = next;
    document.querySelectorAll('[data-view]').forEach(button => {
      const on = button.dataset.view === view;
      button.classList.toggle('selected', on);
      button.setAttribute('aria-pressed', String(on));
    });
    document.querySelectorAll('[data-open]').forEach(link => {
      link.href = './?direction=' + link.dataset.open + '&view=' + view;
    });
    frames.forEach(sendView);
    updateAddress();
  }
  function selectDirection(next) {
    if (!Object.hasOwn(names, next)) return;
    selection = next;
    document.querySelectorAll('[data-select]').forEach(button => {
      const on = button.dataset.select === selection;
      button.classList.toggle('selected', on);
      button.setAttribute('aria-pressed', String(on));
    });
    document.querySelectorAll('.direction-card').forEach(card => card.classList.toggle('active', card.dataset.direction === selection));
    updateAddress();
  }
  function renderPicks() {
    document.querySelectorAll('[data-pick]').forEach(button => {
      const picked = picks.includes(button.dataset.pick);
      button.setAttribute('aria-pressed', String(picked));
      button.innerHTML = picked ? '<span aria-hidden="true">✓</span> Shortlisted' : '<span aria-hidden="true">＋</span> Shortlist';
    });
    document.getElementById('shortlistState').textContent = picks.length
      ? 'Your shortlist: ' + picks.map(x => names[x]).join(' + ') + '. Saved on this browser.'
      : 'Shortlist the directions you like, or open any one at full size.';
  }
  document.addEventListener('click', event => {
    const screen = event.target.closest('[data-view]');
    if (screen) selectScreen(screen.dataset.view);
    const option = event.target.closest('[data-select]');
    if (option) selectDirection(option.dataset.select);
    const pick = event.target.closest('[data-pick]');
    if (pick && Object.hasOwn(names, pick.dataset.pick)) {
      const next = pick.dataset.pick;
      picks = picks.includes(next) ? picks.filter(x => x !== next) : [...picks, next];
      renderPicks();
      try { localStorage.setItem('fynd-refinement-shortlist', JSON.stringify(picks)); }
      catch { document.getElementById('shortlistState').textContent = 'Shortlist kept for this session. Browser storage is unavailable.'; }
    }
  });
  frames.forEach(frame => frame.addEventListener('load', () => sendView(frame)));
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.data?.type !== 'fynd-refinement-ready') return;
    const frame = frames.find(frame => frame.contentWindow === event.source);
    if (frame) sendView(frame);
  });
  selectDirection(selection);
  selectScreen(view);
  renderPicks();
})();
