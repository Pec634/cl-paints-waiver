const orderDialog = document.getElementById('order-dialog');
document.querySelectorAll('[data-order-details]').forEach(link => link.addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey) return;
  event.preventDefault();
  const detailsUrl = new URL(link.href);
  detailsUrl.searchParams.set('popup', '1');
  orderDialog.querySelector('iframe').src = detailsUrl.href;
  orderDialog.showModal();
}));
document.getElementById('close-order').addEventListener('click', () => { orderDialog.close(); location.reload(); });
orderDialog.addEventListener('cancel', () => location.reload());
