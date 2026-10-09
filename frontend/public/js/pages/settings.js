import { api } from '../api.js';
import { esc, num, toast, formModal } from '../ui.js';

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
    <div class="small mute" style="margin-top:8px">Доля бригады задаётся в <code>.env</code> на сервере (CREW_SHARE) и применяется ко всем объектам при расчёте.</div></div>`;
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
