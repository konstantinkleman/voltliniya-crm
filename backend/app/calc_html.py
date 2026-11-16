"""HTML-документы расчёта: КП (для клиента, открывается по ссылке с телефона), смета по тарифу, наполнение щита.
Страницы самодостаточные: стили внутри, печать в PDF из браузера («Поделиться → Печать» на телефоне)."""
from datetime import date
from html import escape

from . import calc

PHONE = "+7 911 469-16-70"
SITE = "voltliniya.ru"

CSS = """
:root{--navy:#14213D;--ink:#1B2430;--ink2:#4A5563;--mute:#7A8594;--line:#E3E6EA;--soft:#F5F6F8;--gold:#E2B33C;--gold-soft:#FBF3DE}
*{box-sizing:border-box}
body{margin:0;background:#EEF0F3;color:var(--ink);font:15px/1.45 -apple-system,"Segoe UI",Roboto,Manrope,Arial,sans-serif;-webkit-font-smoothing:antialiased}
.page{max-width:900px;margin:0 auto;background:#fff;min-height:100vh}
.top{background:var(--navy);color:#fff;padding:22px 28px 20px;display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
.brand{font-weight:800;font-size:20px;letter-spacing:.2px;display:flex;align-items:center;gap:10px}
.brand i{width:12px;height:26px;background:var(--gold);display:inline-block;clip-path:polygon(60% 0,0 58%,45% 58%,30% 100%,100% 38%,55% 38%)}
.contacts{font-size:13px;color:#C9D1DD;text-align:right}
.contacts a{color:#fff;text-decoration:none;font-weight:600}
.body{padding:22px 28px 30px}
h1{font-size:24px;margin:0 0 4px}
.obj{font-size:16px;font-weight:600;margin:0}
.sum{color:var(--ink2);font-size:14px;margin:4px 0 0}
.intro{color:var(--ink2);font-size:14px;margin:14px 0 18px}
.tariffs{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.t{border:1px solid var(--line);border-radius:14px;padding:16px 16px 14px;position:relative}
.t.rec{border:2px solid var(--gold);background:var(--gold-soft)}
.t .badge{position:absolute;top:-11px;left:14px;background:var(--gold);color:var(--navy);font-size:12px;font-weight:800;padding:2px 10px;border-radius:999px}
.t h3{margin:0;font-size:16px}
.t .price{font-size:28px;font-weight:800;margin:6px 0 2px;letter-spacing:-.3px;white-space:nowrap}
.t .sub{color:var(--ink2);font-size:13px}
.t .m2{margin-top:8px;font-weight:700;font-size:14px}
table.cmp{width:100%;border-collapse:collapse;margin-top:22px;font-size:14px}
table.cmp th,table.cmp td{border-bottom:1px solid var(--line);padding:10px 8px;text-align:left;vertical-align:top}
table.cmp th{font-size:13px;color:var(--mute);font-weight:700}
table.cmp td:first-child{color:var(--ink2);width:32%}
table.cmp td.rec,table.cmp th.rec{background:var(--gold-soft)}
.cards{display:none}
.opt{margin-top:18px;padding:12px 14px;border-radius:12px;background:var(--soft);display:flex;justify-content:space-between;gap:12px;font-size:14px}
.cond{margin-top:18px;font-size:13px;color:var(--ink2)}
.cond p{margin:4px 0}
.date{margin-top:16px;font-size:13px;color:var(--mute)}
.cta{margin-top:20px;display:flex;gap:10px;flex-wrap:wrap}
.cta a{flex:1;min-width:150px;text-align:center;text-decoration:none;font-weight:700;padding:12px 14px;border-radius:12px;background:var(--navy);color:#fff}
.cta a.l{background:#fff;color:var(--navy);border:1.5px solid var(--navy)}
table.est{width:100%;border-collapse:collapse;font-size:13.5px}
table.est td,table.est th{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
table.est th{font-size:12px;color:var(--mute);text-align:left}
table.est td.n,table.est th.n{text-align:right;white-space:nowrap}
table.est tr.hdr td{font-weight:800;font-size:15px;padding-top:18px;border-bottom:2px solid var(--navy)}
table.est tr.sub td{font-weight:700;background:var(--soft)}
table.est tr.note td{color:var(--ink2);font-size:13px;font-style:italic}
table.est tr.pt td{font-weight:700;color:var(--ink2);padding-top:12px}
table.est tr.tot td{font-weight:800;font-size:17px;border-top:2px solid var(--navy);border-bottom:0;padding-top:12px}
table.est tr.grp td{font-weight:700;background:var(--soft)}
table.est td.fl{text-align:center;font-weight:800}
.foot{margin-top:16px;font-size:13px;color:var(--ink2)}
.foot p{margin:4px 0}
.print{display:block;width:max-content;margin:0 auto;padding:22px 0 30px;background:none;border:0;color:var(--navy);font-weight:700;font-size:14px;text-decoration:underline;cursor:pointer}
@media (max-width:680px){
  .top{padding:16px 16px 14px}.body{padding:16px}
  .contacts{text-align:left}
  h1{font-size:21px}
  .tariffs{grid-template-columns:1fr}
  table.cmp{display:none}.cards{display:block;margin-top:18px}
  .card{border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:12px}
  .card.rec{border:2px solid var(--gold)}
  .card h3{margin:0 0 6px;font-size:16px}
  .card dl{margin:0;display:grid;grid-template-columns:1fr;gap:2px}
  .card dt{color:var(--mute);font-size:12px;margin-top:6px}.card dd{margin:0;font-size:14px}
  table.est{font-size:12.5px}table.est td,table.est th{padding:6px 4px}
}
@media print{body{background:#fff}.page{max-width:none}.print,.cta{display:none}.top{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .t.rec,td.rec,th.rec{-webkit-print-color-adjust:exact;print-color-adjust:exact} table.cmp{display:table!important}.cards{display:none!important}}
"""


def money(x: float, dec: bool = False) -> str:
    if dec and abs(x - round(x)) > 0.004:
        s = f"{x:,.2f}"
    else:
        s = f"{calc.xround(x):,.0f}"
    return s.replace(",", " ").replace(".", ",")


def qty(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return f"{round(x):,}".replace(",", " ")
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def page(title: str, body: str, printable: bool = True, pdf_url: str | None = None) -> str:
    if pdf_url:      # PDF одной страницей с сервера — без разрывов по листам A4
        btn = f'<a class="print" href="{escape(pdf_url)}" download>Скачать PDF</a>'
    else:
        btn = '<button class="print" onclick="window.print()">Сохранить PDF / печать</button>' if printable else ""
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><title>{escape(title)}</title><style>{CSS}</style></head>'
            f'<body><div class="page">{header()}<div class="body">{body}</div>{btn}</div></body></html>')


def header() -> str:
    tel = "+" + "".join(ch for ch in PHONE if ch.isdigit())
    return (f'<div class="top"><div class="brand"><i></i>ВольтЛиния</div>'
            f'<div class="contacts">черновой электромонтаж<br><a href="tel:{tel}">{PHONE}</a> · <a href="https://{SITE}">{SITE}</a></div></div>')


def kp_html(res: dict, when: date | None = None, public: bool = False, pdf_url: str | None = None) -> str:
    k = calc.kp(res)
    tcards = []
    for t in k["tariffs"]:
        rec = ' rec' if t["recommended"] else ''
        badge = '<span class="badge">рекомендуем</span>' if t["recommended"] else ''
        tcards.append(f'<div class="t{rec}">{badge}<h3>{t["name"]}</h3><div class="price">{money(t["price"], True)} ₽</div>'
                      f'<div class="sub">работы + материалы</div><div class="sub">работы {money(t["works"], True)} ₽<br>материалы {money(t["materials"], True)} ₽</div>'
                      f'<div class="m2">{money(t["per_m2"])} ₽/м²</div></div>')
    rec_i = [i for i, t in enumerate(k["tariffs"]) if t["recommended"]]
    head = "".join(f'<th class="{"rec" if i in rec_i else ""}">{escape(t["name"])}</th>' for i, t in enumerate(k["tariffs"]))
    rows = "".join("<tr><td>" + escape(r[0]) + "</td>" + "".join(
        f'<td class="{"rec" if i in rec_i else ""}">{escape(v)}</td>' for i, v in enumerate(r[1:])) + "</tr>" for r in k["rows"])
    cards = ""
    for i, t in enumerate(k["tariffs"]):
        items = "".join(f"<dt>{escape(r[0])}</dt><dd>{escape(r[1 + i])}</dd>" for r in k["rows"])
        cards += f'<div class="card{" rec" if t["recommended"] else ""}"><h3>{t["name"]} — {money(t["price"], True)} ₽</h3><dl>{items}</dl></div>'
    cond = "".join(f"<p>{escape(c)}</p>" for c in k["conditions"])
    obj = f'<p class="obj">Объект: {escape(k["object"])}</p>' if k["object"] else ""
    when = when or date.today()
    tel = "+" + "".join(ch for ch in PHONE if ch.isdigit())
    cta = f'<div class="cta"><a href="tel:{tel}">Позвонить {PHONE}</a></div>' if public else ""
    body = (f'<h1>Коммерческое предложение</h1>{obj}<p class="sum">{escape(k["summary"])}</p>'
            f'<p class="intro">{escape(k["intro"])}</p><div class="tariffs">{"".join(tcards)}</div>'
            f'<table class="cmp"><thead><tr><th></th>{head}</tr></thead><tbody>{rows}</tbody></table>'
            f'<div class="cards">{cards}</div>'
            f'<div class="opt"><span>Опция к «Базовому» и «Стандарту»: 3D-тур квартиры с трассами кабеля</span><b>{money(k["tour_option"])} ₽</b></div>'
            f'<div class="cond"><b>Условия</b>{cond}</div><div class="date">Дата предложения: {when:%d.%m.%Y}</div>{cta}')
    return page("КП — ВольтЛиния" + (f" — {k['object']}" if k["object"] else ""), body, pdf_url=pdf_url)


def smeta_html(res: dict, tariff: str, when: date | None = None) -> str:
    s = calc.smeta(res, tariff)
    d = res["inputs"]
    v = res["volumes"]
    pn = res["panel"]["basic" if tariff == "basic" else "std"]
    rows = []
    for sec in s["sections"]:
        if not sec["lines"] and not sec.get("panel") and not sec.get("note"):
            continue
        rows.append(f'<tr class="hdr"><td>{escape(sec["title"])}</td><td class="n">Кол-во</td><td class="n">Цена</td><td class="n">Сумма</td></tr>')
        if sec.get("note"):
            rows.append(f'<tr class="note"><td colspan="4">{escape(sec["note"])}</td></tr>')
        for ln in sec["lines"]:
            rows.append(f'<tr><td>{escape(ln["name"])}</td><td class="n">{qty(ln["qty"])}</td><td class="n">{money(ln["price"], True)}</td>'
                        f'<td class="n">{money(calc._ls(ln), True)}</td></tr>')
        if sec.get("panel"):
            rows.append(f'<tr class="pt"><td colspan="4">{escape(sec["panel_title"])}</td></tr>')
            for ln in sec["panel"]:
                rows.append(f'<tr><td>{escape(ln["name"])}</td><td class="n">{qty(ln["qty"])}</td><td class="n">{money(ln["price"], True)}</td>'
                            f'<td class="n">{money(calc._ls(ln), True)}</td></tr>')
        label = {"1. Работы": "Итого работы", "2. Материалы": "Итого материалы"}.get(sec["title"],
                                                                                       "Итого чистовая установка" if "Чистовая" in sec["title"] else "Итого по тарифу")
        sec_total = round(sum(calc._ls(ln) for ln in sec["lines"] + sec.get("panel", [])), 2)     # как в договоре
        rows.append(f'<tr class="sub"><td colspan="3">{label}</td><td class="n">{money(sec_total, True)}</td></tr>')
    rows.append(f'<tr class="tot"><td colspan="3">ИТОГО К ОПЛАТЕ</td><td class="n">{money(calc.smeta_price(s), True)} ₽</td></tr>')
    obj = f'<p class="obj">Объект: {escape(d["object"])}</p>' if d["object"] else ""
    info = (f'{d["area"]:g} м² · {v["points"]:g} электроточек · кабель ~{calc.xround(v["cable_power"], -1):g} м · '
            f'щит {pn["assembly_qty"]:g} модулей')
    foot = "".join(f"<p>{escape(x)}</p>" for x in s["footer"])
    when = when or date.today()
    body = (f'<h1>Смета — тариф «{s["tariff_name"]}»</h1>{obj}<p class="sum">{escape(info)}</p>'
            f'<table class="est" style="margin-top:10px"><tbody>{"".join(rows)}</tbody></table>'
            f'<div class="foot">{foot}<p>Дата: {when:%d.%m.%Y}</p></div>')
    return page(f"Смета «{s['tariff_name']}»", body)


def panel_html(res: dict, tariff: str) -> str:
    f = calc.panel_fill(res, tariff)
    d = res["inputs"]
    rows = []
    for r in f["rows"]:
        cls = ' class="grp"' if r["top"] and not r["mod"] else ""
        rows.append(f'<tr{cls}><td>{escape(r["no"])}</td><td>{escape(r["device"])}</td><td>{escape(r["purpose"])}</td>'
                    f'<td class="fl">{escape(r["flag"])}</td><td class="n">{qty(r["mod"]) if r["mod"] else ""}</td></tr>')
    obj = f'<p class="obj">Объект: {escape(d["object"])}</p>' if d["object"] else ""
    hdr = "".join(f'<p class="sum">{escape(x)}</p>' for x in f["header"])
    notes = "".join(f"<p>• {escape(x.lstrip('• '))}</p>" for x in f["notes"])
    body = (f'<h1>Наполнение электрощита — для монтажника</h1>{obj}{hdr}'
            f'<table class="est" style="margin-top:12px"><thead><tr><th>№</th><th>Аппарат</th><th>Назначение (линия)</th>'
            f'<th>Через мастер-выкл.</th><th class="n">Мод.</th></tr></thead><tbody>{"".join(rows)}'
            f'<tr class="tot"><td colspan="4">Итого модулей</td><td class="n">{qty(f["modules"])}</td></tr></tbody></table>'
            f'<div class="foot">{notes}</div>')
    return page("Щит для монтажника", body)
