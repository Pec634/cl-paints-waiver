(() => {
  if (!window.isSecureContext || !window.PublicKeyCredential) return;
  const decode = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0));
  const encode = buffer => btoa(String.fromCharCode(...new Uint8Array(buffer))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');

  document.querySelectorAll('[data-passkey-action]').forEach(button => {
    if (!button.hidden) return;
    button.hidden = false;
    const container = button.closest('[data-passkey-controls]');
    const status = container.querySelector('[data-passkey-status]');
    async function post(url, body) {
      const response = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Passkey-CSRF': button.dataset.csrf},
        body: JSON.stringify(body)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Passkey sign-in is unavailable. Use your usual sign-in and try again.');
      return data;
    }
    button.addEventListener('click', async () => {
      button.disabled = true;
      status.textContent = 'Follow the prompt on your device.';
      try {
        const {options} = await post(button.dataset.start, {});
        const enrol = button.dataset.operation === 'enrol';
        options.challenge = decode(options.challenge);
        if (enrol) options.user.id = decode(options.user.id);
        for (const descriptor of options.allowCredentials || options.excludeCredentials || []) descriptor.id = decode(descriptor.id);
        const credential = await navigator.credentials[enrol ? 'create' : 'get']({publicKey: options});
        if (!credential) throw new Error('No passkey was selected.');
        const response = credential.response;
        const fields = enrol ? ['clientDataJSON', 'attestationObject'] :
            ['clientDataJSON', 'authenticatorData', 'signature', 'userHandle'];
        const data = {
          id: credential.id, rawId: encode(credential.rawId), type: credential.type,
          response: Object.fromEntries(fields.map(field => [field, response[field] ? encode(response[field]) : null]))
        };
        const {next} = await post(button.dataset.finish, {credential: data, name: container.querySelector('[name="passkey_name"]')?.value});
        location.assign(next);
      } catch (error) {
        status.textContent = error.name === 'NotAllowedError' ? 'The passkey prompt was closed. Try again when ready.' : error.message;
      } finally {
        button.disabled = false;
      }
    });
  });
})();
