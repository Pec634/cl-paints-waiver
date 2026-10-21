'use strict';
const STORAGE_KEY = 'hearth.home.v1';
const $ = selector => document.querySelector(selector);
let settings = { homeName: 'Our home', calendarId: '', cameras: [] };
let storageAvailable = true;
try {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
  if (saved && typeof saved === 'object') {
    settings.homeName = typeof saved.homeName === 'string' ? saved.homeName.slice(0, 60) : 'Our home';
    settings.calendarId = typeof saved.calendarId === 'string' ? saved.calendarId.slice(0, 300) : '';
    settings.cameras = Array.isArray(saved.cameras) ? saved.cameras.filter(camera => camera && typeof camera.id === 'string' && typeof camera.name === 'string' && validUrl(camera.viewerUrl) && (!camera.streamUrl || validUrl(camera.streamUrl))) : [];
  }
} catch { storageAvailable = false; }

function validUrl(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash; }
  catch { return false; }
}
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { $('#toast').hidden = true; }, 5000);
}
function save() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); storageAvailable = true; }
  catch { storageAvailable = false; }
  render();
  toast(storageAvailable ? 'Your home settings have been saved.' : 'Changes apply for this session only. Browser storage is unavailable.');
}
function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}
function openSettings() {
  $('#settings-form').elements.homeName.value = settings.homeName;
  $('#settings-form').elements.calendarId.value = settings.calendarId;
  $('#settings-dialog').showModal();
}
function openCamera(camera) {
  const form = $('#camera-form');
  form.reset();
  form.elements.cameraId.value = camera?.id || '';
  form.elements.cameraName.value = camera?.name || '';
  form.elements.model.value = camera?.model || '';
  form.elements.viewerUrl.value = camera?.viewerUrl || '';
  form.elements.streamUrl.value = camera?.streamUrl || '';
  $('#camera-dialog-title').textContent = camera ? 'Camera settings' : 'Add a camera';
  $('#delete-camera').hidden = !camera;
  $('#camera-error').textContent = '';
  $('#camera-dialog').showModal();
}
function renderCameras() {
  const grid = $('#camera-grid');
  grid.replaceChildren();
  const cameras = settings.cameras.length ? settings.cameras : ['Front door', 'Living room', 'Garden'].map(name => ({ name, placeholder: true }));
  cameras.forEach(camera => {
    const card = element('article', 'camera-card');
    const view = element('div', 'camera-view');
    view.append(element('span', 'camera-tag', camera.streamUrl ? 'VIDEO CONFIGURED' : camera.placeholder ? 'SUGGESTED CAMERA' : 'VIEWER LINK'));
    if (camera.streamUrl) {
      const video = element('video');
      video.controls = true; video.muted = true; video.playsInline = true;
      video.preload = 'none'; video.src = camera.streamUrl;
      video.setAttribute('aria-label', `${camera.name} video`);
      video.addEventListener('error', () => toast(`${camera.name}: video is unavailable. Check your bridge and network connection.`));
      view.append(video);
    } else {
      const placeholder = element('div', 'camera-placeholder');
      placeholder.append(element('span', 'outline-house', camera.name === 'Garden' ? '♧' : '⌂'));
      placeholder.append(element('p', '', camera.placeholder ? 'A little peace of mind starts here' : 'Open your camera viewer to check in'));
      if (camera.placeholder) {
        const button = element('button', 'camera-link', '＋ Set up camera');
        button.type = 'button'; button.addEventListener('click', () => { openCamera(); $('#camera-form').elements.cameraName.value = camera.name; });
        placeholder.append(button);
      } else {
        const link = element('a', 'camera-link', 'Open camera ↗');
        link.href = camera.viewerUrl; link.target = '_blank'; link.rel = 'noopener noreferrer';
        placeholder.append(link);
      }
      view.append(placeholder);
    }
    const info = element('div', 'camera-info');
    const details = element('div');
    details.append(element('h3', '', camera.name), element('p', '', camera.placeholder ? 'Not connected · Set up Wansview' : camera.model ? `Wansview · ${camera.model}` : 'Wansview · Camera access'));
    const edit = element('button', 'icon-button', camera.placeholder ? '＋' : '⚙');
    edit.type = 'button'; edit.setAttribute('aria-label', `Configure ${camera.name}`);
    edit.addEventListener('click', () => camera.placeholder ? openCamera() : openCamera(camera));
    info.append(details, edit);
    if (camera.streamUrl) {
      const link = element('a', 'text-link', 'Open viewer ↗');
      link.href = camera.viewerUrl; link.target = '_blank'; link.rel = 'noopener noreferrer'; details.append(link);
    }
    card.append(view, info); grid.append(card);
  });
  $('#camera-count').textContent = settings.cameras.length;
  $('#camera-summary').textContent = settings.cameras.length ? `${settings.cameras.length} camera${settings.cameras.length === 1 ? '' : 's'} configured` : 'Ready to connect';
}
function renderCalendar() {
  const content = $('#calendar-content'); content.replaceChildren();
  if (settings.calendarId) {
    const frame = element('iframe', 'calendar-frame');
    const params = new URLSearchParams({ src: settings.calendarId, ctz: 'Europe/London', mode: 'AGENDA', showTitle: '0', showPrint: '0', showTabs: '1', showCalendars: '0', wkst: '2', bgcolor: '#ffffff' });
    frame.src = `https://calendar.google.com/calendar/embed?${params}`;
    frame.title = 'Google family calendar'; frame.referrerPolicy = 'strict-origin-when-cross-origin';
    const note = element('p', 'calendar-note', 'Live Google Calendar view. If events do not appear, sign in to an account with access in Google Calendar, then reload. Your browser must allow the embedded Google view.');
    const edit = element('button', 'text-link today-button', 'Change calendar'); edit.type = 'button'; edit.addEventListener('click', openSettings);
    content.append(frame, note, edit);
    $('#calendar-summary').textContent = 'Google calendar configured';
  } else {
    const empty = element('div', 'calendar-empty');
    empty.append(element('span', 'calendar-symbol', '▤'), element('h3', '', 'Everyone’s plans. One happy home.'), element('p', '', 'Bring your Google family calendar here, so the school runs, birthdays and weekend plans have a place together.'));
    const button = element('button', 'button secondary'); button.type = 'button';
    button.append(element('span', 'google-mark', 'G'), document.createTextNode('Set up Google Calendar'));
    button.addEventListener('click', openSettings); empty.append(button); content.append(empty);
    $('#calendar-summary').textContent = 'Bring everyone together';
  }
}
function render() {
  document.title = `${settings.homeName || 'Our home'} · Hearth`;
  $('.breadcrumb').replaceChildren(document.createTextNode(settings.homeName || 'Our home'), element('span', '', '/'), document.createTextNode('Overview'));
  $('.sidebar-bottom strong').textContent = settings.homeName || 'Our home';
  renderCameras(); renderCalendar();
}
const londonParts = () => Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', hourCycle: 'h23' }).formatToParts(new Date()).filter(part => part.type !== 'literal').map(part => [part.type, Number(part.value)]));
let visibleMonth;
function renderMonth() {
  const today = londonParts();
  if (!visibleMonth) visibleMonth = new Date(today.year, today.month - 1, 1);
  const year = visibleMonth.getFullYear(), month = visibleMonth.getMonth();
  $('#month-label').textContent = visibleMonth.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
  const offset = (new Date(year, month, 1).getDay() + 6) % 7;
  const numberOfDays = new Date(year, month + 1, 0).getDate();
  const cells = Math.ceil((offset + numberOfDays) / 7) * 7;
  $('#month-days').replaceChildren();
  for (let i = 0; i < cells; i++) {
    const date = new Date(year, month, i - offset + 1);
    const isToday = date.getFullYear() === today.year && date.getMonth() === today.month - 1 && date.getDate() === today.day;
    const cell = element('span', isToday ? 'today' : date.getMonth() !== month ? 'outside' : '', date.getDate());
    if (isToday) cell.setAttribute('aria-current', 'date');
    $('#month-days').append(cell);
  }
}
function updateClock() {
  const now = new Date(), hour = londonParts().hour;
  $('#today-label').textContent = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(now);
  $('#clock').textContent = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit' }).format(now);
  $('#greeting').textContent = hour < 12 ? 'Good morning, home.' : hour < 18 ? 'Good afternoon, home.' : 'Good evening, home.';
  renderMonth();
}
$('#settings-button').addEventListener('click', openSettings);
$('#profile-button').addEventListener('click', openSettings);
$('#add-camera').addEventListener('click', () => openCamera());
document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$('#settings-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  settings.homeName = form.elements.homeName.value.trim() || 'Our home';
  settings.calendarId = form.elements.calendarId.value.trim();
  save(); $('#settings-dialog').close();
});
$('#camera-form').addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  const viewerUrl = form.elements.viewerUrl.value.trim(), streamUrl = form.elements.streamUrl.value.trim();
  if (!form.elements.cameraName.value.trim()) { $('#camera-error').textContent = 'Enter a name for this camera.'; return; }
  if (!validUrl(viewerUrl) || (streamUrl && !validUrl(streamUrl))) {
    $('#camera-error').textContent = 'Use an HTTP or HTTPS URL without credentials, query parameters or fragments. RTSP needs a browser-compatible bridge.'; return;
  }
  const existingId = form.elements.cameraId.value;
  const camera = { id: existingId || crypto.randomUUID(), name: form.elements.cameraName.value.trim(), model: form.elements.model.value.trim(), viewerUrl, streamUrl };
  const index = settings.cameras.findIndex(item => item.id === existingId);
  if (index >= 0) settings.cameras[index] = camera; else settings.cameras.push(camera);
  save(); $('#camera-dialog').close();
});
$('#delete-camera').addEventListener('click', () => {
  settings.cameras = settings.cameras.filter(camera => camera.id !== $('#camera-form').elements.cameraId.value);
  save(); $('#camera-dialog').close();
});
$('#previous-month').addEventListener('click', () => { visibleMonth.setMonth(visibleMonth.getMonth() - 1); renderMonth(); });
$('#next-month').addEventListener('click', () => { visibleMonth.setMonth(visibleMonth.getMonth() + 1); renderMonth(); });
$('#this-month').addEventListener('click', () => { visibleMonth = undefined; renderMonth(); });
document.querySelectorAll('nav a').forEach(link => link.addEventListener('click', () => {
  document.querySelectorAll('nav a').forEach(item => item.classList.toggle('active', item === link));
}));
render(); updateClock(); setInterval(updateClock, 30000);
if (!storageAvailable) toast('Saved settings could not be loaded. You can configure this session using Settings.');
