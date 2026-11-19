(() => {
  'use strict';
  const input = document.querySelector('#manual-search');
  if (!input) return;
  const guides = [...document.querySelectorAll('[data-tutorial]')];
  const groups = [...document.querySelectorAll('[data-group]')];
  const links = [...document.querySelectorAll('[data-category]')];
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const index = new Map(guides.map(guide => [guide, normalize(
    guide.textContent + ' ' + guide.dataset.keywords + ' ' + guide.closest('[data-group]').querySelector('.manual-category-heading h2').textContent
  )]));
  let category = 'todos';
  document.querySelector('[data-search-ui]').hidden = false;
  const menu = document.querySelector('#manual-menu');
  const media = window.matchMedia('(max-width: 800px)');
  const adaptMenu = () => { menu.open = !media.matches; };
  adaptMenu();
  media.addEventListener('change', adaptMenu);

  function filter() {
    const words = normalize(input.value.trim()).split(/\s+/).filter(Boolean);
    let count = 0;
    for (const guide of guides) {
      const matchCategory = words.length || category === 'todos' || guide.closest('[data-group]').dataset.group === category;
      guide.hidden = !matchCategory || !words.every(word => index.get(guide).includes(word));
      if (!guide.hidden) count++;
    }
    for (const group of groups) group.hidden = ![...group.querySelectorAll('[data-tutorial]')].some(guide => !guide.hidden);
    for (const link of links) {
      if (link.closest('nav') && link.dataset.category === (words.length ? 'todos' : category)) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
    document.querySelector('#manual-empty').hidden = count > 0;
    document.querySelector('#manual-results').textContent = `${count} ${count === 1 ? 'tutorial encontrado' : 'tutoriais encontrados'}${words.length ? ' na pesquisa' : ''}.`;
  }
  function activateVideo(selectedGroup) {
    for (const section of document.querySelectorAll('[data-category-video]')) {
      const selected = section.closest('[data-group]') === selectedGroup;
      section.hidden = !selected;
      const player = section.querySelector('[data-video-player]');
      if (!player) continue;
      const videoId = player.dataset.videoId;
      if (selected && /^[A-Za-z0-9_-]{11}$/.test(videoId)) {
        const source = `https://www.youtube-nocookie.com/embed/${videoId}`;
        if (player.getAttribute('src') !== source) player.setAttribute('src', source);
      } else {
        player.removeAttribute('src');
      }
    }
  }

  function navigate() {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    const guide = guides.find(item => item.id === id);
    if (guide) {
      input.value = '';
      category = guide.closest('[data-group]').dataset.group;
      filter();
      activateVideo(guide.closest('[data-group]'));
      guide.open = true;
      guide.querySelector('summary').focus({preventScroll: true});
      guide.scrollIntoView({block: 'start'});
    } else if (id === 'todos' || groups.some(group => group.id === id)) {
      category = id;
      input.value = '';
      filter();
      const selectedGroup = groups.find(group => group.id === id);
      activateVideo(selectedGroup);
      document.querySelector('#manual-content').focus({preventScroll: true});
      if (media.matches) menu.open = false;
      if (id === 'primeiros-passos') {
        selectedGroup.querySelector('[data-tutorial]').open = true;
        selectedGroup.scrollIntoView({block: 'start'});
      }
    }
  }
  for (const guide of guides) {
    guide.querySelector('summary').addEventListener('click', () => {
      if (!guide.open && location.hash !== '#' + guide.id) history.pushState(null, '', '#' + guide.id);
    });
  }
  input.addEventListener('input', () => {
    filter();
    activateVideo(input.value.trim() ? null : groups.find(group => group.id === category));
  });
  document.querySelector('#manual-clear').addEventListener('click', () => {
    input.value = ''; category = 'todos'; filter(); input.focus();
  });
  window.addEventListener('hashchange', navigate);
  // Reopening the current hash also works after a search or a collapsed tutorial.
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href^="#"]');
    if (anchor && anchor.hash === location.hash) navigate();
  });
  for (const box of document.querySelectorAll('[data-feedback]')) {
    box.hidden = false;
    const key = `tacombinado-manual-v1:${box.dataset.feedback}`;
    const status = box.querySelector('[role="status"]');
    function vote(value, saved) {
      for (const button of box.querySelectorAll('[data-vote]')) button.setAttribute('aria-pressed', String(button.dataset.vote === value));
      status.textContent = value === 'sim' ? 'Que bom! Obrigado pela avaliação.' : 'Tente os tutoriais relacionados ou pesquise por outra palavra. Esta avaliação não abre um chamado de suporte.';
      if (!saved) status.textContent += ' Não foi possível guardar a escolha neste navegador.';
    }
    try { const value = localStorage.getItem(key); if (['sim', 'ajuda'].includes(value)) vote(value, true); } catch (_) { /* Reading remains available. */ }
    box.addEventListener('click', event => {
      const button = event.target.closest('[data-vote]');
      if (!button) return;
      let saved = true;
      try { localStorage.setItem(key, button.dataset.vote); } catch (_) { saved = false; }
      vote(button.dataset.vote, saved);
    });
  }
  filter();
  navigate();
})();
