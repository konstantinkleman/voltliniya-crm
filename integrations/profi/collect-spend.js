// Сбор расходов Профи.ру для CRM. Выполняется на странице https://profi.ru/backoffice/bill.php (вход в Профи уже выполнен).
// Открывает «Историю транзакций», подгружает все строки нужных месяцев и считает деньги, реально потраченные на канал:
//   списания в рублях (отклики, Профи-премиум, абонементы) − возвраты в рублях. Бонусы и пополнения баланса не учитываются.
// Результат — массив { month: 'YYYY-MM', date: 'YYYY-MM-DD', amount, note } для POST /api/expenses/upsert в CRM.
(async () => {
  const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
  const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const dlg = () => [...document.querySelectorAll('[role=dialog]')].find((d) => /История транзакций/.test(d.innerText));
  if (!dlg()) {
    const btn = [...document.querySelectorAll('button')].find((b) => b.innerText.trim() === 'Смотреть все');
    if (!btn) return { error: 'Нет кнопки «Смотреть все» — Профи не открыт или не выполнен вход' };
    btn.click();
    await sleep(2000);
  }
  if (!dlg()) return { error: 'Не открылась «История транзакций»' };

  const today = new Date();
  const wanted = [new Date(today.getFullYear(), today.getMonth(), 1)];
  if (today.getDate() <= 5) wanted.unshift(new Date(today.getFullYear(), today.getMonth() - 1, 1)); // прошлый месяц дозакрываем
  const pad = (n) => String(n).padStart(2, '0');

  const parse = (text) => {
    const skip = /^(История транзакций|Скачать полный отчёт|Mir|СберБанк|Visa|MasterCard|SBP|СБП)/;
    const lines = text.split('\n').map((s) => s.trim()).filter(Boolean);
    const items = [];
    let cur = null;
    for (const l of lines) {
      if (MONTHS.includes(l) || skip.test(l)) continue;
      let m;
      if ((m = l.match(/^([+\-−–])\s?([\d\s]+)\s?₽$/))) { if (cur) cur.rub = (m[1] === '+' ? 1 : -1) * Number(m[2].replace(/\s/g, '')); continue; }
      if (/^([+\-−–])\s?[\d\s]+$/.test(l)) continue; // бонусы — не деньги
      if ((m = l.match(/^(\d{1,2}) ([а-я]+)/))) { if (cur && !cur.day) cur.day = Number(m[1]); continue; }
      if (/^[А-ЯЁ]/.test(l) && !/[₽]/.test(l)) { cur = { title: l, rub: null, day: null }; items.push(cur); }
    }
    return items;
  };

  const out = [];
  for (const d of wanted) {
    const name = MONTHS[d.getMonth()];
    const tab = [...dlg().querySelectorAll('button')].find((b) => b.innerText.trim() === name);
    if (!tab) { out.push({ month: `${d.getFullYear()}-${pad(d.getMonth() + 1)}`, error: `нет вкладки «${name}»` }); continue; }
    tab.click();
    await sleep(1500);
    const sc = [...dlg().querySelectorAll('*')].find((e) => e.scrollHeight > e.clientHeight + 20 && /(auto|scroll)/.test(getComputedStyle(e).overflowY));
    let prev = -1;
    for (let k = 0; k < 40 && sc; k++) { // подгрузка «бесконечной» ленты
      sc.scrollTop = sc.scrollHeight;
      await sleep(1200);
      const n = dlg().innerText.length;
      if (n === prev) break;
      prev = n;
    }
    const items = parse(dlg().innerText);
    const spentItems = items.filter((i) => i.rub < 0);
    const spent = spentItems.reduce((a, i) => a - i.rub, 0);
    const refunds = items.filter((i) => /Возврат/.test(i.title) && i.rub > 0).reduce((a, i) => a + i.rub, 0);
    const responses = items.filter((i) => /Отклик/.test(i.title)).length;
    const other = spentItems.filter((i) => !/Отклик/.test(i.title)).map((i) => `${i.title} ${-i.rub} ₽`);
    const lastDay = Math.max(1, ...items.map((i) => i.day || 0));
    const isCurrent = d.getMonth() === today.getMonth() && d.getFullYear() === today.getFullYear();
    const day = isCurrent ? today.getDate() : new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
    const net = Math.max(0, spent - refunds);
    out.push({
      month: `${d.getFullYear()}-${pad(d.getMonth() + 1)}`,
      date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(day)}`,
      amount: net,
      note: `Профи · ${MONTHS[d.getMonth()].toLowerCase()}, по ${lastDay} ${MONTHS_GEN[d.getMonth()]}: откликов ${responses}, списано ${spent} ₽, возвраты ${refunds} ₽${other.length ? ' (в т.ч. ' + other.join(', ') + ')' : ''} · автозагрузка`,
      items: items.length,
    });
  }
  return out;
})();
