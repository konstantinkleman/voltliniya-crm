import json, openpyxl, sys, os
SRC = '../calc.xlsx'
cases = json.load(open('cases.json'))
os.makedirs('in', exist_ok=True)
yn = lambda b: "да" if b else "нет"
TN = {"basic": "Базовый", "std": "Стандарт", "turnkey": "Под ключ"}
for i, c in enumerate(cases):
    wb = openpyxl.load_workbook(SRC)
    ws = wb['Расчёт']
    ws['B5'] = c['object']; ws['B6'] = c['area']; ws['B7'] = c['sockets']; ws['B8'] = c['lv']; ws['B9'] = c['switches']
    ws['B10'] = c['lights']; ws['B11'] = c['out220']; ws['B13'] = c['junctions']; ws['B14'] = c['cust_cable25']
    ws['B15'] = c['draw15']; ws['B16'] = c['draw25']; ws['B17'] = c['windows']; ws['B18'] = yn(c['chase'])
    ws['B19'] = 'по полу' if c['route'] == 'floor' else 'по потолку'; ws['B20'] = yn(c['discount'])
    ws['B23'] = '3 фазы' if c['phase'] == '3' else '1 фаза'; ws['B24'] = c['main_a']; ws['B25'] = c['brand']
    ws['B26'] = 'накладной' if c['case_type'] == 'surface' else 'встраиваемый'
    if c['kup'] is not None: ws['B30'] = c['kup']
    ws['B32'] = yn(c['oven']); ws['B33'] = yn(c['hob'])
    if c['hob_len'] is not None: ws['B34'] = c['hob_len']
    ws['B35'] = yn(c['dishwasher']); ws['B36'] = yn(c['washer']); ws['B37'] = yn(c['dryer']); ws['B38'] = yn(c['apron'])
    ws['B39'] = yn(c['fridge']); ws['B40'] = yn(c['flow'])
    if c['flow_len'] is not None: ws['B41'] = c['flow_len']
    ws['B43'] = yn(c['boiler']); ws['B44'] = yn(c['neptun'])
    ws['B45'] = {'none': 'нет', 'light': 'свет', 'all': 'свет + розетки'}[c['master']]
    ws['B46'] = yn(c['router']); ws['B47'] = yn(c['media'])
    for r in range(50, 62):
        for col in 'ABCDE': ws[f'{col}{r}'] = None
    for j, room in enumerate(c['rooms']):
        r = 50 + j
        ws[f'A{r}'] = room['name'] or None; ws[f'B{r}'] = room['type']; ws[f'C{r}'] = yn(room['sockets'])
        ws[f'D{r}'] = yn(room['floor']); ws[f'E{r}'] = yn(room['ac'])
    for j in range(5):
        r = 127 + j
        e = c['extra'][j] if j < len(c['extra']) else None
        ws[f'A{r}'] = e['name'] if e else None; ws[f'B{r}'] = e['qty'] if e else None; ws[f'C{r}'] = e['price'] if e else None
    wb['Смета']['C5'] = TN[c['tariff']]
    wb.save(f'in/case{i:03d}.xlsx')
print('filled', len(cases))
