window.initializeAvailabilityAddressAutocomplete = async function() {
    const host=document.getElementById('availability-address-search');
    const input=document.getElementById('availability-address');
    if (!host || !input || host.dataset.attached || !window.google?.maps?.importLibrary) return;
    try {
        const {PlaceAutocompleteElement}=await google.maps.importLibrary('places');
        const autocomplete=new PlaceAutocompleteElement();
        autocomplete.includedRegionCodes=['gb'];
        autocomplete.placeholder='Search for your venue or postcode';
        autocomplete.setAttribute('aria-label','Search Google Maps for the venue address');
        autocomplete.style.width='100%';
        autocomplete.addEventListener('gmp-select',async ({placePrediction})=>{
            try {
                const place=placePrediction.toPlace();
                await place.fetchFields({fields:['formattedAddress']});
                if(place.formattedAddress){
                    input.value=place.formattedAddress;
                    input.dispatchEvent(new Event('input',{bubbles:true}));
                    input.dispatchEvent(new Event('change',{bubbles:true}));
                }
            } catch { input.focus(); }
        });
        host.append(autocomplete);host.hidden=false;host.dataset.attached='true';
    } catch { /* Manual entry remains available if Google is unavailable. */ }
};
