"""Движок калькулятора против значений, пересчитанных LibreOffice по Калькулятор_ВольтЛиния.xlsx (calc_fixtures.json).

PYTHONPATH=. python tests/calc_test.py   — без БД и без FastAPI
"""
import json
import pathlib

from app import calc
from app.calc_defaults import DEFAULTS

P = {k: {"v1": v1, "v2": v2, "v3": v3, "vtext": vt} for (k, s, l, u, v1, v2, v3, n, vt) in DEFAULTS}
fx = json.loads((pathlib.Path(__file__).parent / "calc_fixtures.json").read_text())


def close(a, b, tol=0.011):
    return abs((a or 0) - (b or 0)) <= tol


bad = []
for i, f in enumerate(fx):
    res = calc.compute(f["inputs"], P)
    e = f["expected"]
    checks = [
        ("works_total", res["works_total"], e["works_total"]),
        ("materials_total", res["materials_total"], e["materials_total"]),
        ("finishing_total", res["finishing_total"], e["finishing_total"]),
        ("modules_std", res["panel"]["std"]["modules"], e["modules_std"]),
        ("modules_basic", res["panel"]["basic"]["modules"], e["modules_basic"]),
    ]
    for t in calc.TARIFFS:
        for k in ("price", "works_total", "materials_total"):
            checks.append((f"{t}.{k}", res["tariffs"][t][k], e["tariffs"][t][k]))
        checks.append((f"kp.{t}", calc.xround(res["tariffs"][t]["price"], -3), e["kp"][t]))   # Excel: КП до тысяч
        if abs(res["kp"][t]["price"] - res["tariffs"][t]["price"]) > 5:     # КП в CRM — точная сумма по строкам сметы
            checks.append((f"kp_exact.{t}", res["kp"][t]["price"], round(res["tariffs"][t]["price"])))
    sm = calc.smeta(res, f["inputs"]["tariff"])
    checks.append(("smeta_total", sm["total"], e["smeta_total"]))
    for name, mine, xl in checks:
        if not close(mine, xl, 0.02):
            bad.append(f"случай {i}: {name} CRM {mine} ≠ Excel {xl}")
    # наполнение щита: модули таблицы монтажника = модули щита
    for t in calc.TARIFFS:
        pf = calc.panel_fill(res, t)
        pn = res["panel"]["basic" if t == "basic" else "std"]
        if not close(pf["modules"], pn["modules"]):
            bad.append(f"случай {i}: щит {t} — в таблице {pf['modules']} мод., в расчёте {pn['modules']}")
    # смета по тарифу ≈ цене тарифа (разница — только округление цен до копеек)
    for t in calc.TARIFFS:
        sm = calc.smeta(res, t)
        if abs(sm["total"] - res["tariffs"][t]["price"]) > 1.0:
            bad.append(f"случай {i}: смета {t} {sm['total']:.2f} ≠ цена тарифа {res['tariffs'][t]['price']:.2f}")
    calc.kp(res)

# правило защиты группы из описания: 1 → диф; 2–4 → 1 УЗО; 5 → УЗО + диф; 6–8 → 2 УЗО; 9 → 2 УЗО + диф
assert [calc.protect(n, 4) for n in (0, 1, 2, 4, 5, 6, 8, 9)] == [(0, 0, 0), (0, 0, 1), (1, 2, 0), (1, 4, 0), (1, 4, 1), (2, 6, 0), (2, 8, 0), (2, 8, 1)]
# накладной корпус: 33 модуля → 36 (в Excel 16.11 из-за ошибки в диапазоне выходило 54)
cases = calc.pick_cases(calc.Params(P), "surface", 33)
assert [c["nominal"] for c in cases] == [36], cases
assert [c["nominal"] for c in calc.pick_cases(calc.Params(P), "surface", 60)] == [54, 12]
assert [c["nominal"] for c in calc.pick_cases(calc.Params(P), "flush", 71)] == [60, 12]
# скидка: 400 → 320, 120 → 100 (−20 %, вверх до 5 ₽)
r = calc.compute({**fx[0]["inputs"], "discount": True}, P)
W = {w["key"]: w for w in r["works"]}
assert W["chase"]["price"] == 320 and W["lay_drop"]["price"] == 100 and r["prices"]["add_point"] == 2000, W["chase"]

if bad:
    print("\n".join(bad[:40]))
    raise SystemExit(f"CALC FAIL: {len(bad)} расхождений")
print(f"CALC OK ({len(fx)} объектов сверено с Excel)")
