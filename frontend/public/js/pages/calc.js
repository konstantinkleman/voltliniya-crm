// Калькулятор: список расчётов, экран замера (телефон/планшет), документы (КП, смета, щит), справочник расценок.
import { api } from '../api.js';
import { esc, fmt, num, dateRu, toast, openModal, closeModal, closeDrawer, confirmModal, comboHtml, mountCombo, emptyState } from '../ui.js';

const TN = { basic: 'Базовый', std: 'Стандарт', turnkey: 'Под ключ' };
const TARIFFS = ['basic', 'std', 'turnkey'];
let S;

export async function render(main, r, state) {
  S = state;
  closeDrawer();
  if (r.id === 'params') return renderParams(main);
  if (r.id === 'new') {
    const lead = r.q.get('lead');
    const e = await api.post('/api/estimates', { lead_id: lead ? Number(lead) : null });
    location.replace('#/calc/' + e.id);
    return;
  }
  if (r.id && r.sub === 'contract') return renderContract(main, Number(r.id));
  if (r.id) return renderEditor(main, Number(r.id));
  return renderList(main);
}

// ---------- список ----------
async function renderList(main) {
  const list = await api.get('/api/estimates');
  main.innerHTML = `<div class="head"><div><h1>Расчёты</h1><p>Калькулятор чернового электромонтажа: замер → три тарифа → КП клиенту</p></div>
    <div class="row"><a class="btn" href="#/calc/params">Расценки и нормы</a><a class="btn p" href="#/calc/new">Новый расчёт</a></div></div>
    ${list.length ? `<div class="card wrap"><table><tr><th>Объект</th><th>Заявка</th><th class="num">Базовый</th><th class="num">Стандарт</th><th class="num">Под ключ</th><th>Изменён</th></tr>
      ${list.map(e => `<tr class="click" data-id="${e.id}"><td><b>${esc(e.title || 'Расчёт')}</b><div class="small mute">${e.summary.area ? num(e.summary.area, 1) + ' м² · ' : ''}${e.summary.points ? num(e.summary.points) + ' точек' : ''}${e.share_token ? ' · <span class="tag act">КП отправлено</span>' : ''}</div></td>
        <td>${e.lead_name ? esc(e.lead_name) : '<span class="mute">—</span>'}</td>
        ${TARIFFS.map(t => `<td class="num ${e.tariff === t ? 'b' : ''}">${e.summary[t] ? fmt(e.summary[t].price) : '—'}</td>`).join('')}
        <td class="small mute">${dateRu(e.updated_at)}</td></tr>`).join('')}</table></div>`
      : emptyState('Расчётов пока нет', 'Нажмите «Новый расчёт» или откройте заявку и начните расчёт из неё — тогда объект и площадь подставятся сами.')}`;
  main.querySelectorAll('tr.click').forEach(tr => tr.onclick = () => location.hash = '#/calc/' + tr.dataset.id);
}

// ---------- редактор ----------
const POINTS = [['sockets', 'Розетки 220 В'], ['lv', 'Слаботочные розетки'], ['switches', 'Выключатели (все типы)'], ['lights', 'Выводы под освещение'], ['out220', 'Выводы 220 В (без силовых)']];
const APPL = [['oven', 'Духовка'], ['hob', 'Варочная панель'], ['dishwasher', 'Посудомойка'], ['washer', 'Стиральная'], ['dryer', 'Сушильная'], ['apron', 'Розетки фартука'], ['fridge', 'СВЧ + холодильник'], ['flow', 'Проточный водонагреватель'], ['boiler', 'Накопительный водонагреватель'], ['neptun', 'Нептун'], ['router', 'Роутер / модем'], ['media', 'Мультимедийный щит']];
const QUICK_ROOMS = [['Комната', 'Спальня'], ['Комната', 'Детская'], ['Гостиная', 'Гостиная'], ['Кухня-гостиная', 'Кухня-гостиная'], ['Кухня', 'Кухня'], ['Прихожая / коридор', 'Прихожая'], ['Санузел', 'Санузел'], ['Гардеробная', 'Гардеробная'], ['Балкон / лоджия', 'Балкон'], ['Другое', '']];

async function renderEditor(main, id) {
  let est = await api.get('/api/estimates/' + id);
  const defs = await api.get('/api/calc/defaults');
  let inp = est.result.inputs;
  let res = est.result;
  let tariff = est.tariff;
  let saveT = null, inflight = 0, dirty = false;
  main.classList.add('calc-main');

  main.innerHTML = `<div class="calc">
    <div class="calc-top">
      <a href="${est.lead_id ? '#/leads/' + est.lead_id : '#/calc'}" class="small">← ${est.lead_id ? esc(est.lead_name || 'заявка') : 'все расчёты'}</a>
      <span class="small mute" data-status>Сохранено</span>
    </div>
    ${est.params_outdated ? `<div class="infobox" data-outdated>Расценки менялись после этого расчёта — он посчитан по ценам на ${dateRu(est.created_at)}. <button class="btn s" data-refresh>Пересчитать по новым</button></div>` : ''}
    <div class="calc-grid">
      <div class="calc-form" data-form></div>
      <aside class="calc-res" data-res></aside>
    </div>
    <div class="calc-bar" data-bar></div>
  </div>`;
  const form = main.querySelector('[data-form]');
  const resEl = main.querySelector('[data-res]');
  const bar = main.querySelector('[data-bar]');
  const status = main.querySelector('[data-status]');

  const setStatus = (t) => { status.textContent = t; };
  const schedule = (delay = 450) => {
    dirty = true; setStatus('Считаю…');
    clearTimeout(saveT); saveT = setTimeout(save, delay);
  };
  async function save() {
    inflight++;
    try {
      const out = await api.put('/api/estimates/' + id, { inputs: inp, tariff });
      est = out; res = out.result; dirty = false;
      drawResults(); drawBar();
      setStatus('Сохранено');
      const pm = form.querySelector('[data-flowmode]'); if (pm) pm.textContent = res.volumes.flow_mode !== '—' ? 'исполнение: ' + res.volumes.flow_mode : '';
      const kh = form.querySelector('[data-kup-hint]'); if (kh) kh.textContent = `по умолчанию = санузлов (${res.volumes.su})`;
      const ki = form.querySelector('input[data-k=kup]'); if (ki) ki.placeholder = String(res.volumes.su);
    } catch (e) { setStatus('Не сохранено'); toast(e.message, true); }
    finally { inflight--; }
  }
  window.onbeforeunload = () => (dirty ? true : undefined);

  // --- поля формы ---
  const numField = (key, label, opts = {}) => `<label class="cf ${opts.wide ? 'wide' : ''}"><span>${esc(label)}</span>
    <span class="stepper-in">${opts.noStep ? '' : `<button type="button" data-dec="${key}" aria-label="меньше">−</button>`}<input type="number" inputmode="${opts.dec ? 'decimal' : 'numeric'}" step="any" min="0" data-k="${key}" value="${inp[key] === null || inp[key] === undefined ? '' : esc(+inp[key] || (opts.blankZero ? '' : 0))}" placeholder="${esc(opts.ph ?? '0')}">${opts.noStep ? '' : `<button type="button" data-inc="${key}" aria-label="больше">+</button>`}</span>
    ${opts.hint ? `<small ${opts.hintAttr || ''}>${esc(opts.hint)}</small>` : ''}</label>`;
  const seg = (key, options) => `<div class="seg2" data-seg="${key}">${options.map(([v, l]) => `<button type="button" data-v="${esc(v)}" class="${String(inp[key]) === String(v) ? 'on' : ''}">${esc(l)}</button>`).join('')}</div>`;
  const chip = (key, label) => `<button type="button" class="chip ${inp[key] ? 'on' : ''}" data-chip="${key}">${esc(label)}</button>`;

  function drawForm() {
    form.innerHTML = `
      <section class="cs"><h3>Объект</h3>
        <label class="cf wide"><span>Объект (адрес / клиент) — попадает в КП</span><input type="text" data-k="object" value="${esc(inp.object)}" placeholder="ЖК, квартира, имя клиента"></label>
        <div class="cf-row">${numField('area', 'Площадь, м²', { dec: true, noStep: true })}${numField('windows', 'Окон и дверей (оклейка)')}</div>
        <div class="toggles">${chip('discount', 'Материал закупаем мы: −20 % на работы')}</div>
      </section>
      <section class="cs"><h3>Точки</h3>
        <div class="cf-grid">${POINTS.map(([k, l]) => numField(k, l)).join('')}${numField('junctions', 'Распредкоробки', { hint: '0 — распайка в подрозетниках' })}</div>
      </section>
      <section class="cs"><h3>Помещения <span class="mute small" data-rooms-count></span></h3>
        <p class="small mute" style="margin:0 0 8px">По помещениям считаются линии света, розеток, тёплые полы, кондиционеры, санузлы и подписи в щите.</p>
        <div data-rooms></div>
        <div class="quick">${QUICK_ROOMS.map(([t, n], i) => `<button type="button" class="chip add" data-addroom="${i}">+ ${esc(n || t)}</button>`).join('')}</div>
      </section>
      <section class="cs"><h3>Щит</h3>
        <div class="cf-line"><span>Ввод</span>${seg('phase', [['3', '3 фазы'], ['1', '1 фаза']])}</div>
        <div class="cf-line"><span>Вводной, А</span>${seg('main_a', [25, 32, 40, 50, 63].map(a => [a, a]))}</div>
        <div class="cf-line"><span>Автоматика</span>${seg('brand', [['Dekraft', 'Dekraft'], ['ABB', 'ABB']])}</div>
        <div class="cf-line"><span>Корпус</span>${seg('case_type', [['flush', 'встраиваемый'], ['surface', 'накладной']])}</div>
        <div class="cf-line"><span>Мастер-выключатель</span>${seg('master', [['none', 'нет'], ['light', 'свет'], ['all', 'свет + розетки']])}</div>
        <div class="cf-row">${numField('kup', 'КУП, шт', { blankZero: true, ph: String(res.volumes.su), hint: `по умолчанию = санузлов (${res.volumes.su})`, hintAttr: 'data-kup-hint' })}</div>
      </section>
      <section class="cs"><h3>Техника — отдельные линии</h3>
        <div class="toggles">${APPL.map(([k, l]) => chip(k, l)).join('')}</div>
        <div class="cf-row" data-lens>
          ${inp.hob ? numField('hob_len', 'Линия варочной панели, м', { noStep: true, dec: true }) : ''}
          ${inp.flow ? numField('flow_len', 'Линия проточника, м', { noStep: true, dec: true, hint: res.volumes.flow_mode !== '—' ? 'исполнение: ' + res.volumes.flow_mode : '', hintAttr: 'data-flowmode' }) : ''}
        </div>
      </section>
      <section class="cs"><h3>Прокладка</h3>
        <div class="cf-line"><span>Штробление</span>${seg('chase', [[true, 'да'], [false, 'нет']])}</div>
        <div class="cf-line"><span>Магистрали</span>${seg('route', [['ceiling', 'по потолку'], ['floor', 'по полу']])}</div>
      </section>
      <details class="cs" ${inp.draw15 || inp.draw25 || inp.cust_cable25 || (inp.extra || []).length ? 'open' : ''}><summary><h3>Кабель по чертежу, материал заказчика, доп. материалы</h3></summary>
        <div class="cf-row">${numField('draw15', 'Кабель 3×1,5 по чертежу, м', { noStep: true, dec: true, hint: '0 — по норме' })}${numField('draw25', 'Кабель 3×2,5 по чертежу, м', { noStep: true, dec: true, hint: '0 — по норме' })}</div>
        <div class="cf-row">${numField('cust_cable25', 'Кабель 3×2,5 заказчика, м', { noStep: true, dec: true, hint: 'вычитается из материалов' })}</div>
        <h4 style="margin:14px 0 6px">Не учтённый материал <span class="small mute">— идёт во все тарифы и в смету</span></h4>
        <div data-extra></div>
        <button type="button" class="btn s" data-addextra>+ строка</button>
      </details>`;
    drawRooms(); drawExtra(); bindForm();
  }

  function drawRooms() {
    const box = form.querySelector('[data-rooms]');
    const rooms = inp.rooms || [];
    form.querySelector('[data-rooms-count]').textContent = rooms.length ? '· ' + rooms.length : '';
    box.innerHTML = rooms.map((r, i) => `<div class="room" data-room="${i}">
      <div class="room-h"><input type="text" value="${esc(r.name)}" placeholder="${esc(r.type || 'Название')}" data-rf="name" aria-label="Название">
        <select data-rf="type" aria-label="Тип">${['', ...defs.room_types].map(t => `<option value="${esc(t)}" ${t === r.type ? 'selected' : ''}>${esc(t || '— тип —')}</option>`).join('')}</select>
        <button type="button" class="x" data-delroom aria-label="Удалить">×</button></div>
      <div class="toggles sm">
        <button type="button" class="chip ${r.sockets ? 'on' : ''} ${['Санузел', 'Кухня'].includes(r.type) ? 'dim' : ''}" data-rt="sockets" title="${['Санузел', 'Кухня'].includes(r.type) ? 'У санузла и кухни своя линия не считается' : ''}">Линия розеток</button>
        <button type="button" class="chip ${r.floor ? 'on' : ''}" data-rt="floor">Тёплый пол</button>
        <button type="button" class="chip ${r.ac ? 'on' : ''}" data-rt="ac">Кондиционер</button>
      </div></div>`).join('') || '<div class="small mute" style="padding:6px 0">Добавьте помещения кнопками ниже.</div>';
    box.querySelectorAll('[data-room]').forEach(el => {
      const i = Number(el.dataset.room);
      el.querySelectorAll('[data-rf]').forEach(f => f.addEventListener(f.tagName === 'SELECT' ? 'change' : 'input', () => {
        inp.rooms[i][f.dataset.rf] = f.value;
        if (f.dataset.rf === 'type') drawRooms();
        schedule();
      }));
      el.querySelectorAll('[data-rt]').forEach(b => b.onclick = () => { inp.rooms[i][b.dataset.rt] = !inp.rooms[i][b.dataset.rt]; b.classList.toggle('on'); schedule(); });
      el.querySelector('[data-delroom]').onclick = () => { inp.rooms.splice(i, 1); drawRooms(); schedule(); };
    });
  }

  function drawExtra() {
    const box = form.querySelector('[data-extra]');
    inp.extra = inp.extra || [];
    box.innerHTML = inp.extra.map((e, i) => `<div class="extra" data-ex="${i}"><input type="text" value="${esc(e.name)}" placeholder="Наименование" data-ef="name">
      <input type="number" step="any" inputmode="decimal" value="${e.qty || ''}" placeholder="Кол-во" data-ef="qty"><input type="number" step="any" inputmode="decimal" value="${e.price || ''}" placeholder="Цена" data-ef="price">
      <button type="button" class="x" data-delex aria-label="Удалить">×</button></div>`).join('');
    box.querySelectorAll('[data-ex]').forEach(el => {
      const i = Number(el.dataset.ex);
      el.querySelectorAll('[data-ef]').forEach(f => f.addEventListener('input', () => { inp.extra[i][f.dataset.ef] = f.dataset.ef === 'name' ? f.value : (f.value === '' ? 0 : Number(f.value)); schedule(); }));
      el.querySelector('[data-delex]').onclick = () => { inp.extra.splice(i, 1); drawExtra(); schedule(); };
    });
  }

  function bindForm() {
    form.querySelectorAll('input[data-k]').forEach(el => el.addEventListener('input', () => {
      const k = el.dataset.k;
      if (el.type === 'number') inp[k] = el.value === '' ? (['kup', 'hob_len', 'flow_len'].includes(k) ? null : 0) : Number(el.value);
      else inp[k] = el.value;
      schedule();
    }));
    const step = (k, d) => {
      const el = form.querySelector(`input[data-k="${k}"]`);
      const base = el.value === '' ? (k === 'kup' ? res.volumes.su : 0) : Number(el.value);
      const v = Math.max(0, base + d);
      el.value = v; inp[k] = v; schedule();
    };
    form.querySelectorAll('[data-inc]').forEach(b => b.onclick = () => step(b.dataset.inc, 1));
    form.querySelectorAll('[data-dec]').forEach(b => b.onclick = () => step(b.dataset.dec, -1));
    form.querySelectorAll('[data-seg]').forEach(s => s.querySelectorAll('button').forEach(b => b.onclick = () => {
      const k = s.dataset.seg; let v = b.dataset.v;
      if (v === 'true') v = true; else if (v === 'false') v = false; else if (k === 'main_a') v = Number(v);
      inp[k] = v;
      if (k === 'phase') { inp.main_a = v === '1' ? 50 : 32; drawForm(); }
      s.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      schedule(150);
    }));
    form.querySelectorAll('[data-chip]').forEach(b => b.onclick = () => {
      const k = b.dataset.chip; inp[k] = !inp[k]; b.classList.toggle('on', inp[k]);
      if (k === 'hob' || k === 'flow') { const y = window.scrollY; drawForm(); window.scrollTo(0, y); }
      schedule(150);
    });
    form.querySelectorAll('[data-addroom]').forEach(b => b.onclick = () => {
      const [type, name] = QUICK_ROOMS[Number(b.dataset.addroom)];
      const same = name ? (inp.rooms || []).filter(r => r.name === name || (r.name || '').startsWith(name + ' ')).length : 0;
      const nm = same ? `${name} ${same + 1}` : name;
      const living = ['Комната', 'Гостиная', 'Кухня-гостиная'].includes(type);
      inp.rooms = [...(inp.rooms || []), { name: nm, type, sockets: living, floor: false, ac: false }];
      drawRooms(); schedule();
    });
    form.querySelector('[data-addextra]').onclick = () => { inp.extra.push({ name: '', qty: 1, price: 0 }); drawExtra(); };
  }

  // --- итоги ---
  function drawResults() {
    const T = res.tariffs, K = res.kp, v = res.volumes;
    const t = T[tariff];
    const pn = res.panel[tariff === 'basic' ? 'basic' : 'std'];
    const mg = res.margin[tariff === 'basic' ? 'basic' : 'std'];
    resEl.innerHTML = `
      <div class="tcards">${TARIFFS.map(k => `<button type="button" class="tcard ${k === tariff ? 'on' : ''}" data-t="${k}">
        <span>${TN[k]}</span><b>${fmt(K[k].price)}</b><small>${num(K[k].per_m2)} ₽/м² · точно ${fmt(T[k].price)}</small></button>`).join('')}</div>
      ${res.warnings.length ? `<div class="warnbox">${res.warnings.map(esc).join('<br>')}</div>` : ''}
      <div class="card pad" style="margin-top:12px">
        <h3 style="margin:0 0 8px">${TN[tariff]}: из чего цена</h3>
        <dl class="dl2">
          <dt>Работы без щита</dt><dd>${fmt(t.works_nopanel)}</dd>
          <dt>Сборка щита (${num(t.panel_nominal)} мод.)</dt><dd>${fmt(t.assembly)}</dd>
          ${t.surcharge ? `<dt>Надбавка за фикс. цену (${Math.round(t.surcharge_pct * 100)} %)</dt><dd>${fmt(t.surcharge)}</dd>` : ''}
          ${t.finishing ? `<dt>Чистовая установка</dt><dd>${fmt(t.finishing)}</dd>` : ''}
          <dt class="b">Работы итого</dt><dd class="b">${fmt(t.works_total)}</dd>
          <dt>Материалы без щита</dt><dd>${fmt(t.materials_nopanel)}</dd>
          <dt>Щит: автоматика ${esc(res.inputs.brand)} + корпус</dt><dd>${fmt(t.materials_panel)}</dd>
          <dt class="b">Материалы итого</dt><dd class="b">${fmt(t.materials_total)}</dd>
          ${t.taping ? `<dt>Оклейка окон и дверей</dt><dd>${fmt(t.taping)}</dd>` : ''}
          ${t.trash ? `<dt>Вывоз мусора</dt><dd>${fmt(t.trash)}</dd>` : ''}
          <dt class="b">Цена для клиента</dt><dd class="b">${fmt(t.price)}</dd>
        </dl>
        <div class="small mute" style="margin-top:8px">Щит: занято ${esc(pn.case_text)} — только для вас, в КП не идёт.</div>
        ${mg.lines ? `<div class="small" style="margin-top:6px">Материалы, привязанные к складу (${mg.lines} поз.): клиенту ${fmt(mg.revenue)}, себестоимость ${fmt(mg.cost)}, <b class="ok">наценка ${fmt(mg.profit)}</b></div>` : ''}
      </div>
      <details class="card pad" style="margin-top:12px"><summary><b>Объёмы</b> <span class="small mute">${num(v.points)} точек · кабель ${num(v.cable_power)} м</span></summary>
        <dl class="dl2" style="margin-top:8px">
          <dt>Кабель 3×1,5</dt><dd>${num(v.cable15, 1)} м</dd><dt>Кабель 3×2,5</dt><dd>${num(v.cable25, 1)} м</dd>
          ${v.cable54 ? `<dt>Кабель 5×4</dt><dd>${num(v.cable54, 1)} м</dd>` : ''}${v.cable36 ? `<dt>Кабель 3×6</dt><dd>${num(v.cable36, 1)} м</dd>` : ''}
          <dt>Спуски</dt><dd>${num(v.drops, 1)} м</dd><dt>В гофре</dt><dd>${num(v.in_corr, 1)} м</dd>
          <dt>Подрозетников</dt><dd>${num(v.boxes)}</dd><dt>Витая пара</dt><dd>${num(v.twisted)} м</dd>
          <dt>Помещений / розеточных линий</dt><dd>${num(v.rooms_total)} / ${num(v.sock_lines)}</dd>
          <dt>Санузлов / КУП / тёплых полов / кондиционеров</dt><dd>${num(v.su)} / ${num(v.kup)} / ${num(v.tp)} / ${num(v.ac)}</dd>
        </dl></details>`;
    resEl.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { tariff = b.dataset.t; drawResults(); drawBar(); schedule(100); });
  }

  function drawBar() {
    bar.innerHTML = `<div class="bar-prices">${TARIFFS.map(k => `<button type="button" class="${k === tariff ? 'on' : ''}" data-t="${k}"><span>${TN[k]}</span><b>${fmt(res.kp[k].price)}</b></button>`).join('')}</div>
      <div class="bar-acts">
        <button type="button" class="btn p" data-doc="kp">КП</button>
        <button type="button" class="btn" data-doc="smeta">Смета</button>
        <button type="button" class="btn" data-doc="panel">Щит</button>
        <button type="button" class="btn" data-share>Отправить КП</button>
        <button type="button" class="btn" data-contract>Договор</button>
        <button type="button" class="btn" data-more aria-label="Ещё">⋯</button>
      </div>`;
    bar.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { tariff = b.dataset.t; drawResults(); drawBar(); schedule(100); });
    bar.querySelectorAll('[data-doc]').forEach(b => b.onclick = () => openDoc(id, b.dataset.doc, tariff, flush));
    bar.querySelector('[data-share]').onclick = () => shareKp(id, est, flush);
    bar.querySelector('[data-more]').onclick = () => moreMenu();
    bar.querySelector('[data-contract]').onclick = async () => { await flush(); location.hash = `#/calc/${id}/contract`; };
  }

  async function flush() {
    if (dirty || inflight) { clearTimeout(saveT); await save(); }
  }

  function moreMenu() {
    const m = openModal(`<h2>${esc(est.title || 'Расчёт')}</h2>
      <div class="big">
        ${est.lead_id ? `<button data-a="tolead">Записать сумму КП в заявку (${TN[tariff]}, ${fmt(res.kp[tariff].price)})</button>` : `<button data-a="link">Привязать к заявке</button>`}
        <button data-a="copy">Сделать копию расчёта</button>
        ${est.share_token ? '<button data-a="unshare">Отключить ссылку на КП</button>' : ''}
        <button data-a="refresh">Пересчитать по текущим расценкам</button>
        <button data-a="del" style="color:var(--danger)">Удалить расчёт</button>
      </div><div class="actions"><button class="btn" data-cancel>Закрыть</button></div>`);
    m.querySelector('[data-cancel]').onclick = closeModal;
    m.querySelectorAll('[data-a]').forEach(b => b.onclick = async () => {
      const a = b.dataset.a;
      try {
        await flush();
        if (a === 'tolead') { const r = await api.post(`/api/estimates/${id}/to-lead`, {}); closeModal(); toast(`В заявку записано: ${r.tariff}, ${fmt(r.offer_sum)}`); }
        if (a === 'copy') { const c = await api.post(`/api/estimates/${id}/copy`, {}); closeModal(); location.hash = '#/calc/' + c.id; }
        if (a === 'unshare') { await api.del(`/api/estimates/${id}/share`); est.share_token = null; closeModal(); toast('Ссылка отключена — клиент её больше не откроет'); }
        if (a === 'refresh') { const out = await api.put('/api/estimates/' + id, { inputs: inp, tariff, refresh_params: true }); est = out; res = out.result; closeModal(); main.querySelector('[data-outdated]')?.remove(); drawResults(); drawBar(); toast('Пересчитано по текущим расценкам'); }
        if (a === 'del') confirmModal('Удалить расчёт? Ссылка на КП перестанет работать.', async () => { await api.del('/api/estimates/' + id); window.onbeforeunload = null; location.hash = est.lead_id ? '#/leads/' + est.lead_id : '#/calc'; }, 'Удалить');
        if (a === 'link') linkLead();
      } catch (e) { toast(e.message, true); }
    });
  }

  async function linkLead() {
    const leads = await api.get('/api/leads?include_closed=false');
    const m = openModal(`<h2>Привязать к заявке</h2><div class="field"><label>Заявка</label>${comboHtml('lead', { placeholder: '— выбрать заявку —' })}</div>
      <div class="actions"><button class="btn" data-cancel>Отмена</button><button class="btn p" data-ok>Привязать</button></div>`);
    const combo = mountCombo(m.querySelector('[data-combo]'), { options: leads.map(l => ({ value: l.id, label: l.name, sub: l.address || '' })) });
    m.querySelector('[data-cancel]').onclick = closeModal;
    m.querySelector('[data-ok]').onclick = async () => {
      const lid = Number(m.querySelector('input[name=lead]').value); if (!lid) return;
      est = await api.put('/api/estimates/' + id, { lead_id: lid }); closeModal(); toast('Привязано'); renderEditor(main, id);
    };
    void combo;
  }

  main.querySelector('[data-refresh]')?.addEventListener('click', async () => {
    const out = await api.put('/api/estimates/' + id, { inputs: inp, tariff, refresh_params: true });
    est = out; res = out.result; main.querySelector('[data-outdated]').remove(); drawResults(); drawBar(); toast('Пересчитано по текущим расценкам');
  });

  drawForm(); drawResults(); drawBar();
}

// ---------- документы ----------
async function openDoc(id, kind, tariff, flush) {
  await flush();
  const titles = { kp: 'КП', smeta: 'Смета', panel: 'Щит для монтажника' };
  const ov = document.createElement('div');
  ov.className = 'docview';
  ov.innerHTML = `<div class="docbar"><button class="btn s" data-close>← Назад</button><b>${titles[kind]}</b>
    ${kind !== 'kp' ? `<div class="seg2 sm">${TARIFFS.map(t => `<button type="button" data-t="${t}" class="${t === tariff ? 'on' : ''}">${TN[t]}</button>`).join('')}</div>` : ''}
    <button class="btn s p" data-print>Печать / PDF</button></div><iframe title="${titles[kind]}"></iframe>`;
  document.body.appendChild(ov);
  document.body.style.overflow = 'hidden';
  const frame = ov.querySelector('iframe');
  const load = async (t) => { frame.srcdoc = await api.get(`/api/estimates/${id}/doc/${kind}?tariff=${t}`); };
  await load(tariff);
  ov.querySelectorAll('[data-t]').forEach(b => b.onclick = () => { ov.querySelectorAll('[data-t]').forEach(x => x.classList.toggle('on', x === b)); load(b.dataset.t); });
  ov.querySelector('[data-print]').onclick = () => frame.contentWindow.print();
  ov.querySelector('[data-close]').onclick = () => { ov.remove(); document.body.style.overflow = ''; };
}

async function shareKp(id, est, flush) {
  await flush();
  let r;
  try { r = await api.post(`/api/estimates/${id}/share`, {}); } catch (e) { return toast(e.message, true); }
  est.share_token = r.token;
  const url = location.origin + r.url;
  const text = 'Коммерческое предложение ВольтЛиния — электромонтаж' + (est.title ? ': ' + est.title : '');
  const m = openModal(`<h2>КП для клиента</h2>
    <p class="small mute" style="margin:6px 0 10px">Клиент откроет ссылку с телефона без входа. Цены зафиксированы на момент расчёта; если поменяете расчёт — по ссылке будет новая версия.</p>
    <div class="field"><input type="text" readonly value="${esc(url)}" data-url></div>
    <div class="big">
      ${navigator.share ? '<button class="p" data-a="share">Отправить… (WhatsApp, Telegram, MAX)</button>' : ''}
      <button data-a="copy">Скопировать ссылку</button>
      <button data-a="open">Открыть как клиент</button>
    </div><div class="actions"><button class="btn" data-cancel>Готово</button></div>`);
  m.querySelector('[data-cancel]').onclick = closeModal;
  m.querySelectorAll('[data-a]').forEach(b => b.onclick = async () => {
    if (b.dataset.a === 'share') { try { await navigator.share({ title: 'КП ВольтЛиния', text, url }); } catch { /* отменено */ } }
    if (b.dataset.a === 'copy') { try { await navigator.clipboard.writeText(url); toast('Ссылка скопирована'); } catch { m.querySelector('[data-url]').select(); toast('Выделите и скопируйте ссылку'); } }
    if (b.dataset.a === 'open') window.open(url, '_blank');
  });
}

// ---------- справочник ----------
async function renderParams(main) {
  const [data, products] = await Promise.all([api.get('/api/calc/params'), api.get('/api/stock/products')]);
  const pOpts = products.filter(p => p.is_active !== false).map(p => ({ value: p.id, label: p.name, sub: p.client_price ? fmt(p.client_price) : 'без цены клиенту' }));
  const isPct = (it) => (it.unit || '').startsWith('%');
  const show = (v, it) => v === null || v === undefined ? '' : (isPct(it) ? +(v * 100).toFixed(4) : v);
  const checks = data.sections.flatMap(s => s.items.filter(it => it.check));
  const onlyCheck = renderParams.onlyCheck && checks.length;
  main.innerHTML = `<div class="head"><div><h1>Расценки и нормы калькулятора</h1><p>Перенесены с листа «Расценки». Меняются здесь — новые расчёты считаются по новым значениям, сохранённые КП не меняются.</p></div>
    <div class="row"><a class="btn" href="#/calc">← Расчёты</a></div></div>
    ${checks.length ? `<div class="infobox warn"><b>Требуют проверки: ${checks.length}</b> — значения, которые в Excel были помечены «ПРОВЕРИТЬ». Если цифра верная — нажмите «Верно»; если нет — исправьте её, отметка снимется сама.
      <button class="btn s" data-only>${onlyCheck ? 'Показать все строки' : 'Показать только их'}</button></div>` : ''}
    <div class="infobox">Цены материалов, автоматики и корпусов можно привязать к позиции склада: если у позиции задана цена клиенту, калькулятор возьмёт её, а в расчёте появится наценка по себестоимости.</div>
    ${data.sections.map(sec => ({ ...sec, items: onlyCheck ? sec.items.filter(it => it.check) : sec.items })).filter(sec => sec.items.length).map(sec => sec.section === 'contractor' ? `<div class="card wrap" style="margin-top:14px"><h3 style="padding:12px 14px 0;margin:0">${esc(sec.title)}</h3>
      <p class="small mute" style="padding:4px 14px 0;margin:0">Подставляются в раздел «Реквизиты сторон» договора. Хранятся только в CRM.</p>
      <table class="params">${sec.items.map(it => `<tr><td>${esc(it.label)}</td><td><input type="text" class="txt" data-key="${it.key}" data-col="vtext" value="${esc(it.vtext || '')}"></td></tr>`).join('')}</table></div>` : `<div class="card wrap" style="margin-top:14px"><h3 style="padding:12px 14px 0;margin:0">${esc(sec.title)}</h3>
      <table class="params"><tr><th>Позиция</th>${sec.cols.map(c => `<th class="num">${esc(c)}</th>`).join('')}<th>Ед.</th><th>Склад</th></tr>
      ${sec.items.map(it => {
        const cols = ['v1', 'v2', 'v3'].slice(0, sec.cols.length);
        const linkByCol = Object.fromEntries((it.links || []).map(l => [l.col, l]));
        const cells = it.key === 'general.brand'
          ? `<td><select data-key="${it.key}" data-col="vtext"><option ${it.vtext === 'Dekraft' ? 'selected' : ''}>Dekraft</option><option ${it.vtext === 'ABB' ? 'selected' : ''}>ABB</option></select></td>`
          : cols.map(c => {
            const l = linkByCol[c];
            const overridden = l && l.product_price !== null && l.product_price !== undefined;
            return `<td class="num"><input type="number" step="any" inputmode="decimal" data-key="${it.key}" data-col="${c}" data-pct="${isPct(it) ? 1 : ''}" value="${show(it[c], it)}" ${overridden ? 'disabled title="Цена берётся со склада"' : ''}>${overridden ? `<div class="small ok">${fmt(l.product_price)} со склада</div>` : ''}</td>`;
          }).join('');
        const links = (it.links || []).map(l => `<div class="small">${sec.section === 'auto' ? (l.col === 'v1' ? 'Dekraft: ' : 'ABB: ') : ''}${l.product_id ? `${esc(l.product_name)} <button class="btn s" data-unlink="${it.key}" data-f="${l.field}">×</button>` : `<button class="btn s" data-link="${it.key}" data-f="${l.field}">привязать</button>`}</div>`).join('');
        return `<tr class="${it.check ? 'chk' : ''}"><td>${esc(it.label)}${it.note ? `<div class="small mute">${it.check ? '<span class="chk-tag">проверить</span>' : ''}${esc(it.note)}</div>` : ''}${it.check ? `<button class="btn s" data-confirm="${it.key}" style="margin-top:4px">Верно</button>` : ''}</td>${cells}<td class="small mute">${esc(isPct(it) ? '%' : (it.unit || ''))}</td><td>${links}</td></tr>`;
      }).join('')}</table></div>`).join('')}`;
  main.querySelectorAll('input[data-key], select[data-key]').forEach(el => el.addEventListener('change', async () => {
    const body = {};
    if (el.dataset.col === 'vtext') body.vtext = el.value;
    else body[el.dataset.col] = el.value === '' ? null : (el.dataset.pct ? Number(el.value) / 100 : Number(el.value));
    try {
      await api.patch('/api/calc/params/' + el.dataset.key, body); toast('Сохранено');
      if (el.closest('tr')?.classList.contains('chk')) renderParams(main);
    } catch (e) { toast(e.message, true); }
  }));
  main.querySelector('[data-only]')?.addEventListener('click', () => { renderParams.onlyCheck = !onlyCheck; renderParams(main); });
  main.querySelectorAll('[data-confirm]').forEach(b => b.onclick = async () => {
    try { await api.patch('/api/calc/params/' + b.dataset.confirm, { confirm: true }); toast('Отмечено как проверенное'); renderParams(main); } catch (e) { toast(e.message, true); }
  });
  main.querySelectorAll('[data-unlink]').forEach(b => b.onclick = async () => { await api.patch('/api/calc/params/' + b.dataset.unlink, { unlink: [b.dataset.f] }); renderParams(main); });
  main.querySelectorAll('[data-link]').forEach(b => b.onclick = () => {
    const m = openModal(`<h2>Привязать к позиции склада</h2><p class="small mute">Цена клиенту будет браться из карточки позиции на складе.</p>
      <div class="field">${comboHtml('pid', { placeholder: '— позиция склада —' })}</div>
      <div class="actions"><button class="btn" data-cancel>Отмена</button><button class="btn p" data-ok>Привязать</button></div>`);
    mountCombo(m.querySelector('[data-combo]'), { options: pOpts });
    m.querySelector('[data-cancel]').onclick = closeModal;
    m.querySelector('[data-ok]').onclick = async () => {
      const pid = Number(m.querySelector('input[name=pid]').value); if (!pid) return;
      try { await api.patch('/api/calc/params/' + b.dataset.link, { [b.dataset.f]: pid }); closeModal(); toast('Привязано'); renderParams(main); } catch (e) { toast(e.message, true); }
    };
  });
}

// ---------- договор ----------
const DATE_FIELDS = new Set(['date', 'start', 'end', 'birth', 'pass_date']);
const WIDE = new Set(['address', 'pass_issued', 'reg_address', 'org_name', 'legal_address', 'signer', 'bank']);
const PH = { number: 'например, 1611/26', address: 'индекс, город, улица, дом, корпус, квартира', pass_issued: 'как в паспорте', pass_code: '000-000',
  reg_address: 'как в штампе о регистрации', signer: 'генерального директора Иванова Ивана Ивановича', basis: 'Устава / записи в ЕГРИП',
  sign_name: 'Иванов И.И.', phone: '+7 …', org_phone: '+7 …' };

async function authFetch(url) {
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + localStorage.getItem('token') } });
  if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail || d; } catch {} throw new Error(d); }
  return r.blob();
}

async function saveFile(url, name, share = false) {
  const blob = await authFetch(url);
  const file = new File([blob], name, { type: blob.type });
  if (share && navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: name }); return; } catch (e) { if (e.name === 'AbortError') return; }
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
}

async function renderContract(main, id) {
  let st = await api.get(`/api/estimates/${id}/contract`);
  let data = st.data;
  const ocr = new Set();       // поля, подставленные распознаванием (подсвечены до правки)
  let saveT = null, dirty = false;
  main.classList.add('calc-main');
  main.innerHTML = `<div class="calc contract">
    <div class="calc-top"><a href="#/calc/${id}" class="small">← к расчёту</a><span class="small mute" data-status>${st.saved ? 'Сохранено' : 'Новый договор'}</span></div>
    <h1 style="margin:4px 0 2px">Договор подряда</h1><p class="small mute" style="margin:0 0 12px">${esc(st.title || 'Расчёт')} · от ИП Клемань К. В.</p>
    <div data-body></div>
    <div class="calc-bar" data-bar></div>
  </div>`;
  const body = main.querySelector('[data-body]');
  const bar = main.querySelector('[data-bar]');
  const status = main.querySelector('[data-status]');
  window.onbeforeunload = () => (dirty ? true : undefined);

  const schedule = (delay = 600) => { dirty = true; status.textContent = 'Сохраняю…'; clearTimeout(saveT); saveT = setTimeout(save, delay); };
  async function save(tariff) {
    try {
      st = await api.put(`/api/estimates/${id}/contract`, { data, tariff });
      dirty = false; status.textContent = 'Сохранено';
      drawSums(); drawMissing(); drawBar();
    } catch (e) { status.textContent = 'Не сохранено'; toast(e.message, true); }
  }
  async function flush() { if (dirty) { clearTimeout(saveT); await save(); } }

  const field = ([k, label]) => {
    const v = data[k] ?? '';
    const type = DATE_FIELDS.has(k) ? 'date' : (k === 'email' || k === 'org_email' ? 'email' : (k === 'phone' || k === 'org_phone' ? 'tel' : 'text'));
    return `<label class="cf ${WIDE.has(k) ? 'wide' : ''} ${ocr.has(k) ? 'ocr' : ''}"><span>${esc(label)}</span>
      <input type="${type}" data-f="${k}" value="${esc(v)}" placeholder="${esc(PH[k] || '')}" ${k === 'pass_series' || k === 'pass_number' || k === 'inn' || k === 'ogrn' || k === 'bik' ? 'inputmode="numeric"' : ''}></label>`;
  };

  function draw() {
    const kind = data.kind || 'person';
    const common = st.fields.common.filter(([k]) => k !== 'advance');
    body.innerHTML = `
      <section class="cs ocr-box"><h3>Распознать документ</h3>
        <p class="small mute" style="margin:0 0 10px">Сфотографируйте разворот паспорта с фото${kind === 'person' ? ' и страницу с пропиской' : ''} или карточку реквизитов ИП/ООО — данные подставятся в договор. Можно выбрать до 4 фото сразу. Фото не сохраняется, распознаёт Яндекс (данные остаются в России).</p>
        ${st.ocr_ready ? `<label class="btn p upl">Фото документа<input type="file" accept="image/*" multiple data-ocr hidden></label> <span class="small mute" data-ocr-status></span>`
          : `<div class="infobox">Распознавание пока не подключено: на сервере нужен ключ Yandex Vision (YANDEX_VISION_API_KEY и YANDEX_FOLDER_ID в .env). Поля можно заполнить вручную.</div>`}
      </section>
      <section class="cs"><h3>Договор</h3>
        <div class="cf-line"><span>Тариф</span><div class="seg2" data-tariff>${TARIFFS.map(t => `<button type="button" data-v="${t}" class="${st.tariff === t ? 'on' : ''}">${TN[t]}</button>`).join('')}</div></div>
        <div class="cf-grid">${common.map(field).join('')}</div>
        <div data-sums></div>
      </section>
      <section class="cs"><h3>Заказчик</h3>
        <div class="cf-line"><span>Кто заказчик</span><div class="seg2" data-kind><button type="button" data-v="person" class="${kind === 'person' ? 'on' : ''}">Физлицо</button><button type="button" data-v="org" class="${kind === 'org' ? 'on' : ''}">ИП или ООО</button></div></div>
        <div class="cf-grid">${(kind === 'person' ? st.fields.person : st.fields.org).map(field).join('')}</div>
      </section>
      <div data-missing></div>`;
    body.querySelectorAll('input[data-f]').forEach(el => el.addEventListener('input', () => {
      data[el.dataset.f] = el.value; ocr.delete(el.dataset.f); el.closest('.cf')?.classList.remove('ocr'); schedule();
    }));
    body.querySelectorAll('[data-tariff] button').forEach(b => b.onclick = async () => {
      body.querySelectorAll('[data-tariff] button').forEach(x => x.classList.toggle('on', x === b));
      clearTimeout(saveT); await save(b.dataset.v);
    });
    body.querySelectorAll('[data-kind] button').forEach(b => b.onclick = () => { data.kind = b.dataset.v; draw(); schedule(100); });
    const up = body.querySelector('[data-ocr]');
    if (up) up.onchange = () => recognize([...up.files]);
    drawSums(); drawMissing();
  }

  function drawSums() {
    const n = st.numbers;
    const el = body.querySelector('[data-sums]'); if (!el) return;
    el.innerHTML = `<dl class="dl2 sums">
      <dt>Цена договора</dt><dd><b>${fmt(n.price)}</b>${n.tariff === 'basic' ? ' <span class="small mute">ориентировочно, по факту</span>' : ''}</dd>
      <dt>Аванс</dt><dd><input type="number" inputmode="numeric" data-adv value="${data.advance ?? ''}" placeholder="${n.advance_default}"> <span class="small mute">по умолчанию — материалы, до тысяч</span></dd>
      ${n.stage2 ? `<dt>Этап 2 (чистовая)</dt><dd>${fmt(n.stage2)} <span class="small mute">до ${n.mech} шт.</span></dd>` : ''}
      <dt>Окончательный расчёт</dt><dd>${fmt(n.rest)}</dd>
      <dt>Гарантия</dt><dd>${n.guarantee} мес.</dd>
      <dt>Бесплатных изменений</dt><dd>${n.limit || '—'}</dd>
      <dt>Автоматика</dt><dd>${esc(n.brand)}</dd></dl>`;
    const adv = el.querySelector('[data-adv]');
    adv.oninput = () => { data.advance = adv.value === '' ? null : Number(adv.value); schedule(); };
  }

  function drawMissing() {
    const el = body.querySelector('[data-missing]'); if (!el) return;
    el.innerHTML = st.missing.length ? `<div class="infobox warn"><b>Не заполнено</b> — в документах останутся пропуски «[___]», их можно вписать от руки:<br>${st.missing.map(esc).join(' · ')}
      ${st.missing.some(x => x.startsWith('Реквизиты исполнителя')) ? '<br><a href="#/calc/params">Реквизиты исполнителя — в «Расценках», внизу страницы</a>' : ''}</div>` : '<div class="infobox ok">Все поля заполнены.</div>';
  }

  async function recognize(files) {
    if (!files.length) return;
    const s = body.querySelector('[data-ocr-status]');
    s.textContent = 'Распознаю…';
    const form = new FormData(); files.slice(0, 4).forEach(f => form.append('files', f));
    try {
      const r = await api.upload('/api/contract/recognize', form);
      const f = r.fields || {};
      if (f.kind) data.kind = f.kind;
      let n = 0;
      for (const [k, v] of Object.entries(f)) { if (k !== 'kind' && v) { data[k] = v; ocr.add(k); n++; } }
      draw(); schedule(100);
      const what = { passport: 'паспорт', registration: 'прописка', org: 'реквизиты', unknown: 'не распознано' };
      body.querySelector('[data-ocr-status]').textContent = n ? `Подставлено полей: ${n} (${r.kinds.map(k => what[k]).join(', ')}) — проверьте подсвеченные` : 'Данных не нашлось';
      if (!n && r.text) openModal(`<h2>Распознанный текст</h2><p class="small mute">Поля определить не удалось — скопируйте нужное вручную.</p><pre class="ocr-text">${esc(r.text)}</pre><div class="actions"><button class="btn" data-cancel>Закрыть</button></div>`).querySelector('[data-cancel]').onclick = closeModal;
    } catch (e) { s.textContent = ''; toast(e.message, true); }
  }

  function drawBar() {
    bar.innerHTML = `<div class="bar-prices"><span class="small mute">${TN[st.tariff]} · ${fmt(st.numbers.price)}</span></div>
      <div class="bar-acts">
        <button type="button" class="btn p" data-zip>Скачать пакет</button>
        <button type="button" class="btn" data-one>Файлы по одному</button>
        ${st.lead_id ? '<button type="button" class="btn" data-lead>В документы заявки</button>' : ''}
      </div>`;
    bar.querySelector('[data-zip]').onclick = async () => {
      try { await flush(); await saveFile(`/api/estimates/${id}/contract/files`, `Договор_${(data.number || id).toString().replace(/[^\wа-яё-]+/gi, '-')}.zip`, true); } catch (e) { toast(e.message, true); }
    };
    bar.querySelector('[data-one]').onclick = async () => {
      await flush();
      const list = await api.get(`/api/estimates/${id}/contract/list`);
      const m = openModal(`<h2>Документы</h2><p class="small mute">Word и Excel — открываются на iPad в «Файлах», печать оттуда.</p>
        <div class="big">${list.map(f => `<button data-n="${esc(f.name)}">${esc(f.title)} <span class="small mute">${f.name.endsWith('.xlsx') ? 'Excel' : 'Word'}</span></button>`).join('')}</div>
        <div class="actions"><button class="btn" data-cancel>Закрыть</button></div>`);
      m.querySelector('[data-cancel]').onclick = closeModal;
      m.querySelectorAll('[data-n]').forEach(b => b.onclick = async () => {
        try { await saveFile(`/api/estimates/${id}/contract/files?name=${encodeURIComponent(b.dataset.n)}`, b.dataset.n, true); } catch (e) { toast(e.message, true); }
      });
    };
    bar.querySelector('[data-lead]')?.addEventListener('click', async () => {
      try { await flush(); const r = await api.post(`/api/estimates/${id}/contract/to-lead`, {}); toast(`В заявку сохранено файлов: ${r.count}`); } catch (e) { toast(e.message, true); }
    });
  }

  draw(); drawBar();
}
