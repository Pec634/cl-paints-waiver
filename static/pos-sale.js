(() => {
  try {
    const submitted = sessionStorage.getItem('clpaints-pos-submitted');
    if ('POS-' + submitted === document.getElementById('pos-sale-reference').dataset.reference) {
      sessionStorage.removeItem('clpaints-pos-draft');
      sessionStorage.removeItem('clpaints-pos-submitted');
    }
  } catch (_) {}
})();
