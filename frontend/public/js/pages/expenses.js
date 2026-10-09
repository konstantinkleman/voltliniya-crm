import { api } from '../api.js';
import { esc, fmt, dateRu, srcClass, toast, formModal, confirmModal, opt, emptyState, today, monthKey, monthName } from '../ui.js';
import { monthPicker } from './crews.js';

let S, D;
const TYPE_NAMES = { channel: 'маркетинг по каналу', marketing: 'общий маркетинг', staff: 'персонал', operating: 'операционный' };

export async function render(main, r, state) {
  S = state; D = state.dicts;
  const month = r.q.get('month') || monthKey();
  const [list, foremen] = await Promise.all([api.get('/api/expenses?month=' + month), api.get('/api/foremen')]);
  const cats = D.expense_categories;
  const sum = (t) => list.filter(e => (cats[e.category] || {}).type === t).reduce((a, e) => a + Number(e.amount), 0);
  const total = list.reduce((a, e) => a + Number(e.amount), 0);
  main.innerHTML = `<div class="head"><div><h1>Расходы</h1><p>${monthName(month)}: ${fmt(total)} · маркетинг ${fmt(sum('channel') + sum('marketing'))} · персонал ${fmt(sum('staff'))} · операционные ${fmt(sum('operating'))}</p></div>
    <div class="row">${monthPicker(month)}<button class="btn p" data-new>Добавить расход</button></div></div>
    ${list.length ? `<div class="card wrap"><table><tr><th>Дата</th><th>Категория</th><th>Тип</th><th>Комментарий</th><th class="r">Сумма</th><th></th></tr>
      ${list.map(e => { const c = cats[e.category] || { name: e.category, type: 'operating' }; return `<tr><td class="num">${dateRu(e.date)}</td><td><b>${esc(c.name)}</b>${e.foreman_name ? `<div class="small mute">${esc(e.foreman_name)}${e.period ? ' · за ' + monthName(e.period) : ''}</div>` : ''}</td>
        <td>${e.channel ? `<span class="src ${srcClass(e.channel)}">${esc(D.sources[e.channel] || e.channel)}</span>` : `<span class="small mute">${TYPE_NAMES[c.type]}</span>`}</td><td class="mute">${esc(e.note || '')}</td><td class="r num">${fmt(e.amount)}</td><td class="r"><button class="btn s" data-del="${e.id}">×</button></td></tr>`; }).join('')}</table></div>`
    : emptyState('За этот месяц расходов нет', 'Вносите все расходы, не только рекламу — иначе прибыль за месяц будет неполной. Зарплата прораба вносится из раздела «Прорабы».')}`;
  main.querySelector('[data-month]').onchange = (e) => location.hash = '#/expenses?month=' + e.target.value;
  main.querySelector('[data-new]').onclick = () => newExpense(() => render(main, r, S), foremen);
  main.querySelectorAll('[data-del]').forEach(b => b.onclick = () => confirmModal('Удалить расход?', async () => { await api.del('/api/expenses/' + b.dataset.del); render(main, r, S); }, 'Удалить'));
}

export function newExpense(onDone, foremen) {
  const cats = D.expense_categories;
  const groups = ['channel', 'marketing', 'staff', 'operating'];
  const options = groups.flatMap(t => Object.entries(cats).filter(([, c]) => c.type === t).map(([k, c]) => ({ value: k, label: `${c.name} — ${TYPE_NAMES[t]}` })));
  formModal({ title: 'Новый расход', submit: 'Сохранить',
    fields: [{ name: 'amount', label: 'Сумма, ₽', type: 'number', required: true, inputmode: 'decimal' }, { name: 'category', label: 'Категория', type: 'select', options, value: 'direct' }, { name: 'date', label: 'Дата', type: 'date', value: today() },
      { name: 'foreman_id', label: 'Прораб (для зарплаты)', type: 'select', options: [{ value: '', label: '—' }, ...foremen.map(f => ({ value: f.id, label: f.name }))] }, { name: 'method', label: 'Способ', type: 'select', options: [{ value: '', label: '—' }, ...opt(D.pay_methods)] }, { name: 'note', label: 'Комментарий' }],
    onSubmit: async (v) => { v.foreman_id = v.foreman_id ? Number(v.foreman_id) : null; await api.post('/api/expenses', v); toast('Расход сохранён'); onDone(); } });
}
