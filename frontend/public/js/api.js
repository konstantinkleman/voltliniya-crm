// Тонкий клиент к /api. Токен хранится в localStorage.
export const token = {
  get: () => { try { return localStorage.getItem('token'); } catch { return null; } },
  set: (t) => { try { t ? localStorage.setItem('token', t) : localStorage.removeItem('token'); } catch {} },
};

export class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

async function req(method, url, body, isForm) {
  const headers = {};
  const t = token.get();
  if (t) headers.Authorization = 'Bearer ' + t;
  let payload = body;
  if (body && !isForm) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  const r = await fetch(url, { method, headers, body: payload });
  if (r.status === 401) { token.set(null); location.hash = '#/login'; throw new ApiError(401, 'Нужно войти'); }
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new ApiError(r.status, detail);
  }
  if (r.status === 204) return null;
  return r.json();
}

export const api = {
  get: (u) => req('GET', u),
  post: (u, b) => req('POST', u, b),
  patch: (u, b) => req('PATCH', u, b),
  del: (u) => req('DELETE', u),
  upload: (u, form) => req('POST', u, form, true),
  async login(email, password) {
    const form = new URLSearchParams({ username: email, password });
    const r = await fetch('/api/auth/login', { method: 'POST', body: form });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new ApiError(r.status, j.detail || 'Ошибка входа'); }
    const j = await r.json();
    token.set(j.access_token);
    return j;
  },
};

// Справочники кешируем на сессию.
let dicts = null;
export async function getDicts() {
  if (!dicts) dicts = await api.get('/api/dictionaries');
  return dicts;
}
export function resetDicts() { dicts = null; }
