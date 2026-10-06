(() => {
  'use strict';
  const studio = document.querySelector('.paint-studio');
  const sidebar = document.querySelector('.paint-progress-sidebar');
  if (!studio || !sidebar) return;
  const ranks = [
    {xp: 0, name: 'Colour Explorer'}, {xp: 100, name: 'Paint Apprentice'},
    {xp: 250, name: 'Creative Artist'}, {xp: 450, name: 'Studio Star'},
    {xp: 700, name: 'Colour Champion'}
  ];
  const rewards = [
    {id: 'candy', name: 'Candy Cloud', level: 2, colours: ['#f9a8d4', '#c4b5fd', '#bae6fd', '#ffffff']},
    {id: 'aurora', name: 'Aurora Glow', level: 3, colours: ['#0f172a', '#22d3ee', '#a78bfa', '#86efac']},
    {id: 'gold', name: 'Golden Celebration', level: 4, colours: ['#92400e', '#f59e0b', '#fde68a', '#ffffff']},
    {id: 'champion', name: 'Champion Rainbow', level: 5, colours: ['#f52f83', '#ffb43f', '#ffe876', '#40c9bf', '#a379df']}
  ];
  const key = `cl-paints-studio-progress-v1-${studio.dataset.player || 'guest'}`;
  const validChallenge = value => /^(missions|customer|follow|timed):[0-4]$/.test(value);
  let state = {xp: 0, completions: 0, cleared: []};
  let storageAvailable = true;
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null');
    if (saved && Number.isSafeInteger(saved.xp) && saved.xp >= 0 &&
        Number.isSafeInteger(saved.completions) && saved.completions >= 0 && Array.isArray(saved.cleared)) {
      state = {xp: saved.xp, completions: saved.completions,
        cleared: [...new Set(saved.cleared.filter(value => typeof value === 'string' && validChallenge(value)))]};
    }
  } catch { storageAvailable = false; }
  const panel = document.createElement('section');
  panel.className = 'paint-player-progress';
  panel.setAttribute('aria-labelledby', 'paint-player-heading');
  panel.innerHTML = `<div class="paint-journey-summary"><h3 id="paint-player-heading">Your artist journey</h3>
    <strong id="paint-player-rank"></strong><p id="paint-player-xp"></p>
    <label for="paint-player-progress">Artist level progress</label>
    <progress id="paint-player-progress" max="100" value="0"></progress>
    <p id="paint-player-next"></p><p id="paint-player-completions"></p></div>
    <div class="paint-journey-rewards"><h3>Your unlocked split cakes</h3><div class="paint-reward-collection"></div></div>
    <div class="paint-reward-reveal" hidden role="status" aria-live="polite"></div>
    <p class="paint-progress-note">First completion: 100 XP. Replays: 25 XP. Complete all three tasks to earn XP. Free play does not award XP.</p>
    <p class="paint-progress-storage"></p>`;
  studio.prepend(panel);
  const get = id => panel.querySelector(`#paint-player-${id}`);
  const level = () => ranks.filter(rank => state.xp >= rank.xp).length;
  function render() {
    const current = level(), rank = ranks[current - 1], next = ranks[current];
    get('rank').textContent = `Level ${current} · ${rank.name}`;
    get('xp').textContent = `${state.xp} XP earned`;
    get('progress').max = next ? next.xp - rank.xp : 1;
    get('progress').value = next ? state.xp - rank.xp : 1;
    get('next').textContent = next ? `${next.xp - state.xp} XP to level ${current + 1} · ${next.name}` : 'Top rank reached! Keep painting and collecting XP.';
    get('completions').textContent = `${state.completions} completed challenges`;
    panel.querySelector('.paint-progress-storage').textContent = storageAvailable
      ? 'Your game progress is saved for this account in this browser.'
      : 'Browser saving is unavailable. Your progress lasts for this visit.';
    panel.querySelector('.paint-reward-collection').replaceChildren(...rewards.map(reward => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'paint-unlock-card';
      button.disabled = current < reward.level;
      const swatch = document.createElement('span');
      swatch.className = 'paint-unlock-swatch'; swatch.setAttribute('aria-hidden', 'true');
      swatch.style.background = `linear-gradient(90deg, ${reward.colours.join(',')})`;
      const label = document.createElement('span');
      label.textContent = `${reward.name} · ${button.disabled ? 'Unlock at level ' + reward.level : 'Use split cake'}`;
      button.append(swatch, label);
      button.addEventListener('click', () => {
        const core = window.CLStudioCore;
        if (!core) return;
        const id = `reward-${reward.id}`;
        core.cakes[id] = [...reward.colours];
        const select = document.getElementById('paint-colour-mode');
        if (![...select.options].some(option => option.value === id)) select.add(new Option(reward.name + ' (earned)', id));
        select.value = id; select.dispatchEvent(new Event('change'));
        document.getElementById('paint-status').textContent = `${reward.name} equipped! Paint with your new split cake.`;
      });
      return button;
    }));
  }
  window.CLStudioProgress = {
    isCompleted(mode, mission) { return state.cleared.includes(`${mode}:${mission}`); },
    isUnlocked(mode, mission) {
      return validChallenge(`${mode}:${mission}`) && (state.cleared.includes(`${mode}:${mission}`) ||
        Array.from({length: mission}, (_, index) => `${mode}:${index}`).every(challenge => state.cleared.includes(challenge)));
    },
    complete(mode, mission) {
      const challenge = `${mode}:${mission}`;
      if (!this.isUnlocked(mode, mission)) return;
      const previousLevel = level(), first = !state.cleared.includes(challenge);
      const earned = first ? 100 : 25;
      state.xp += earned; state.completions++;
      if (first) state.cleared.push(challenge);
      try { localStorage.setItem(key, JSON.stringify(state)); } catch { storageAvailable = false; }
      render();
      const current = level(), reveal = panel.querySelector('.paint-reward-reveal');
      const unlocked = rewards.filter(reward => reward.level > previousLevel && reward.level <= current);
      reveal.hidden = false;
      reveal.textContent = `Challenge complete! +${earned} XP${first ? ' · First completion bonus' : ' · Replay reward'}.` +
        (current > previousLevel ? ` Level up! You are now ${ranks[current - 1].name}.` : '') +
        (unlocked.length ? ` Unlocked: ${unlocked.map(reward => reward.name).join(', ')}. Equip your new split cake below!` : '');
      reveal.classList.remove('is-revealing'); void reveal.offsetWidth; reveal.classList.add('is-revealing');
    }
  };
  render();
})();
