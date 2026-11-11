(() => {
  'use strict';
  const form = document.querySelector('#batch-form');
  if (!form) return;
  const byId = id => document.getElementById(id);
  const selected = name => [...form.querySelectorAll(`input[name="${name}"]:checked`)];
  const days = byId('batch-days'), button = byId('batch-submit'), dialog = byId('batch-confirm');
  let busy = false, completed = false;
  function isoDate(value) {
    const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
    if (!match) return '';
    const iso = `${match[3]}-${match[2]}-${match[1]}`;
    const date = new Date(`${iso}T12:00:00Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === iso ? iso : '';
  }
  function dates() {
    const previous = new Map([...days.querySelectorAll('input')].map(input => [input.value, input.checked]));
    days.replaceChildren();
    const count = Number(form.elements.quantidade_dias.value), raw = isoDate(form.elements.data_inicial.value);
    if (!raw || !Number.isInteger(count) || count < 1 || count > 7) { update(); return; }
    const start = new Date(`${raw}T12:00:00Z`);
    if (!Number.isFinite(start.getTime())) return;
    for (let i = 0; i < count; i++) {
      const day = new Date(start); day.setUTCDate(start.getUTCDate() + i);
      const iso = day.toISOString().slice(0, 10), label = document.createElement('label');
      label.className = 'batch-choice day-choice';
      const input = document.createElement('input'); input.type = 'checkbox'; input.name = 'datas'; input.value = iso;
      input.checked = previous.has(iso) ? previous.get(iso) : true;
      const weekday = document.createElement('span'); weekday.textContent = day.toLocaleDateString('pt-BR', {weekday: 'short', timeZone: 'UTC'});
      const date = document.createElement('strong'); date.textContent = day.toLocaleDateString('pt-BR', {day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC'});
      label.append(input, weekday, date); days.append(label);
    }
    update();
  }
  function update() {
    const professionals = selected('profissionais').length, count = selected('datas').length;
    byId('batch-count').textContent = `👥 ${professionals} profissionais | 📅 ${count} dias selecionados`;
    byId('batch-summary').textContent = `${professionals} profissionais × ${count} dias = ${professionals * count} configurações selecionadas.`;
    byId('batch-operation').textContent = completed ? 'Operação concluída' : 'A prévia verificará horários já configurados';
    const shifts = ['manha', 'tarde'].filter(name => form.elements[name].checked);
    ['manha', 'tarde'].forEach(name => ['inicio', 'fim'].forEach(edge => {
      form.elements[`${name}_${edge}`].disabled = !form.elements[name].checked;
    }));
    byId('batch-hours').textContent = shifts.map(name => `${name === 'manha' ? 'Manhã' : 'Tarde'}: ${form.elements[name + '_inicio'].value} → ${form.elements[name + '_fim'].value}`).join(' · ');
    byId('batch-break').textContent = shifts.length === 2 ? `Intervalo entre turnos: ${form.elements.manha_fim.value} → ${form.elements.tarde_inicio.value}` : 'Um turno ativo · sem intervalo entre turnos';
    button.disabled = busy || !professionals || !count || !shifts.length;
  }
  form.addEventListener('input', event => {
    completed = false;
    if (['quantidade_dias', 'data_inicial'].includes(event.target.name)) dates(); else update();
  });
  form.querySelector('[data-professionals-all]').addEventListener('click', () => {
    completed = false;
    const inputs = [...form.querySelectorAll('[name="profissionais"]')];
    const check = !inputs.every(input => input.checked); inputs.forEach(input => input.checked = check); update();
  });
  form.querySelectorAll('[data-days]').forEach(control => control.addEventListener('click', () => {
    completed = false;
    days.querySelectorAll('input').forEach(input => {
      const day = new Date(`${input.value}T12:00:00Z`).getUTCDay();
      input.checked = control.dataset.days === 'all' || (control.dataset.days === 'week' && day > 0 && day < 6) || (control.dataset.days === 'saturday' && day > 0);
    }); update();
  }));
  const status = (text, error = false) => {
    const box = byId('batch-status'); box.textContent = text; box.dataset.error = error; box.focus();
  };
  async function send(data) {
    const response = await fetch(form.action, {method: 'POST', body: data, headers: {Accept: 'application/json'}, credentials: 'same-origin'});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(Object.values(result.errors || {}).flat().map(e => e.message).join(' ') || 'Não foi possível salvar. Confira sua sessão e tente novamente.');
    return result;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !form.reportValidity()) return;
    busy = true; form.inert = true; form.setAttribute('aria-busy', 'true'); update(); button.textContent = 'Conferindo agendas…';
    try {
      const data = new FormData(form); data.set('acao', 'prever_lote');
      const preview = await send(data);
      byId('batch-preview-summary').textContent = `${preview.created} novas · ${preview.updated} existentes · ${preview.unchanged} sem alteração. ${preview.professionals} profissionais e ${preview.days} dias.`;
      byId('batch-preview-schedule').textContent = `${preview.names.join(', ')}. Datas: ${preview.dates.join(', ')}. Turnos: ${preview.hours.join(' · ')}.`;
      byId('batch-changes').replaceChildren(...preview.changes.map(change => { const li = document.createElement('li'); li.textContent = change; return li; }));
      byId('batch-consent').hidden = !preview.updated;
      byId('batch-overwrite').checked = false;
      const confirm = byId('batch-confirm-submit'); confirm.disabled = !!preview.updated;
      byId('batch-overwrite').onchange = () => confirm.disabled = preview.updated && !byId('batch-overwrite').checked;
      dialog.returnValue = 'cancel'; dialog.showModal();
      const answer = await new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue), {once: true}));
      if (answer !== 'confirm') return;
      button.textContent = 'Abrindo agendas…';
      data.set('acao', 'salvar_lote'); data.set('token', preview.token);
      data.set('confirmar', preview.updated ? 'on' : '');
      const result = await send(data);
      completed = true;
      status(`${result.message} ${result.created} novas · ${result.updated} atualizadas · ${result.unchanged} sem alteração.`);
      const viewAgenda = document.createElement('a');
      viewAgenda.href = result.agenda_url;
      viewAgenda.className = 'ui-button ui-button-secondary';
      viewAgenda.textContent = 'Conferir agenda configurada';
      byId('batch-status').append(document.createElement('br'), viewAgenda);
      byId('batch-operation').textContent = 'Operação concluída';
    } catch (error) {
      status(error instanceof SyntaxError ? 'Não foi possível confirmar a resposta. Confira sua sessão e tente novamente.' : error.message, true);
    } finally { busy = false; form.inert = false; form.removeAttribute('aria-busy'); button.textContent = 'Confirmar abertura das agendas'; update(); }
  });
  update();
})();
