import { api } from '../api.js';
import { esc, fmt, dateRu, srcClass, toast, formModal, confirmModal, opt, emptyState, today, monthKey, monthName } from '../ui.js';
import { monthPicker } from './crews.js';

let S, D;
const TYPE_NAMES = { channel: 'маркетинг по каналу', marketing: 'общий маркетинг', staff: 'персонал', operating: 'операционный' };

export async function render(main, r, state) {
  S = state; D = state.dicts;
  const month = r.q.get('month') || monthKey();
  const crewF = r.q.get('crew') || '';
  const [all, foremen, crews, auto] = await Promise.all([api.get('/api/expenses?month=' + month), api.get('/api/foremen'), api.get('/api/crews'), api.get('/api/expenses/autoload').catch(() => null)]);
  // категории, которые этот месяц уже загружены автоматически: ручная строка там же — скорее всего дубль
  const autoCats = new Set(all.filter(e => e.external_ref).map(e => e.category));
  const list = crewF ? all.filter(e => String(e.crew_id) === crewF) : all;
  const crewSum = all.filter(e => e.crew_id).reduce((a, e) => a + Number(e.amount), 0);
  const cats = D.expense_categories;
  const sum = (t) => list.filter(e => (cats[e.category] || {}).type === t).reduce((a, e) => a + Number(e.amount), 0);
  const total = list.reduce((a, e) => a + Number(e.amount), 0);
  main.innerHTML = `<div class="head"><div><h1>Расходы</h1><p>${monthName(month)}: ${fmt(total)} · маркетинг ${fmt(sum('channel') + sum('marketing'))} · персонал ${fmt(sum('staff'))} · операционные ${fmt(sum('operating'))}${crewSum ? ` · на бригады ${fmt(crewSum)}` : ''}</p></div>
    <div class="row">${monthPicker(month)}<select data-crewf class="btn" style="padding:7px 10px"><option value="">Все расходы</option>${crews.map(c => `<option value="${c.id}" ${String(c.id) === crewF ? 'selected' : ''}>На бригаду: ${esc(c.name)}</option>`).join('')}</select><button class="btn p" data-new>Добавить расход</button></div></div>
    ${autoloadBar(auto)}
    ${list.length ? `<div class="card wrap"><table><tr><th>Дата</th><th>Категория</th><th>Тип</th><th>Комментарий</th><th class="r">Сумма</th><th></th></tr>
      ${list.map(e => { const c = cats[e.category] || { name: e.category, type: 'operating' }; return `<tr><td class="num">${dateRu(e.date)}</td><td><b>${esc(c.name)}</b>${e.foreman_name ? `<div class="small mute">${esc(e.foreman_name)}${e.period ? ' · за ' + monthName(e.period) : ''}</div>` : ''}${e.crew_name ? `<div class="small"><span class="tag">бригада · ${esc(e.crew_name)}</span></div>` : ''}${e.external_ref ? ' <span class="tag act" title="Загружено автоматически, сумма обновляется сама">авто</span>' : autoCats.has(e.category) ? ' <span class="tag warn" title="За этот месяц расход по каналу уже загружен автоматически — если это та же сумма, удалите ручную строку">дубль автозагрузки?</span>' : ''}</td>
        <td>${e.channel ? `<span class="src ${srcClass(e.channel)}">${esc(D.sources[e.channel] || e.channel)}</span>` : `<span class="small mute">${TYPE_NAMES[c.type]}</span>`}</td><td class="mute">${esc(e.note || '')}</td><td class="r num">${fmt(e.amount)}</td><td class="r"><button class="btn s" data-del="${e.id}">×</button></td></tr>`; }).join('')}</table></div>`
    : emptyState('За этот месяц расходов нет', 'Вносите все расходы, не только рекламу — иначе прибыль за месяц будет неполной. Зарплата прораба вносится из раздела «Прорабы».')}`;
  main.querySelector('[data-month]').onchange = (e) => location.hash = '#/expenses?month=' + e.target.value + (crewF ? '&crew=' + crewF : '');
  main.querySelector('[data-crewf]').onchange = (e) => location.hash = '#/expenses?month=' + month + (e.target.value ? '&crew=' + e.target.value : '');
  main.querySelector('[data-new]').onclick = () => newExpense(() => render(main, r, S), foremen, crews);
  const sync = main.querySelector('[data-sync]');
  if (sync) sync.onclick = async () => {
    sync.disabled = true; sync.textContent = 'Загружаю…';
    await api.post('/api/expenses/autoload', {});
    for (let i = 0; i < 60; i++) {           // Директ может строить отчёт до пары минут
      await new Promise(res => setTimeout(res, 3000));
      const st = await api.get('/api/expenses/autoload');
      if (!st.running) break;
    }
    if (location.hash.startsWith('#/expenses')) render(main, r, S);
  };
  main.querySelectorAll('[data-del]').forEach(b => b.onclick = () => confirmModal('Удалить расход?', async () => { await api.del('/api/expenses/' + b.dataset.del); render(main, r, S); }, 'Удалить'));
}

export function newExpense(onDone, foremen, crews = []) {
  const cats = D.expense_categories;
  const groups = ['channel', 'marketing', 'staff', 'operating'];
  const options = groups.flatMap(t => Object.entries(cats).filter(([, c]) => c.type === t).map(([k, c]) => ({ value: k, label: `${c.name} — ${TYPE_NAMES[t]}` })));
  formModal({ title: 'Новый расход', submit: 'Сохранить',
    fields: [{ name: 'amount', label: 'Сумма, ₽', type: 'number', required: true, inputmode: 'decimal' }, { name: 'category', label: 'Категория', type: 'select', options, value: 'direct' }, { name: 'date', label: 'Дата', type: 'date', value: today() },
      { name: 'foreman_id', label: 'Прораб (для зарплаты)', type: 'select', options: [{ value: '', label: '—' }, ...foremen.map(f => ({ value: f.id, label: f.name }))] },
      { name: 'crew_id', label: 'На бригаду (форма, инструмент — расход компании, из выплат бригаде не вычитается)', type: 'select', options: [{ value: '', label: '— не на бригаду —' }, ...crews.filter(c => c.is_active).map(c => ({ value: c.id, label: c.name + (c.foreman_name ? ' · ' + c.foreman_name : '') }))] },
      { name: 'method', label: 'Способ', type: 'select', options: [{ value: '', label: '—' }, ...opt(D.pay_methods)] }, { name: 'note', label: 'Комментарий', placeholder: 'например: форма, 6 комплектов' }],
    onSubmit: async (v) => { v.foreman_id = v.foreman_id ? Number(v.foreman_id) : null; v.crew_id = v.crew_id ? Number(v.crew_id) : null; await api.post('/api/expenses', v); toast('Расход сохранён'); onDone(); } });
}

function timeRu(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// Полоска «Автозагрузка»: какие каналы подключены и как прошла последняя загрузка
function autoloadBar(st) {
  if (!st) return '';
  const chans = Object.values(st.channels);
  const on = chans.filter(c => c.configured);
  const items = chans.map(c => {
    if (!c.configured) return `<span class="small mute">${esc(c.name)}: не подключён</span>`;
    if (c.ok === false) return `<span class="tag warn" title="${esc(c.error || '')}">${esc(c.name)}: ошибка</span>`;
    if (c.ok) return `<span class="tag act">${esc(c.name)} ✓ ${timeRu(c.at)}</span>`;
    return `<span class="tag">${esc(c.name)}: ждёт первой загрузки</span>`;
  });
  items.push('<span class="small mute">Профи и SMS: через сборщик</span>');
  const err = chans.find(c => c.configured && c.ok === false);
  return `<div class="card pad" style="margin-bottom:14px"><div class="row" style="justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
    <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center"><b>Автозагрузка рекламы</b>${items.join('')}</div>
    ${on.length ? `<button class="btn s" data-sync ${st.running ? 'disabled' : ''}>${st.running ? 'Загружаю…' : 'Обновить сейчас'}</button>` : ''}</div>
    ${err ? `<div class="small" style="margin-top:6px;color:var(--bad,#b42318)">${esc(err.name)}: ${esc(err.error || '')}</div>` : ''}
    ${on.length ? `<div class="small mute" style="margin-top:6px">Одна строка на канал в месяц, сумма обновляется сама каждые ${st.every_hours} ч. Расходы этих каналов вручную больше не вносите.</div>`
      : '<div class="small mute" style="margin-top:6px">Ключи Директа и Авито вносятся в .env на сервере — после этого расходы будут подставляться сами.</div>'}</div>`;
}
