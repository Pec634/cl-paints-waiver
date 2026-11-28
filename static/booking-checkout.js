(() => {
  const card = document.getElementById('sumup-card');
  const status = document.getElementById('booking-payment-status');
  const refresh = document.getElementById('booking-payment-refresh');
  const unavailable = 'The card form could not load. Reload this page to try again.';
  let verifying = false;

  window.addEventListener('pageshow', event => {
    if (event.persisted) window.location.reload();
  });

  if (!window.SumUpCard) {
    status.textContent = unavailable;
    return;
  }

  try {
    window.SumUpCard.mount({
      id: card.id,
      checkoutId: card.dataset.checkoutId,
      amount: card.dataset.amount,
      currency: 'GBP',
      locale: 'en-GB',
      country: 'GB',
      onLoad() {
        status.textContent = '';
      },
      onResponse(type) {
        if (verifying) return;
        switch (type) {
          case 'sent':
            status.textContent = 'SumUp is processing your payment.';
            break;
          case 'auth-screen':
            status.textContent = 'Follow your bank’s instructions to verify the payment.';
            break;
          case 'invalid':
            status.textContent = 'Check the card details highlighted in the form.';
            break;
          case 'success':
            verifying = true;
            status.textContent = 'Checking your payment with SumUp.';
            refresh.requestSubmit();
            break;
          case 'error':
          case 'fail':
            status.textContent = 'SumUp could not complete this payment. Use Check payment status before trying again.';
            break;
        }
      }
    });
  } catch {
    status.textContent = unavailable;
  }
})();
