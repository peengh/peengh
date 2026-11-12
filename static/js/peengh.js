/* Peengh Custom JavaScript */

// Auto-hide mobile menu on route change
document.body.addEventListener('htmx:afterSwap', function() {
  if (typeof Alpine !== 'undefined') {
    // Close mobile menu after navigation
    const nav = document.querySelector('[x-data]');
    if (nav && nav.__x) {
      nav.__x.$data.mobileMenu = false;
      nav.__x.$data.filterOpen = false;
    }
  }
});

// Refresh price polling (if refresh was triggered)
function pollPriceRefresh(productId, maxAttempts = 10) {
  let attempts = 0;
  const interval = setInterval(() => {
    attempts++;
    if (attempts >= maxAttempts) {
      clearInterval(interval);
      return;
    }
    fetch('/api/refresh-price/' + productId, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(r => r.text())
    .then(html => {
      const container = document.getElementById('price-table-container');
      if (container && html.includes('price-table')) {
        container.innerHTML = html;
        clearInterval(interval);
      }
    })
    .catch(() => {});
  }, 3000);
}
