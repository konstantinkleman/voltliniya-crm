"""Пакет документов договора на фикстурах калькулятора: без БД и FastAPI.

PYTHONPATH=. python tests/contract_test.py
Сверка с исходным сформировать_документы.py (по Excel) — tests/excel_check/README.md, раздел «Договор».
"""
import io
import json
import pathlib
import re
import zipfile

import openpyxl

from app import calc, contract
from app.calc_defaults import DEFAULTS

P = {k: {"v1": v1, "v2": v2, "v3": v3, "vtext": vt} for (k, s, l, u, v1, v2, v3, n, vt) in DEFAULTS}
fx = json.loads((pathlib.Path(__file__).parent / "calc_fixtures.json").read_text())
CON = {"contractor.address": "Адрес ИП", "contractor.account": "40802810000000000001", "contractor.bank": "Банк",
       "contractor.corr": "30101810000000000002", "contractor.bik": "044500001"}
PERSON = {"kind": "person", "number": "1611/26", "date": "2026-11-16", "start": "2026-11-23", "end": "2026-12-14",
          "address": "Москва, ул. Тестовая, 1", "fio": "Иванов Иван Иванович", "birth": "1985-03-04", "pass_series": "4510",
          "pass_number": "123456", "pass_issued": "ГУ МВД", "pass_date": "2015-06-07", "pass_code": "770-001",
          "reg_address": "Москва, ул. Регистрационная, 1", "phone": "+7 900 000-00-00", "email": "a@b.ru"}
ORG = {"kind": "org", "number": "1711/26", "date": "2026-11-17", "start": "2026-11-24", "end": "2026-12-15",
       "address": "Москва, ул. Офисная, 2", "org_name": "ООО «Тест»", "ogrn": "1027700000000", "inn": "7700000000",
       "kpp": "770001001", "legal_address": "Москва, ул. Юридическая, 5", "signer": "генерального директора Петрова Петра Петровича",
       "basis": "Устава", "sign_name": "Петров П.П.", "account": "40702810000000000001", "bank": "ПАО Банк",
       "corr": "30101810000000000002", "bik": "044500000", "org_phone": "+7 900 111-11-11", "org_email": "o@b.ru"}
ALLOWED = {"[1/2]", "[2 (двух)]"}


def text(docx: bytes) -> tuple[str, str]:
    xml = zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml").decode()
    return xml, re.sub(r"<[^>]+>", "", xml)


assert contract.num2words(359455) == "триста пятьдесят девять тысяч четыреста пятьдесят пять"
assert contract.num2words(2001) == "две тысячи один" and contract.num2words(21000) == "двадцать одна тысяча"
assert contract.rub_words(30000) == "30 000 (тридцать тысяч) рублей"
assert contract.short_fio("Иванов Иван Иванович") == "Иванов И.И."
assert contract.date_words("2026-11-16") == "«16» ноября 2026 г." and contract.fmt_date("2026-01-05") == "05.01.2026"

bad = []
n = 0
for i, f in enumerate(fx[:60]):
    res = calc.compute(f["inputs"], P)
    for t in calc.TARIFFS:
        for data in (PERSON, ORG):
            n += 1
            N = contract.numbers(res, t)
            files = contract.build(res, t, data, CON)
            assert list(files)[0].startswith("01_Договор_") and len(files) == 7
            xml, tx = text(files[next(k for k in files if k.startswith("01_"))])
            left = set(re.findall(r"\[[^\[\]]*\]", tx)) - ALLOWED
            if left or "{{C_" in xml:
                bad.append(f"{i}/{t}/{data['kind']}: в договоре остались места {left}")
            if contract.fmt_money(N["price"]) not in tx or contract.num2words(N["price"]) not in tx:
                bad.append(f"{i}/{t}: цены {N['price']} нет в договоре")
            if N["rest"] != N["price"] - N["advance"] - N["stage2"] or N["advance"] % 1000:
                bad.append(f"{i}/{t}: суммы {N}")
            if (t == "turnkey") != (N["stage2"] > 0 and "Этап 2" in tx):
                bad.append(f"{i}/{t}: этап 2")
            if (t == "basic") != ("по фактически выполненному объёму" in tx):
                bad.append(f"{i}/{t}: цена «Базового»")
            # смета: строка итога = цена договора, сумма строк ≈ итогу
            ws = openpyxl.load_workbook(io.BytesIO(files["02_Приложение_1_Смета.xlsx"])).active
            tot = next(r for r in ws.iter_rows() if str(r[0].value or "").startswith("ИТОГО ЦЕНА"))
            lines = sum((r[3].value or 0) * (r[4].value or 0) for r in ws.iter_rows(min_row=10) if isinstance(r[0].value, int))
            if tot[5].value != N["price"] or abs(lines - N["price"]) > 1:
                bad.append(f"{i}/{t}: смета {tot[5].value} / строки {lines:.2f} / цена {N['price']}")
            # спецификация: в разделе щита — только аппараты и корпуса
            ws = openpyxl.load_workbook(io.BytesIO(files["03_Приложение_2_Спецификация.xlsx"])).active
            names = [r[1].value for r in ws.iter_rows() if isinstance(r[0].value, int)]
            if any(x in names for x in ("Оклейка окон и дверей, уборка", "Вынос строительного мусора")):
                bad.append(f"{i}/{t}: условия тарифа попали в щит")
            panel = [x for x in N["smeta"]["sections"][1]["panel"]]
            if not all(p["name"] in names for p in panel):
                bad.append(f"{i}/{t}: не все аппараты щита в спецификации")
            _, kv = text(files["07_Квитанции.docx"])
            if contract.fmt_money(N["advance"]) not in kv or contract.fmt_money(N["rest"]) not in kv:
                bad.append(f"{i}/{t}: квитанции")
            openpyxl.load_workbook(io.BytesIO(files["08_Щит_для_монтажника.xlsx"]))

for b in bad[:30]:
    print(b)
assert not bad, f"{len(bad)} расхождений"
print(f"CONTRACT OK — {n} пакетов")
