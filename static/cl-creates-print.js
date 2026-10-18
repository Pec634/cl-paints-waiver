document.getElementById('print-shipping-address').addEventListener('click', () => window.print());
window.addEventListener('load', () => window.print(), { once: true });
