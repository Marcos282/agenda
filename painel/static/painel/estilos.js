(() => {
 'use strict';
 function contrast(hex) {
  const v = [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)/255).map(c => c <= .04045 ? c/12.92 : ((c+.055)/1.055)**2.4);
  return v[0]*.2126+v[1]*.7152+v[2]*.0722 > .179 ? '#000000' : '#ffffff';
 }
 document.querySelectorAll('.theme-card').forEach(card => {
  const color = card.querySelector('input[type=color]'), mini = card.querySelector('.theme-mini');
  const update = () => {
   mini.style.setProperty('--theme-primary', color.value);
   mini.style.setProperty('--theme-on-primary', contrast(color.value));
   card.querySelector('output').value = color.value;
   card.querySelectorAll('[data-color]').forEach(s => s.setAttribute('aria-pressed', String(s.dataset.color === color.value)));
  };
  color.addEventListener('input', update);
  card.querySelectorAll('[data-color]').forEach(s => s.addEventListener('click', () => {color.value = s.dataset.color; update();}));
  update();
 });
 const dialog = document.getElementById('theme-preview-dialog');
 let pending;
 document.querySelectorAll('[data-preview]').forEach(button => button.addEventListener('click', async () => {
  const form = button.closest('form');
  if (!form.reportValidity()) return;
  if (pending) pending.abort();
  pending = new AbortController();
  const status = document.getElementById('preview-status'), frame = dialog.querySelector('iframe');
  frame.removeAttribute('srcdoc'); status.textContent = 'Carregando a prévia…';
  if (!dialog.open) dialog.showModal();
  try {
   const response = await fetch(form.dataset.previewUrl, {method:'POST', body:new FormData(form), credentials:'same-origin', signal:pending.signal});
   if (!response.ok || response.redirected) throw new Error('Verifique os campos e as imagens antes de visualizar.');
   frame.srcdoc = await response.text();
   status.textContent = 'Esta prévia não altera o site publicado. Feche para salvar e aplicar.';
  } catch (error) {if (error.name !== 'AbortError') status.textContent = error.message;}
 }));
 document.querySelector('[data-close-preview]')?.addEventListener('click', () => dialog.close());
 dialog?.addEventListener('close', () => {pending?.abort(); dialog.querySelector('iframe').removeAttribute('srcdoc');});
 document.querySelector('[data-use-suggestion]')?.addEventListener('click', () => {
  const suggestion = document.getElementById('profession-suggestion').value, title = document.getElementById('id_title');
  if (suggestion && (!title.value || window.confirm('Substituir o título preenchido pela sugestão?'))) title.value = suggestion;
 });
 document.querySelector('[data-restore]')?.addEventListener('submit', event => {
  if (!window.confirm('Restaurar tema, cores e conteúdos visuais originais deste estabelecimento?')) event.preventDefault();
 });
})();
