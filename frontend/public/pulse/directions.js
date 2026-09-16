(() => {
  const query = new URLSearchParams(location.search);
  const aliases = { signal: 'pulse', platinum: 'atlas' };
  const direction = aliases[query.get('direction')] || query.get('direction');
  if (!['studio', 'pulse', 'atlas'].includes(direction)) return;
  document.body.dataset.direction = direction;
  if (direction === 'pulse') {
    const favicon = document.querySelector('link[rel="icon"]');
    if (favicon) favicon.href = favicon.href.replace('%23d7f78b', '%23c8d0d9');
  }
  const embedded = query.get('embedded') === '1';
  if (embedded) document.body.dataset.embedded = 'true';
  const labels = {
    studio: ['Studio', 'STUDIO / REFINED', 'People.\nPossibilities.', 'A considered rhythm for people, conversations and new opportunities.'],
    pulse: ['Pulse', 'PULSE / REFINED', 'Be part of\nwhat happens next.', 'Ideas, conversations and openings from the people you follow.'],
    atlas: ['Atlas', 'ATLAS / REFINED', 'A new perspective.\nA new possibility.', 'Discover the people and work that open up your next chapter.']
  };
  const [name, edition, headline, copy] = labels[direction];
  const label = document.querySelector('.desktop-label span');
  if (label) label.textContent = edition;
  const title = document.querySelector('.desktop-context h2');
  if (title && !document.body.dataset.responsive) { title.textContent = headline; title.style.whiteSpace = 'pre-line'; }
  const description = document.querySelector('.desktop-context p');
  if (description && !document.body.dataset.responsive) description.textContent = copy;
  const foot = document.querySelector('.rail-foot');
  if (foot && !document.body.dataset.responsive) foot.textContent = name + ' · FYND refinement study';
  document.title = 'FYND — ' + name;
  if (!embedded) {
    const view = ['feed', 'discover', 'inbox', 'profile', 'settings', 'collider'].includes(query.get('view')) ? query.get('view') : 'feed';
    const back = document.createElement('a');
    back.className = 'study-return';
    back.href = 'refinements.html?direction=' + direction + '&view=' + view;
    back.innerHTML = '← Compare designs <span>' + name + '</span>';
    document.querySelector('.device')?.prepend(back);
  }
})();
