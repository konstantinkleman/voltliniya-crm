import { api } from '../api.js';
import { esc, fmt, num, pct, srcClass, monthKey, monthName, emptyState, dateRu } from '../ui.js';
import { monthPicker } from './crews.js';

export async function render(main, r, state) {
  const D = state.dicts;
  const month = r.q.get('month') || monthKey();
  const [sm, ch, fs, st, cr] = await Promise.all([api.get('/api/stats/summary?month=' + month), api.get('/api/stats/channels?month=' + month), api.get('/api/stats/foremen?month=' + month), api.get('/api/stock/summary'), api.get('/api/stats/crews?month=' + month)]);
  const T = ch.reduce((a, c) => { for (const k of ['spent', 'leads', 'contacted', 'measured', 'offered', 'won', 'lost', 'revenue', 'profit']) a[k] = (a[k] || 0) + Number(c[k]); return a; }, {});
  const resNeg = Number(sm.result) < 0;
  main.innerHTML = `<div class="head"><div><h1>Аналитика</h1><p>${monthName(month)} · всё считается из заявок, объектов и расходов</p></div>${monthPicker(month)}</div>
  <div class="grid g4" style="margin-bottom:14px">
    <div class="card pad kpi"><div class="l">Получено от клиентов</div><div class="v num">${fmt(sm.received)}</div><div class="d">клиенты должны ${fmt(sm.receivable)}</div></div>
    <div class="card pad kpi"><div class="l">Итог месяца</div><div class="v num ${resNeg ? 'warn' : 'ok'}">${fmt(sm.result)}</div><div class="d">по деньгам: получено − все расходы</div></div>
    <div class="card pad kpi"><div class="l">Стоимость клиента</div><div class="v num">${T.won ? fmt(T.spent / T.won) : '—'}</div><div class="d">${T.leads ? 'лид ' + fmt(T.spent / T.leads) + ' · конверсия ' + pct(T.won, T.leads) : 'лидов нет'}</div></div>
    <div class="card pad kpi"><div class="l">Объекты</div><div class="v">${sm.objects_active} <span class="small mute">в работе</span></div><div class="d">средняя маржа ${sm.avg_margin !== null ? num(sm.avg_margin) + '%' : '—'} · долг бригадам ${fmt(sm.crew_due)}</div></div>
  </div>
  <div class="card wrap" style="margin-bottom:14px"><div class="pad" style="padding-bottom:0"><h2>Каналы и воронка</h2></div>
    ${ch.length ? `<table><tr><th>Канал</th><th class="r">Потрачено</th><th class="r">Лидов</th><th class="r">Лид</th><th class="r">Связались</th><th class="r">Замер</th><th class="r">Смета</th><th class="r">Договор</th><th class="r">Клиент</th><th class="r">Ср. чек</th><th class="r">Прибыль</th><th class="r">Окуп.</th></tr>
      ${ch.map(c => `<tr><td><span class="src ${srcClass(c.source)}">${esc(c.name)}</span></td><td class="r num">${fmt(c.spent)}</td><td class="r num">${c.leads}</td><td class="r num">${c.cost_per_lead ? fmt(c.cost_per_lead) : '—'}</td><td class="r num">${pct(c.contacted, c.leads)}</td><td class="r num">${pct(c.measured, c.leads)}</td><td class="r num">${pct(c.offered, c.leads)}</td><td class="r num"><b>${c.won}</b> · ${pct(c.won, c.leads)}</td><td class="r num">${c.cost_per_client ? fmt(c.cost_per_client) : '—'}</td><td class="r num">${c.avg_check ? fmt(c.avg_check) : '—'}</td><td class="r num ${Number(c.profit) < 0 ? 'warn' : ''}">${fmt(c.profit)}</td><td class="r num">${Number(c.spent) ? (Number(c.profit) / Number(c.spent)).toFixed(1) + '×' : '—'}</td></tr>`).join('')}
      <tr style="font-weight:700"><td>Итого</td><td class="r num">${fmt(T.spent)}</td><td class="r num">${T.leads}</td><td class="r num">${T.leads ? fmt(T.spent / T.leads) : '—'}</td><td class="r num">${pct(T.contacted, T.leads)}</td><td class="r num">${pct(T.measured, T.leads)}</td><td class="r num">${pct(T.offered, T.leads)}</td><td class="r num">${T.won} · ${pct(T.won, T.leads)}</td><td class="r num">${T.won ? fmt(T.spent / T.won) : '—'}</td><td class="r num">${T.won ? fmt(T.revenue / T.won) : '—'}</td><td class="r num">${fmt(T.profit)}</td><td class="r num">${T.spent ? (T.profit / T.spent).toFixed(1) + '×' : '—'}</td></tr></table>
      <div class="pad small mute">Воронка — по заявкам, созданным в этом месяце; сделки и расходы — по месяцу договора. При нескольких договорах в месяц цифры по каналу шаткие: решения — по данным за 2–3 месяца.</div>`
    : emptyState('Данных за месяц нет', 'Заявки появятся здесь, как только у них будет источник.')}</div>
  <div class="card wrap" style="margin-bottom:14px" id="crews-card"></div>
  <div class="grid g2">
    <div class="card pad"><h2>Деньги за месяц</h2><table style="margin-top:8px">
      <tr><td>Получено от клиентов</td><td class="r num">${fmt(sm.received)}</td></tr>
      <tr><td>Закупка материалов <span class="small mute">списано на объекты: ${fmt(sm.materials)}</span></td><td class="r num">−${fmt(sm.materials_purchased)}</td></tr>
      <tr><td>Выплаты бригадам</td><td class="r num">−${fmt(sm.crew_payouts)}</td></tr>
      <tr><td>Зарплата прорабов</td><td class="r num">−${fmt(sm.staff)}</td></tr>
      <tr><td>Маркетинг</td><td class="r num">−${fmt(sm.marketing)}</td></tr>
      <tr><td>Операционные</td><td class="r num">−${fmt(sm.operating)}</td></tr>
      <tr style="font-weight:800"><td>Итог</td><td class="r num ${resNeg ? 'warn' : 'ok'}">${fmt(sm.result)}</td></tr></table>
      ${resNeg && Number(sm.receivable) > 0 ? `<div class="warnbox">Минус отчасти потому, что клиенты ещё должны ${fmt(sm.receivable)} по объектам в работе.</div>` : ''}</div>
    <div class="card pad"><h2>Прорабы</h2><table style="margin-top:8px"><tr><th>Прораб</th><th class="r">Объектов</th><th class="r">ЗП на объект</th><th class="r">Долг бригаде</th></tr>
      ${fs.filter(f => f.objects_total || f.salary).map(f => `<tr><td>${esc(f.name)}</td><td class="r num">${f.objects_in_month}</td><td class="r num">${f.salary_per_object ? fmt(f.salary_per_object) : '—'}</td><td class="r num ${Number(f.crew_due) > 0 ? 'copper' : ''}">${fmt(f.crew_due)}</td></tr>`).join('') || '<tr><td colspan="4" class="mute">—</td></tr>'}</table>
      <h2 style="margin-top:18px">Склад</h2><table style="margin-top:8px">${st.by_warehouse.map(w => `<tr><td>${esc(w.name)}</td><td class="r num">${fmt(w.value)}</td></tr>`).join('')}<tr><td><b>Остатки на складах</b></td><td class="r num"><b>${fmt(st.total_value)}</b></td></tr><tr><td>Списано на объекты за месяц</td><td class="r num">${fmt(sm.materials)}</td></tr><tr><td>Ниже минимума</td><td class="r num ${st.low.length ? 'warn' : ''}">${st.low.length} поз.</td></tr>${st.pending_transfers ? `<tr><td>Перемещений в пути</td><td class="r num">${st.pending_transfers}</td></tr>` : ''}</table>
      ${st.low.length ? `<div class="warnbox">Докупить: ${st.low.slice(0, 5).map(l => esc(l.product) + ' (' + num(l.qty) + ' из ' + num(l.min_qty) + ' ' + esc(l.unit) + ')').join(', ')}${st.low.length > 5 ? ' и ещё ' + (st.low.length - 5) : ''}</div>` : ''}</div>
  </div>`;
  main.querySelector('[data-month]').onchange = (e) => location.hash = '#/stats?month=' + e.target.value;
  crewsBlock(main.querySelector('#crews-card'), cr, month, D);
}

// ---------- бригады: что заработала бригада и что осталось компании ----------
// Сданные объекты относятся к месяцу сдачи (акт подписан); объекты в работе — отдельной строкой, у них месяца ещё нет.
// Период: месяц аналитики, произвольный диапазон месяцев или всё время.
let crewPeriod = 'month', crewFrom = null, crewTo = null;
async function crewsBlock(el, base, month, D) {
  let cr = base;   // base — данные за месяц аналитики и за всё время; для диапазона запрашиваем отдельно
  if (crewPeriod === 'range') {
    crewFrom = crewFrom || month; crewTo = crewTo || month;
    if (crewFrom > crewTo) [crewFrom, crewTo] = [crewTo, crewFrom];
    el.innerHTML = '<div class="pad mute">Считаю…</div>';
    cr = await api.get(`/api/stats/crews?date_from=${crewFrom}&date_to=${crewTo}`);
  }
  const doneKey = crewPeriod === 'total' ? 'done_total' : 'done', expKey = crewPeriod === 'total' ? 'expenses_total' : 'expenses';
  const rows = cr.filter(c => c[doneKey].objects || c.active.objects || Number(c[expKey].sum) || (c.is_active && crewPeriod === 'total'));
  // объект с несколькими монтажниками в итогах считается один раз: складываем доли объекта, а не участия
  const sum = (key) => rows.reduce((a, c) => { const x = c[key]; for (const k of ['works', 'revenue', 'crew', 'crew_paid', 'crew_due', 'profit']) a[k] = (a[k] || 0) + Number(x[k]); a.objects = Math.round(((a.objects || 0) + Number(x.objects_share ?? x.objects)) * 100) / 100; return a; }, {});
  const TD = sum(doneKey), TA = sum('active'), TE = rows.reduce((a, c) => a + Number(c[expKey].sum), 0);
  const sign = (v) => Number(v) < 0 ? 'warn' : '';
  const periodLabel = crewPeriod === 'total' ? 'за всё время' : crewPeriod === 'range' ? (crewFrom === crewTo ? monthName(crewFrom) : `${monthName(crewFrom)} — ${monthName(crewTo)}`) : monthName(month);
  const inp = 'padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink)';
  const cells = (x) => `<td class="r num">${x.objects}</td><td class="r num">${fmt(x.works)}</td><td class="r num"><b>${fmt(x.crew)}</b></td><td class="r num">${fmt(x.crew_paid)}${Number(x.crew_due) > 0 ? `<div class="small copper">долг ${fmt(x.crew_due)}</div>` : ''}</td>
      <td class="r num ${sign(x.profit)}"><b>${fmt(x.profit)}</b></td><td class="r num ${sign(x.profit)}">${x.margin !== null ? num(x.margin) + '%' : '—'}</td><td class="r num">${x.crew_per_object ? fmt(x.crew_per_object) : '—'}</td><td class="r num ${sign(x.profit_per_object)}">${x.profit_per_object ? fmt(x.profit_per_object) : '—'}</td>`;
  const items = (x, done) => x.items.length ? `<table><tr><th>Объект</th><th>${done ? 'Сдан' : 'Этап'}</th><th class="r">Работ</th><th class="r">Бригаде</th><th class="r">Материалы</th><th class="r">Компании</th><th class="r">Маржа</th></tr>
      ${x.items.map(o => `<tr class="click" data-obj="${o.id}"><td>${esc(o.client_name)}<div class="small mute">${esc(o.address || '')}${o.foreman_name ? ' · ' + esc(o.foreman_name) : ''}${o.start_date ? ' · договор ' + dateRu(o.start_date) : ''}${o.shared ? ` · <span class="tag">несколько монтажников · доля ${num(o.share_pct)}%</span>` : ''}</div></td><td>${done ? (o.end_date ? dateRu(o.end_date) : '—') : esc(D.object_stage_names[o.stage] || o.stage)}</td><td class="r num">${fmt(o.works)}</td><td class="r num">${fmt(o.crew)}${Number(o.crew_paid) < Number(o.crew) ? `<div class="small mute">выпл. ${fmt(o.crew_paid)}</div>` : ''}</td><td class="r num">${fmt(o.materials)}</td><td class="r num ${sign(o.profit)}">${fmt(o.profit)}</td><td class="r num ${sign(o.profit)}">${o.margin !== null ? num(o.margin) + '%' : '—'}</td></tr>`).join('')}</table>` : '<div class="small mute" style="padding:8px 0">Объектов нет</div>';
  const expList = (ex) => ex && ex.items.length ? `<div class="small mute" style="margin:10px 0 4px"><b>Расходы компании на бригаду</b> · ${fmt(ex.sum)} (из выплат бригаде не вычитаются)</div><table><tr><th>Дата</th><th>Категория</th><th>Комментарий</th><th class="r">Сумма</th></tr>${ex.items.map(e => `<tr><td class="num">${dateRu(e.date)}</td><td>${esc(e.category_name)}</td><td class="mute">${esc(e.note || '')}</td><td class="r num">${fmt(e.amount)}</td></tr>`).join('')}</table>` : '';
  const sub = (id, x, done, ex = null) => `<tr class="hidden sub" data-sub="${id}"><td colspan="10" style="padding:0 10px 10px 28px;background:var(--bg)">${items(x, done)}${expList(ex)}</td></tr>`;
  el.innerHTML = `<div class="pad row sp" style="padding-bottom:0;align-items:flex-start"><div><h2>Бригады · <span class="mute" style="font-weight:500">${esc(periodLabel)}</span></h2><div class="small mute">«Заработано» — сданные объекты, по месяцу сдачи. «В работе» — текущие объекты, они попадут в месяц, когда подпишете акт. Бригаде — её доля с работ; компании — прибыль после материалов, бригады, доли зарплаты прораба и стоимости клиента. Расходы на бригаду (форма, инструмент) — по дате расхода, «чистыми» = компании − эти расходы</div></div>
      <div class="row" style="gap:8px"><div class="seg"><button class="${crewPeriod === 'month' ? 'on' : ''}" data-cp="month">${esc(monthName(month))}</button><button class="${crewPeriod === 'range' ? 'on' : ''}" data-cp="range">Период</button><button class="${crewPeriod === 'total' ? 'on' : ''}" data-cp="total">За всё время</button></div>
      ${crewPeriod === 'range' ? `<div class="row" style="gap:6px"><input type="month" data-from value="${crewFrom}" style="${inp}"><span class="mute">—</span><input type="month" data-to value="${crewTo}" style="${inp}"></div>` : ''}</div></div>
    ${rows.length ? `<table style="margin-top:10px"><tr><th>Бригада</th><th class="r">Объектов</th><th class="r">Работ</th><th class="r">Бригаде</th><th class="r">Выплачено</th><th class="r">Компании</th><th class="r">Маржа</th><th class="r">Бригаде / объект</th><th class="r">Компании / объект</th><th class="r">Расходы на бригаду</th></tr>
      ${rows.map(c => { const d = c[doneKey], a = c.active, id = c.id ?? 'none', ex = c[expKey]; const net = Number(d.profit) - Number(ex.sum); return `
        <tr class="click crew-head" data-crew="d${id}"><td><b>${esc(c.name)}</b>${!c.is_active ? ' <span class="tag warn">расформирована</span>' : ''}<div class="small mute">${c.foreman_name ? 'прораб ' + esc(c.foreman_name) : (c.id === null ? 'объекты без выбранной бригады' : 'без прораба')}</div><div class="small ok" style="margin-top:4px">✓ Заработано · сдано ${d.objects}</div></td>${cells(d)}<td class="r num">${Number(ex.sum) ? fmt(ex.sum) : '—'}${Number(ex.sum) ? `<div class="small ${net < 0 ? 'warn' : 'mute'}">чистыми ${fmt(net)}</div>` : ''}</td></tr>
        ${sub('d' + id, d, true, ex)}
        <tr class="click" data-crew="a${id}"><td style="padding-left:22px"><div class="small mute">⏳ В работе · ${a.objects} ${a.objects === 1 ? 'объект' : 'объектов'}</div></td>${cells(a)}<td class="r mute">—</td></tr>
        ${sub('a' + id, a, false)}`; }).join('')}
      <tr style="font-weight:700"><td>Итого заработано</td><td class="r num">${TD.objects}</td><td class="r num">${fmt(TD.works)}</td><td class="r num">${fmt(TD.crew)}</td><td class="r num">${fmt(TD.crew_paid)}</td><td class="r num ${sign(TD.profit)}">${fmt(TD.profit)}</td><td class="r num">${TD.revenue ? num(TD.profit / TD.revenue * 100) + '%' : '—'}</td><td class="r num">${TD.objects ? fmt(TD.crew / TD.objects) : '—'}</td><td class="r num">${TD.objects ? fmt(TD.profit / TD.objects) : '—'}</td><td class="r num">${TE ? fmt(TE) : '—'}${TE ? `<div class="small ${TD.profit - TE < 0 ? 'warn' : 'mute'}" style="font-weight:500">чистыми ${fmt(TD.profit - TE)}</div>` : ''}</td></tr>
      <tr class="mute"><td>Итого в работе</td><td class="r num">${TA.objects}</td><td class="r num">${fmt(TA.works)}</td><td class="r num">${fmt(TA.crew)}</td><td class="r num">${fmt(TA.crew_paid)}</td><td class="r num">${fmt(TA.profit)}</td><td class="r num">${TA.revenue ? num(TA.profit / TA.revenue * 100) + '%' : '—'}</td><td class="r num">${TA.objects ? fmt(TA.crew / TA.objects) : '—'}</td><td class="r num">${TA.objects ? fmt(TA.profit / TA.objects) : '—'}</td><td></td></tr></table>
      <div class="pad small mute">Месяц сдачи — дата «Сдача» в карточке объекта; ставится сама при этапе «Акт подписан», её можно поправить через «Изменить». По объектам в работе цифры предварительные: материалы ещё списываются, доп. работы добавляются. Нажмите на строку — раскроются объекты.</div>`
    : `<div class="pad mute">${crewPeriod === 'total' ? 'Бригад с объектами пока нет.' : 'За этот период сданных объектов нет, в работе тоже ничего.'}</div>`}`;
  el.querySelectorAll('[data-cp]').forEach(b => b.onclick = () => { crewPeriod = b.dataset.cp; crewsBlock(el, base, month, D); });
  el.querySelector('[data-from]')?.addEventListener('change', (e) => { crewFrom = e.target.value || month; crewsBlock(el, base, month, D); });
  el.querySelector('[data-to]')?.addEventListener('change', (e) => { crewTo = e.target.value || month; crewsBlock(el, base, month, D); });
  el.querySelectorAll('tr[data-crew]').forEach(tr => tr.onclick = () => el.querySelector(`tr[data-sub="${tr.dataset.crew}"]`).classList.toggle('hidden'));
  el.querySelectorAll('tr[data-obj]').forEach(tr => tr.onclick = (e) => { e.stopPropagation(); location.hash = '#/objects/' + tr.dataset.obj; });
}
