(() => {
  document.querySelectorAll('form').forEach(form => {
    const kind = form.querySelector('[name="client_type"]');
    const birth = form.querySelector('[name="date_of_birth"]');
    const businessName = form.querySelector('[name="business_name"]');
    if (!kind || !birth) return;
    const update = () => {
      const isBusiness = kind.value === 'business';
      birth.required = !isBusiness;
      if (businessName) {
        businessName.closest('label').hidden = !isBusiness;
        businessName.disabled = !isBusiness;
      }
    };
    kind.addEventListener('change', update); update();
  });
})();
