import { api } from '../api.js';
import { esc, num, toast, openModal, closeModal, today, comboHtml, mountCombo } from '../ui.js';

// Списание со склада на объект (и возврат) — несколько позиций одним документом.
// Открывается из карточки объекта, кабинета прораба и из карточки позиции на складе.
//   stockIssueModal({ warehouse, object, objects, products, returnMode, presetProductId, onDone })
//   warehouse — откуда; object — фиксированный объект, иначе objects — список для выбора.
export async function stockIssueModal({ warehouse: wh, object = null, objects = [], products = null, returnMode = false, presetProductId = null, onDone }) {
  const prods = products || await api.get('/api/stock/products?warehouse_id=' + wh.id);
  // доступные остатки: на складе (списание) или на объекте (возврат)
  let avail = {};
  if (returnMode) {
    if (!object) return toast('Возврат — из карточки объекта', true);
    const mvs = await api.get('/api/stock/movements?object_id=' + object.id + '&limit=500');
    for (const mv of mvs) if (mv.kind === 'issue' || mv.kind === 'return') avail[mv.product_id] = (avail[mv.product_id] || 0) - Number(mv.qty);
  } else {
    for (const p of prods) if (p.stock[wh.id]) avail[p.id] = Number(p.stock[wh.id].qty);
  }
  const list = prods.filter(p => avail[p.id] > 0);
  if (!list.length) return toast(returnMode ? 'С этого склада на объект ничего не списывалось' : `На складе «${wh.name}» нет остатков`, true);
  const byId = Object.fromEntries(list.map(p => [p.id, p]));
  const opts = list.map(p => ({ value: p.id, label: p.name, sub: `${num(avail[p.id], 3)} ${p.unit}${p.category_path ? ' · ' + p.category_path : ''}` }));
  const inp = 'padding:7px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink)';
  const line = (i) => `<tr data-line="${i}"><td>${comboHtml(`p${i}`, { placeholder: 'Позиция — начните вводить' })}<div name="av${i}" class="small mute" style="margin-top:3px;min-height:14px"></div></td>
    <td><input name="q${i}" type="number" step="0.001" inputmode="decimal" placeholder="кол-во" style="width:96px;${inp}"></td>
    <td style="padding-left:0"><button type="button" class="btn s" data-rm="${i}" title="Убрать строку" style="padding:4px 8px">×</button></td></tr>`;
  const title = returnMode ? 'Вернуть на склад' : 'Списать со склада';
  const m = openModal(`<h2>${title}</h2><p class="small mute" style="margin:6px 0 0">${esc(wh.name)} ${returnMode ? '←' : '→'} ${object ? esc(object.client_name) : 'объект'}${returnMode ? '' : ' · себестоимость уйдёт в объект по средней цене склада'}</p><form>
    ${object ? '' : `<div class="field"><label>Объект</label>${comboHtml('object_id', { placeholder: 'Объект — начните вводить' })}</div>`}
    <table style="margin-top:12px" id="is-lines"><tr><th>Позиция</th><th>Кол-во</th><th></th></tr></table>
    <button type="button" class="btn s" data-more style="margin-top:6px">+ позиция</button>
    <div class="fields2"><div class="field"><label>Дата</label><input name="date" type="date" value="${today()}"></div><div class="field"><label>Комментарий</label><input name="note"></div></div>
    <div class="actions"><button type="button" class="btn" data-cancel>Отмена</button><button type="submit" class="btn p">${returnMode ? 'Вернуть' : 'Списать'}</button></div></form>`);
  m.querySelector('.box').style.width = 'min(640px,100%)';
  const f = m.querySelector('form');
  if (!object) mountCombo(m.querySelector('[data-combo="object_id"]'), { options: objects.map(o => ({ value: o.id, label: o.client_name, sub: o.address || '' })), allowEmpty: false });
  let n = 0;
  const addLine = (pid = null) => {
    const i = n++;
    m.querySelector('#is-lines').insertAdjacentHTML('beforeend', line(i));
    const av = m.querySelector(`[name=av${i}]`), q = f[`q${i}`];
    const show = (v) => { const p = byId[v]; av.textContent = p ? `${returnMode ? 'на объекте' : 'на складе'} ${num(avail[p.id], 3)} ${p.unit}` : ''; q.placeholder = p ? p.unit : 'кол-во'; };
    mountCombo(m.querySelector(`[data-combo="p${i}"]`), { options: opts, value: pid || '', allowEmpty: false, onChange: (v) => { show(v); if (!q.value) q.focus(); } });
    show(pid || '');
    m.querySelector(`[data-rm="${i}"]`).onclick = () => m.querySelector(`tr[data-line="${i}"]`).remove();
    return i;
  };
  addLine(presetProductId); addLine(); addLine();
  m.querySelector('[data-more]').onclick = () => { const i = addLine(); m.querySelector(`[data-combo="p${i}"] .combo-in`).focus(); };
  m.querySelector('[data-cancel]').onclick = closeModal;
  f.onsubmit = async (e) => {
    e.preventDefault();
    const lines = [], seen = new Set();
    for (let i = 0; i < n; i++) {
      const sel = f[`p${i}`]; if (!sel) continue;
      const pid = Number(sel.value), qty = Number(f[`q${i}`].value);
      if (!pid && !qty) continue;
      if (!pid) return toast('Выберите позицию в заполненной строке', true);
      if (!qty || qty <= 0) return toast(`Укажите количество: ${byId[pid].name}`, true);
      if (qty > avail[pid] + 1e-9) return toast(`${byId[pid].name}: ${returnMode ? 'на объекте' : 'на складе'} только ${num(avail[pid], 3)} ${byId[pid].unit}`, true);
      if (seen.has(pid)) return toast(`${byId[pid].name} указана дважды — объедините строки`, true);
      seen.add(pid); lines.push({ product_id: pid, qty });
    }
    if (!lines.length) return toast('Добавьте хотя бы одну позицию', true);
    const object_id = object ? object.id : Number(f.object_id.value);
    if (!object_id) return toast('Выберите объект', true);
    try {
      await api.post(returnMode ? '/api/stock/return' : '/api/stock/issue', { warehouse_id: wh.id, object_id, lines, date: f.date.value, note: f.note.value || null });
      closeModal(); toast(returnMode ? `Возвращено на склад: ${lines.length} поз.` : `Списано со склада: ${lines.length} поз.`); onDone && onDone();
    } catch (err) { toast(err.message, true); }
  };
}

// Из карточки объекта / кабинета прораба: склад — прораба объекта (или первый доступный).
export async function stockIssueForObject(o, onDone, { returnMode = false } = {}) {
  const whs = await api.get('/api/stock/warehouses');
  const wh = whs.find(w => w.foreman_id === o.foreman_id) || whs[0];
  if (!wh) return toast('Склад не найден — заведите прораба или склад', true);
  return stockIssueModal({ warehouse: wh, object: o, returnMode, onDone });
}
