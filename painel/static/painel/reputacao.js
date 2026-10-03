(function (root) {
  'use strict';
  function renderRating(reputation) {
    const container = document.createElement('span');
    container.className = 'client-reputation';
    container.setAttribute('data-customer-reputation', '');
    const count = Number(reputation?.estrelas || 0);
    if (!count) {
      container.classList.add('client-reputation-new');
      container.textContent = 'Cliente Novo';
      return container;
    }
    const stars = document.createElement('span');
    stars.className = 'rating-stars';
    stars.setAttribute('role', 'img');
    stars.setAttribute('aria-label', `${count} de 4 estrelas`);
    for (let i = 1; i <= 4; i++) {
      const star = document.createElement('span');
      star.className = `star ${i <= count ? 'active' : 'inactive'}`;
      star.setAttribute('aria-hidden', 'true');
      star.textContent = '★';
      stars.append(star);
    }
    container.append(stars);
    return container;
  }
  root.CustomerReputation = {renderRating};
  if (typeof module !== 'undefined' && module.exports) module.exports = {renderRating};
})(typeof window !== 'undefined' ? window : globalThis);
