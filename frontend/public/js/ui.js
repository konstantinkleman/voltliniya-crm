// Утилиты разметки и общие элементы: тосты, модалки, ящик, форматирование.

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const html = (strings, ...vals) => strings.reduce((a, s, i) => a + s + (i < vals.length ? (vals[i] instanceof Raw ? vals[i].s : Array.isArray(vals[i]) ? vals[i].map(v => v instanceof Raw ? v.s : esc(v)).join('') : esc(vals[i])) : ''), '');
class Raw { constructor(s) { this.s = s; } }
export const raw = (s) => new Raw(s);

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
export const fmt = (n) => (n === null || n === undefined || n === '') ? '—' : nf.format(Math.round(Number(n))) + ' ₽';
export const num = (n, d = 0) => (n === null || n === undefined) ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: d }).format(Number(n));
export const pct = (a, b) => (b && Number(b)) ? Math.round(Number(a) / Number(b) * 100) + '%' : '—';
export const dateRu = (s) => { if (!s) return '—'; const d = new Date(s); return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' }); };
export const dateTimeRu = (s) => { if (!s) return ''; const d = new Date(s); return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); };
export const today = () => new Date().toISOString().slice(0, 10);
export const monthKey = (d = new Date()) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
export const monthName = (key) => { const [y, m] = key.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }); };

export const srcClass = (s) => ({ profi: 'profi', site_direct: 'site', site_seo: 'site', site_other: 'site', avito: 'avito', recommendation: 'rec', designer: 'rec', renovation: 'rec' }[s] || '');

export function toast(msg, isErr = false) {
  const e = document.getElementById('toast');
  e.textContent = msg; e.className = 'toast on' + (isErr ? ' err' : '');
  clearTimeout(e._t); e._t = setTimeout(() => e.classList.remove('on'), isErr ? 3500 : 1800);
}

export function openDrawer(content) {
  const d = document.getElementById('drawer');
  d.innerHTML = '<button class="x" aria-label="Закрыть">×</button>' + content;
  d.querySelector('.x').onclick = closeDrawer;
  d.classList.add('open');
  return d;
}
export function closeDrawer() { document.getElementById('drawer').classList.remove('open'); }

export function openModal(content) {
  const m = document.getElementById('modal');
  m.innerHTML = '<div class="box">' + content + '</div>';
  m.classList.add('open');
  m.onclick = (e) => { if (e.target === m) closeModal(); };
  const first = m.querySelector('input,select,textarea'); if (first) setTimeout(() => first.focus(), 30);
  return m;
}
export function closeModal() { document.getElementById('modal').classList.remove('open'); }

// Простая форма в модалке: fields = [{name,label,type,options,value,required,placeholder}]
// onSubmit(values) → если вернёт false, модалка не закрывается.
export function formModal({ title, fields, submit = 'Сохранить', onSubmit, intro = '' }) {
  const body = fields.map(f => {
    if (f.type === 'select') {
      const opts = (f.options || []).map(o => `<option value="${esc(o.value)}" ${String(o.value) === String(f.value ?? '') ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
      return `<div class="field"><label>${esc(f.label)}</label><select name="${esc(f.name)}" ${f.required ? 'required' : ''}>${opts}</select></div>`;
    }
    if (f.type === 'textarea') return `<div class="field"><label>${esc(f.label)}</label><textarea name="${esc(f.name)}" placeholder="${esc(f.placeholder || '')}">${esc(f.value ?? '')}</textarea></div>`;
    if (f.type === 'file') return `<div class="field"><label>${esc(f.label)}</label><input type="file" name="${esc(f.name)}" ${f.accept ? `accept="${f.accept}"` : ''} ${f.required ? 'required' : ''} ${f.capture ? 'capture="environment"' : ''}></div>`;
    return `<div class="field"><label>${esc(f.label)}</label><input type="${f.type || 'text'}" name="${esc(f.name)}" value="${esc(f.value ?? '')}" placeholder="${esc(f.placeholder || '')}" ${f.required ? 'required' : ''} ${f.step ? `step="${f.step}"` : ''} ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.inputmode ? `inputmode="${f.inputmode}"` : ''}></div>`;
  }).join('');
  const m = openModal(`<h2>${esc(title)}</h2>${intro ? `<p class="mute small" style="margin:6px 0 0">${intro}</p>` : ''}<form>${body}<div class="actions"><button type="button" class="btn" data-cancel>Отмена</button><button type="submit" class="btn p">${esc(submit)}</button></div></form>`);
  const form = m.querySelector('form');
  m.querySelector('[data-cancel]').onclick = closeModal;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('[type=submit]'); btn.disabled = true;
    const values = {};
    for (const f of fields) {
      const el = form.elements[f.name];
      if (!el) continue;
      if (f.type === 'file') values[f.name] = el.files[0] || null;
      else if (f.type === 'number') values[f.name] = el.value === '' ? null : Number(el.value);
      else values[f.name] = el.value === '' ? null : el.value;
    }
    try {
      const r = await onSubmit(values);
      if (r !== false) closeModal();
    } catch (err) { toast(err.message || 'Ошибка', true); }
    finally { btn.disabled = false; }
  };
  return m;
}

export function confirmModal(text, onYes, yes = 'Да') {
  const m = openModal(`<p style="margin:0 0 4px">${esc(text)}</p><div class="actions"><button class="btn" data-cancel>Отмена</button><button class="btn p danger" data-yes>${esc(yes)}</button></div>`);
  m.querySelector('[data-cancel]').onclick = closeModal;
  m.querySelector('[data-yes]').onclick = async () => { try { await onYes(); closeModal(); } catch (e) { toast(e.message, true); } };
}

export const opt = (obj) => Object.entries(obj).map(([value, label]) => ({ value, label }));
export const emptyState = (title, text) => `<div class="empty"><b>${esc(title)}</b>${esc(text)}</div>`;
