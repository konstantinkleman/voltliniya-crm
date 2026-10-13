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
  const first = m.querySelector('input:not([type=hidden]),select,textarea'); if (first) setTimeout(() => first.focus(), 30);
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
    if (f.type === 'combo') return `<div class="field"><label>${esc(f.label)}</label>${comboHtml(f.name, { placeholder: f.placeholder || 'Начните вводить…' })}</div>`;
    if (f.type === 'textarea') return `<div class="field"><label>${esc(f.label)}</label><textarea name="${esc(f.name)}" placeholder="${esc(f.placeholder || '')}">${esc(f.value ?? '')}</textarea></div>`;
    if (f.type === 'file') return `<div class="field"><label>${esc(f.label)}</label><input type="file" name="${esc(f.name)}" ${f.accept ? `accept="${f.accept}"` : ''} ${f.required ? 'required' : ''} ${f.capture ? 'capture="environment"' : ''} ${f.multiple ? 'multiple' : ''}></div>`;
    return `<div class="field"><label>${esc(f.label)}</label><input type="${f.type || 'text'}" name="${esc(f.name)}" value="${esc(f.value ?? '')}" placeholder="${esc(f.placeholder || '')}" ${f.required ? 'required' : ''} ${f.step ? `step="${f.step}"` : ''} ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.inputmode ? `inputmode="${f.inputmode}"` : ''}></div>`;
  }).join('');
  const m = openModal(`<h2>${esc(title)}</h2>${intro ? `<p class="mute small" style="margin:6px 0 0">${intro}</p>` : ''}<form>${body}<div class="actions"><button type="button" class="btn" data-cancel>Отмена</button><button type="submit" class="btn p">${esc(submit)}</button></div></form>`);
  const form = m.querySelector('form');
  for (const f of fields) if (f.type === 'combo') mountCombo(form.querySelector(`[data-combo="${f.name}"]`), { options: f.options || [], value: f.value ?? '', allowEmpty: !f.required, onChange: f.onChange });
  m.querySelector('[data-cancel]').onclick = closeModal;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector('[type=submit]'); btn.disabled = true;
    const values = {};
    for (const f of fields) {
      const el = form.elements[f.name];
      if (!el) continue;
      if (f.type === 'file') values[f.name] = f.multiple ? Array.from(el.files) : (el.files[0] || null);
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

// ---------- combo: выпадающий список с поиском ----------
// Разметка: comboHtml(name, {style}) → <div class="combo" data-combo="name">…</div>; затем mountCombo(el, {options, value, placeholder, onChange}).
// Внутри — скрытый <input name="…"> с выбранным значением: form.elements[name].value работает как у <select>.
// Управление: el.querySelector('input[type=hidden]')._combo → { set(value), setOptions(options), get value }.
const cyr = (s) => String(s ?? '').toLowerCase().replace(/ё/g, 'е').replace(/[×x]/g, 'х').replace(/,/g, '.');
export const comboHtml = (name, { style = '', placeholder = '' } = {}) => `<div class="combo" data-combo="${esc(name)}" style="${style}"><input type="hidden" name="${esc(name)}"><input type="text" class="combo-in" autocomplete="off" spellcheck="false" placeholder="${esc(placeholder)}"><span class="combo-arr">▾</span></div>`;
let comboList = null; // единый выпадающий список на всю страницу (fixed, чтобы не резался модалкой)
export function mountCombo(el, { options = [], value = '', placeholder, onChange = null, allowEmpty = true } = {}) {
  const hid = el.querySelector('input[type=hidden]'), inp = el.querySelector('.combo-in');
  if (placeholder !== undefined) inp.placeholder = placeholder;
  let opts = options, active = -1, shown = [];
  const label = (v) => (opts.find(o => String(o.value) === String(v)) || {}).label ?? '';
  const render = () => { inp.value = label(hid.value); inp.classList.toggle('is-empty', !hid.value); };
  const close = () => { if (comboList && comboList._owner === el) { comboList.remove(); comboList = null; } el.classList.remove('open'); };
  const open = (q = '') => {
    close();
    const qq = cyr(q).trim(); const toks = qq.split(/\s+/).filter(Boolean);
    shown = toks.length ? opts.filter(o => { const l = cyr(o.label) + ' ' + cyr(o.sub || ''); return toks.every(t => l.includes(t)); }) : opts;
    if (allowEmpty && shown === opts && !opts.some(o => o.value === '')) shown = [{ value: '', label: '—' }, ...opts];
    shown = shown.slice(0, 200);
    const r = inp.getBoundingClientRect();
    const below = window.innerHeight - r.bottom; const h = Math.min(280, Math.max(120, below > 200 ? below - 12 : r.top - 12));
    comboList = document.createElement('div'); comboList.className = 'combo-list'; comboList._owner = el;
    comboList.style.cssText = `left:${r.left}px;width:${Math.max(r.width, 220)}px;max-height:${h}px;` + (below > 200 || r.top < 200 ? `top:${r.bottom + 2}px` : `bottom:${window.innerHeight - r.top + 2}px`);
    comboList.innerHTML = shown.map((o, i) => `<div class="combo-it ${String(o.value) === String(hid.value) ? 'sel' : ''} ${o.value === 'new' ? 'new' : ''}" data-i="${i}">${esc(o.label)}${o.sub ? `<span class="small mute"> · ${esc(o.sub)}</span>` : ''}</div>`).join('') || '<div class="combo-it mute">ничего не найдено</div>';
    comboList.onmousedown = (e) => { e.preventDefault(); const it = e.target.closest('[data-i]'); if (it) pick(shown[Number(it.dataset.i)]); };
    document.body.appendChild(comboList); el.classList.add('open');
    active = shown.findIndex(o => String(o.value) === String(hid.value)); hl();
  };
  const hl = () => { if (!comboList) return; comboList.querySelectorAll('.combo-it').forEach((x, i) => x.classList.toggle('act', i === active)); const a = comboList.querySelector('.combo-it.act'); if (a) a.scrollIntoView({ block: 'nearest' }); };
  const pick = (o) => { if (!o) return; const changed = String(hid.value) !== String(o.value); hid.value = o.value; render(); close(); if (changed) { hid.dispatchEvent(new Event('change', { bubbles: true })); if (onChange) onChange(o.value, o); } };
  inp.onfocus = () => { inp.select(); open(''); };
  inp.onclick = () => { if (!comboList || comboList._owner !== el) open(''); };
  inp.oninput = () => open(inp.value);
  inp.onkeydown = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); if (!comboList || comboList._owner !== el) open(inp.value); active = Math.max(0, Math.min(shown.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1))); hl(); }
    else if (e.key === 'Enter') { if (comboList && comboList._owner === el) { e.preventDefault(); pick(shown[active] || (shown.length === 1 ? shown[0] : null)); } }
    else if (e.key === 'Escape') { render(); close(); }
    else if (e.key === 'Tab') { if (comboList && comboList._owner === el && shown.length === 1 && inp.value) pick(shown[0]); else { render(); close(); } }
  };
  inp.onblur = () => { setTimeout(() => { render(); close(); }, 120); };
  hid._combo = {
    get value() { return hid.value; },
    set: (v) => { hid.value = v ?? ''; render(); },
    setOptions: (o) => { opts = o; render(); },
    el,
  };
  hid.value = value ?? ''; render();
  return hid._combo;
}
window.addEventListener('scroll', () => { if (comboList) { comboList.remove(); comboList = null; } }, true);
window.addEventListener('resize', () => { if (comboList) { comboList.remove(); comboList = null; } });

export function confirmModal(text, onYes, yes = 'Да') {
  const m = openModal(`<p style="margin:0 0 4px">${esc(text)}</p><div class="actions"><button class="btn" data-cancel>Отмена</button><button class="btn p danger" data-yes>${esc(yes)}</button></div>`);
  m.querySelector('[data-cancel]').onclick = closeModal;
  m.querySelector('[data-yes]').onclick = async () => { try { await onYes(); closeModal(); } catch (e) { toast(e.message, true); } };
}

// Поле «Бригада» рядом с полем «Прораб»: список сужается до бригад выбранного прораба; единственная подставляется сама.
export const crewField = (crews, value = '') => ({ name: 'crew_id', label: 'Бригада', type: 'select', value, options: [{ value: '', label: '— у прораба одна бригада / позже —' }, ...crews.filter(c => c.is_active).map(c => ({ value: c.id, label: c.name + (c.foreman_name ? ' · ' + c.foreman_name : ''), foreman_id: c.foreman_id }))] });
export function bindCrewFilter(m, crews) {
  const fs = m.querySelector('[name=foreman_id]'), cs = m.querySelector('[name=crew_id]'); if (!fs || !cs) return;
  const apply = (keep) => {
    const fid = Number(fs.value); const own = crews.filter(c => c.is_active && (!fid || c.foreman_id === fid));
    const cur = keep ? cs.value : '';
    cs.innerHTML = `<option value="">${own.length === 1 && fid ? '— ' + esc(own[0].name) + ' (единственная) —' : own.length ? '— выбрать —' : '— у прораба нет бригад —'}</option>` + own.map(c => `<option value="${c.id}">${esc(c.name)}${!fid && c.foreman_name ? ' · ' + esc(c.foreman_name) : ''}</option>`).join('');
    cs.value = own.some(c => String(c.id) === cur) ? cur : '';
    cs.closest('.field').classList.toggle('hidden', !!fid && own.length <= 1);
  };
  fs.addEventListener('change', () => apply(false)); apply(true);
}

export const opt = (obj) => Object.entries(obj).map(([value, label]) => ({ value, label }));
export const emptyState = (title, text) => `<div class="empty"><b>${esc(title)}</b>${esc(text)}</div>`;
