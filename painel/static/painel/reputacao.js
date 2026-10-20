(function (root) {
  'use strict';
  function renderRating(reputation) {
    const container = document.createElement('span');
    container.className = 'client-reputation';
    container.setAttribute('data-customer-reputation', '');
    const count = Number(reputation?.quantidade || 0);
    const score = Number(reputation?.nota ?? reputation?.media);
    if (!reputation?.disponivel || count < 3 || !Number.isFinite(score)) {
      container.classList.add('client-reputation-new');
      container.textContent = 'Cliente Novo — Reputação em formação';
      return container;
    }
    const stars = document.createElement('span');
    stars.className = 'rating-stars';
    stars.setAttribute('role', 'img');
    const formattedScore = score.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    stars.setAttribute('aria-label', `${formattedScore} de 4 estrelas`);
    for (let i = 1; i <= 4; i++) {
      const star = document.createElement('span');
      star.className = 'star';
      const fill = Math.min(1, Math.max(0, score - (i - 1))) * 100;
      star.style.setProperty('--star-fill', `${fill}%`);
      star.setAttribute('aria-hidden', 'true');
      star.textContent = '★';
      stars.append(star);
    }
    container.append(stars);
    const average = document.createElement('span');
    average.className = 'rating-average';
    average.textContent = `${formattedScore}/4`;
    const total = document.createElement('span');
    total.className = 'rating-count';
    total.textContent = `${count} avaliações`;
    container.append(average, total);
    return container;
  }
  root.CustomerReputation = {renderRating};
  if (typeof module !== 'undefined' && module.exports) module.exports = {renderRating};
})(typeof window !== 'undefined' ? window : globalThis);
