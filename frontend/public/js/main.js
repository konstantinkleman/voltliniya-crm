import { api, token, getDicts, resetDicts } from './api.js';
import { html, esc, toast } from './ui.js';
import * as leads from './pages/leads.js';
import * as objects from './pages/objects.js';
import * as crews from './pages/crews.js';
import * as expenses from './pages/expenses.js';
import * as stats from './pages/stats.js';
import * as foreman from './pages/foreman.js';
import * as settings from './pages/settings.js';

export const state = { me: null, dicts: null };
const app = document.getElementById('app');

const NAV = [
  ['leads', 'Заявки'], ['objects', 'Объекты'], ['crews', 'Прорабы и бригады'],
  ['expenses', 'Расходы'], ['stats', 'Аналитика'], ['settings', 'Настройки'],
];
const PAGES = { leads, objects, crews, expenses, stats, settings };

function route() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  return { page: parts[0] || '', id: parts[1] || null, sub: parts[2] || null, q: new URLSearchParams(qs || '') };
}

function renderLogin(err = '') {
  app.innerHTML = html`<div class="login"><form>
    <div class="brand"><i></i>ВольтЛиния CRM</div>
    <div class="field"><label>E-mail</label><input name="email" type="email" autocomplete="username" required></div>
    <div class="field"><label>Пароль</label><input name="password" type="password" autocomplete="current-password" required></div>
    <div class="err">${err}</div>
    <button class="btn p" style="width:100%;margin-top:14px;padding:11px">Войти</button>
  </form></div>`;
  app.querySelector('form').onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    try { await api.login(f.email.value.trim(), f.password.value); resetDicts(); location.hash = '#/'; await boot(); }
    catch (err) { renderLogin(err.message); }
  };
}

function shell(page, content) {
  const nav = NAV.map(([k, t]) => `<a href="#/${k}" class="${page === k ? 'on' : ''}">${t}</a>`).join('');
  const links = (state.me.is_foreman ? '<a href="#/my">кабинет прораба</a> · ' : '') + '<a href="#/logout">выйти</a>';
  app.innerHTML = `<div class="app">
    <aside class="rail">
      <div class="brand"><i></i>ВольтЛиния</div>
      <nav class="nav">${nav}</nav>
      <div class="user"><div><b>${esc(state.me.name)}</b></div><div class="mute small">${links}</div></div>
    </aside>
    <main class="main" id="main"></main></div>`;
  document.getElementById('main').innerHTML = content;
  return document.getElementById('main');
}

export async function render() {
  const r = route();
  if (!token.get()) { if (r.page !== 'login') location.hash = '#/login'; return renderLogin(); }
  if (r.page === 'logout') { token.set(null); state.me = null; location.hash = '#/login'; return renderLogin(); }
  if (!state.me) {
    try { state.me = await api.get('/api/me'); state.dicts = await getDicts(); }
    catch { return renderLogin(); }
  }
  if (r.page === 'login') { location.hash = state.me.is_director ? '#/leads' : '#/my'; return; }
  // прораб без прав директора — только мобильный кабинет
  if (!state.me.is_director || r.page === 'my') {
    return foreman.render(app, r, state);
  }
  const page = PAGES[r.page] ? r.page : 'leads';
  if (!PAGES[r.page]) { location.hash = '#/leads'; return; }
  const main = shell(page, '<div class="empty">Загрузка…</div>');
  try { await PAGES[page].render(main, r, state); }
  catch (e) { main.innerHTML = `<div class="empty"><b>Не удалось загрузить</b>${esc(e.message)}</div>`; }
}

async function boot() { await render(); }
window.addEventListener('hashchange', render);
boot();
