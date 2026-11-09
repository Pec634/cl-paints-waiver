(() => {
  const button=document.getElementById('copy-creates-return-link'),link=document.getElementById('creates-return-link'),status=document.getElementById('creates-return-link-status');
  if(!button)return;
  button.addEventListener('click',async()=>{
    try{await navigator.clipboard.writeText(link.value);status.textContent='Link copied. Save it somewhere private so you can return to this order.';}
    catch{link.focus();link.select();status.textContent='Your link is selected. Copy it and save it somewhere private.';}
  });
})();
