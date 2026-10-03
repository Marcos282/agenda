/* One reusable timeline per professional. Coordinates are real elapsed wall-clock
   seconds within the selected day; hour ticks are presentation only. */
(function (root) {
  'use strict';
  function clock(seconds) {
    if (seconds === 86400) return '24:00';
    const h = Math.floor(seconds / 3600), m = Math.floor(seconds % 3600 / 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }
  function coordinate(iso, day, timeZone) {
    const instant = new Date(iso);
    if (!Number.isFinite(instant.getTime())) throw new Error('Invalid appointment datetime');
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
      timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
    }).formatToParts(instant).map(p => [p.type, p.value]));
    const localDay = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day));
    const [year, month, date] = day.split('-').map(Number);
    return (localDay - Date.UTC(year, month - 1, date)) / 1000 + Number(parts.hour) * 3600 + Number(parts.minute) * 60 + Number(parts.second);
  }
  function layout(data) {
    const windows = [...data.windows].sort((a, b) => a.start - b.start);
    if (!windows.length) return {blocks: [], ticks: [], height: 0};
    const start = windows[0].start, end = windows[windows.length - 1].end;
    const scale = 1.4 / 60; // px/second, independent of any tenant setting.
    const appointments = (data.appointments || []).map(a => ({...a,
      start: coordinate(a.inicio, data.date, data.timeZone),
      end: coordinate(a.fim, data.date, data.timeZone)
    })).filter(a => a.end > a.start && a.end > start && a.start < end);
    const blocks = [];
    const add = (kind, from, to, extra = {}) => {
      if (to <= from) return;
      blocks.push({kind, start: from, end: to, top: (from - start) * scale, height: (to - from) * scale, ...extra});
    };
    let cursor = start;
    for (const window of windows) {
      add('closed', cursor, window.start);
      let freeStart = window.start;
      for (const a of appointments.filter(a => a.status !== 'CANCELADO' && a.end > window.start && a.start < window.end).sort((a, b) => a.start - b.start)) {
        add('free', freeStart, Math.min(window.end, Math.max(freeStart, a.start)));
        freeStart = Math.max(freeStart, Math.min(a.end, window.end));
      }
      add('free', freeStart, window.end);
      cursor = window.end;
    }
    for (const a of appointments) add(a.status === 'CANCELADO' ? 'cancelled' : a.status === 'NAO_COMPARECEU' ? 'no-show' : 'booked', Math.max(start, a.start), Math.min(end, a.end), {appointment: a});
    const ticks = [{at: start, text: clock(start)}];
    for (let at = Math.ceil(start / 3600) * 3600; at < end; at += 3600) {
      if (at > start && at - start >= 900 && end - at >= 900) ticks.push({at, text: clock(at)});
    }
    ticks.push({at: end, text: clock(end)});
    return {blocks, ticks: ticks.map(t => ({...t, top: (t.at - start) * scale})), height: (end - start) * scale};
  }
  function renderTimeline(element, data) {
    const plan = layout(data);
    element.replaceChildren();
    element.style.height = `${plan.height}px`;
    for (const tick of plan.ticks) {
      const row = document.createElement('div'); row.className = 'time-tick'; row.style.top = `${tick.top}px`;
      const text = document.createElement('span'); text.textContent = tick.text; row.append(text); element.append(row);
    }
    for (const item of plan.blocks) {
      const appointment = item.appointment;
      const block = document.createElement(appointment ? 'button' : 'div');
      if (appointment) block.type = 'button';
      block.className = `timeline-block ${item.kind}${item.height < 48 ? ' compact' : ''}`;
      block.style.top = `${item.top}px`; block.style.height = `${item.height}px`;
      const title = appointment ? `${item.kind === 'no-show' ? 'Não compareceu' : item.kind === 'cancelled' ? 'Cancelado' : 'Ocupado'} · ${appointment.cliente} · ${appointment.servico}` : item.kind === 'closed' ? 'Intervalo / fechado' : 'Livre';
      const details = `${clock(item.start)} → ${clock(item.end)}${appointment ? ` · ${Math.round((appointment.end - appointment.start) / 60)} min · R$ ${appointment.valor} · ${appointment.statusLabel || appointment.status}` : ''}`;
      block.setAttribute('aria-label', `${title}. ${details}`); block.title = `${title}. ${details}`;
      const heading = document.createElement('strong');
      if (appointment) {
        heading.append(root.CustomerReputation.renderRating(appointment.reputacao));
        heading.append(document.createTextNode(`${appointment.cliente} · ${appointment.servico}`));
      } else heading.textContent = title;
      const text = document.createElement('span'); text.textContent = details;
      block.append(heading, text);
      if (appointment) block.addEventListener('click', () => {
        const dialog = document.createElement('dialog'); dialog.className = 'appointment-details';
        const h = document.createElement('h3');
        h.append(root.CustomerReputation.renderRating(appointment.reputacao));
        h.append(document.createTextNode(` ${appointment.cliente} · ${appointment.servico}`));
        const p = document.createElement('p'); p.textContent = details;
        const close = document.createElement('button'); close.textContent = 'Fechar'; close.addEventListener('click', () => dialog.close());
        dialog.append(h, p);
        if (appointment.cancelUrl) {
          const cancel = document.createElement('a'); cancel.className = 'ui-button ui-button-secondary';
          cancel.href = appointment.cancelUrl; cancel.textContent = 'Desmarcou'; dialog.append(cancel);
        }
        if (appointment.lateUrl) {
          const late = document.createElement('a'); late.className = 'ui-button ui-button-secondary';
          late.href = appointment.lateUrl; late.textContent = 'Chegou atrasado'; dialog.append(late);
        }
        if (appointment.noShowUrl) {
          const noShow = document.createElement('a'); noShow.className = 'ui-button ui-button-secondary';
          noShow.href = appointment.noShowUrl; noShow.textContent = 'Cliente ausente'; dialog.append(noShow);
        }
        dialog.append(close); document.body.append(dialog); dialog.addEventListener('close', () => dialog.remove()); dialog.showModal();
      });
      element.append(block);
    }
    element.classList.add('is-rendered');
  }
  const api = {layout, coordinate, renderTimeline};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;
  root.DailyAgenda = api;
  document.addEventListener('DOMContentLoaded', () => {
    const payload = document.getElementById('agenda-data'), timeline = document.querySelector('[data-timeline]');
    if (payload && timeline) {
      renderTimeline(timeline, JSON.parse(payload.textContent));
      const refreshStatus = document.querySelector('[data-agenda-refresh]');
      let refreshing = false;
      const refresh = async () => {
        if (refreshing || document.hidden || !refreshStatus) return;
        refreshing = true;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        try {
          const response = await fetch(refreshStatus.dataset.url, {
            cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
            headers: {'Accept': 'application/json'}
          });
          if (!response.ok || response.redirected) throw new Error('Agenda unavailable');
          const result = await response.json();
          const data = result.timeline;
          renderTimeline(timeline, data);
          payload.textContent = JSON.stringify(data);
          timeline.closest('[data-timeline-container]').hidden = !result.aberta;
          const closed = document.querySelector('.closed-day');
          if (closed) closed.hidden = result.aberta;
          document.querySelectorAll('.timeline-legend, .day-footer').forEach(el => {el.hidden = !result.aberta;});
          const badge = document.querySelector('.day-actions .agenda-status');
          if (badge) {
            badge.classList.toggle('is-open', result.aberta);
            badge.classList.toggle('is-closed', !result.aberta);
            badge.textContent = result.aberta ? '● Agenda aberta' : '○ Agenda fechada';
          }
          const summary = document.querySelector('.booked-summary');
          const template = document.createElement('template');
          template.innerHTML = result.resumo_html;
          const nextSummary = template.content.querySelector('.booked-summary');
          if (summary) {
            if (nextSummary) summary.replaceWith(nextSummary);
            else summary.remove();
          } else if (nextSummary) document.querySelector('.day-card').append(nextSummary);
          refreshStatus.textContent = 'Agenda atualizada automaticamente.';
        } catch (error) {
          refreshStatus.textContent = 'Não foi possível atualizar a agenda. Tentaremos novamente em alguns segundos.';
        } finally {
          clearTimeout(timeout);
          refreshing = false;
        }
      };
      refresh();
      setInterval(refresh, 15000);
      document.addEventListener('visibilitychange', refresh);
      root.addEventListener('focus', refresh);
    }
    const editor = document.querySelector('[data-editor]');
    if (!editor) return;
    let previousFocus = null;
    const open = () => {
      previousFocus = document.activeElement; editor.hidden = false;
      editor.classList.remove('editor-collapsed'); editor.classList.add('as-dialog');
      editor.setAttribute('role', 'dialog'); editor.setAttribute('aria-modal', 'true');
      document.body.classList.add('modal-open');
      editor.querySelector('input[type=time], [data-close-schedule]').focus();
    };
    const close = () => {
      editor.hidden = true; editor.classList.add('editor-collapsed'); editor.classList.remove('as-dialog');
      editor.removeAttribute('role'); editor.removeAttribute('aria-modal'); document.body.classList.remove('modal-open');
      if (previousFocus && previousFocus !== document.body) previousFocus.focus();
      else document.querySelector('[data-open-schedule]')?.focus();
    };
    document.querySelectorAll('[data-open-schedule]').forEach(a => a.addEventListener('click', e => {e.preventDefault(); open();}));
    editor.querySelectorAll('[data-close-schedule]').forEach(a => a.addEventListener('click', e => {e.preventDefault(); close();}));
    editor.addEventListener('keydown', e => {
      if (!editor.classList.contains('as-dialog')) return;
      if (e.key === 'Escape') {e.preventDefault(); close();}
      if (e.key === 'Tab') {
        const items = [...editor.querySelectorAll('a[href], button:not([disabled]), input:not([type=hidden]):not([disabled])')].filter(el => el.getClientRects().length);
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {e.preventDefault(); last.focus();}
        if (!e.shiftKey && document.activeElement === last) {e.preventDefault(); first.focus();}
      }
    });
    const rows = editor.querySelector('[data-period-rows]'), add = editor.querySelector('[data-add-period]');
    const total = editor.querySelector('[name="periodos-TOTAL_FORMS"]');
    const updateSave = () => {
      const activeRows = [...rows.children].filter(row => !row.querySelector('[name$="-DELETE"]').checked);
      const submit = editor.querySelector('[type=submit]');
      submit.textContent = activeRows.length ? 'Salvar horários' : 'Fechar agenda';
    };
    const wireRow = row => {
      const checkbox = row.querySelector('[name$="-DELETE"]');
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'period-remove'; remove.textContent = 'Remover'; remove.style.background = 'transparent';
      remove.setAttribute('aria-label', 'Remover período');
      checkbox.parentElement.hidden = true;
      remove.addEventListener('click', () => {
        checkbox.checked = true; row.classList.add('removed');
        row.querySelectorAll('input[type=time]').forEach(input => input.required = false);
        updateSave(); add.focus();
      });
      row.append(remove);
      if (checkbox.checked) row.classList.add('removed');
    };
    [...rows.children].forEach(wireRow); add.hidden = false;
    add.addEventListener('click', () => {
      if (Number(total.value) >= 100) return;
      const html = editor.querySelector('[data-empty-period]').innerHTML.replaceAll('__prefix__', total.value);
      const template = document.createElement('template'); template.innerHTML = html;
      const row = template.content.firstElementChild; rows.append(row); total.value = String(Number(total.value) + 1);
      wireRow(row); row.querySelector('input[type=time]').focus(); updateSave();
    });
    updateSave();
    if (editor.dataset.show === 'true') open();
  });
})(typeof window !== 'undefined' ? window : globalThis);
