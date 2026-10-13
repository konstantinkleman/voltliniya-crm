import { api } from '../api.js';
import { esc, num, toast, formModal, today } from '../ui.js';

// Списание со склада на конкретный объект — из карточки объекта и из кабинета прораба.
// Склад: прораба объекта (или первый доступный). Возврат — тем же окном с отрицательным смыслом не делаем: отдельная кнопка.
export async function stockIssueForObject(o, onDone, { returnMode = false } = {}) {
  const whs = await api.get('/api/stock/warehouses');
  const wh = whs.find(w => w.foreman_id === o.foreman_id) || whs[0];
  if (!wh) return toast('Склад не найден — заведите прораба или склад', true);
  const prods = await api.get('/api/stock/products?warehouse_id=' + wh.id);
  let list;
  if (returnMode) {
    const mvs = await api.get('/api/stock/movements?object_id=' + o.id + '&limit=500');
    const issued = {};
    for (const mv of mvs) { if (mv.kind === 'issue') issued[mv.product_id] = (issued[mv.product_id] || 0) - Number(mv.qty); if (mv.kind === 'return') issued[mv.product_id] = (issued[mv.product_id] || 0) - Number(mv.qty); }
    list = prods.filter(p => issued[p.id] > 0).map(p => ({ value: p.id, label: `${p.name} — на объекте ${num(issued[p.id], 3)} ${p.unit}` }));
    if (!list.length) return toast('С этого склада на объект ничего не списывалось', true);
  } else {
    list = prods.filter(p => p.stock[wh.id] && Number(p.stock[wh.id].qty) > 0).map(p => ({ value: p.id, label: `${p.name} — ${num(p.stock[wh.id].qty, 3)} ${p.unit}` }));
    if (!list.length) return toast(`На складе «${wh.name}» нет остатков`, true);
  }
  formModal({ title: returnMode ? 'Вернуть на склад' : 'Списать со склада', intro: `${esc(wh.name)} → ${esc(o.client_name)}`, submit: returnMode ? 'Вернуть' : 'Списать',
    fields: [{ name: 'product_id', label: 'Позиция', type: 'select', options: list }, { name: 'qty', label: 'Количество', type: 'number', step: '0.001', required: true, inputmode: 'decimal' }, { name: 'date', label: 'Дата', type: 'date', value: today() }, { name: 'note', label: 'Комментарий' }],
    onSubmit: async (v) => { await api.post(returnMode ? '/api/stock/return' : '/api/stock/issue', { warehouse_id: wh.id, product_id: Number(v.product_id), qty: v.qty, object_id: o.id, date: v.date, note: v.note }); toast(returnMode ? 'Возвращено на склад' : 'Списано со склада'); onDone(); } });
}
