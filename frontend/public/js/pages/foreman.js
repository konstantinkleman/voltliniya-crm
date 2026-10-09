import { api } from '../api.js';
import { esc, fmt, num, dateRu, dateTimeRu, toast, formModal, confirmModal, emptyState, today } from '../ui.js';
import { docsBlock, uploadDoc, loadThumbs } from './docs.js';

let S, D;

// Маршруты: #/my (объекты), #/my/obj/ID, #/my/money
export async function render(app, r, state) {
  S = state; D = state.dicts;
  const sub = r.page === 'my' ? (r.id || 'objects') : 'objects';
  const objId = sub === 'obj' ? Number(r.sub) : null;
  app.innerHTML = `<div class="fm">
    <div class="fm-top"><div><h2>${esc(S.me.name)}</h2><div class="small mute">прораб · ВольтЛиния</div></div>
      <div class="small">${S.me.is_director ? '<a href="#/leads">кабинет директора</a> · ' : ''}<a href="#/logout">выйти</a></div></div>
    <div id="fm-body"><div class="empty">Загрузка…</div></div></div>
    <nav class="fm-nav">
      <a href="#/my" class="${sub === 'objects' || sub === 'obj' ? 'on' : ''}"><b>▤</b>Объекты</a>
      <a href="#/my/money" class="${sub === 'money' ? 'on' : ''}"><b>₽</b>Деньги</a>
    </nav>`;
  const body = app.querySelector('#fm-body');
  try {
    if (objId) await renderObject(body, objId);
    else if (sub === 'money') await renderMoney(body);
    else await renderObjects(body);
  } catch (e) { body.innerHTML = `<div class="empty"><b>Не удалось загрузить</b>${esc(e.message)}</div>`; }
}

async function renderObjects(body) {
  const objs = await api.get('/api/objects');
  const active = objs.filter(o => !['act', 'warranty'].includes(o.stage)), done = objs.filter(o => ['act', 'warranty'].includes(o.stage));
  const card = (o) => `<a class="pcard" href="#/my/obj/${o.id}" style="display:block;text-decoration:none;color:inherit"><div class="row sp"><b>${esc(o.client_name)}</b><span class="tag ${['act', 'warranty'].includes(o.stage) ? 'ok' : 'act'}">${esc(D.object_stage_names[o.stage])}</span></div>
    <div class="small mute">${esc(o.address || '')}${o.area_m2 ? ' · ' + num(o.area_m2) + ' м²' : ''}${o.start_date ? ' · с ' + dateRu(o.start_date) : ''}</div></a>`;
  body.innerHTML = `<div class="small mute" style="margin:0 2px 8px">Мои объекты</div>${active.map(card).join('') || emptyState('Объектов в работе нет', 'Когда директор назначит вас на объект, он появится здесь.')}
    ${done.length ? `<details style="margin-top:14px"><summary class="small mute" style="cursor:pointer;margin-bottom:8px">Сданные · ${done.length}</summary>${done.map(card).join('')}</details>` : ''}`;
}

async function renderObject(body, id) {
  const o = await api.get('/api/objects/' + id);
  const f = o.finance;
  const stages = D.object_stages, idx = stages.indexOf(o.stage);
  const next = stages[idx + 1];
  const photos = o.documents.filter(d => d.kind === 'photo');
  body.innerHTML = `<a class="btn s" href="#/my">← Объекты</a>
    <div class="pcard" style="margin-top:10px"><b>${esc(o.client_name)}</b><div class="small mute">${esc(o.address || '')}${o.area_m2 ? ' · ' + num(o.area_m2) + ' м²' : ''}${o.tariff ? ' · ' + esc(o.tariff) : ''}</div>
      ${o.phone ? `<div class="small" style="margin-top:4px"><a href="tel:${esc(o.phone)}">${esc(o.phone)}</a></div>` : ''}
      <div class="stages" style="margin-top:10px">${stages.map((s, i) => `<span class="${i <= idx ? 'on' : ''}"></span>`).join('')}</div>
      <div class="small mute">${esc(D.object_stage_names[o.stage])}${o.stage_log.length ? ' · с ' + dateRu(o.stage_log[o.stage_log.length - 1].created_at) : ''}</div></div>
    <div class="big">
      <button class="p" data-photo>📷 Фото с объекта</button>
      <button data-mat>Списать материал на объект</button>
      ${next ? `<button data-next>Перевести на «${esc(D.object_stage_names[next])}»</button>` : ''}
    </div>
    <div class="pcard"><b>Смета работ</b><div class="small mute">${fmt(f.works_base)} работ · бригаде ${num(Number(f.crew_share) * 100)}% = ${fmt(f.crew_plan)}</div></div>
    <div class="pcard"><div class="row sp"><b>Фото · ${photos.length}</b></div>
      <div class="photos" style="margin-top:8px" id="fm-photos">${photos.slice(0, 12).map(p => `<a href="#" data-id="${p.id}" title="${esc(p.title)}"><img alt="${esc(p.title)}" loading="lazy"></a>`).join('') || '<span class="small mute">Пока нет</span>'}</div></div>
    <div class="pcard"><b>Материалы на объекте</b><table style="margin-top:6px">${o.materials.map(m => `<tr><td>${esc(m.name)}<div class="small mute">${dateRu(m.date)}</div></td><td class="r num">${m.qty ? num(m.qty, 2) + ' ' + esc(m.unit || '') : ''}</td><td class="r num">${fmt(m.cost_sum)}</td></tr>`).join('') || '<tr><td class="mute">Пока ничего</td></tr>'}</table></div>
    <div class="pcard" id="fm-docs"></div>`;
  const reload = () => renderObject(body, id);
  docsBlock(body.querySelector('#fm-docs'), o.documents, { object_id: id }, reload, 'План, приложение с объёмами, схема щита — загрузит директор.', { canDelete: false });
  body.querySelector('#fm-docs h3').textContent = 'Документы';
  loadThumbs(body.querySelectorAll('#fm-photos a'));
  body.querySelector('[data-photo]').onclick = () => formModal({ title: 'Фото с объекта', submit: 'Загрузить',
    fields: [{ name: 'file', label: 'Снимок', type: 'file', accept: 'image/*', capture: true, required: true }, { name: 'title', label: 'Подпись', placeholder: 'День 3 — штробление', value: 'Фото ' + dateRu(new Date()) }],
    onSubmit: async (v) => { await uploadDoc(v.file, { object_id: id, kind: 'photo', title: v.title }); toast('Фото загружено'); reload(); } });
  body.querySelector('[data-mat]').onclick = () => formModal({ title: 'Списать на объект', submit: 'Списать',
    fields: [{ name: 'name', label: 'Что', required: true, placeholder: 'ВВГнг-LS 3×2,5' }, { name: 'qty', label: 'Сколько', type: 'number', step: '0.01', inputmode: 'decimal' }, { name: 'unit', label: 'Ед.', value: 'м' }, { name: 'cost_sum', label: 'Себестоимость итого, ₽ (если знаете)', type: 'number', value: 0 }],
    onSubmit: async (v) => { v.date = today(); v.cost_sum = v.cost_sum || 0; await api.post(`/api/objects/${id}/materials`, v); toast('Списано'); reload(); } });
  body.querySelector('[data-next]')?.addEventListener('click', () => confirmModal(`Перевести объект на «${D.object_stage_names[next]}»?`, async () => { await api.post(`/api/objects/${id}/stage`, { stage: next }); toast('Этап переведён'); reload(); }, 'Перевести'));
}

async function renderMoney(body) {
  const objs = await api.get('/api/objects');
  const crews = await api.get('/api/crews');
  const due = objs.reduce((a, o) => a + Number(o.finance.crew_due), 0);
  body.innerHTML = `<div class="small mute" style="margin:0 2px 8px">Моя бригада</div>
    <div class="pcard"><b>${crews.map(c => esc(c.name)).join(', ') || 'Бригада не закреплена'}</b><div class="small mute">${num(Number(D.crew_share) * 100)}% от стоимости работ по каждому объекту, выплата через вас</div></div>
    <div class="pcard"><b class="num">${fmt(due)}</b><div class="small mute">остаток к выплате бригаде по всем объектам</div></div>
    <div class="small mute" style="margin:14px 2px 8px">По объектам</div>
    ${objs.map(o => { const f = o.finance; return `<div class="pcard"><div class="row sp"><b>${esc(o.client_name)}</b><span class="num">${fmt(f.crew_plan)}</span></div><div class="small mute">выплачено ${fmt(f.crew_paid)} · остаток ${fmt(f.crew_due)}</div></div>`; }).join('') || '<div class="mute small">Объектов пока нет</div>'}
    <div class="infobox">Зарплата и дата её выплаты — у директора в разделе «Прорабы».</div>`;
}
