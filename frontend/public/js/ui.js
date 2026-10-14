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
// даты чатов Авито хранятся в UTC без пояса — помечаем, чтобы браузер показал местное время
export const utc = (s) => !s ? s : (/([zZ]|[+-]\d\d:?\d\d)$/.test(s) ? s : s + 'Z');
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
    if (f.type === 'combo') return `<div class="field"><label>${esc(f.label)}</label>${comboHtml(f.name, { placeholder: f.placeholder || '— выбрать —' })}</div>`;
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
// Кнопка с выбранным значением; по клику сразу раскрывается весь список, сверху — строка поиска (как у «ВсеИнструменты»).
// Разметка: comboHtml(name, {style, placeholder}) → <div class="combo" data-combo="name">…</div>; затем mountCombo(el, {options, value, onChange, allowEmpty}).
// Внутри — скрытый <input name="…"> с выбранным значением: form.elements[name].value работает как у <select>, событие change тоже.
// Управление: form.elements[name]._combo → { set(value), setOptions(options), get value }.
const cyr = (s) => String(s ?? '').toLowerCase().replace(/ё/g, 'е').replace(/[×x]/g, 'х').replace(/,/g, '.');
export const comboHtml = (name, { style = '', placeholder = '' } = {}) => `<div class="combo" data-combo="${esc(name)}" style="${style}"><input type="hidden" name="${esc(name)}"><button type="button" class="combo-btn is-empty" data-ph="${esc(placeholder || '— выбрать —')}">${esc(placeholder || '— выбрать —')}</button><span class="combo-arr">▾</span></div>`;
let panel = null; // единая панель на всю страницу (fixed — не режется прокруткой модалки)
const closePanel = () => { if (panel) { panel._owner?.classList.remove('open'); panel.remove(); panel = null; } };
const isTouch = () => matchMedia('(pointer: coarse)').matches;
export function mountCombo(el, { options = [], value = '', onChange = null, allowEmpty = true } = {}) {
  const hid = el.querySelector('input[type=hidden]'), btn = el.querySelector('.combo-btn');
  let opts = options, shown = [], active = -1;
  const label = (v) => (opts.find(o => String(o.value) === String(v)) || {}).label ?? '';
  const render = () => { const l = label(hid.value); btn.textContent = l || btn.dataset.ph; btn.classList.toggle('is-empty', !l); };
  const filter = (q) => {
    const toks = cyr(q).trim().split(/\s+/).filter(Boolean);
    let list = toks.length ? opts.filter(o => { const l = cyr(o.label) + ' ' + cyr(o.sub || ''); return toks.every(t => l.includes(t)); }) : opts;
    if (allowEmpty && !toks.length && !opts.some(o => o.value === '')) list = [{ value: '', label: '—' }, ...list];
    return list.slice(0, 300);
  };
  const place = () => {
    if (!panel) return;
    const r = btn.getBoundingClientRect(), vw = window.innerWidth, vh = (window.visualViewport?.height) || window.innerHeight;
    if (vw < 640) { panel.style.cssText = `left:8px;right:8px;top:8px;max-height:${Math.max(200, vh - 16)}px`; return; }
    const below = vh - r.bottom - 12, above = r.top - 12, down = below >= 220 || below >= above;
    const h = Math.min(360, Math.max(160, down ? below : above));
    panel.style.cssText = `left:${Math.min(r.left, vw - Math.max(r.width, 280) - 8)}px;width:${Math.max(r.width, 280)}px;max-height:${h}px;` + (down ? `top:${r.bottom + 4}px` : `bottom:${window.innerHeight - r.top + 4}px`);
  };
  const draw = (q) => {
    shown = filter(q);
    const box = panel.querySelector('.combo-items');
    box.innerHTML = shown.map((o, i) => `<div class="combo-it ${String(o.value) === String(hid.value) ? 'sel' : ''} ${o.value === 'new' ? 'new' : ''}" data-i="${i}">${esc(o.label)}${o.sub ? `<span class="small mute"> · ${esc(o.sub)}</span>` : ''}</div>`).join('') || '<div class="combo-it mute">ничего не найдено</div>';
    active = shown.findIndex(o => String(o.value) === String(hid.value)); hl(false);
  };
  const hl = (scroll = true) => { if (!panel) return; panel.querySelectorAll('.combo-it').forEach((x, i) => x.classList.toggle('act', i === active)); if (scroll) panel.querySelector('.combo-it.act')?.scrollIntoView({ block: 'nearest' }); };
  const pick = (o) => { if (!o) return; const changed = String(hid.value) !== String(o.value); hid.value = o.value; render(); close(); btn.focus(); if (changed) { hid.dispatchEvent(new Event('change', { bubbles: true })); if (onChange) onChange(o.value, o); } };
  const close = () => { if (panel && panel._owner === el) closePanel(); };
  const open = () => {
    if (btn.disabled) return;
    closePanel();
    panel = document.createElement('div'); panel.className = 'combo-panel'; panel._owner = el; el.classList.add('open');
    panel.innerHTML = `<div class="combo-search-w"><input type="text" class="combo-search" placeholder="Поиск…" autocomplete="off" spellcheck="false"><span>⌕</span></div><div class="combo-items"></div>`;
    document.body.appendChild(panel); place(); draw('');
    const inp = panel.querySelector('.combo-search');
    inp.oninput = () => draw(inp.value);
    inp.onkeydown = (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, Math.min(shown.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1))); hl(); }
      else if (e.key === 'Enter') { e.preventDefault(); pick(shown[active] || (shown.length === 1 ? shown[0] : null)); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); btn.focus(); }
      else if (e.key === 'Tab') close();
    };
    panel.querySelector('.combo-items').onmousedown = (e) => { e.preventDefault(); const it = e.target.closest('[data-i]'); if (it) pick(shown[Number(it.dataset.i)]); };
    // на телефоне не вызываем клавиатуру сразу — сначала показываем список; поиск по тапу в поле
    if (!isTouch()) inp.focus();
    // выделенный пункт — в зоне видимости
    panel.querySelector('.combo-it.sel')?.scrollIntoView({ block: 'center' });
  };
  btn.onclick = () => (panel && panel._owner === el) ? close() : open();
  btn.onkeydown = (e) => { if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } else if (e.key === 'Escape') close(); };
  hid._combo = {
    get value() { return hid.value; },
    set: (v) => { hid.value = v ?? ''; render(); },
    setOptions: (o) => { opts = o; render(); },
    el, open, close,
  };
  el._place = place;
  hid.value = value ?? ''; render();
  return hid._combo;
}
// клик вне панели — закрыть; прокрутка страницы/модалки (не самого списка) — переставить панель
document.addEventListener('mousedown', (e) => { if (panel && !panel.contains(e.target) && !panel._owner.contains(e.target)) closePanel(); });
document.addEventListener('touchstart', (e) => { if (panel && !panel.contains(e.target) && !panel._owner.contains(e.target)) closePanel(); }, { passive: true });
window.addEventListener('scroll', (e) => { if (panel && !panel.contains(e.target)) panel._owner._place(); }, true);
window.addEventListener('resize', () => { if (panel) panel._owner._place(); });
window.visualViewport?.addEventListener('resize', () => { if (panel) panel._owner._place(); });

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
