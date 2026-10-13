import { api } from '../api.js';
import { esc, fmt, num, pct, srcClass, monthKey, monthName, emptyState } from '../ui.js';
import { monthPicker } from './crews.js';

export async function render(main, r, state) {
  const D = state.dicts;
  const month = r.q.get('month') || monthKey();
  const [sm, ch, fs, st] = await Promise.all([api.get('/api/stats/summary?month=' + month), api.get('/api/stats/channels?month=' + month), api.get('/api/stats/foremen?month=' + month), api.get('/api/stock/summary')]);
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
}
