"""Пакет документов ИП по фикстурам калькулятора: без БД и FastAPI.

PYTHONPATH=. python tests/contract_test.py
Сверка текстов с исходным make_ip_docs.py — tests/excel_check/README.md, раздел «Договор».
"""
import io
import json
import pathlib
import re

import docx
import openpyxl

from app import calc, contract
from app.calc_defaults import DEFAULTS

P = {k: {"v1": v1, "v2": v2, "v3": v3, "vtext": vt} for (k, s, l, u, v1, v2, v3, n, vt) in DEFAULTS}
fx = json.loads((pathlib.Path(__file__).parent / "calc_fixtures.json").read_text())
CON = {"contractor.address": "Адрес ИП", "contractor.account": "40802810000000000001", "contractor.bank": "Банк",
       "contractor.corr": "30101810000000000002", "contractor.bik": "044500001", "contractor.phone": "+7 900 000-00-01",
       "contractor.email": "ip@example.com"}
BASE = {"number": "1611/26", "date": "2026-11-16", "end": "2026-12-16", "address": "Москва, ул. Тестовая, 1"}
PERSON = {**BASE, "kind": "person", "fio": "Иванова Анна Сергеевна", "birth": "1985-03-04", "pass_series": "4510",
          "pass_number": "123456", "pass_issued": "ГУ МВД РОССИИ ПО Г. МОСКВЕ", "pass_date": "2015-06-07", "pass_code": "770-001",
          "reg_address": "Москва, ул. Регистрационная, 1", "phone": "+7 900 000-00-00", "email": "a@b.ru"}
ORG = {**BASE, "kind": "org", "org_name": "ООО «Тест»", "ogrn": "1027700000000", "inn": "7700000000", "kpp": "770001001",
       "legal_address": "Москва, ул. Юридическая, 5", "signer": "генерального директора Петрова Петра Петровича", "basis": "Устава",
       "account": "40702810000000000001", "bank": "ПАО Банк", "corr": "30101810000000000002", "bik": "044500000",
       "org_phone": "+7 900 111-11-11"}
IP = {**BASE, "kind": "ip", "org_name": "Денисов Денис Денисович", "ogrn": "321000000000000", "inn": "770000000000",
      "legal_address": "Москва", "account": "40802810000000000009", "bank": "Банк", "corr": "30101810000000000002", "bik": "044500000",
      "org_phone": "+7 900 222-22-22", "materials": "customer"}


def text(b: bytes) -> str:
    d = docx.Document(io.BytesIO(b))
    return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])


assert contract.money(310573.81) == "310 573 (триста десять тысяч пятьсот семьдесят три) рубля 81 копейка"
assert contract.money(21000) == "21 000 (двадцать одна тысяча) рублей 00 копеек"
assert contract.add_month(contract.parse_date("2026-01-31")).isoformat() == "2026-02-28"
assert contract.parse_pages("9-11, 14") == [9, 10, 11, 14] and contract.parse_pages("") is None

# минимальный PDF для приложения с дизайн-проектом
from reportlab.pdfgen import canvas  # noqa: E402
_b = io.BytesIO()
_c = canvas.Canvas(_b)
for _ in range(3):
    _c.drawString(100, 700, "plan")
    _c.showPage()
_c.save()
PDF = _b.getvalue()

bad = []
n = 0
for i, f in enumerate(fx[:40]):
    res = calc.compute(f["inputs"], P)
    for t in calc.TARIFFS:
        for data in (PERSON, ORG, IP):
            n += 1
            design = PDF if (i + n) % 4 == 0 else None
            if design:
                data = {**data, "design_sheets": "листы 1–2", "design_pages": "1-2"}
            files = contract.build(res, t, data, CON, design)
            N = contract.numbers(res, t, data.get("materials", "executor"))
            names = list(files)
            M = data.get("materials", "executor") == "executor"
            want = ["01", "02"] + (["03"] if M else []) + (["0" + str(4 if M else 3)] if design else [])
            if [x[:2] for x in names[:len(want)]] != want or ("Акт" not in names[-1]):
                bad.append(f"{i}/{t}/{data['kind']}: состав пакета {names}")
            tx = text(files[names[0]])
            if "[___]" in tx or re.search(r"\{\w+\}", tx):
                bad.append(f"{i}/{t}/{data['kind']}: в договоре пропуски/ссылки: {re.findall(r'.{30}(?:\[___\]|\{\w+\}).{10}', tx)[:3]}")
            if contract.money(N["total"]) not in tx:
                bad.append(f"{i}/{t}: цены {N['total']} нет в договоре")
            if M and abs(N["total"] - res["kp"][t]["price"]) > 0.005:
                bad.append(f"{i}/{t}: цена договора {N['total']} ≠ КП {res['kp'][t]['price']}")
            if (t == "turnkey") != ("Второй этап Работ" in tx):
                bad.append(f"{i}/{t}: второй этап")
            if (t == "basic") != ("по фактически выполненному объёму" in tx):
                bad.append(f"{i}/{t}: цена «Базового»")
            if f"{contract.mwords(contract.GUAR[t])}" not in tx:
                bad.append(f"{i}/{t}: гарантия")
            if t != "basic" and f"до {contract.mwords(contract.LIMIT[t])} переносов" not in tx:
                bad.append(f"{i}/{t}: бесплатные изменения")
            if design and "дизайн-проектом (листы 1–2)" not in tx:
                bad.append(f"{i}/{t}: пункт о дизайн-проекте")
            if data["kind"] == "person" and "гражданка РФ **" not in tx and "гражданка РФ Иванова" not in tx:
                bad.append(f"{i}/{t}: род заказчика")
            ws = openpyxl.load_workbook(io.BytesIO(files[names[1]])).active
            s = sum(r[5].value for r in ws.iter_rows(min_row=9) if isinstance(r[0].value, int))
            if abs(s - N["works_sum"]) > 0.01:
                bad.append(f"{i}/{t}: смета работ {s} ≠ {N['works_sum']}")
            if M:
                ws = openpyxl.load_workbook(io.BytesIO(files[names[2]])).active
                s = sum(r[5].value for r in ws.iter_rows(min_row=9) if isinstance(r[0].value, int))
                if abs(s - N["mat_sum"]) > 0.01:
                    bad.append(f"{i}/{t}: спецификация {s} ≠ {N['mat_sum']}")
            acts = [k for k in names if "Акт" in k]
            if len(acts) != (2 if t == "turnkey" else 1):
                bad.append(f"{i}/{t}: акты {acts}")
            for a in acts:
                at = text(files[a])
                if "{" in at or "[___]" in at:
                    bad.append(f"{i}/{t}: в акте пропуски")
            if design:
                from pypdf import PdfReader
                pr = PdfReader(io.BytesIO(files[next(k for k in names if k.endswith(".pdf"))]))
                if len(pr.pages) != 2 or "Приложение" not in pr.pages[0].extract_text():
                    bad.append(f"{i}/{t}: штамп на PDF")
    openpyxl.load_workbook(io.BytesIO(contract.panel_xlsx(res, "std")))

for b in bad[:30]:
    print(b)
assert not bad, f"{len(bad)} расхождений"
print(f"CONTRACT OK — {n} пакетов")
