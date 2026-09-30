(() => {
  const selector = document.getElementById('payment-select');
  selector?.addEventListener('change', () => selector.form.requestSubmit());
  document.querySelector('[data-print-receipt]')?.addEventListener('click', () => window.print());

  const page = document.querySelector('[data-payment-poll]');
  if (!page) return;
  let attempts = 0;
  async function checkPayment() {
    if (++attempts > 30) return;
    if (!document.hidden) {
      try {
        const response = await fetch(page.dataset.paymentPoll, {
          credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'},
        });
        if (response.redirected || response.status === 403) return;
        if (response.ok) {
          const state = await response.json();
          if (state.versao !== page.dataset.paymentVersion) {
            window.location.reload();
            return;
          }
        }
      } catch (_) {
        // Keep the manual refresh available while the connection recovers.
      }
    }
    window.setTimeout(checkPayment, 10000);
  }
  window.setTimeout(checkPayment, 10000);
})();
