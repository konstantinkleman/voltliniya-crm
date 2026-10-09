import { api } from '../api.js';
import { esc, fmt, num, dateRu, toast, formModal, opt, emptyState, today, monthKey, monthName } from '../ui.js';

let S, D;

export async function render(main, r, state) {
  S = state; D = state.dicts;
  const month = r.q.get('month') || monthKey();
  const [foremen, crews, stats, expenses] = await Promise.all([
    api.get('/api/users'), api.get('/api/crews'), api.get('/api/stats/foremen?month=' + month), api.get('/api/expenses?category=salary'),
  ]);
  const fm = foremen.filter(u => u.is_foreman);
  const stat = (id) => stats.find(s => s.id === id) || {};
  main.innerHTML = `<div class="head"><div><h1>Прорабы и бригады</h1><p>Бригада получает ${num(Number(D.crew_share) * 100)}% от стоимости работ через прораба. Прораб — на зарплате</p></div>
    <div class="row">${monthPicker(month)}<button class="btn" data-new-crew>Новая бригада</button><button class="btn p" data-new-foreman>Новый прораб</button></div></div>
    ${fm.map(u => { const s = stat(u.id); const crew = crews.find(c => c.foreman_id === u.id && c.is_active); const salary = expenses.filter(e => e.foreman_id === u.id); return `
    <div class="card pad" style="margin-bottom:14px">
      <div class="row sp"><div><h2>${esc(u.name)}${u.is_director ? ' <span class="tag">директор</span>' : ''}${!u.is_active ? ' <span class="tag warn">неактивен</span>' : ''}</h2>
        <div class="mute small">${u.salary ? 'зарплата ' + fmt(u.salary) + '/мес' : '<span class="warn">зарплата не указана</span>'} · ${crew ? esc(crew.name) : '<span class="warn">без бригады</span>'} · ${esc(u.email)}${u.phone ? ' · ' + esc(u.phone) : ''}</div></div>
        <div class="row"><button class="btn s" data-salary="${u.id}">Выплатить зарплату</button><button class="btn s" data-edit-user="${u.id}">Изменить</button></div></div>
      <div class="grid g4" style="margin-top:14px;grid-template-columns:repeat(5,1fr)">
        <div class="kpi"><div class="l">Объектов в ${monthName(month).split(' ')[0]}</div><div class="v">${s.objects_in_month ?? 0}</div><div class="d">всего ${s.objects_total ?? 0}</div></div>
        <div class="kpi"><div class="l">Зарплата на объект</div><div class="v num">${s.salary_per_object ? fmt(s.salary_per_object) : '—'}</div><div class="d">${u.salary && (s.objects_in_month ?? 0) < 4 ? 'при 4 объектах — ' + fmt(Number(u.salary) / 4) : ''}</div></div>
        <div class="kpi"><div class="l">Начислено бригаде</div><div class="v num">${fmt(s.crew_accrued)}</div></div>
        <div class="kpi"><div class="l">Выплачено бригаде</div><div class="v num">${fmt(s.crew_paid)}</div></div>
        <div class="kpi"><div class="l">Долг бригаде</div><div class="v num ${Number(s.crew_due) > 0 ? 'copper' : ''}">${fmt(s.crew_due)}</div><div class="d">зарплата за месяц: ${fmt(s.salary_paid)}</div></div>
      </div>
      ${salary.length ? `<details style="margin-top:10px"><summary class="small mute" style="cursor:pointer">Журнал зарплаты · ${salary.length}</summary><table style="margin-top:6px"><tr><th>Дата</th><th>За месяц</th><th>Способ</th><th class="r">Сумма</th></tr>${salary.slice(0, 12).map(e => `<tr><td class="num">${dateRu(e.date)}</td><td>${e.period ? monthName(e.period) : '—'}</td><td>${esc(D.pay_methods[e.method] || e.method || '—')}</td><td class="r num">${fmt(e.amount)}</td></tr>`).join('')}</table></details>` : ''}
    </div>`; }).join('') || emptyState('Прорабов пока нет', 'Заведите прораба — он получит вход в мобильный кабинет.')}
    <div class="card pad"><div class="row sp"><h2>Бригады</h2><span class="small mute">бригада закреплена за одним прорабом, он её старший</span></div>
      <table style="margin-top:10px"><tr><th>Бригада</th><th>Прораб</th><th>С какого времени</th><th></th></tr>
      ${crews.map(c => { const cur = c.history.find(h => !h.to_date); const past = c.history.filter(h => h.to_date); return `<tr><td><b>${esc(c.name)}</b>${c.members_count ? ` <span class="small mute">${c.members_count} чел.</span>` : ''}${!c.is_active ? ' <span class="tag warn">расформирована</span>' : ''}${past.length ? `<div class="small mute">ранее: ${past.map(h => esc(h.foreman_name || '—') + ' до ' + dateRu(h.to_date)).join(', ')}</div>` : ''}</td>
        <td>${esc(c.foreman_name || '—')}</td><td>${cur ? dateRu(cur.from_date) : '—'}</td><td class="r"><button class="btn s" data-reassign="${c.id}">Переназначить прораба</button></td></tr>`; }).join('') || '<tr><td colspan="4" class="mute">Бригад пока нет</td></tr>'}</table></div>`;

  main.querySelector('[data-month]').onchange = (e) => location.hash = '#/crews?month=' + e.target.value;
  main.querySelector('[data-new-foreman]').onclick = () => formModal({ title: 'Новый прораб', intro: 'Получит вход в мобильный кабинет: только свои объекты, без цен клиента и маржи.', submit: 'Создать',
    fields: [{ name: 'name', label: 'Имя', required: true }, { name: 'email', label: 'E-mail для входа', type: 'email', required: true }, { name: 'password', label: 'Пароль (не меньше 6 символов)', required: true }, { name: 'phone', label: 'Телефон' }, { name: 'salary', label: 'Зарплата в месяц, ₽', type: 'number', value: 150000 }],
    onSubmit: async (v) => { await api.post('/api/users', { ...v, is_foreman: true }); toast('Прораб создан'); render(main, r, S); } });
  main.querySelector('[data-new-crew]').onclick = () => formModal({ title: 'Новая бригада', submit: 'Создать',
    fields: [{ name: 'name', label: 'Название', required: true, placeholder: 'Бригада № 1' }, { name: 'members_count', label: 'Монтажников', type: 'number' }, { name: 'foreman_id', label: 'Прораб', type: 'select', options: [{ value: '', label: '— без прораба —' }, ...fm.filter(u => u.is_active).map(u => ({ value: u.id, label: u.name }))] }, { name: 'note', label: 'Заметка' }],
    onSubmit: async (v) => { v.foreman_id = v.foreman_id ? Number(v.foreman_id) : null; await api.post('/api/crews', v); toast('Бригада создана'); render(main, r, S); } });
  main.querySelectorAll('[data-reassign]').forEach(b => b.onclick = () => { const c = crews.find(x => x.id === Number(b.dataset.reassign)); formModal({ title: 'Переназначить бригаду', intro: `${esc(c.name)} перейдёт вместе с объектами в работе. История сохранится.`, submit: 'Переназначить',
    fields: [{ name: 'foreman_id', label: 'Новый прораб', type: 'select', options: fm.filter(u => u.is_active && u.id !== c.foreman_id).map(u => ({ value: u.id, label: u.name })), required: true }, { name: 'note', label: 'Причина', placeholder: 'прежний прораб уволился' }],
    onSubmit: async (v) => { await api.post(`/api/crews/${c.id}/reassign`, { foreman_id: Number(v.foreman_id), note: v.note }); toast('Бригада переназначена'); render(main, r, S); } }); });
  main.querySelectorAll('[data-salary]').forEach(b => b.onclick = () => { const u = fm.find(x => x.id === Number(b.dataset.salary)); formModal({ title: 'Выплата зарплаты — ' + u.name, intro: 'Попадёт в журнал прораба и в расходы месяца.', submit: 'Записать',
    fields: [{ name: 'amount', label: 'Сумма, ₽', type: 'number', required: true, value: u.salary || '' }, { name: 'period', label: 'За какой месяц', type: 'month', value: month }, { name: 'date', label: 'Дата выплаты', type: 'date', value: today() }, { name: 'method', label: 'Способ', type: 'select', options: opt(D.pay_methods) }, { name: 'note', label: 'Комментарий' }],
    onSubmit: async (v) => { await api.post('/api/expenses', { ...v, category: 'salary', foreman_id: u.id }); toast('Зарплата записана'); render(main, r, S); } }); });
  main.querySelectorAll('[data-edit-user]').forEach(b => b.onclick = () => { const u = fm.find(x => x.id === Number(b.dataset.editUser)); formModal({ title: 'Изменить — ' + u.name,
    fields: [{ name: 'name', label: 'Имя', value: u.name, required: true }, { name: 'phone', label: 'Телефон', value: u.phone || '' }, { name: 'salary', label: 'Зарплата в месяц, ₽', type: 'number', value: u.salary || '' }, { name: 'password', label: 'Новый пароль (пусто — не менять)' }, { name: 'is_active', label: 'Доступ', type: 'select', options: [{ value: 'true', label: 'активен' }, { value: 'false', label: 'закрыт' }], value: String(u.is_active) }],
    onSubmit: async (v) => { if (!v.password) delete v.password; v.is_active = v.is_active === 'true'; await api.patch('/api/users/' + u.id, v); toast('Сохранено'); render(main, r, S); } }); });
}

export function monthPicker(month) { return `<input type="month" class="btn" data-month value="${month}" style="padding:7px 10px">`; }
