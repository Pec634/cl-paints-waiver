(() => {
  document.querySelectorAll('form').forEach(form => {
    const kind = form.querySelector('[name="client_type"]');
    const birth = form.querySelector('[name="date_of_birth"]');
    if (!kind || !birth) return;
    const update = () => { birth.required = kind.value !== 'business'; };
    kind.addEventListener('change', update); update();
  });
})();
