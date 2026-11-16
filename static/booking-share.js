(() => {
  const button = document.getElementById('copy-private-booking-url');
  if (!button) return;
  button.addEventListener('click', async () => {
    const field = document.getElementById('private-booking-url');
    const status = document.getElementById('copy-private-booking-status');
    try {
      await navigator.clipboard.writeText(field.value);
      status.textContent = 'Booking link copied.';
    } catch {
      field.focus();
      field.select();
      status.textContent = 'Link selected. Copy it using your device’s copy command.';
    }
  });
})();
