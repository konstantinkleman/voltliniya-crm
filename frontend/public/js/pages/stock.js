import { api } from '../api.js';
import { stockIssueModal } from './stockissue.js';
import { esc, fmt, num, dateRu, toast, openDrawer, closeDrawer, openModal, closeModal, formModal, confirmModal, emptyState, today, comboHtml, mountCombo } from '../ui.js';

let S, D, whs = [], cats = [], prods = [], whSel = null, catSel = null, query = '';

const catName = (id) => (cats.find(c => c.id === id) || {}).name || '';
const catChildren = (pid) => cats.filter(c => c.parent_id === pid);
const catSubtree = (id) => { const ids = new Set([id]); let ch = true; while (ch) { ch = false; for (const c of cats) if (ids.has(c.parent_id) && !ids.has(c.id)) { ids.add(c.id); ch = true; } } return ids; };
const unitOpts = ['м', 'шт', 'упак', 'кг', 'компл'].map(u => ({ value: u, label: u }));

export async function render(main, r, state) {
  S = state; D = state.dicts;
  [whs, cats] = await Promise.all([api.get('/api/stock/warehouses'), api.get('/api/stock/categories')]);
  if (r.q.get('wh')) whSel = Number(r.q.get('wh'));
  if (!whs.find(w => w.id === whSel)) whSel = whs[0]?.id || null;
  prods = await api.get('/api/stock/products' + (whSel ? '?warehouse_id=' + whSel : ''));
  const wh = whs.find(w => w.id === whSel);
  const total = whs.reduce((a, w) => a + Number(w.value), 0);
  const list = prods.filter(p => (!catSel || catSubtree(catSel).has(p.category_id)) && (!query || p.name.toLowerCase().includes(query.toLowerCase())));
  const inStock = list.filter(p => Number(p.total_qty) > 0), noStock = list.filter(p => Number(p.total_qty) <= 0);

  main.innerHTML = `<div class="head"><div><h1>Склад</h1><p>У каждого прораба свой склад; приход проводит директор. Остатки считаются проводками</p></div>
    <div class="row"><button class="btn" data-cats>Категории</button><button class="btn" data-newprod>Новая позиция</button><button class="btn" data-adjust>Инвентаризация</button><button class="btn" data-transfer>Переместить</button><button class="btn p" data-receipt>Приход</button></div></div>
  <div class="row sp" style="margin-bottom:14px"><div class="seg">${whs.map(w => `<button class="${w.id === whSel ? 'on' : ''}" data-wh="${w.id}">${esc(w.name)}${w.pending_in ? ` <span class="tag warn">в пути ${w.pending_in}</span>` : ''}</button>`).join('')}<button data-newwh title="Новый склад">+</button></div>
    <input class="btn" data-q placeholder="Поиск по названию" value="${esc(query)}" style="min-width:220px"></div>
  ${wh ? `<div class="grid g4" style="margin-bottom:14px">
    <div class="card pad kpi"><div class="l">${esc(wh.name)}${wh.foreman_name ? ' · ' + esc(wh.foreman_name) : ''}</div><div class="v num">${fmt(wh.value)}</div><div class="d">${wh.positions} позиций по средней себестоимости</div></div>
    <div class="card pad kpi"><div class="l">Все склады</div><div class="v num">${fmt(total)}</div><div class="d">${whs.length} ${whs.length === 1 ? 'склад' : 'склада'}</div></div>
    <div class="card pad kpi"><div class="l">Ниже минимума</div><div class="v num ${wh.low ? 'warn' : ''}">${wh.low}</div><div class="d">пора докупить на этот склад</div></div>
    <div class="card pad kpi"><div class="l">В пути</div><div class="v num">${wh.pending_in}</div><div class="d">${wh.pending_in ? '<a href="#" data-pending>подтвердить получение</a>' : 'перемещений нет'}</div></div></div>` : ''}
  <div class="wh"><div class="card pad tree">
    <button class="${!catSel ? 'on' : ''}" data-cat="">Все позиции<span class="c">${prods.length}</span></button>
    ${renderTree(null, 0)}
    <button class="l1" style="color:var(--act)" data-newcat>+ категория</button></div>
   <div class="card wrap">${list.length ? `<table><tr><th>Позиция</th><th class="r">Остаток</th><th class="r">Себест.</th><th class="r">Клиенту</th><th class="r">Стоимость</th><th></th></tr>
    ${[...inStock, ...noStock].map(p => { const st = whSel ? (p.stock[whSel] || {}) : null; const qty = st ? Number(st.qty || 0) : Number(p.total_qty); const low = p.min_qty && qty < Number(p.min_qty);
      return `<tr class="${low ? 'low' : ''} ${qty <= 0 ? 'mute' : ''}"><td><a href="#" data-prod="${p.id}"><b>${esc(p.name)}</b></a><div class="small mute">${esc(p.category_path || 'без категории')}${p.sku ? ' · ' + esc(p.sku) : ''}${low ? ' · <span class="warn">ниже минимума ' + num(p.min_qty) + '</span>' : ''}</div></td>
        <td class="r num">${num(qty, 3)} ${esc(p.unit)}${p.pack_qty && qty > 0 ? `<div class="small mute">${num(qty / Number(p.pack_qty), 1)} ${esc(p.pack_name || 'уп.')}</div>` : ''}</td>
        <td class="r num">${st && st.avg_cost ? num(st.avg_cost, 2) + ' ₽' : '—'}</td><td class="r num">${p.price ? num(p.price, 2) + ' ₽' : '<span class="warn" title="Цена клиенту не задана — откройте позицию и укажите">—</span>'}</td><td class="r num">${st ? fmt(st.value) : fmt(p.total_value)}</td>
        <td class="r">${qty > 0 && whSel ? `<button class="btn s" data-issue="${p.id}">Списать</button>` : ''}</td></tr>`; }).join('')}</table>`
    : emptyState(prods.length ? 'Ничего не найдено' : 'Номенклатуры пока нет', prods.length ? 'Измените фильтр или поиск.' : 'Нажмите «Приход» — позиции можно создать прямо в накладной, или «Новая позиция».')}</div></div>`;

  main.querySelectorAll('[data-wh]').forEach(b => b.onclick = () => { whSel = Number(b.dataset.wh); render(main, r, S); });
  main.querySelectorAll('[data-cat]').forEach(b => b.onclick = () => { catSel = b.dataset.cat ? Number(b.dataset.cat) : null; render(main, r, S); });
  main.querySelector('[data-q]').oninput = (e) => { query = e.target.value; clearTimeout(main._t); main._t = setTimeout(() => render(main, r, S), 250); };
  main.querySelector('[data-newwh]').onclick = () => newWarehouse(main, r);
  main.querySelector('[data-newcat]').onclick = () => catForm(main, r, null);
  main.querySelector('[data-cats]').onclick = () => catsDrawer(main, r);
  main.querySelector('[data-newprod]').onclick = () => prodForm(main, r, null);
  main.querySelector('[data-receipt]').onclick = () => receiptModal(main, r);
  main.querySelector('[data-transfer]').onclick = () => transferModal(main, r);
  main.querySelector('[data-adjust]').onclick = () => adjustModal(main, r);
  main.querySelector('[data-pending]')?.addEventListener('click', (e) => { e.preventDefault(); pendingDrawer(main, r); });
  main.querySelectorAll('[data-prod]').forEach(a => a.onclick = (e) => { e.preventDefault(); prodDrawer(main, r, Number(a.dataset.prod)); });
  main.querySelectorAll('[data-issue]').forEach(b => b.onclick = () => issueModal(main, r, Number(b.dataset.issue)));
}

function renderTree(pid, depth) {
  return catChildren(pid).map(c => { const n = prods.filter(p => catSubtree(c.id).has(p.category_id)).length;
    return `<button class="l${Math.min(depth + 1, 2)} ${catSel === c.id ? 'on' : ''}" data-cat="${c.id}" style="padding-left:${12 + depth * 14}px">${esc(c.name)}<span class="c">${n}</span></button>${renderTree(c.id, depth + 1)}`; }).join('');
}

const catOpts = () => [{ value: '', label: '— без категории —' }, ...cats.map(c => ({ value: c.id, label: pathOf(c.id) }))];
function pathOf(id) { const parts = []; let c = cats.find(x => x.id === id); const seen = new Set(); while (c && !seen.has(c.id)) { seen.add(c.id); parts.unshift(c.name); c = cats.find(x => x.id === c.parent_id); } return parts.join(' → '); }

function newWarehouse(main, r) {
  api.get('/api/foremen').then(fm => formModal({ title: 'Новый склад', intro: 'Склад создаётся автоматически при добавлении прораба; здесь — если нужен дополнительный.', submit: 'Создать',
    fields: [{ name: 'name', label: 'Название', required: true, placeholder: 'Склад Андрея К.' }, { name: 'foreman_id', label: 'Прораб', type: 'select', options: [{ value: '', label: '— без прораба —' }, ...fm.map(f => ({ value: f.id, label: f.name }))] }, { name: 'address', label: 'Адрес' }],
    onSubmit: async (v) => { v.foreman_id = v.foreman_id ? Number(v.foreman_id) : null; const w = await api.post('/api/stock/warehouses', v); whSel = w.id; toast('Склад создан'); render(main, r, S); } }));
}

function catForm(main, r, cat) {
  formModal({ title: cat ? 'Категория' : 'Новая категория', submit: cat ? 'Сохранить' : 'Создать',
    fields: [{ name: 'name', label: 'Название', required: true, value: cat?.name || '' }, { name: 'parent_id', label: 'Внутри', type: 'combo', options: catOpts().filter(o => !cat || o.value !== cat.id), value: cat?.parent_id ?? (catSel || '') }],
    onSubmit: async (v) => { v.parent_id = v.parent_id ? Number(v.parent_id) : null; if (cat) await api.patch('/api/stock/categories/' + cat.id, v); else await api.post('/api/stock/categories', v); toast('Сохранено'); closeDrawer(); render(main, r, S); } });
}

function catsDrawer(main, r) {
  const rows = (pid, d) => catChildren(pid).map(c => `<tr><td style="padding-left:${10 + d * 16}px">${esc(c.name)}</td><td class="r"><button class="btn s" data-edit="${c.id}">изменить</button> <button class="btn s" data-del="${c.id}">×</button></td></tr>${rows(c.id, d + 1)}`).join('');
  const d = openDrawer(`<h2>Категории</h2><p class="small mute">Любая вложенность: Кабель → ВВГнг-LS → 3×2,5.</p><table style="margin-top:8px">${rows(null, 0) || '<tr><td class="mute">Пусто</td></tr>'}</table><button class="btn s" style="margin-top:10px" data-new>+ категория</button>`);
  d.querySelector('[data-new]').onclick = () => catForm(main, r, null);
  d.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => catForm(main, r, cats.find(c => c.id === Number(b.dataset.edit))));
  d.querySelectorAll('[data-del]').forEach(b => b.onclick = () => confirmModal('Удалить категорию?', async () => { await api.del('/api/stock/categories/' + b.dataset.del); closeDrawer(); render(main, r, S); }, 'Удалить'));
}

function prodFields(p) {
  return [
    { name: 'name', label: 'Название', required: true, value: p?.name || '', placeholder: 'ВВГнг-LS 3×2,5' },
    { name: 'category_id', label: 'Категория', type: 'combo', options: catOpts(), value: p?.category_id ?? (catSel || '') },
    { name: 'unit', label: 'Единица', type: 'select', options: unitOpts, value: p?.unit || 'м' },
    { name: 'pack_qty', label: 'В упаковке (бухта 100 м → 100)', type: 'number', step: '0.001', value: p?.pack_qty ?? '' },
    { name: 'pack_name', label: 'Название упаковки', value: p?.pack_name || '', placeholder: 'бухта' },
    { name: 'min_qty', label: 'Минимальный остаток (уведомление «пора докупить»)', type: 'number', step: '0.001', value: p?.min_qty ?? '' },
    { name: 'client_price', label: 'Цена клиенту, ₽', type: 'number', step: '0.01', value: p?.client_price ?? '' },
    { name: 'sku', label: 'Артикул', value: p?.sku || '' }, { name: 'note', label: 'Заметка', value: p?.note || '' },
  ];
}
const cleanProd = (v) => ({ ...v, category_id: v.category_id ? Number(v.category_id) : null, is_active: true });

function prodForm(main, r, p) {
  formModal({ title: p ? 'Позиция' : 'Новая позиция', submit: p ? 'Сохранить' : 'Создать', fields: prodFields(p),
    onSubmit: async (v) => { if (p) await api.patch('/api/stock/products/' + p.id, cleanProd(v)); else await api.post('/api/stock/products', cleanProd(v)); toast('Сохранено'); closeDrawer(); render(main, r, S); } });
}

async function prodDrawer(main, r, pid) {
  const p = prods.find(x => x.id === pid);
  const mvs = await api.get('/api/stock/movements?product_id=' + pid + '&limit=50');
  const d = openDrawer(`<h2>${esc(p.name)}</h2><div class="small mute">${esc(p.category_path || 'без категории')} · ${esc(p.unit)}${p.pack_qty ? ' · ' + esc(p.pack_name || 'уп.') + ' ' + num(p.pack_qty) : ''}</div>
    <dl class="dl"><dt>Всего</dt><dd class="num">${num(p.total_qty, 3)} ${esc(p.unit)} · ${fmt(p.total_value)}</dd>
    ${whs.map(w => { const st = p.stock[w.id]; return st ? `<dt>${esc(w.name)}</dt><dd class="num">${num(st.qty, 3)} ${esc(p.unit)} · себест. ${num(st.avg_cost, 2)} ₽</dd>` : ''; }).join('')}
    <dt>Клиенту</dt><dd>${p.price ? num(p.price, 2) + ' ₽' : '<span class="warn">не задана</span>'}</dd>
    <dt>Минимум</dt><dd>${p.min_qty ? num(p.min_qty) + ' ' + esc(p.unit) : '—'}</dd></dl>
    <div class="row"><button class="btn" data-edit>Изменить</button>${whSel && p.stock[whSel] ? `<button class="btn p" data-issue>Списать на объект</button>` : ''}<button class="btn" data-off>${p.is_active ? 'Скрыть' : 'Вернуть'}</button></div>
    <h3 style="margin-top:20px">Движения</h3><table style="margin-top:6px"><tr><th>Дата</th><th>Что</th><th class="r">Кол-во</th><th class="r">Цена</th></tr>
    ${mvs.map(mv => `<tr class="${mv.confirmed ? '' : 'mute'}"><td class="num">${dateRu(mv.date)}</td><td>${esc(mv.kind_name)}${mv.object_name ? ' · ' + esc(mv.object_name) : ''}${mv.supplier ? ' · ' + esc(mv.supplier) : ''}<div class="small mute">${esc(mv.warehouse_name)}${mv.user_name ? ' · ' + esc(mv.user_name) : ''}${!mv.confirmed ? ' · в пути' : ''}</div></td><td class="r num ${Number(mv.qty) < 0 ? 'copper' : 'ok'}">${Number(mv.qty) > 0 ? '+' : ''}${num(mv.qty, 3)}</td><td class="r num">${num(mv.unit_cost, 2)} ₽</td></tr>`).join('') || '<tr><td colspan="4" class="mute">Движений не было</td></tr>'}</table>`);
  d.querySelector('[data-edit]').onclick = () => prodForm(main, r, p);
  d.querySelector('[data-issue]')?.addEventListener('click', () => issueModal(main, r, pid));
  d.querySelector('[data-off]').onclick = async () => { await api.patch('/api/stock/products/' + pid, { ...p, is_active: !p.is_active }); closeDrawer(); render(main, r, S); };
}

// ---------- приход: несколько строк, позиции на лету ----------
function receiptModal(main, r) {
  const wh = whs.find(w => w.id === whSel);
  const prodOpts = () => [...prods.map(p => ({ value: p.id, label: p.name, sub: p.unit + (p.category_path ? ' · ' + p.category_path : '') })), { value: 'new', label: '+ новая позиция…' }];
  const inp = 'padding:7px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink)';
  // строка: позиция; под ней — название (для новой), категория + единица (для новой или нераспознанной), либо подпись категории найденной позиции
  const line = (i, hint = '') => `<tr data-line="${i}"><td>${hint}${comboHtml(`p${i}`, { placeholder: '— выбрать позицию —' })}
    <div name="new${i}" class="hidden" style="margin-top:4px"><input name="n${i}" placeholder="Название новой позиции" style="width:100%;${inp}"></div>
    <div name="meta${i}" class="row hidden" style="margin-top:4px;gap:6px;flex-wrap:nowrap">${comboHtml(`k${i}`, { style: 'flex:1', placeholder: 'Категория' })}<select name="u${i}" title="Единица" style="width:84px;${inp}">${unitOpts.map(u => `<option value="${u.value}">${u.label}</option>`).join('')}</select></div>
    <div name="info${i}" class="small mute hidden" style="margin-top:3px"></div></td>
    <td><input name="q${i}" type="number" step="0.001" inputmode="decimal" placeholder="кол-во" style="width:80px;${inp}"></td>
    <td><input name="c${i}" type="number" step="0.01" inputmode="decimal" placeholder="закупка" style="width:90px;${inp}"></td>
    <td><input name="s${i}" type="number" step="0.01" inputmode="decimal" placeholder="клиенту" style="width:90px;${inp}"><div name="mk${i}" class="small mute num" style="margin-top:2px;min-height:14px"></div></td>
    <td style="padding-left:0"><button type="button" class="btn s" data-skip="${i}" title="Не заносить эту строку в приход" style="padding:4px 8px">×</button></td></tr>`;
  const m = openModal(`<div class="row sp"><h2>Приход на ${esc(wh?.name || 'склад')}</h2>${D.invoice_ai ? `<label class="btn s p" style="cursor:pointer">📷 По фото накладной<input type="file" accept="image/*,application/pdf" capture="environment" data-scan class="hidden"></label>` : ''}</div>
    <div class="small mute" data-scan-status style="margin-top:4px"></div><form>
    <div class="fields2"><div class="field"><label>Склад</label><select name="warehouse_id">${whs.map(w => `<option value="${w.id}" ${w.id === whSel ? 'selected' : ''}>${esc(w.name)}</option>`).join('')}</select></div><div class="field"><label>Дата</label><input name="date" type="date" value="${today()}"></div></div>
    <div class="fields2"><div class="field"><label>Поставщик</label><input name="supplier" placeholder="Кабель-Центр"></div><div class="field"><label>№ накладной</label><input name="doc_number"></div></div>
    <table style="margin-top:12px" id="rc-lines"><tr><th>Позиция</th><th>Кол-во</th><th>Закупка, ₽</th><th>Клиенту, ₽ <span class="small mute" title="Цена продажи клиенту — сохранится у позиции. Пусто — останется прежняя.">?</span></th><th></th></tr>${line(0)}${line(1)}${line(2)}</table>
    <button type="button" class="btn s" data-more style="margin-top:6px">+ строка</button>
    <div class="field"><label><input type="checkbox" name="add_expense" checked> Записать сумму закупки в расходы (категория «Закупка материалов»)</label></div>
    <div class="actions"><button type="button" class="btn" data-cancel>Отмена</button><button type="submit" class="btn p">Провести приход</button></div></form>`);
  m.querySelector('.box').style.width = 'min(760px,100%)';
  let n = 0;
  const f = m.querySelector('form');
  const ctl = (name) => f[name]?._combo;
  // наценка под ценой клиенту: показываем % к закупке
  const markup = (i) => { const c = Number(f[`c${i}`].value), sp = Number(f[`s${i}`].value); const el = m.querySelector(`[name=mk${i}]`); el.textContent = c > 0 && sp > 0 ? (sp >= c ? '+' : '') + num((sp - c) / c * 100) + '%' : ''; };
  // что показывать под позицией: новая → название + категория/единица; распознана, но не найдена → категория/единица; найдена → её категория
  const sync = (i) => {
    const tr = m.querySelector(`tr[data-line="${i}"]`); if (!tr) return;
    const v = f[`p${i}`].value, isNew = v === 'new', prod = v && !isNew ? prods.find(p => String(p.id) === v) : null;
    tr.querySelector(`[name=new${i}]`).classList.toggle('hidden', !isNew);
    tr.querySelector(`[name=meta${i}]`).classList.toggle('hidden', !(isNew || (tr.dataset.scanned && !v)));
    const info = tr.querySelector(`[name=info${i}]`);
    info.classList.toggle('hidden', !prod);
    if (prod) { info.textContent = `${prod.category_path || 'без категории'} · ${prod.unit}`; if (!f[`s${i}`].value && prod.price) { f[`s${i}`].value = Number(prod.price); f[`s${i}`].dataset.auto = String(Number(prod.price)); markup(i); } }
    if (isNew && !f[`u${i}`].dataset.set) f[`u${i}`].value = tr.dataset.unit || 'шт';
  };
  const skipped = (tr) => tr.dataset.skip === '1';
  const mountLine = (i) => {
    mountCombo(m.querySelector(`[data-combo="p${i}"]`), { options: prodOpts(), onChange: () => sync(i) });
    mountCombo(m.querySelector(`[data-combo="k${i}"]`), { options: catOpts(), value: catSel || '' });
    f[`c${i}`].oninput = () => markup(i); f[`s${i}`].oninput = () => { delete f[`s${i}`].dataset.auto; markup(i); };
    f[`u${i}`].onchange = () => f[`u${i}`].dataset.set = '1';
    m.querySelector(`[data-skip="${i}"]`).onclick = (e) => {
      const b = e.currentTarget, tr = b.closest('tr'), off = !skipped(tr);
      tr.dataset.skip = off ? '1' : '';
      tr.style.opacity = off ? '.4' : ''; tr.style.textDecoration = off ? 'line-through' : '';
      b.textContent = off ? '↶' : '×'; b.title = off ? 'Вернуть строку в приход' : 'Не заносить эту строку в приход';
      tr.querySelectorAll('input,select,.combo-btn').forEach(el => el.disabled = off);
    };
  };
  const addLine = (hint = '') => { const i = n++; m.querySelector('#rc-lines').insertAdjacentHTML('beforeend', line(i, hint)); mountLine(i); return i; };
  // три стартовые строки уже в разметке
  for (let i = 0; i < 3; i++) { mountLine(i); n = i + 1; }
  m.querySelector('[data-more]').onclick = () => addLine();
  const scan = m.querySelector('[data-scan]');
  if (scan) scan.onchange = async () => {
    const file = scan.files[0]; if (!file) return;
    const status = m.querySelector('[data-scan-status]');
    status.textContent = 'Распознаю накладную… обычно 10–30 секунд'; scan.disabled = true;
    try {
      const fd = new FormData(); fd.append('file', file);
      const res = await api.upload('/api/stock/recognize', fd);
      if (res.supplier && !f.supplier.value) f.supplier.value = res.supplier;
      if (res.doc_number && !f.doc_number.value) f.doc_number.value = res.doc_number;
      if (res.date && /^\d{4}-\d{2}-\d{2}$/.test(res.date)) f.date.value = res.date;
      // очищаем пустые строки и заполняем распознанными
      m.querySelectorAll('#rc-lines tr[data-line]').forEach(tr => { const i = tr.dataset.line; if (!f[`p${i}`].value && !f[`q${i}`].value) tr.remove(); });
      let matched = 0;
      for (const ln of res.lines) {
        const low = ln.confidence === 'low';
        const hint = `<div class="small ${ln.product_id ? 'ok' : 'warn'}" style="margin-bottom:3px" title="${esc(ln.raw || '')}">${esc(ln.raw || ln.name)}${ln.product_id ? ' → найдено' : ln.candidates?.length ? ' → выберите или создайте' : ' → новая позиция'}${low ? ' · <b class="warn">проверьте кол-во и цену</b>' : ''}</div>`;
        const i = addLine(hint);
        const tr = m.querySelector(`tr[data-line="${i}"]`); tr.dataset.unit = ln.unit || ''; tr.dataset.raw = ln.raw || ''; tr.dataset.scanned = '1';
        if (low) tr.style.background = 'var(--warn-soft)';
        if (ln.unit) { f[`u${i}`].value = ln.unit; f[`u${i}`].dataset.set = '1'; }
        ctl(`k${i}`).set(ln.category_id ? String(ln.category_id) : '');
        const pc = ctl(`p${i}`);
        if (ln.product_id) { pc.set(String(ln.product_id)); matched++; }
        else {
          // варианты — наверх списка
          const cands = (ln.candidates || []).map(c => ({ value: c.id, label: `≈ ${c.name}`, sub: c.unit }));
          if (cands.length) pc.setOptions([...cands, ...prodOpts().filter(o => !cands.some(c => String(c.value) === String(o.value)))]);
          pc.set(cands.length ? '' : 'new');
          f[`n${i}`].value = ln.name;
        }
        f[`q${i}`].value = Number(ln.qty) || '';
        f[`c${i}`].value = Number(ln.unit_cost) || '';
        sync(i); markup(i);
      }
      const lows = res.lines.filter(l => l.confidence === 'low').length;
      status.textContent = res.lines.length ? `Распознано строк: ${res.lines.length}, сопоставлено: ${matched}${lows ? `, сомнительных: ${lows} (подсвечены)` : ''}. Проверьте количество, цены и категории; лишние строки исключите крестиком.` : 'Строки не распознаны — попробуйте более чёткое фото или введите вручную.';
    } catch (err) { status.textContent = ''; toast(err.message, true); }
    finally { scan.disabled = false; scan.value = ''; }
  };
  m.querySelector('[data-cancel]').onclick = closeModal;
  f.onsubmit = async (e) => {
    e.preventDefault(); const lines = [];
    for (let i = 0; i < n; i++) {
      const sel = f[`p${i}`]; if (!sel) continue;
      const tr = sel.closest('tr');
      if (skipped(tr)) continue;
      const qty = Number(f[`q${i}`].value), cost = Number(f[`c${i}`].value);
      if (!qty) continue;
      if (!sel.value) { if (tr.dataset.scanned) return toast(`Строка «${(tr.dataset.raw || '').slice(0, 40)}» не сопоставлена: выберите позицию, создайте новую или исключите её (×)`, true); continue; }
      // цена клиенту: отправляем только если ввели вручную (подставленная автоматически текущая цена не делает её фиксированной)
      const sEl = f[`s${i}`]; const client_price = sEl.value !== '' && sEl.dataset.auto !== String(Number(sEl.value)) ? Number(sEl.value) : undefined;
      if (sel.value === 'new') { const name = f[`n${i}`].value.trim(); if (!name) return toast('Укажите название новой позиции', true); lines.push({ new_product: { name, unit: f[`u${i}`].value, category_id: f[`k${i}`].value ? Number(f[`k${i}`].value) : null, note: tr.dataset.raw || null, client_price: client_price ?? null }, qty, unit_cost: cost }); }
      else lines.push({ product_id: Number(sel.value), qty, unit_cost: cost, client_price });
    }
    if (!lines.length) return toast('Заполните хотя бы одну строку', true);
    try { await api.post('/api/stock/receipt', { warehouse_id: Number(f.warehouse_id.value), date: f.date.value, supplier: f.supplier.value || null, doc_number: f.doc_number.value || null, lines, add_expense: f.add_expense.checked });
      closeModal(); toast(`Приход проведён: ${lines.length} ${lines.length === 1 ? 'позиция' : 'позиции'}`); whSel = Number(f.warehouse_id.value); render(main, r, S); }
    catch (err) { toast(err.message, true); }
  };
}

export async function issueModal(main, r, pid) {
  const wh = whs.find(w => w.id === whSel);
  const objs = await api.get('/api/objects?active=true');
  if (!objs.length) return toast('Нет объектов в работе', true);
  stockIssueModal({ warehouse: wh, objects: objs, products: prods, presetProductId: pid, onDone: () => { closeDrawer(); render(main, r, S); } });
}

function transferModal(main, r) {
  const from = whs.find(w => w.id === whSel); const others = whs.filter(w => w.id !== whSel);
  if (!others.length) return toast('Нужен второй склад', true);
  const mine = prods.filter(p => p.stock[whSel] && Number(p.stock[whSel].qty) > 0);
  formModal({ title: 'Переместить на другой склад', intro: 'Получатель подтверждает в своём кабинете; до этого позиция «в пути» и не считается ни у кого.', submit: 'Переместить',
    fields: [{ name: 'to', label: 'Куда', type: 'select', options: others.map(w => ({ value: w.id, label: w.name })) }, { name: 'product_id', label: 'Позиция', type: 'combo', required: true, options: mine.map(p => ({ value: p.id, label: p.name, sub: `${num(p.stock[whSel].qty, 3)} ${p.unit}${p.category_path ? ' · ' + p.category_path : ''}` })) }, { name: 'qty', label: 'Количество', type: 'number', step: '0.001', required: true }, { name: 'note', label: 'Комментарий' }],
    onSubmit: async (v) => { if (!v.product_id) { toast('Выберите позицию', true); return false; } await api.post('/api/stock/transfer', { from_warehouse_id: from.id, to_warehouse_id: Number(v.to), product_id: Number(v.product_id), qty: v.qty, note: v.note }); toast('Отправлено, ждёт подтверждения'); render(main, r, S); } });
}

async function pendingDrawer(main, r) {
  const mvs = (await api.get('/api/stock/movements?warehouse_id=' + whSel + '&kind=transfer_in')).filter(m => !m.confirmed);
  const d = openDrawer(`<h2>В пути</h2><table style="margin-top:12px"><tr><th>Позиция</th><th class="r">Кол-во</th><th></th></tr>${mvs.map(mv => `<tr><td>${esc(mv.product_name)}<div class="small mute">${dateRu(mv.date)}${mv.user_name ? ' · ' + esc(mv.user_name) : ''}</div></td><td class="r num">${num(mv.qty, 3)} ${esc(mv.unit)}</td><td class="r"><button class="btn s p" data-ok="${mv.id}">Получил</button> <button class="btn s" data-no="${mv.id}">Отменить</button></td></tr>`).join('') || '<tr><td class="mute">Пусто</td></tr>'}</table>`);
  d.querySelectorAll('[data-ok]').forEach(b => b.onclick = async () => { await api.post(`/api/stock/movements/${b.dataset.ok}/confirm`, {}); toast('Принято на склад'); closeDrawer(); render(main, r, S); });
  d.querySelectorAll('[data-no]').forEach(b => b.onclick = () => confirmModal('Отменить перемещение? Товар вернётся отправителю.', async () => { await api.del('/api/stock/movements/' + b.dataset.no); closeDrawer(); render(main, r, S); }, 'Отменить'));
}

function adjustModal(main, r) {
  const mine = prods.filter(p => p.stock[whSel]);
  if (!mine.length) return toast('На этом складе нет остатков', true);
  const m = openModal(`<h2>Инвентаризация · ${esc(whs.find(w => w.id === whSel)?.name)}</h2><p class="small mute" style="margin:6px 0 0">Введите фактический остаток там, где он отличается. Разница спишется или добавится отдельной проводкой с датой.</p><form>
    <table style="margin-top:10px"><tr><th>Позиция</th><th class="r">Учёт</th><th class="r">Факт</th></tr>${mine.map(p => `<tr><td>${esc(p.name)}</td><td class="r num">${num(p.stock[whSel].qty, 3)} ${esc(p.unit)}</td><td class="r"><input name="a${p.id}" type="number" step="0.001" inputmode="decimal" placeholder="${num(p.stock[whSel].qty, 3)}" style="width:100px;padding:6px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);text-align:right"></td></tr>`).join('')}</table>
    <div class="field"><label>Комментарий</label><input name="note"></div><div class="actions"><button type="button" class="btn" data-cancel>Отмена</button><button type="submit" class="btn p">Провести</button></div></form>`);
  m.querySelector('[data-cancel]').onclick = closeModal;
  m.querySelector('form').onsubmit = async (e) => { e.preventDefault(); const f = e.target; const lines = [];
    for (const p of mine) { const v = f[`a${p.id}`].value; if (v !== '') lines.push({ product_id: p.id, actual_qty: Number(v) }); }
    if (!lines.length) return toast('Ничего не изменено', true);
    try { const res = await api.post('/api/stock/adjust', { warehouse_id: whSel, lines, note: f.note.value || null }); closeModal(); toast(res.length ? `Проведено расхождений: ${res.length}` : 'Расхождений нет'); render(main, r, S); } catch (err) { toast(err.message, true); } };
}
