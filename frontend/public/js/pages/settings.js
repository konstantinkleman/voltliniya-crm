import { api } from '../api.js';
import { esc, num, toast, formModal, dateTimeRu, confirmModal } from '../ui.js';

export async function render(main, r, state) {
  const D = state.dicts;
  const users = await api.get('/api/users');
  main.innerHTML = `<div class="head"><div><h1>Настройки</h1><p>Пользователи и правила расчёта</p></div><button class="btn p" data-new>Новый пользователь</button></div>
  <div class="card pad" style="margin-bottom:14px"><h2>Пользователи</h2><table style="margin-top:8px"><tr><th>Имя</th><th>E-mail</th><th>Роли</th><th></th></tr>
    ${users.map(u => `<tr><td>${esc(u.name)}${u.id === state.me.id ? ' <span class="small mute">(вы)</span>' : ''}</td><td>${esc(u.email)}</td><td>${u.is_director ? '<span class="tag act">директор</span> ' : ''}${u.is_foreman ? '<span class="tag">прораб</span>' : ''}${!u.is_active ? ' <span class="tag warn">закрыт</span>' : ''}</td><td class="r"><button class="btn s" data-edit="${u.id}">Изменить</button></td></tr>`).join('')}</table></div>
  <div class="card pad"><h2>Правила расчёта</h2><table style="margin-top:8px">
    <tr><td>Доля бригады от стоимости работ</td><td class="r num">${num(Number(D.crew_share) * 100)}%</td></tr>
    <tr><td>Зарплата прораба</td><td class="r">распределяется поровну на его объекты месяца сделки</td></tr>
    <tr><td>Стоимость клиента по каналу</td><td class="r">расходы канала за месяц ÷ договоров канала + общий маркетинг ÷ всех договоров</td></tr></table>
    <div class="small mute" style="margin-top:8px">Доля бригады задаётся в <code>.env</code> на сервере (CREW_SHARE) и применяется ко всем объектам при расчёте.</div></div>
  <div class="card pad" style="margin-top:14px" id="avito-card"><h2>Авито: чаты, бот-продажник, уведомления</h2><div class="small mute">Загрузка…</div></div>`;
  renderAvito(main.querySelector('#avito-card'));
  main.querySelector('[data-new]').onclick = () => formModal({ title: 'Новый пользователь', submit: 'Создать',
    fields: [{ name: 'name', label: 'Имя', required: true }, { name: 'email', label: 'E-mail', type: 'email', required: true }, { name: 'password', label: 'Пароль', required: true }, { name: 'phone', label: 'Телефон' },
      { name: 'role', label: 'Роль', type: 'select', options: [{ value: 'foreman', label: 'Прораб' }, { value: 'director', label: 'Директор' }, { value: 'both', label: 'Директор и прораб' }] }, { name: 'salary', label: 'Зарплата в месяц, ₽ (для прораба)', type: 'number' }],
    onSubmit: async (v) => { const role = v.role; delete v.role; await api.post('/api/users', { ...v, is_director: role !== 'foreman', is_foreman: role !== 'director' }); toast('Создан'); render(main, r, state); } });
  main.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => { const u = users.find(x => x.id === Number(b.dataset.edit)); formModal({ title: 'Изменить — ' + u.name,
    fields: [{ name: 'name', label: 'Имя', value: u.name, required: true }, { name: 'phone', label: 'Телефон', value: u.phone || '' }, { name: 'password', label: 'Новый пароль (пусто — не менять)' },
      { name: 'is_director', label: 'Директор', type: 'select', options: [{ value: 'true', label: 'да' }, { value: 'false', label: 'нет' }], value: String(u.is_director) },
      { name: 'is_foreman', label: 'Прораб', type: 'select', options: [{ value: 'true', label: 'да' }, { value: 'false', label: 'нет' }], value: String(u.is_foreman) },
      { name: 'salary', label: 'Зарплата, ₽', type: 'number', value: u.salary || '' }, { name: 'is_active', label: 'Доступ', type: 'select', options: [{ value: 'true', label: 'активен' }, { value: 'false', label: 'закрыт' }], value: String(u.is_active) }],
    onSubmit: async (v) => { if (!v.password) delete v.password; for (const k of ['is_director', 'is_foreman', 'is_active']) v[k] = v[k] === 'true'; await api.patch('/api/users/' + u.id, v); toast('Сохранено'); render(main, r, state); } }); });
}


async function renderAvito(card) {
  let st, scripts, chats;
  try { [st, scripts, chats] = await Promise.all([api.get('/api/avito/status'), api.get('/api/avito/script'), api.get('/api/avito/chats')]); }
  catch (e) { card.innerHTML = `<h2>Авито</h2><div class="small mute">${esc(e.message)}</div>`; return; }
  const yes = (b) => b ? '<span class="tag act">да</span>' : '<span class="tag warn">нет</span>';
  const active = scripts.find(s => s.is_active);
  const drafts = scripts.filter(s => !s.is_active && s.created_by === 'review');
  card.innerHTML = `<h2>Авито: чаты, бот-продажник, уведомления</h2>
  <table style="margin-top:8px">
    <tr><td>Ключи API Авито заданы</td><td class="r">${yes(st.configured)}${st.account_id ? ` <span class="small mute">аккаунт ${st.account_id}</span>` : ''}</td></tr>
    <tr><td>Вебхук подписан</td><td class="r">${st.subscribed === null ? '<span class="tag">нет данных</span>' : yes(st.subscribed)} ${st.configured ? `<button class="btn s" data-sub>${st.subscribed ? 'Переподписать' : 'Подписать'}</button>` : ''}</td></tr>
    <tr><td>Бот отвечает сам</td><td class="r">${yes(st.bot_enabled && st.anthropic)}${!st.anthropic ? ' <span class="small mute">нет ANTHROPIC_API_KEY</span>' : ''}</td></tr>
    <tr><td>Telegram-уведомления</td><td class="r">${yes(st.telegram)} ${st.telegram ? '<button class="btn s" data-tg>Проверить</button>' : ''}</td></tr>
    <tr><td>Чатов в CRM</td><td class="r num">${st.chats}</td></tr>
    <tr><td>Скрипт бота</td><td class="r">версия ${active ? active.version : '—'} <button class="btn s" data-script>Открыть</button></td></tr>
  </table>
  ${st.error ? `<div class="small" style="color:#c33;margin-top:6px">${esc(st.error)}</div>` : ''}
  ${drafts.length ? `<div style="margin-top:10px"><b>Черновики после разбора переписок:</b> ${drafts.map(d => `<div class="small">v${d.version} · ${dateTimeRu(d.created_at)} · ${esc(d.note || '')} <button class="btn s" data-activate="${d.id}">Включить</button></div>`).join('')}</div>` : ''}
  <div class="small mute" style="margin-top:8px">Адрес вебхука: <code>${esc(st.webhook_url)}</code>. Ключи и токены задаются в <code>.env</code> на сервере. Разбор переписок — раз в неделю, отчёт приходит в Telegram; <button class="btn s" data-review>запустить сейчас</button></div>
  ${chats.length ? `<h3 style="margin-top:14px">Последние чаты</h3><table><tr><th>Клиент</th><th>Объявление</th><th>Режим</th><th>Квалификация</th><th>Заявка</th><th></th></tr>
    ${chats.slice(0, 15).map(c => `<tr><td>${esc(c.client_name || '—')}<br><small class="mute">${dateTimeRu(c.last_message_at)}</small></td><td>${esc(c.item_title || '—')}</td><td>${c.mode === 'bot' ? 'бот' : 'вы'}</td><td>${{ yes: '<span class="tag act">наш</span>', no: '<span class="tag warn">мелочь</span>' }[c.qualified] || '—'}${c.handoff_reason ? `<br><small class="mute">${esc(c.handoff_reason)}</small>` : ''}</td><td>${c.lead_id ? `<a href="#/leads/${c.lead_id}">№ ${c.lead_id}</a>` : '—'}</td><td class="r"><button class="btn s" data-mode="${c.id}" data-to="${c.mode === 'bot' ? 'manual' : 'bot'}">${c.mode === 'bot' ? 'Вести самому' : 'Вернуть боту'}</button></td></tr>`).join('')}</table>` : ''}`;
  const act = async (fn, okMsg) => { try { await fn(); toast(okMsg); renderAvito(card); } catch (e) { toast(e.message, true); } };
  card.querySelector('[data-sub]')?.addEventListener('click', () => act(() => api.post('/api/avito/subscribe', {}), 'Вебхук подписан'));
  card.querySelector('[data-tg]')?.addEventListener('click', () => act(() => api.post('/api/avito/test-telegram', {}), 'Отправлено в Telegram'));
  card.querySelector('[data-review]')?.addEventListener('click', () => confirmModal('Запустить разбор переписок за 7 дней? Отчёт придёт в Telegram.', () => act(() => api.post('/api/avito/review?days=7', {}), 'Разбор запущен')));
  card.querySelectorAll('[data-activate]').forEach(b => b.onclick = () => act(() => api.post(`/api/avito/script/${b.dataset.activate}/activate`, {}), 'Скрипт включён'));
  card.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => act(() => api.post(`/api/avito/chats/${b.dataset.mode}/mode`, { mode: b.dataset.to }), 'Режим изменён'));
  card.querySelector('[data-script]')?.addEventListener('click', () => formModal({ title: 'Скрипт бота-продажника' + (active ? ` (v${active.version})` : ''), submit: 'Сохранить как новую версию',
    intro: 'Это системная инструкция бота: факты о компании, цены, что спрашивать, когда передавать вам. Сохранение создаёт новую версию и сразу включает её.',
    fields: [{ name: 'text', label: 'Текст', type: 'textarea', value: active ? active.text : '' }, { name: 'note', label: 'Что изменили' }],
    onSubmit: async (v) => { await api.post('/api/avito/script', { text: v.text, note: v.note, activate: true }); toast('Новая версия включена'); renderAvito(card); } }));
}
