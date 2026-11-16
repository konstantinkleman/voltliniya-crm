# Сверка калькулятора CRM с Excel

Нужен LibreOffice и файл `Калькулятор_ВольтЛиния.xlsx` (источник истины).

```
cd backend/tests/excel_check
cp ~/…/Калькулятор_ВольтЛиния.xlsx ../calc.xlsx      # путь в fill.py: SRC = '../calc.xlsx'
python3 gen_cases.py 200 23        # случайные замеры → cases.json
python3 fill.py                    # in/caseNNN.xlsx с этими данными
soffice --headless --calc --convert-to xlsx --outdir out in/*.xlsx   # пересчёт формул
PYTHONPATH=../.. python3 compare.py   # построчное сравнение + fixtures.json
```

`fixtures.json` из прогона кладётся в `backend/tests/calc_fixtures.json` — по нему CI проверяет движок без LibreOffice.
Корпус «накладной» в сверку не входит: в Excel (16.11.2026) формула подбора накладного корпуса берёт диапазон
со встраиваемыми корпусами и выбирает корпус больше нужного; в CRM — правильное правило из описания логики.
