(() => {
  const workspace=document.querySelector('.email-workspace');
  if (!workspace) return;
  const forms=Array.from(workspace.querySelectorAll('[data-email-composer]'));
  workspace.querySelectorAll('.email-folders a[href^="#"]').forEach(link => link.addEventListener('click',()=>{
    const target=workspace.querySelector(link.getAttribute('href'));
    if (target && target.tagName==='DETAILS') target.open=true;
  }));
  function select(kind) {
    forms.forEach(form => { form.hidden=form.dataset.emailComposer!==kind; });
    workspace.querySelectorAll('[data-email-select]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.emailSelect===kind)));
    workspace.querySelector('[data-email-preview]').src='/admin/email-preview/'+kind+'?embed=1';
    workspace.querySelector('[data-email-preview-link]').href='/admin/email-preview/'+kind;
    workspace.querySelector('[data-email-preview]').title=(kind==='booking'?'Booking':'Reward')+' email preview';
    try { sessionStorage.setItem('email-composer-kind',kind); } catch (_) {}
    workspace.dispatchEvent(new CustomEvent('email-template-selected',{detail:kind}));
  }
  workspace.querySelectorAll('[data-email-select]').forEach(button => button.addEventListener('click',()=>select(button.dataset.emailSelect)));
  forms.forEach(form => {
    form.addEventListener('input',()=>{form.querySelector('[data-email-draft-status]').textContent='Unsaved changes';});
    form.querySelectorAll('[data-email-token]').forEach(button => button.addEventListener('click',()=>{
      const body=form.querySelector('textarea');
      body.setRangeText(button.dataset.emailToken,body.selectionStart,body.selectionEnd,'end');
      body.focus();body.dispatchEvent(new Event('input',{bubbles:true}));
    }));
    form.querySelectorAll('[data-email-add]').forEach(button => button.addEventListener('click',()=>{
      const drawer=workspace.querySelector('.email-media-drawer');drawer.open=true;
      const media=drawer.querySelector('form');
      media.querySelector('[name="area"]').value=form.dataset.emailComposer;
      media.querySelector('[name="kind"]').value=button.dataset.emailAdd;
      updateMedia(media);drawer.scrollIntoView({behavior:'auto',block:'nearest'});
      media.querySelector('[name="label"]').focus();
    }));
  });
  function updateMedia(form) {
    const link=form.querySelector('[name="kind"]').value==='link';
    const file=form.querySelector('[name="file"]'),url=form.querySelector('[name="url"]');
    file.closest('label').hidden=link;file.disabled=link;file.required=!link;
    url.closest('label').hidden=!link;url.disabled=!link;url.required=link;
  }
  const media=workspace.querySelector('.email-media-drawer form');
  media.querySelector('[name="kind"]').addEventListener('change',()=>updateMedia(media));updateMedia(media);
  let kind='booking';
  try { kind=sessionStorage.getItem('email-composer-kind')||kind; } catch (_) {}
  select(kind==='reward'?'reward':'booking');
  if (location.hash==='#email-media') workspace.querySelector('.email-media-drawer').open=true;
})();
