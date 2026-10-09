import { api } from '../api.js';
import { esc, fmt, num, pct, dateRu, dateTimeRu, srcClass, toast, formModal, confirmModal, opt, emptyState, today } from '../ui.js';
import { docsBlock } from './docs.js';

let S, D;

export async function render(main, r, state) {
  S = state; D = state.dicts;
  if (r.id) return renderOne(main, Number(r.id));
  const objs = await api.get('/api/objects');
  const active = objs.filter(o => !['act', 'warranty'].includes(o.stage));
  main.innerHTML = `<div class="head"><div><h1>Объекты</h1><p>${active.length} в работе · ${objs.length - active.length} сдано</p></div>
    <button class="btn p" data-new>Объект без заявки</button></div>
    ${objs.length ? `<div class="card wrap"><table><tr><th>Объект</th><th>Этап</th><th>Прораб · бригада</th><th class="r">Договор</th><th class="r">Получено</th><th class="r">Прибыль</th><th class="r">Бригада</th></tr>
    ${objs.map(o => { const f = o.finance; return `<tr class="click" data-id="${o.id}">
      <td><b>${esc(o.client_name)}</b><div class="small mute">${o.area_m2 ? num(o.area_m2) + ' м² · ' : ''}${esc(o.address || '')}${o.tariff ? ' · ' + esc(o.tariff) : ''}</div></td>
      <td><span class="tag ${['act', 'warranty'].includes(o.stage) ? 'ok' : 'act'}">${esc(D.object_stage_names[o.stage])}</span></td>
      <td>${esc(o.foreman_name || '—')}<div class="small mute">${esc(o.crew_name || '')}</div></td>
      <td class="r num">${fmt(f.contract_total)}</td>
      <td class="r num">${fmt(f.received)}<div class="small mute">${pct(f.received, f.contract_total)}</div></td>
      <td class="r num"><b class="${Number(f.profit) < 0 ? 'warn' : ''}">${fmt(f.profit)}</b><div class="small mute">${f.margin !== null ? num(f.margin) + '%' : '—'}</div></td>
      <td class="r num">${crewShareCell(f)}</td></tr>`; }).join('')}</table></div>`
    : emptyState('Объектов пока нет', 'Объект появляется из заявки на этапе «Договор». Можно завести и напрямую.')}`;
  main.querySelector('[data-new]').onclick = newObject;
  main.querySelectorAll('tr.click').forEach(tr => tr.onclick = () => location.hash = '#/objects/' + tr.dataset.id);
}

function crewShareCell(f) {
  const over = Number(f.crew_paid) > Number(f.crew_plan) + 0.5;
  const v = f.crew_share_actual !== null ? num(Number(f.crew_share_actual) * 100) + '%' : num(Number(f.crew_share) * 100) + '% план';
  return over ? `<span class="tag warn">${v}</span>` : v;
}

async function newObject() {
  const foremen = await api.get('/api/foremen');
  formModal({ title: 'Новый объект', submit: 'Создать',
    fields: [
      { name: 'client_name', label: 'Клиент', required: true }, { name: 'phone', label: 'Телефон' }, { name: 'address', label: 'Адрес' },
      { name: 'area_m2', label: 'Площадь, м²', type: 'number', step: '0.1' },
      { name: 'source', label: 'Откуда клиент', type: 'select', options: opt(D.sources), value: 'recommendation' },
      { name: 'tariff', label: 'Тариф', type: 'select', options: opt(Object.fromEntries(D.tariffs.map(t => [t, t]))), value: 'Стандарт' },
      { name: 'works_sum', label: 'Работы по смете, ₽', type: 'number', required: true },
      { name: 'materials_client_sum', label: 'Материалы для клиента, ₽', type: 'number', value: 0 },
      { name: 'foreman_id', label: 'Прораб', type: 'select', options: [{ value: '', label: '— назначить позже —' }, ...foremen.map(f => ({ value: f.id, label: f.name }))] },
      { name: 'start_date', label: 'Дата старта', type: 'date', value: today() }, { name: 'contract_number', label: 'Номер договора' },
    ],
    onSubmit: async (v) => { v.foreman_id = v.foreman_id ? Number(v.foreman_id) : null; const o = await api.post('/api/objects', v); toast('Объект создан'); location.hash = '#/objects/' + o.id; } });
}

async function renderOne(main, id) {
  const o = await api.get('/api/objects/' + id);
  const f = o.finance;
  const stages = D.object_stages, idx = stages.indexOf(o.stage);
  const max = Math.max(Number(f.contract_total), 1);
  const bar = (v, cls, off = 0) => `<div class="bar"><i class="${cls}" style="left:${Math.min(off / max * 100, 100)}%;width:${Math.max(Math.min(Math.abs(v) / max * 100, 100 - Math.min(off / max * 100, 100)), 0.5)}%"></i></div>`;
  let off = 0; const rows = [];
  const push = (label, v, cls) => { rows.push(`<div class="li"><span>${label}</span>${bar(v, cls, off)}<span class="num ${cls === 'in' ? 'ok' : 'copper'}" style="text-align:right">${cls === 'in' ? '' : '−'}${fmt(Math.abs(v))}</span></div>`); if (cls !== 'in') off += Number(v); };
  push('По договору' + (Number(f.extra_works_sum) ? ' (с доп. работами)' : ''), f.contract_total, 'in');
  push('Материалы по себестоимости', f.materials_cost, 'out');
  push(`Бригада · ${num(Number(f.crew_share) * 100)}% работ`, f.crew_plan, 'out');
  if (f.foreman_share !== null) push(`Зарплата прораба · доля (${f.foreman_objects_in_month} об. в месяце)`, f.foreman_share, 'out');
  push(`Клиент из канала «${esc(D.sources[o.source] || '—')}»`, f.client_cost, 'out');
  const profitNeg = Number(f.profit) < 0;
  const over = Number(f.crew_paid) > Number(f.crew_plan) + 0.5;

  main.innerHTML = `
  <div class="head"><div><a class="btn s" href="#/objects">← Объекты</a><h1 style="margin-top:8px">${esc(o.client_name)}</h1>
    <p>${esc(o.address || 'адрес не указан')}${o.area_m2 ? ' · ' + num(o.area_m2) + ' м²' : ''}${o.tariff ? ' · ' + esc(o.tariff) : ''} · ${o.foreman_name ? 'прораб ' + esc(o.foreman_name) + (o.crew_name ? ', ' + esc(o.crew_name) : '') : '<span class="warn">прораб не назначен</span>'}${o.contract_number ? ' · договор № ' + esc(o.contract_number) : ''}</p></div>
    <div class="row"><button class="btn" data-foreman>${o.foreman_id ? 'Сменить прораба' : 'Назначить прораба'}</button><button class="btn" data-edit>Изменить</button>${idx < stages.length - 1 ? `<button class="btn p" data-next>Следующий этап: ${esc(D.object_stage_names[stages[idx + 1]])}</button>` : ''}</div></div>
  <div class="card"><div class="stepper">${stages.map((s, i) => `<button class="step ${i < idx ? 'done' : i === idx ? 'cur' : ''}" data-stage="${s}" title="Перевести на этот этап">${esc(D.object_stage_names[s])}</button>`).join('')}</div></div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card pad"><h2>Прибыль объекта</h2>
      <div class="ladder" style="margin-top:8px">${rows.join('')}
        <div class="li total"><span>Прибыль${f.margin !== null ? ' · ' + num(f.margin) + '%' : ''}</span>${profitNeg ? `<div class="bar" style="background:none"><span class="small warn">расходы больше договора на ${fmt(-Number(f.profit))}</span></div>` : bar(f.profit, 'res', off)}<span class="num ${profitNeg ? 'warn' : ''}" style="text-align:right">${fmt(f.profit)}</span></div></div>
      ${over ? `<div class="warnbox">Бригаде выплачено ${fmt(f.crew_paid)} — это ${num(Number(f.crew_share_actual) * 100)}% от работ, на ${fmt(Number(f.crew_paid) - Number(f.crew_plan))} выше плана ${num(Number(f.crew_share) * 100)}%.</div>` : ''}
      ${!o.materials.length ? `<div class="infobox">Материалы ещё не списаны — себестоимость 0, прибыль завышена.</div>` : ''}
    </div>
    <div class="grid">
      <div class="card pad"><div class="row sp"><h2>Деньги клиента</h2><button class="btn s" data-pay>+ платёж</button></div>
        <table style="margin-top:8px">
          <tr><td>Работы по смете</td><td class="r num">${fmt(o.finance.works_sum)}</td></tr>
          ${o.extra_works.map(e => `<tr><td>Доп.: ${esc(e.title)} <button class="btn s" data-del-extra="${e.id}" title="Удалить">×</button></td><td class="r num">${fmt(e.amount)}</td></tr>`).join('')}
          <tr><td>Материалы для клиента <span class="small mute">наценка ${fmt(f.materials_markup)}</span></td><td class="r num">${fmt(o.finance.materials_client_sum)}</td></tr>
          ${o.payments.map(p => `<tr><td>Платёж № ${p.number} · ${dateRu(p.date)} · ${esc(D.pay_methods[p.method] || p.method)}${p.note ? ' · ' + esc(p.note) : ''} <button class="btn s" data-del-pay="${p.id}" title="Удалить">×</button></td><td class="r num ok">+${fmt(p.amount)}</td></tr>`).join('')}
          <tr><td><b>Остаток к оплате</b></td><td class="r num"><b>${fmt(f.receivable)}</b></td></tr></table>
        <div class="row" style="margin-top:10px"><button class="btn s" data-extra>+ доп. работы</button></div></div>
      <div class="card pad"><div class="row sp"><h2>Бригада</h2><button class="btn s" data-payout>+ выплата</button></div>
        <table style="margin-top:8px">
          <tr><td>План · ${num(Number(f.crew_share) * 100)}% от ${fmt(f.works_base)}</td><td class="r num">${fmt(f.crew_plan)}</td></tr>
          ${o.payouts.map(p => `<tr><td>${dateRu(p.date)} · ${esc(D.pay_methods[p.method] || p.method)}${p.note ? ' · ' + esc(p.note) : ''} <button class="btn s" data-del-payout="${p.id}" title="Удалить">×</button></td><td class="r num">${fmt(p.amount)}</td></tr>`).join('')}
          <tr><td><b>Остаток бригаде</b></td><td class="r num"><b>${fmt(f.crew_due)}</b></td></tr></table></div>
    </div>
  </div>
  <div class="card pad" style="margin-top:14px"><div class="row sp"><h2>Материалы на объекте</h2><button class="btn s" data-mat>+ списать</button></div>
    <table style="margin-top:8px"><tr><th>Позиция</th><th class="r">Кол-во</th><th class="r">Себестоимость</th><th></th></tr>
      ${o.materials.map(m => `<tr><td>${esc(m.name)}<div class="small mute">${dateRu(m.date)}</div></td><td class="r num">${m.qty ? num(m.qty, 2) + ' ' + esc(m.unit || '') : '—'}</td><td class="r num">${fmt(m.cost_sum)}</td><td class="r"><button class="btn s" data-del-mat="${m.id}">×</button></td></tr>`).join('') || '<tr><td colspan="4" class="mute">Пока ничего не списано. В первой версии — суммами; складские списания появятся со складом.</td></tr>'}
      <tr><td><b>Итого</b></td><td></td><td class="r num"><b>${fmt(f.materials_cost)}</b></td><td></td></tr></table></div>
  <div class="grid g2" style="margin-top:14px"><div class="card pad" id="obj-docs"></div><div class="card pad" id="obj-photos"></div></div>
  <div class="card pad" style="margin-top:14px"><h2>История этапов</h2><ul class="timeline">${o.stage_log.map(s => `<li>${esc(D.object_stage_names[s.stage])}<small>${dateTimeRu(s.created_at)}</small></li>`).join('')}</ul>${o.note ? `<p class="mute small">${esc(o.note)}</p>` : ''}</div>`;

  const reload = () => renderOne(main, id);
  docsBlock(main.querySelector('#obj-docs'), o.documents, { object_id: id }, reload, 'Договор, КП, приложения, акты, план.');
  docsBlock(main.querySelector('#obj-photos'), o.documents, { object_id: id }, reload, 'Фотоотчёт с объекта.', { photos: true });

  main.querySelector('[data-next]')?.addEventListener('click', () => setStage(id, stages[idx + 1], reload));
  main.querySelectorAll('[data-stage]').forEach(b => b.onclick = () => { if (b.dataset.stage !== o.stage) setStage(id, b.dataset.stage, reload); });
  main.querySelector('[data-foreman]').onclick = async () => {
    const foremen = await api.get('/api/foremen');
    formModal({ title: 'Назначить прораба', intro: 'Бригада подставится автоматически — та, что закреплена за прорабом.',
      fields: [{ name: 'foreman_id', label: 'Прораб', type: 'select', options: foremen.map(f => ({ value: f.id, label: f.name })), value: o.foreman_id || '' }],
      onSubmit: async (v) => { await api.patch('/api/objects/' + id, { foreman_id: Number(v.foreman_id) }); toast('Прораб назначен'); reload(); } });
  };
  main.querySelector('[data-edit]').onclick = () => formModal({ title: 'Изменить объект',
    fields: [
      { name: 'client_name', label: 'Клиент', value: o.client_name, required: true }, { name: 'phone', label: 'Телефон', value: o.phone || '' }, { name: 'address', label: 'Адрес', value: o.address || '' },
      { name: 'area_m2', label: 'Площадь, м²', type: 'number', step: '0.1', value: o.area_m2 || '' },
      { name: 'tariff', label: 'Тариф', type: 'select', options: opt(Object.fromEntries(D.tariffs.map(t => [t, t]))), value: o.tariff || 'Стандарт' },
      { name: 'source', label: 'Откуда клиент', type: 'select', options: opt(D.sources), value: o.source || 'other' },
      { name: 'works_sum', label: 'Работы по смете, ₽', type: 'number', value: f.works_sum }, { name: 'materials_client_sum', label: 'Материалы для клиента, ₽', type: 'number', value: f.materials_client_sum },
      { name: 'start_date', label: 'Старт', type: 'date', value: o.start_date || '' }, { name: 'end_date', label: 'Сдача', type: 'date', value: o.end_date || '' },
      { name: 'contract_number', label: 'Номер договора', value: o.contract_number || '' }, { name: 'note', label: 'Заметка', type: 'textarea', value: o.note || '' },
    ],
    onSubmit: async (v) => { await api.patch('/api/objects/' + id, v); toast('Сохранено'); reload(); } });
  main.querySelector('[data-pay]').onclick = () => formModal({ title: 'Платёж клиента', submit: 'Записать',
    fields: [{ name: 'number', label: 'Какой платёж', type: 'select', options: [{ value: 1, label: '№ 1 — до старта' }, { value: 2, label: '№ 2 — после сдачи' }, { value: 3, label: 'Дополнительный' }], value: o.payments.length ? 2 : 1 },
      { name: 'amount', label: 'Сумма, ₽', type: 'number', required: true, value: o.payments.length ? f.receivable : f.materials_client_sum }, { name: 'date', label: 'Дата', type: 'date', value: today() },
      { name: 'method', label: 'Способ', type: 'select', options: opt(D.pay_methods) }, { name: 'note', label: 'Комментарий' }],
    onSubmit: async (v) => { v.number = Number(v.number); await api.post(`/api/objects/${id}/payments`, v); toast('Платёж записан'); reload(); } });
  main.querySelector('[data-payout]').onclick = () => formModal({ title: 'Выплата бригаде', intro: `Через прораба ${esc(o.foreman_name || '')}. План ${fmt(f.crew_plan)}, остаток ${fmt(f.crew_due)}.`, submit: 'Записать',
    fields: [{ name: 'amount', label: 'Сумма, ₽', type: 'number', required: true, value: Math.max(Number(f.crew_due), 0) }, { name: 'date', label: 'Дата', type: 'date', value: today() }, { name: 'method', label: 'Способ', type: 'select', options: opt(D.pay_methods) }, { name: 'note', label: 'Комментарий' }],
    onSubmit: async (v) => { await api.post(`/api/objects/${id}/payouts`, v); toast('Выплата записана'); reload(); } });
  main.querySelector('[data-extra]').onclick = () => formModal({ title: 'Дополнительные работы', intro: 'Оплаченные клиентом сверх сметы. Входят в базу для доли бригады.', submit: 'Добавить',
    fields: [{ name: 'title', label: 'Что сделали', required: true }, { name: 'amount', label: 'Сумма, ₽', type: 'number', required: true }, { name: 'date', label: 'Дата', type: 'date', value: today() }],
    onSubmit: async (v) => { await api.post(`/api/objects/${id}/extra-works`, v); reload(); } });
  main.querySelector('[data-mat]').onclick = () => formModal({ title: 'Списать материал на объект', submit: 'Списать',
    fields: [{ name: 'name', label: 'Что', required: true, placeholder: 'ВВГнг-LS 3×2,5' }, { name: 'qty', label: 'Количество', type: 'number', step: '0.01' }, { name: 'unit', label: 'Ед.', value: 'м' }, { name: 'cost_sum', label: 'Себестоимость итого, ₽', type: 'number', required: true }, { name: 'date', label: 'Дата', type: 'date', value: today() }],
    onSubmit: async (v) => { await api.post(`/api/objects/${id}/materials`, v); toast('Списано'); reload(); } });
  const delBtn = (sel, url, text) => main.querySelectorAll(sel).forEach(b => b.onclick = () => confirmModal(text, async () => { await api.del(url(b.dataset[Object.keys(b.dataset)[0]])); reload(); }, 'Удалить'));
  delBtn('[data-del-pay]', (x) => `/api/objects/${id}/payments/${x}`, 'Удалить платёж?');
  delBtn('[data-del-payout]', (x) => `/api/objects/${id}/payouts/${x}`, 'Удалить выплату?');
  delBtn('[data-del-extra]', (x) => `/api/objects/${id}/extra-works/${x}`, 'Удалить доп. работы?');
  delBtn('[data-del-mat]', (x) => `/api/objects/${id}/materials/${x}`, 'Удалить списание?');
}

async function setStage(id, stage, reload) {
  await api.post(`/api/objects/${id}/stage`, { stage }); toast('Этап: ' + D.object_stage_names[stage]); reload();
}
