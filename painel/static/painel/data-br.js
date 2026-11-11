// Brazilian date entry with a themed calendar anchored above the trigger.
document.querySelectorAll('[data-date-br]').forEach((input, index) => {
  if (input.dataset.calendarBound) return;
  input.dataset.calendarBound = 'true';
  const parse = value => {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
    if (!m) return null;
    const date = new Date(`${m[3]}-${m[2]}-${m[1]}T12:00:00Z`);
    return Number.isFinite(date.getTime()) && date.getUTCDate() === +m[1] && date.getUTCMonth() + 1 === +m[2] ? date : null;
  };
  const iso = date => date.toISOString().slice(0, 10);
  const wrapper = document.createElement('span'); wrapper.className = 'data-br-anchor';
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'ui-button ui-button-secondary'; button.textContent = 'Calendário';
  button.setAttribute('aria-label', 'Escolher data no calendário'); button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-expanded', 'false');
  const popup = document.createElement('div'); popup.className = 'data-br-calendar'; popup.hidden = true;
  popup.id = `data-br-calendar-${index}`; popup.setAttribute('role', 'dialog'); popup.setAttribute('aria-label', 'Escolher data do atendimento'); button.setAttribute('aria-controls', popup.id);
  const header = document.createElement('div'); header.className = 'data-br-header';
  const nav = (text, label) => { const el = document.createElement('button'); el.type = 'button'; el.textContent = text; el.setAttribute('aria-label', label); return el; };
  const previous = nav('←', 'Mês anterior'), next = nav('→', 'Próximo mês');
  const title = document.createElement('strong'); title.setAttribute('aria-live', 'polite'); header.append(previous, title, next);
  const grid = document.createElement('div'); grid.className = 'data-br-grid';
  const close = nav('Fechar', 'Fechar calendário'); close.className = 'ui-button ui-button-secondary data-br-close';
  popup.append(header, grid, close); wrapper.append(button, popup); input.after(wrapper);
  let month;
  function render(focusDate = null) {
    title.textContent = month.toLocaleDateString('pt-BR', {month: 'long', year: 'numeric', timeZone: 'UTC'}); grid.replaceChildren();
    ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'].forEach(name => { const label = document.createElement('span'); label.textContent = name; grid.append(label); });
    const first = new Date(month); first.setUTCDate(1);
    for (let i = 0; i < first.getUTCDay(); i++) grid.append(document.createElement('span'));
    const selected = parse(input.value), today = new Date();
    const last = new Date(first); last.setUTCMonth(last.getUTCMonth() + 1); last.setUTCDate(0);
    for (let number = 1; number <= last.getUTCDate(); number++) {
      const date = new Date(first); date.setUTCDate(number);
      const cell = nav(String(number), date.toLocaleDateString('pt-BR', {dateStyle: 'full', timeZone: 'UTC'}));
      cell.dataset.date = iso(date); cell.setAttribute('aria-pressed', String(!!selected && iso(selected) === iso(date)));
      if (iso(date) === iso(today)) cell.setAttribute('aria-current', 'date');
      cell.addEventListener('click', () => {
        input.value = iso(date).split('-').reverse().join('/'); input.dispatchEvent(new Event('input', {bubbles: true})); input.dispatchEvent(new Event('change', {bubbles: true})); hide();
      }); grid.append(cell);
    }
    if (focusDate) grid.querySelector(`[data-date="${iso(focusDate)}"]`)?.focus();
  }
  function position() {
    popup.style.left = '0px'; const box = popup.getBoundingClientRect(), width = document.documentElement.clientWidth;
    if (box.right > width - 8) popup.style.left = `${width - 8 - box.right}px`;
    const adjusted = popup.getBoundingClientRect(); if (adjusted.left < 8) popup.style.left = `${parseFloat(popup.style.left) + 8 - adjusted.left}px`;
  }
  function hide(focus = true) { popup.hidden = true; button.setAttribute('aria-expanded', 'false'); if (focus) button.focus(); }
  button.addEventListener('click', () => {
    if (!popup.hidden) { hide(); return; }
    const selected = parse(input.value); month = selected || new Date(); month = new Date(month); month.setUTCDate(1);
    render(); popup.hidden = false; button.setAttribute('aria-expanded', 'true');
    if (button.getBoundingClientRect().top < popup.offsetHeight + 12) button.scrollIntoView({block: 'end'});
    position(); (selected && grid.querySelector(`[data-date="${iso(selected)}"]`) || grid.querySelector('button')).focus({preventScroll: true});
  });
  previous.addEventListener('click', () => { month.setUTCMonth(month.getUTCMonth() - 1); render(); position(); });
  next.addEventListener('click', () => { month.setUTCMonth(month.getUTCMonth() + 1); render(); position(); });
  close.addEventListener('click', () => hide());
  popup.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); hide(); }
    const offsets = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7};
    if (event.target.dataset.date && event.key in offsets) {
      event.preventDefault(); const date = new Date(`${event.target.dataset.date}T12:00:00Z`); date.setUTCDate(date.getUTCDate() + offsets[event.key]); month = new Date(date); month.setUTCDate(1); render(date); position();
    }
  });
  document.addEventListener('pointerdown', event => { if (!wrapper.contains(event.target)) hide(false); });
  document.addEventListener('focusin', event => { if (!wrapper.contains(event.target)) hide(false); });
  window.addEventListener('resize', () => { if (!popup.hidden) position(); });
});
