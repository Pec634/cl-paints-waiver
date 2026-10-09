(() => {
  const people = document.getElementById('photo-participants');
  if (!people) return;
  document.getElementById('add-photo-person').addEventListener('click', () => {
    if (people.children.length >= 20) return;
    const person = people.firstElementChild.cloneNode(true);
    person.querySelector('legend').textContent = `Person ${people.children.length + 1}`;
    person.querySelector('input[type="text"], input:not([type])').value = '';
    person.querySelector('textarea').value = '';
    person.querySelector('input[type="checkbox"]').checked = false;
    people.appendChild(person);
    people.querySelectorAll('textarea').forEach(description => description.required = true);
  });
  people.closest('form').addEventListener('submit', () => {
    document.getElementById('photo-participant-data').value = JSON.stringify(
      Array.from(people.children, person => ({
        name: person.querySelector('[name="participant_name"]').value.trim(),
        description: person.querySelector('[name="participant_description"]').value.trim(),
        consent: person.querySelector('[name="participant_consent"]').checked
      }))
    );
  });
})();
