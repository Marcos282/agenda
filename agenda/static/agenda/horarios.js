(() => {
  const form = document.querySelector('[data-refresh-url]');
  if (!form) return;

  const slots = form.querySelector('[data-booking-slots]');
  const empty = document.querySelector('[data-booking-empty]');
  const status = document.querySelector('[data-refresh-status]');
  let refreshing = false;

  async function refresh() {
    if (document.hidden || refreshing) return;
    refreshing = true;

    try {
      const response = await fetch(form.dataset.refreshUrl, {
        headers: {Accept: 'application/json'},
        cache: 'no-store',
      });
      if (!response.ok) throw new Error('Horários indisponíveis para atualização.');

      const data = await response.json();
      if (!Array.isArray(data.horarios) || data.horarios.some(
        horario => typeof horario.hora !== 'string' || typeof horario.fim !== 'string'
      )) {
        throw new Error('Resposta inválida ao atualizar horários.');
      }

      const selected = form.querySelector('input[name="hora"]:checked')?.value;
      const fragment = document.createDocumentFragment();
      for (const horario of data.horarios) {
        const label = document.createElement('label');
        label.className = 'booking-slot';

        const input = document.createElement('input');
        input.type = 'radio';
        input.name = 'hora';
        input.value = horario.hora;
        input.required = true;
        input.checked = horario.hora === selected;

        const span = document.createElement('span');
        const start = document.createElement('strong');
        start.textContent = horario.hora;
        const end = document.createElement('small');
        end.textContent = `até ${horario.fim}`;

        span.append(start, end);
        label.append(input, span);
        fragment.append(label);
      }

      slots.replaceChildren(fragment);
      const hasSlots = data.horarios.length > 0;
      form.hidden = !hasSlots;
      empty.hidden = hasSlots;

      const selectionExpired = selected && !data.horarios.some(
        horario => horario.hora === selected
      );
      status.textContent = selectionExpired
        ? 'O horário selecionado já passou ou não está mais disponível. Escolha outro.'
        : '';
      status.hidden = !status.textContent;
    } catch {
      status.textContent = 'Não foi possível atualizar os horários. Tente novamente em instantes.';
      status.hidden = false;
    } finally {
      refreshing = false;
    }
  }

  window.setInterval(refresh, 15000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
})();
