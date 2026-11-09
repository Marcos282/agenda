// Invisible Cloudflare Turnstile check, executed only when the visitor confirms the booking.
(() => {
  const form = document.querySelector('form[data-turnstile-form]');
  const box = form && form.querySelector('[data-turnstile-public]');
  if (!box) return;

  const status = form.querySelector('[data-turnstile-status]');
  const button = form.querySelector('button[type="submit"]');
  let widgetId = null;
  let pending = false;

  function setStatus(text) {
    status.textContent = text;
    status.hidden = !text;
  }

  function stop(text) {
    pending = false;
    button.disabled = false;
    setStatus(text);
  }

  window.tcTurnstilePublicReady = () => {
    widgetId = window.turnstile.render(box, {
      sitekey: box.dataset.sitekey,
      action: box.dataset.action,
      'response-field-name': box.dataset.field,
      execution: 'execute',
      appearance: 'interaction-only',
      language: 'pt-br',
      callback: () => {
        if (!pending) return;
        setStatus('');
        form.submit();
      },
      'error-callback': () => {
        stop('Não foi possível concluir a verificação de segurança. Tente novamente.');
        return true;
      },
      'expired-callback': () => window.turnstile.reset(widgetId),
      'timeout-callback': () => {
        window.turnstile.reset(widgetId);
        stop('A verificação de segurança expirou. Confirme novamente.');
      },
    });
  };

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (pending) return;
    if (!window.turnstile || widgetId === null) {
      setStatus('Carregando a verificação de segurança. Tente novamente em instantes.');
      return;
    }
    pending = true;
    button.disabled = true;
    setStatus('Verificando a segurança da confirmação…');
    // Tokens are single-use; always request a fresh one for each confirmation.
    window.turnstile.reset(widgetId);
    window.turnstile.execute(box);
  });

  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    if (widgetId !== null) window.turnstile.reset(widgetId);
    stop('');
  });
})();
