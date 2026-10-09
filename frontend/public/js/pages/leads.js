import { api } from '../api.js';
import { esc, fmt, num, dateRu, dateTimeRu, srcClass, toast, openDrawer, closeDrawer, formModal, confirmModal, opt, emptyState, today } from '../ui.js';
import { docsBlock, uploadDoc } from './docs.js';

let S, D;

export async function render(main, r, state) {
  S = state; D = state.dicts;
  const all = await api.get('/api/leads');
  const open = all.filter(l => !['won', 'lost'].includes(l.stage));
  const won = all.filter(l => l.stage === 'won'), lost = all.filter(l => l.stage === 'lost');
  const stages = D.lead_stages.filter(s => !['won', 'lost'].includes(s));
  const cols = stages.map(st => {
    const ls = open.filter(l => l.stage === st);
    return `<div class="col"><h3>${esc(D.lead_stage_names[st])}<span>${ls.length}</span></h3>
      ${ls.map(card).join('') || '<div class="small mute" style="padding:8px 4px">Пусто</div>'}</div>`;
  }).join('');
  main.innerHTML = `<div class="head"><div><h1>Заявки</h1><p>${open.length} в работе · ${won.length} договоров · ${lost.length} проиграно</p></div>
    <div class="row"><button class="btn" data-closed>Закрытые · ${won.length + lost.length}</button><button class="btn p" data-new>Новая заявка</button></div></div>
    ${all.length ? `<div class="kan">${cols}</div>` : emptyState('Заявок пока нет', 'Нажмите «Новая заявка». Источник обязателен — на нём держится вся аналитика по каналам.')}`;
  main.querySelector('[data-new]').onclick = newLead;
  main.querySelector('[data-closed]').onclick = () => showClosed([...won, ...lost]);
  main.querySelectorAll('.lead').forEach(el => el.onclick = () => openLead(Number(el.dataset.id)));
  if (r.id) openLead(Number(r.id));
}

function card(l) {
  return `<div class="lead" data-id="${l.id}"><b>${esc(l.name)}</b>
    <div class="m">${l.area_m2 ? num(l.area_m2) + ' м² · ' : ''}${esc(D.project_kinds[l.project_kind] || '')}${l.offer_sum ? ' · КП ' + fmt(l.offer_sum) : ''}</div>
    <div class="f"><span class="src ${srcClass(l.source)}">${esc(D.sources[l.source] || l.source)}</span><span class="small mute">${dateRu(l.updated_at)}</span></div></div>`;
}

function srcOptions() { return opt(D.sources); }

function newLead() {
  formModal({
    title: 'Новая заявка', submit: 'Создать',
    fields: [
      { name: 'name', label: 'Имя и объект', placeholder: 'Марина, ЖК Прокшино', required: true },
      { name: 'phone', label: 'Телефон', type: 'tel', inputmode: 'tel' },
      { name: 'source', label: 'Откуда узнали (обязательно)', type: 'select', options: srcOptions(), value: 'profi' },
      { name: 'lead_cost', label: 'Стоимость лида, ₽ (для профи.ру — по факту)', type: 'number', value: 0, min: 0 },
      { name: 'area_m2', label: 'Площадь, м²', type: 'number', step: '0.1', inputmode: 'decimal' },
      { name: 'project_kind', label: 'Проект', type: 'select', options: opt(D.project_kinds), value: 'none' },
      { name: 'address', label: 'Адрес' },
      { name: 'note', label: 'Заметка', type: 'textarea' },
    ],
    onSubmit: async (v) => { v.lead_cost = v.lead_cost || 0; const l = await api.post('/api/leads', v); toast('Заявка создана'); location.hash = '#/leads/' + l.id; },
  });
}

async function openLead(id) {
  let l;
  try { l = await api.get('/api/leads/' + id); } catch (e) { return toast(e.message, true); }
  const idx = D.lead_stages.indexOf(l.stage);
  const open = !['won', 'lost'].includes(l.stage);
  const next = open && l.stage !== 'offer_sent' ? D.lead_stages[idx + 1] : null;
  const d = openDrawer(`
    <h2>${esc(l.name)}</h2>
    <div class="row" style="margin-top:6px"><span class="src ${srcClass(l.source)}">${esc(D.sources[l.source])}</span><span class="small mute">лид ${fmt(l.lead_cost)}</span>${l.phone ? `<a class="small" href="tel:${esc(l.phone)}">${esc(l.phone)}</a>` : ''}</div>
    <div class="stages">${D.lead_stages.filter(s => s !== 'lost').map((s, i) => `<span class="${l.stage !== 'lost' && i <= idx ? 'on' : ''}"></span>`).join('')}</div>
    <div class="small ${l.stage === 'lost' ? 'warn' : 'mute'}">Этап: ${esc(D.lead_stage_names[l.stage])}${l.lost_reason ? ' — ' + esc(l.lost_reason) : ''}${l.object_id ? ` · <a href="#/objects/${l.object_id}">открыть объект</a>` : ''}</div>
    <dl class="dl">
      <dt>Площадь</dt><dd>${l.area_m2 ? num(l.area_m2) + ' м²' : '—'}</dd>
      <dt>Проект</dt><dd>${esc(D.project_kinds[l.project_kind] || '—')}</dd>
      <dt>Адрес</dt><dd>${esc(l.address || '—')}</dd>
      <dt>КП</dt><dd>${l.offer_sum ? fmt(l.offer_sum) + (l.tariff ? ' · ' + esc(l.tariff) : '') : '—'}</dd>
      <dt>Заметка</dt><dd>${esc(l.note || '—')}</dd>
    </dl>
    <div class="row">
      ${next ? `<button class="btn p" data-next>${esc(D.lead_stage_names[next])} →</button>` : ''}
      ${open && l.stage === 'offer_sent' ? `<button class="btn p" data-convert>Договор подписан → создать объект</button>` : ''}
      ${open ? `<button class="btn" data-lost>Проиграна</button>` : ''}
      <button class="btn" data-edit>Изменить</button>
    </div>
    <div id="lead-docs"></div>
    <div class="row sp" style="margin-top:20px"><h3>История</h3><button class="btn s" data-act>+ запись</button></div>
    <ul class="timeline">${l.activities.map(a => `<li>${esc(a.text)}<small>${dateTimeRu(a.created_at)}${a.user_name ? ' · ' + esc(a.user_name) : ''}</small></li>`).join('') || '<li class="mute">Пусто</li>'}</ul>
  `);
  docsBlock(d.querySelector('#lead-docs'), l.documents, { lead_id: l.id }, () => openLead(id), open ? 'Прикрепите КП на этапе «Смета отправлена», договор — при подписании.' : '');
  d.querySelector('[data-next]')?.addEventListener('click', async () => {
    if (next === 'offer_sent') {
      return formModal({ title: 'Смета отправлена', submit: 'Отметить',
        fields: [{ name: 'offer_sum', label: 'Сумма КП, ₽', type: 'number', required: true, value: l.offer_sum || '' }, { name: 'tariff', label: 'Тариф', type: 'select', options: opt(Object.fromEntries(D.tariffs.map(t => [t, t]))), value: l.tariff || 'Стандарт' }, { name: 'file', label: 'Файл КП (можно позже)', type: 'file' }],
        onSubmit: async (v) => {
          await api.patch('/api/leads/' + id, { offer_sum: v.offer_sum, tariff: v.tariff });
          if (v.file) await uploadDoc(v.file, { lead_id: id, kind: 'offer', title: 'КП «' + v.tariff + '»' });
          await api.post(`/api/leads/${id}/stage`, { stage: 'offer_sent', comment: fmt(v.offer_sum) });
          toast('Отмечено'); refresh(id);
        } });
    }
    await api.post(`/api/leads/${id}/stage`, { stage: next }); toast(D.lead_stage_names[next]); refresh(id);
  });
  d.querySelector('[data-lost]')?.addEventListener('click', () => formModal({ title: 'Причина отказа', submit: 'Закрыть заявку',
    fields: [{ name: 'lost_reason', label: 'Почему проиграли', type: 'select', options: D.lost_reasons.map(x => ({ value: x, label: x })) }, { name: 'comment', label: 'Комментарий' }],
    onSubmit: async (v) => { await api.post(`/api/leads/${id}/stage`, { stage: 'lost', ...v }); toast('Заявка закрыта'); closeDrawer(); location.hash = '#/leads'; render(document.getElementById('main'), {}, S); } }));
  d.querySelector('[data-act]').onclick = () => formModal({ title: 'Запись в историю', submit: 'Добавить',
    fields: [{ name: 'kind', label: 'Тип', type: 'select', options: [{ value: 'call', label: 'Звонок' }, { value: 'message', label: 'Сообщение' }, { value: 'measure', label: 'Замер' }, { value: 'note', label: 'Заметка' }] }, { name: 'text', label: 'Что произошло', required: true }],
    onSubmit: async (v) => { await api.post(`/api/leads/${id}/activities`, v); refresh(id); } });
  d.querySelector('[data-edit]').onclick = () => formModal({ title: 'Изменить заявку',
    fields: [
      { name: 'name', label: 'Имя и объект', value: l.name, required: true }, { name: 'phone', label: 'Телефон', value: l.phone || '' },
      { name: 'source', label: 'Источник', type: 'select', options: srcOptions(), value: l.source },
      { name: 'lead_cost', label: 'Стоимость лида, ₽', type: 'number', value: l.lead_cost },
      { name: 'area_m2', label: 'Площадь, м²', type: 'number', step: '0.1', value: l.area_m2 || '' },
      { name: 'project_kind', label: 'Проект', type: 'select', options: opt(D.project_kinds), value: l.project_kind },
      { name: 'address', label: 'Адрес', value: l.address || '' }, { name: 'note', label: 'Заметка', type: 'textarea', value: l.note || '' },
    ],
    onSubmit: async (v) => { await api.patch('/api/leads/' + id, v); toast('Сохранено'); refresh(id); } });
  d.querySelector('[data-convert]')?.addEventListener('click', async () => {
    const foremen = await api.get('/api/foremen');
    formModal({ title: 'Договор подписан', submit: 'Создать объект',
      intro: 'Заявка станет объектом, документы переедут в него. Суммы — из Приложения 1.',
      fields: [
        { name: 'works_sum', label: 'Работы по смете, ₽', type: 'number', required: true, value: l.offer_sum ? '' : '' },
        { name: 'materials_client_sum', label: 'Материалы для клиента по смете, ₽', type: 'number', value: 0 },
        { name: 'tariff', label: 'Тариф', type: 'select', options: opt(Object.fromEntries(D.tariffs.map(t => [t, t]))), value: l.tariff || 'Стандарт' },
        { name: 'foreman_id', label: 'Прораб', type: 'select', options: [{ value: '', label: '— назначить позже —' }, ...foremen.map(f => ({ value: f.id, label: f.name }))] },
        { name: 'start_date', label: 'Дата старта', type: 'date', value: today() },
        { name: 'contract_number', label: 'Номер договора' },
        { name: 'file', label: 'Файл договора (можно позже)', type: 'file' },
      ],
      onSubmit: async (v) => {
        if (v.file) await uploadDoc(v.file, { lead_id: id, kind: 'contract', title: 'Договор' + (v.contract_number ? ' № ' + v.contract_number : '') });
        v.foreman_id = v.foreman_id ? Number(v.foreman_id) : null;
        delete v.file;
        const o = await api.post(`/api/leads/${id}/convert`, v);
        toast('Объект создан'); closeDrawer(); location.hash = '#/objects/' + o.id;
      } });
  });
}

async function refresh(id) { await render(document.getElementById('main'), {}, S); openLead(id); }

function showClosed(list) {
  openDrawer(`<h2>Закрытые заявки</h2><table style="margin-top:12px"><tr><th>Кто</th><th>Канал</th><th>Итог</th></tr>
    ${list.map(l => `<tr class="click" data-id="${l.id}"><td>${esc(l.name)}<div class="small mute">${dateRu(l.updated_at)}</div></td><td><span class="src ${srcClass(l.source)}">${esc(D.sources[l.source])}</span></td><td>${l.stage === 'won' ? `<span class="tag ok">договор</span>` : `<span class="tag warn">${esc(l.lost_reason || 'проиграна')}</span>`}</td></tr>`).join('') || '<tr><td colspan="3" class="mute">Пусто</td></tr>'}</table>`)
    .querySelectorAll('tr.click').forEach(tr => tr.onclick = () => openLead(Number(tr.dataset.id)));
}
