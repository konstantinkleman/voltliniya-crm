"""Пакет документов по расчёту: договор подряда от ИП (заказчик — физлицо или ИП/ООО), Приложение № 1 (смета),
Приложение № 2 (спецификация), акт сдачи-приёмки, памятка с гарантийным талоном, две квитанции, щит для монтажника.

Перенос сформировать_документы.py: те же шаблоны (contract_tpl/), те же правила подстановки по порядку мест [___].
Отличия от скрипта: данные берутся из расчёта CRM, а не из листов Excel; в спецификацию щита попадают только
аппараты и корпуса (в скрипте второй «note» на листе «СметаДанные» добавлял в щит строки условий тарифа);
подпись представителя организации — отдельным полем.

В шаблонах договора банковские реквизиты и адрес ИП заменены метками {{C_*}} (репозиторий публичный) —
значения берутся из справочника «Реквизиты исполнителя» (CalcParam, раздел contractor).
"""
import io
import os
import re
import zipfile
from copy import copy
from datetime import date, timedelta

from . import calc

TPL = os.path.join(os.path.dirname(__file__), "contract_tpl")
GUAR = {"basic": 12, "std": 36, "turnkey": 60}
LIMIT = {"basic": 0, "std": 3, "turnkey": 8}
CONTRACTOR_KEYS = {"C_ADDRESS": "contractor.address", "C_ACCOUNT": "contractor.account", "C_BANK": "contractor.bank",
                   "C_CORR": "contractor.corr", "C_BIK": "contractor.bik"}

# поля договора: (ключ, подпись) — для формы и проверки заполненности
PERSON_FIELDS = [("fio", "Фамилия Имя Отчество"), ("birth", "Дата рождения"), ("pass_series", "Паспорт: серия"),
                 ("pass_number", "Паспорт: номер"), ("pass_issued", "Паспорт: кем выдан"), ("pass_date", "Паспорт: дата выдачи"),
                 ("pass_code", "Паспорт: код подразделения"), ("reg_address", "Адрес регистрации"),
                 ("phone", "Телефон / WhatsApp"), ("email", "E-mail")]
ORG_FIELDS = [("org_name", "Полное наименование / ИП ФИО"), ("ogrn", "ОГРН / ОГРНИП"), ("inn", "ИНН"), ("kpp", "КПП (для ООО)"),
              ("legal_address", "Юридический адрес"), ("signer", "В лице (должность, ФИО)"), ("basis", "Действует на основании"),
              ("sign_name", "Подпись: Фамилия И.О."), ("account", "Расчётный счёт"), ("bank", "Банк"), ("corr", "Корр. счёт"),
              ("bik", "БИК"), ("org_phone", "Телефон"), ("org_email", "E-mail")]
COMMON_FIELDS = [("number", "Номер договора"), ("date", "Дата договора"), ("address", "Адрес объекта"),
                 ("start", "Ориентировочная дата начала"), ("end", "Дата окончания работ"), ("advance", "Аванс, ₽")]
OPTIONAL = {"email", "org_email", "kpp", "advance", "sign_name", "birth"}

# ---------- сумма прописью ----------
_U = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать",
      "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_UF = ["", "одна", "две"]
_T = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_H = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _triad(n, fem=False):
    w = []
    h, r = divmod(n, 100)
    if h:
        w.append(_H[h])
    if r < 20:
        if r:
            w.append(_UF[r] if fem and r < 3 else _U[r])
    else:
        t, u = divmod(r, 10)
        w.append(_T[t])
        if u:
            w.append(_UF[u] if fem and u < 3 else _U[u])
    return " ".join(w)


def plural(n, forms):
    n = abs(int(n)) % 100
    if 10 < n < 20:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def num2words(n) -> str:
    n = int(calc.xround(n))
    if n == 0:
        return "ноль"
    parts = []
    for base, forms, fem in [(10 ** 9, ("миллиард", "миллиарда", "миллиардов"), False),
                             (10 ** 6, ("миллион", "миллиона", "миллионов"), False),
                             (10 ** 3, ("тысяча", "тысячи", "тысяч"), True)]:
        q, n = divmod(n, base)
        if q:
            parts.append(_triad(q, fem) + " " + plural(q, forms))
    if n:
        parts.append(_triad(n))
    return " ".join(parts)


def rub_words(n) -> str:
    n = int(calc.xround(n))
    return fmt_money(n) + " (" + num2words(n) + ") " + plural(n, ("рубль", "рубля", "рублей"))


def fmt_money(n) -> str:
    return f"{int(calc.xround(n)):,}".replace(",", " ")


def parse_date(s) -> date | None:
    if isinstance(s, date):
        return s
    s = str(s or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s) or None
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def fmt_date(s) -> str:
    d = parse_date(s)
    return d.strftime("%d.%m.%Y") if d else str(s or "")


def date_words(s) -> str | None:
    d = parse_date(s)
    return f"«{d.day:02d}» {MONTHS[d.month - 1]} {d.year} г." if d else None


def short_fio(fio) -> str:
    p = str(fio or "").split()
    if not p:
        return "[___]"
    return p[0] + " " + "".join(x[0] + "." for x in p[1:3])


# ---------- суммы договора из расчёта ----------
def numbers(res: dict, tariff: str, advance=None) -> dict:
    """Как лист «Договор»: цена = итог сметы до рубля, аванс = материалы до тысяч, этап 2 = чистовая (Под ключ)."""
    sm = calc.smeta(res, tariff)
    by = {s["title"].split(". ", 1)[-1]: s for s in sm["sections"]}
    works = by["Работы"]["total"]
    mats = by["Материалы"]["total"]
    cond = by["Условия тарифа"]["total"]
    fin = by["Чистовая установка после отделки (этап 2)"]["total"] if tariff == "turnkey" else 0.0
    # цена = сумма строк Приложения № 1 в том виде, как они напечатаны (кол-во и цена до копеек), до рубля —
    # чтобы итог сметы сходился со строками; от итога «СметаДанные» в Excel отличается на 1–3 ₽
    price = calc.smeta_price(sm)     # = цена в КП
    adv_default = calc.xround(mats, -3)
    adv = adv_default if advance in (None, "") else calc.xround(calc.num(advance))
    fin = calc.xround(fin)
    mech = int(sum(f["qty"] for f in res["finishing"])) if tariff == "turnkey" else 0
    return {"tariff": tariff, "tariff_name": calc.TARIFF_NAMES[tariff], "price": price, "works": works, "materials": mats,
            "conditions": cond, "advance": adv, "advance_default": adv_default, "stage2": fin, "rest": price - adv - fin,
            "guarantee": GUAR[tariff], "limit": LIMIT[tariff], "mech": mech, "brand": res["inputs"]["brand"],
            "smeta": sm}


_q = _p = calc.shown


def default_data(lead=None, inputs: dict | None = None, today: date | None = None) -> dict:
    t = today or date.today()
    return {"kind": "person", "number": t.strftime("%d%m/%y"), "date": t.isoformat(),
            "start": (t + timedelta(days=7)).isoformat(), "end": (t + timedelta(days=28)).isoformat(),
            "address": (getattr(lead, "address", None) or (inputs or {}).get("object") or ""),
            "phone": getattr(lead, "phone", None) or "", "basis": "Устава", "advance": None}


def missing(data: dict, contractor: dict) -> list[str]:
    """Что не заполнено — в документах останутся места [___]."""
    out = []
    fields = COMMON_FIELDS + (PERSON_FIELDS if data.get("kind", "person") == "person" else ORG_FIELDS)
    for k, label in fields:
        if k not in OPTIONAL and not str(data.get(k) or "").strip():
            out.append(label)
    for tok, key in CONTRACTOR_KEYS.items():
        if not (contractor.get(key) or "").strip():
            out.append("Реквизиты исполнителя: " + {"C_ADDRESS": "адрес", "C_ACCOUNT": "расчётный счёт", "C_BANK": "банк",
                                                    "C_CORR": "корр. счёт", "C_BIK": "БИК"}[tok])
    return out


# ---------- docx ----------
PH = re.compile(r"\[[^\[\]]*(?:\[___\][^\[\]]*)?\]")   # [___], [текст], а также [текст … [___]]
DATE = re.compile(r"«___»(?:</w:t>.*?<w:t[^>]*>)?\s*_+\s*(?:</w:t>.*?<w:t[^>]*>)?20___ г\.", re.S)


def esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fill_docx(name: str, ph_values, date_values=(), extra=(), contractor: dict | None = None, footer_num: str | None = None) -> bytes:
    """ph_values — значения по порядку мест [..] (None — оставить как есть); date_values — то же для «___» ____ 20___ г.;
    extra — замены текста (значения уже экранированы)."""
    src = os.path.join(TPL, name)
    out = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "word/document.xml":
                xml = data.decode("utf-8")
                for a, b in extra:
                    xml = xml.replace(a, b)
                i = [0]

                def rep(m):
                    k = i[0]
                    i[0] += 1
                    v = ph_values[k] if k < len(ph_values) else None
                    return m.group(0) if v in (None, "") else esc(v)
                xml = PH.sub(rep, xml)
                j = [0]

                def repd(m):
                    k = j[0]
                    j[0] += 1
                    v = date_values[k] if k < len(date_values) else None
                    return m.group(0) if v in (None, "") else esc(v)
                xml = DATE.sub(repd, xml)
                # «… сорок один) рублей» → «рубль», «… два) рублей» → «рубля» (в шаблоне слово «рублей» после места для суммы)
                xml = re.sub(r"(\bодин\)\s*)рублей", r"\1рубль", xml)
                xml = re.sub(r"(\b(?:два|три|четыре)\)\s*)рублей", r"\1рубля", xml)
                for tok, key in CONTRACTOR_KEYS.items():
                    xml = xml.replace("{{" + tok + "}}", esc((contractor or {}).get(key) or "[___]"))
                data = xml.encode("utf-8")
            elif footer_num and re.fullmatch(r"word/footer\d*\.xml", it.filename):
                data = data.decode("utf-8").replace("№ [___]", "№ " + esc(footer_num)).encode("utf-8")
            zout.writestr(it, data)
    return out.getvalue()


# ---------- пакет ----------
def build(res: dict, tariff: str, data: dict, contractor: dict) -> dict[str, bytes]:
    """Возвращает {имя файла: содержимое}."""
    g = lambda k, default="[___]": (str(data.get(k)).strip() if data.get(k) not in (None, "") else default)  # noqa: E731
    N = numbers(res, tariff, data.get("advance"))
    price, advance, fin, rest = N["price"], N["advance"], N["stage2"], N["rest"]
    guar, limit, mech, brand = N["guarantee"], N["limit"], N["mech"], N["brand"]
    person = data.get("kind", "person") == "person"
    num = g("number", "___")
    dt = data.get("date")
    obj_addr = g("address", "[адрес Объекта]")
    fio = g("fio")
    org = g("org_name")
    customer_name = fio if person else org
    if person:
        customer_short = short_fio(data.get("fio"))
    else:
        sn = (data.get("sign_name") or "").strip()
        signer = (data.get("signer") or "").split()
        customer_short = sn or (short_fio(" ".join(signer[-3:])) if signer else "[___]")
    mon = plural(guar, ("месяц", "месяца", "месяцев"))
    files: dict[str, bytes] = {}
    safe_num = re.sub(r"[^\w\-]+", "-", num)

    # --- договор
    extra = []
    if tariff == "basic":
        extra.append(("Цена Договора является твёрдой (п. 4 ст. 709 ГК РФ) и составляет",
                      "Цена Договора определяется по фактически выполненному объёму Работ по расценкам Сметы (Приложение № 1) и уточняется "
                      "в Акте сдачи-приёмки (п. 3 ст. 709 ГК РФ); ориентировочная цена по Смете составляет"))
    elif limit > 0:
        stage2 = ""
        if fin > 0:
            stage2 = (f" Этап 2 (чистовая установка): после завершения отделочных работ Подрядчик устанавливает и подключает электроустановочные "
                      f"изделия Заказчика (розетки, в том числе интернет-розетки, выключатели, терморегуляторы) в количестве до {mech} шт. по Схеме; "
                      f"стоимость этапа 2 — {rub_words(fin)} 00 копеек — входит в Цену Договора и оплачивается в течение 3 рабочих дней после "
                      f"подписания акта по этапу 2 (п. 2.3.2 применяется к стоимости этапа 1 в размере {rub_words(price - fin)}). "
                      "Электроустановочные изделия, светильники и иное оборудование приобретает Заказчик; установка светильников, бра, светодиодной "
                      "подсветки и подключение бытовой техники в этап 2 не входят и выполняются по отдельному согласованию. "
                      "Заказчик уведомляет Подрядчика о готовности Объекта к этапу 2; Подрядчик приступает в течение 10 рабочих дней после уведомления. "
                      "Если уведомление не поступило в течение 12 месяцев с даты акта по этапу 1, обязательство по этапу 2 прекращается, а его "
                      "стоимость с Заказчика не взимается.")
        extra.append(("Устные договорённости о дополнительных работах юридической силы не имеют.",
                      "Устные договорённости о дополнительных работах юридической силы не имеют. При этом до "
                      f"{limit} изменений расположения электроточек или добавлений электроточек, заявленных Заказчиком до закрытия штроб и "
                      "монтажа потолков, Подрядчик выполняет без изменения Цены Договора и без оформления дополнительного соглашения; изменения "
                      "сверх этого количества оплачиваются по расценкам Сметы." + stage2))
    extra.append(("] месяца", "] " + mon))
    cust25 = calc.num(res["inputs"].get("cust_cable25"))
    if cust25:
        extra.append(("Замена позиции Спецификации на аналог с не худшими характеристиками допускается по согласованию с Заказчиком в порядке раздела 11 Договора.",
                      "Замена позиции Спецификации на аналог с не худшими характеристиками допускается по согласованию с Заказчиком в порядке "
                      f"раздела 11 Договора. Кабель ВВГнг-LS 3×2,5 в количестве {int(cust25)} м предоставляет Заказчик (материал Заказчика, отмечен "
                      "в Спецификации): его стоимость в Цену Договора не входит, Подрядчик проверяет его соответствие ГОСТ при приёмке, гарантия "
                      "Подрядчика на этот материал не распространяется (ст. 713 ГК РФ)."))
    common = [num, None, None, None, None, None, obj_addr, fmt_money(price), num2words(price), fmt_money(advance), num2words(advance),
              fmt_money(rest), num2words(rest), num, fmt_date(dt), None, None, f"{guar} ({num2words(guar)})"]
    ph = list(common)
    if person:
        issued = g("pass_issued")
        ph[1:6] = [fio, g("pass_series"), g("pass_number"), issued + (", " + fmt_date(data["pass_date"]) if data.get("pass_date") else ""),
                   g("reg_address")]
        ph += [fio, fmt_date(data.get("birth")) or "[___]", g("pass_series"), g("pass_number"), issued,
               fmt_date(data.get("pass_date")) or "[дата]", g("pass_code"), g("reg_address"), g("phone"), g("email"), customer_short]
        src = "dogovor_fiz.docx"
    else:
        ph[1:6] = [org, g("ogrn"), g("inn"), g("signer"), g("basis", "Устава")]
        ph += [org, g("inn"), g("kpp", "—"), g("ogrn"), g("legal_address"), g("account"), g("bank"), g("corr"), g("bik"),
               g("org_phone"), g("org_email"), g("signer"), g("basis", "Устава"), customer_short]
        src = "dogovor_org.docx"
    files[f"01_Договор_{safe_num}.docx"] = fill_docx(src, ph, [date_words(dt), date_words(data.get("start")), date_words(data.get("end"))],
                                                     extra, contractor, footer_num=num)
    dnum = f"{num} от {fmt_date(dt)}"
    files["02_Приложение_1_Смета.xlsx"] = smeta_xlsx(N, tariff, dnum, obj_addr, customer_name, customer_short)
    files["03_Приложение_2_Спецификация.xlsx"] = spec_xlsx(res, N, dnum, obj_addr, customer_name, customer_short)
    # --- акт (суммы по договору; остальное заполняется при сдаче)
    act = [num, num, obj_addr, None, fmt_money(price - fin), num2words(price - fin), fmt_money(advance), None, fmt_money(rest),
           None, None, None, None, None, None, str(guar), customer_short]
    files["05_Акт_сдачи-приёмки.docx"] = fill_docx("akt.docx", act, [None, date_words(dt)], [("] месяца", "] " + mon)], footer_num=num)
    files["06_Памятка_и_гарантийный_талон.docx"] = fill_docx("pamyatka.docx", [num, obj_addr, str(guar), customer_short],
                                                             [date_words(dt)], [("] месяца", "] " + mon)])
    q = [num + "/1", obj_addr, num, "1 — аванс", num, "аванс", fmt_money(advance), num2words(advance), customer_name, "Клемань К.В.",
         customer_short, num + "/2", obj_addr, num, "2 — окончательный расчёт", num, "окончательный расчёт", fmt_money(rest),
         num2words(rest), customer_name, "Клемань К.В.", customer_short]
    files["07_Квитанции.docx"] = fill_docx("kvitanciya.docx", q, [None, date_words(dt), None, date_words(dt)])
    files["08_Щит_для_монтажника.xlsx"] = panel_xlsx(res, tariff)
    return files


def zip_files(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


# ---------- Приложение 1 — смета ----------
def unit(name: str) -> str:
    n = name.lower()
    if "модул" in n and "сборка" in n:
        return "модуль"
    if "пачек" in n:
        return "пач."
    if "упак" in n:
        return "уп."
    if any(k in n for k in ("кабел", "ввгнг", "гофра", "пугв", "витая", "штроблен", "прокладка")):
        return "п.м"
    if any(k in n for k in ("пакет", "тариф", "расходники", "вынос", "проход")):
        return "объект"
    if "оклейка" in n:
        return "проём"
    return "шт."


SEC_TITLES = {"Работы": "Работы", "Материалы": "Применяемые материалы, изделия и оборудование", "Условия тарифа": "Условия тарифа"}
SUBS = {"Работы": "Итого работы", "Материалы": "Итого материалы", "Условия тарифа": "Итого по тарифу",
        "Чистовая установка после отделки (этап 2)": "Итого чистовая установка"}


def smeta_xlsx(N: dict, tariff: str, dnum: str, obj_addr: str, customer_name: str, customer_short: str) -> bytes:
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.load_workbook(os.path.join(TPL, "smeta.xlsx"))
    ws = wb.active
    st_sec = [copy(ws[f"{c}10"]._style) for c in "ABCDEF"]
    st_line = [copy(ws[f"{c}11"]._style) for c in "ABCDEF"]
    st_tot = [copy(ws[f"{c}34"]._style) for c in "ABCDEF"]
    foot = {r: [(c, ws[f"{c}{r}"].value, copy(ws[f"{c}{r}"]._style)) for c in "ABCDEF"] for r in range(36, 48)}
    for mr in list(ws.merged_cells.ranges):
        if mr.min_row >= 10:
            ws.unmerge_cells(str(mr))
    for r in range(10, 60):
        for c in "ABCDEF":
            ws[f"{c}{r}"].value = None
    ws["A2"] = f"к Договору подряда на выполнение электромонтажных работ № {dnum}"
    ws["A5"] = "Объект: " + obj_addr
    ws["B5"] = None
    ws["A6"] = "Заказчик: " + customer_name
    ws["B6"] = None
    ws["A7"] = ("Перечень, объём и стоимость Работ и применяемых материалов (п. 1.2, 1.3, 2.1 Договора). Цена Договора едина и включает работы, "
                "применяемые в них материалы, изделия и оборудование по Спецификации (Приложение № 2), их доставку и все издержки Подрядчика "
                "(п. 2 ст. 709 ГК РФ, п. 2.2 Договора). Материалы применяются Подрядчиком при выполнении Работ (ст. 704 ГК РФ) и отдельно не реализуются.")
    if tariff == "basic":
        ws["A7"] = ws["A7"].value + " Тариф «Базовый»: окончательная стоимость определяется по фактически выполненному объёму по расценкам настоящей Сметы."
    ws.row_dimensions[7].height = 62
    r = 10
    n = 0

    def put(vals, styles):
        for c, v, s in zip("ABCDEF", vals, styles):
            cell = ws[f"{c}{r}"]
            cell.value = v
            cell._style = copy(s)

    for s in N["smeta"]["sections"]:
        key = s["title"].split(". ", 1)[-1]
        lines = [ln for ln in s["lines"] if ln["qty"] > 0] + [ln for ln in s.get("panel", []) if ln["qty"] > 0]
        if not lines:
            continue
        put([SEC_TITLES.get(key, key), None, None, None, None, None], st_sec)
        ws.merge_cells(f"A{r}:F{r}")
        r += 1
        first = r
        for ln in lines:
            n += 1
            put([n, ln["name"], unit(ln["name"]), _q(ln["qty"]), _p(ln["price"]), f"=D{r}*E{r}"], st_line)
            r += 1
        put([None, SUBS.get(key, "Итого"), None, None, None, f"=SUM(F{first}:F{r - 1})"], st_line)
        for c in "BF":
            ws[f"{c}{r}"].font = Font(name=ws[f"{c}{r}"].font.name, size=ws[f"{c}{r}"].font.size, bold=True)
        r += 1
    put(["ИТОГО ЦЕНА ДОГОВОРА, руб. (НДС не облагается)", None, None, None, None, N["price"]], st_tot)
    ws.merge_cells(f"A{r}:E{r}")
    r += 2
    guar = N["guarantee"]
    foot_vals = {36: N["tariff_name"], 37: f"{guar} " + plural(guar, ("месяц", "месяца", "месяцев")), 38: f"{N['brand']} — по Спецификации",
                 39: {"basic": "уборка после работ", "std": "защита окон/дверей + уборка",
                      "turnkey": "защита окон/дверей + уборка + вывоз мусора"}[tariff],
                 40: fmt_money(N["advance"]), 41: fmt_money(N["rest"]), 47: f"_______________ / {customer_short} /"}
    for src_r in range(36, 48):
        for c, v, s in foot[src_r]:
            cell = ws[f"{c}{r}"]
            cell._style = copy(s)
            cell.value = foot_vals.get(src_r) if (c == "D" and src_r in foot_vals) else v
        if src_r in (36, 37, 38, 39, 40, 41):
            ws.merge_cells(f"A{r}:C{r}")
            ws.merge_cells(f"D{r}:F{r}")
        if src_r == 43:
            ws.merge_cells(f"A{r}:F{r}")
            ws.row_dimensions[r].height = 42
        r += 1
    ws.print_area = f"A1:F{r}"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------- Приложение 2 — спецификация ----------
def _maker(nm: str, brand: str) -> str:
    n = nm.lower()
    if n.startswith("корпус"):
        return "ABB"
    if "реле напряжения" in n:
        return "[HS / DigiTOP / иное]"
    if n.startswith("шины"):
        return "[марка]"
    if brand == "ABB":
        if "контактор" in n:
            return "ABB ESB"
        if n.startswith("узо"):
            return "ABB FH202"
        if n.startswith("диф") and "3p+n" in n:
            return "ABB DS204"
        if n.startswith("диф"):
            return "ABB DS201"
        return "ABB S200"
    if "контактор" in n:
        return "Dekraft МК-103"
    if n.startswith("узо"):
        return "Dekraft УЗО-03"
    if n.startswith("диф"):
        return "Dekraft ДИФ-103"
    return "Dekraft ВА-103"


def _shift_merges(ws, idx, k):
    ms = [mr for mr in list(ws.merged_cells.ranges) if mr.min_row >= idx]
    for mr in ms:
        ws.unmerge_cells(str(mr))
    return [(mr.min_col, mr.min_row + k, mr.max_col, mr.max_row + k) for mr in ms]


def _remerge(ws, lst):
    for c1, r1, c2, r2 in lst:
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def _ins(ws, idx, k, style_row):
    if k <= 0:
        return
    lst = _shift_merges(ws, idx, k)
    hs = {r: d.height for r, d in ws.row_dimensions.items() if d.height and r >= idx}
    ws.insert_rows(idx, k)
    for r in sorted(hs, reverse=True):
        ws.row_dimensions[r + k].height = hs[r]
        ws.row_dimensions[r].height = None
    for r in range(idx, idx + k):
        for c in "ABCDEF":
            ws[f"{c}{r}"]._style = copy(ws[f"{c}{style_row}"]._style)
    _remerge(ws, lst)


def _del(ws, idx, k):
    if k <= 0:
        return
    lst = _shift_merges(ws, idx + k, -k)
    ws.delete_rows(idx, k)
    _remerge(ws, lst)


def spec_xlsx(res: dict, N: dict, dnum: str, obj_addr: str, customer_name: str, customer_short: str) -> bytes:
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(TPL, "spec.xlsx"))
    w = wb.active
    q = {m["key"]: float(m["qty"] or 0) for m in res["materials"]}
    brand = N["brand"]
    w["A2"] = f"к Договору подряда на выполнение электромонтажных работ № {dnum}"
    w["A5"] = "Объект: " + obj_addr
    w["B5"] = None
    w["A6"] = "Заказчик: " + customer_name
    w["B6"] = None
    w["E11"] = q.get("vvg15", 0)
    w["E12"] = q.get("vvg25", 0)
    if q.get("vvg25_cust"):
        w["F12"] = f"дополнительно {int(q['vvg25_cust'])} м предоставляет Заказчик (материал Заказчика, п. 1.3 Договора)"
    w["B13"] = "Кабель ВВГнг(А)-LS 3×6 (варочная панель при однофазном вводе, однофазный проточный водонагреватель)"
    w["F13"] = None
    w["B14"] = "Кабель ВВГнг(А)-LS 5×4 (варочная панель при трёхфазном вводе, трёхфазный проточный водонагреватель)"
    w["E13"] = q.get("vvg36", 0)
    w["E14"] = q.get("vvg54", 0)
    w["E15"] = q.get("pugv6", 0)
    w["E16"] = q.get("pugv4", 0)
    w["B16"] = "Провод ПУгВ 1×4 жёлто-зелёный (СУП)"
    w["E17"] = q.get("twisted", 0)
    w["E29"] = float(res["volumes"]["kup"])
    w["E31"] = q.get("box", 0)
    w["B32"] = "Клеммники Wago (упак.) и гильзы соединительные"
    w["C32"] = "WAGO"
    w["D32"] = "упак./шт."
    w["E32"] = f'{int(q.get("wago", 0))} уп. + {int(q.get("sleeve", 0))} шт.'
    w["E33"] = q.get("corr_pvc", 0)
    if q.get("corr_pnd"):
        w["B33"] = "Труба гофрированная ПВХ d20 (серая) / ПНД d20 (по полу)"
        w["E33"] = f'{int(q.get("corr_pvc", 0))} ПВХ + {int(q["corr_pnd"])} ПНД'
    w["E34"] = q.get("corr_clip", 0) + q.get("pad", 0)
    extras = []
    if q.get("tape"):
        extras.append(f'нейлоновая монтажная лента {int(q["tape"])} бухт по 100 м')
    if q.get("dowel"):
        extras.append(f'дюбель-хомуты {int(q["dowel"])} пач.')
    if q.get("chase_clips"):
        extras.append(f'клипсы для кабеля в штробе {int(q["chase_clips"])} пач.')
    if extras:
        w["F35"] = "в т.ч. " + ", ".join(extras)
    w["E36"] = q.get("box_cap", 0)
    w["D42"] = f"_______________ / {customer_short} /"
    # не учтённый материал — после строки «Заглушки»
    unacc = [(m["name"] or "Не учтённый материал", float(m["qty"])) for m in res["materials"]
             if m["key"].startswith("extra") and m["qty"] and m["price"]]
    if unacc:
        _ins(w, 37, len(unacc), 36)
        for i, (nm, qq) in enumerate(unacc):
            for c, v in zip("ABCDEF", [0, nm, "—", "шт.", qq, "дополнительно"]):
                w[f"{c}{37 + i}"] = v
    # щит — строки 19–28 шаблона
    sec = next(s for s in N["smeta"]["sections"] if s["title"].endswith("Материалы"))
    shield = [(ln["name"], float(ln["qty"])) for ln in sec.get("panel", []) if ln["qty"] > 0]
    slots = 10
    k = len(shield)
    if k > slots:
        _ins(w, 29, k - slots, 28)
    elif k < slots:
        _del(w, 19 + k, slots - k)
    for i, (nm, qq) in enumerate(shield):
        for c, v in zip("ABCDEF", [0, nm, _maker(nm, brand), "к-т" if nm.lower().startswith("шины") else "шт.", qq, None]):
            w[f"{c}{19 + i}"] = v
    n = 0
    for r in range(10, w.max_row + 1):
        v = w[f"A{r}"].value
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            n += 1
            w[f"A{r}"] = n
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------- щит для монтажника ----------
def panel_xlsx(res: dict, tariff: str) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    f = calc.panel_fill(res, tariff)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Щит"
    for col, wd in zip("ABCDE", (7, 30, 54, 14, 7)):
        ws.column_dimensions[col].width = wd
    th = Side(style="thin", color="FFBFBFBF")
    brd = Border(left=th, right=th, top=th, bottom=th)
    blue = PatternFill("solid", fgColor="FF2F5496")
    lb = PatternFill("solid", fgColor="FFD9E1F2")
    ws["A1"] = "Наполнение электрощита — для монтажника"
    ws["A1"].font = Font(name="Calibri", size=16, bold=True, color="FF2F5496")
    r = 2
    if res["inputs"].get("object"):
        ws.cell(r, 1, "Объект: " + str(res["inputs"]["object"])).font = Font(name="Calibri", bold=True, size=11)
        r += 1
    for h in f["header"]:
        ws.cell(r, 1, h).font = Font(name="Calibri", size=11)
        r += 1
    r += 1
    for c, v in enumerate(["№", "Аппарат", "Назначение (линия)", "Через мастер-выкл.", "Мод."], 1):
        x = ws.cell(r, c, v)
        x.font = Font(name="Calibri", bold=True, color="FFFFFFFF")
        x.fill = blue
        x.border = brd
        x.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r].height = 34
    r += 1
    for row in f["rows"]:
        vals = [row["no"], row["device"], row["purpose"], row["flag"], row["mod"] or None]
        grp = row["top"] and not row["mod"]
        for c, v in enumerate(vals, 1):
            x = ws.cell(r, c, v)
            x.border = brd
            x.alignment = Alignment(horizontal="center" if c in (1, 4, 5) else "left", vertical="center", wrap_text=(c == 3))
            x.font = Font(name="Calibri", size=11, bold=row["top"])
            if grp or str(row["device"]).startswith("УЗО"):
                x.fill = lb
        r += 1
    ws.cell(r, 1, "Итого модулей").font = Font(name="Calibri", bold=True, size=11)
    ws.cell(r, 5, f["modules"]).font = Font(name="Calibri", bold=True, size=11)
    r += 2
    for note in f["notes"]:
        ws.cell(r, 1, "• " + note.lstrip("• ")).font = Font(name="Calibri", size=10)
        r += 1
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
