(() => {
  if (parent === window) return;
  let timer;
  let dirty=false;
  const send = () => {
    clearTimeout(timer);
    timer=setTimeout(() => parent.postMessage({type:'handover-cashup',height:Math.ceil(document.documentElement.scrollHeight),dirty},location.origin),100);
  };
  new ResizeObserver(send).observe(document.body);
  const form=document.querySelector('[data-cashup-form]');
  form?.addEventListener('input',() => { dirty=true; send(); });
  form?.addEventListener('submit',() => { dirty=false; send(); });
  send();
})();
