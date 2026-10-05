(() => {
  const form=document.getElementById('studio-community-share');if(!form)return;
  form.addEventListener('submit',event=>{
    try{
      const core=window.CLStudioCore,image=document.createElement('canvas');image.width=600;image.height=720;
      const ctx=image.getContext('2d');ctx.fillStyle='#faf5ff';ctx.fillRect(0,0,600,720);ctx.drawImage(core.base,0,0);ctx.drawImage(core.canvas,0,0);
      const photo=window.CLStudioBooth?window.CLStudioBooth.compose(image):image;
      form.elements.image.value=photo.toDataURL('image/png');form.elements.template.value=document.getElementById('paint-model').value;
      if(form.elements.image.value.length>2800000)throw Error('This design is too large to share. Download it instead.');
      form.querySelector('button[type=submit]').disabled=true;
      document.getElementById('studio-share-status').textContent='Submitting your design for approval…';
    }catch(error){event.preventDefault();document.getElementById('studio-share-status').textContent=error.message||'Could not prepare the design. Please try again.';}
  });
})();
