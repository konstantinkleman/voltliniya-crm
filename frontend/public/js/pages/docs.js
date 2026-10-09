import { api } from '../api.js';
import { esc, dateRu, toast, formModal, confirmModal, opt } from '../ui.js';

const KINDS = { offer: 'КП', contract: 'Договор', appendix: 'Приложение', act: 'Акт', plan: 'План / проект', photo: 'Фото', tour: '3D-тур', other: 'Другое' };

export async function uploadDoc(file, { lead_id, object_id, kind = 'other', title }) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('kind', kind);
  if (title) fd.append('title', title);
  if (lead_id) fd.append('lead_id', lead_id);
  if (object_id) fd.append('object_id', object_id);
  return api.upload('/api/documents', fd);
}

const sizeStr = (n) => n > 1e6 ? (n / 1e6).toFixed(1) + ' МБ' : Math.max(1, Math.round(n / 1024)) + ' КБ';

// Блок документов с загрузкой. owner = {lead_id} | {object_id}; onChange — перерисовать родителя.
export function docsBlock(el, docs, owner, onChange, hint = '', { photos = false, canDelete = true } = {}) {
  const list = photos ? docs.filter(d => d.kind === 'photo') : docs.filter(d => d.kind !== 'photo');
  el.innerHTML = `<div class="row sp" style="margin-top:20px"><h3>${photos ? 'Фото' : 'Документы'}</h3><button class="btn s" data-up>+ ${photos ? 'фото' : 'файл'}</button></div>
    ${photos ? `<div class="photos" style="margin-top:8px">${list.map(d => `<a href="#" data-id="${d.id}" title="${esc(d.title)}"><img alt="${esc(d.title)}" loading="lazy">${canDelete ? `<button class="del" title="Удалить" data-del="${d.id}" style="position:absolute;right:2px;top:0;border:0;background:rgba(0,0,0,.4);color:#fff;border-radius:50%;width:20px;height:20px;line-height:1">×</button>` : ''}</a>`).join('')}</div>`
    : `<div class="docs" style="margin-top:8px">${list.map(d => `
      <a class="doc" href="#" data-id="${d.id}">
        <b>${esc(d.title)}</b><span class="mute">${esc(KINDS[d.kind] || d.kind)} · ${dateRu(d.created_at)} · ${sizeStr(d.size)}</span>
        ${canDelete ? `<button class="del" title="Удалить" data-del="${d.id}">×</button>` : ''}</a>`).join('')}</div>`}
    ${!list.length && hint ? `<div class="small mute">${esc(hint)}</div>` : ''}`;
  if (photos) loadThumbs(el.querySelectorAll('.photos a'));
  // файл отдаётся только с токеном в заголовке — открываем через fetch и blob-URL
  el.querySelectorAll('a.doc').forEach(a => a.onclick = async (e) => {
    if (e.target.dataset.del) return;
    e.preventDefault();
    try {
      const r = await fetch(`/api/documents/${a.dataset.id}/file`, { headers: { Authorization: 'Bearer ' + localStorage.getItem('token') } });
      if (!r.ok) throw new Error('Не удалось открыть файл');
      const blob = await r.blob(); const url = URL.createObjectURL(blob);
      window.open(url, '_blank'); setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) { toast(err.message, true); }
  });
  el.querySelectorAll('[data-del]').forEach(b => b.onclick = (e) => { e.preventDefault(); e.stopPropagation();
    confirmModal('Удалить документ?', async () => { await api.del('/api/documents/' + b.dataset.del); toast('Удалено'); onChange(); }, 'Удалить'); });
  el.querySelector('[data-up]').onclick = () => formModal({ title: photos ? 'Добавить фото' : 'Загрузить документ', submit: 'Загрузить',
    fields: photos
      ? [{ name: 'file', label: 'Фото', type: 'file', accept: 'image/*', capture: true, required: true }, { name: 'title', label: 'Подпись', placeholder: 'День 3 — штробление' }]
      : [{ name: 'file', label: 'Файл', type: 'file', required: true }, { name: 'kind', label: 'Тип', type: 'select', options: opt(KINDS), value: 'other' }, { name: 'title', label: 'Название (по умолчанию — имя файла)' }],
    onSubmit: async (v) => { await uploadDoc(v.file, { ...owner, kind: photos ? 'photo' : v.kind, title: v.title || undefined }); toast('Загружено'); onChange(); } });
}

// Миниатюры: грузим файл с токеном, подставляем blob-URL в <img>, клик — открыть в новой вкладке.
export function loadThumbs(anchors) {
  anchors.forEach(async (a) => {
    try {
      const r = await fetch(`/api/documents/${a.dataset.id}/file`, { headers: { Authorization: 'Bearer ' + localStorage.getItem('token') } });
      if (!r.ok) return;
      const url = URL.createObjectURL(await r.blob());
      const img = a.querySelector('img'); if (img) img.src = url;
      a.onclick = (e) => { e.preventDefault(); window.open(url, '_blank'); };
    } catch {}
  });
}
