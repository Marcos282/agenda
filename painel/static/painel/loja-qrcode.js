(function () {
  'use strict';
  document.querySelectorAll('.store-qr').forEach((card) => {
    const button = card.querySelector('[data-copy-store-url]');
    const field = card.querySelector('[data-store-url]');
    const status = card.querySelector('[data-copy-status]');
    if (!button || !field || !status) return;
    const selection = card.querySelector('[data-qr-selection]');
    const image = card.querySelector('.qr-image');
    const title = card.querySelector('[data-qr-title]');
    const photo = card.querySelector('[data-professional-photo]');
    if (selection && image && title) {
      const updateQRCode = () => {
        const option = selection.selectedOptions[0];
        image.src = option.dataset.image;
        image.alt = 'QR Code para acessar ' + option.dataset.url;
        field.value = option.dataset.url;
        field.setAttribute('aria-label', 'Endereço: ' + option.textContent);
        title.textContent = option.dataset.title;
        card.setAttribute('aria-label', option.dataset.title);
        button.setAttribute('aria-label', 'Copiar endereço: ' + option.textContent);
        button.title = 'Copiar endereço: ' + option.textContent;
        if (photo) {
          const photoUrl = option.dataset.photo;
          photo.hidden = !photoUrl;
          photo.alt = photoUrl ? 'Foto de ' + option.textContent : '';
          photo.onerror = () => {
            photo.hidden = true;
          };
          if (photoUrl) photo.src = photoUrl;
          else photo.removeAttribute('src');
        }
        status.textContent = '';
      };
      selection.addEventListener('change', updateQRCode);
      updateQRCode();
    }
    button.hidden = false;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await navigator.clipboard.writeText(field.value);
        status.textContent = 'Endereço copiado!';
      } catch (error) {
        field.focus();
        field.select();
        try {
          status.textContent = document.execCommand('copy')
            ? 'Endereço copiado!'
            : 'Selecionei o endereço. Use Ctrl+C ou toque e segure para copiar.';
        } catch (fallbackError) {
          status.textContent = 'Selecionei o endereço. Use Ctrl+C ou toque e segure para copiar.';
        }
      } finally {
        button.disabled = false;
      }
    });
  });
}());
