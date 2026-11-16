import json, sys, openpyxl
sys.path.insert(0, '../..')
from app import calc
from app.calc_defaults import DEFAULTS
P = {k: {"v1": v1, "v2": v2, "v3": v3, "vtext": vt} for (k, s, l, u, v1, v2, v3, n, vt) in DEFAULTS}
cases = json.load(open('cases.json'))
TN = {"basic": "B", "std": "C", "turnkey": "D"}
bad = 0
def close(a, b, tol=0.011):
    return abs((a or 0) - (b or 0)) <= tol
fixtures = []
for i, c in enumerate(cases):
    wb = openpyxl.load_workbook(f'out/case{i:03d}.xlsx', data_only=True)
    ws = wb['Расчёт']
    res = calc.compute(c, P)
    errs = []
    # works
    wkeys = {82:'chase',83:'lay_drop',84:'lay_corr',85:'lv_cable',86:'walls',87:'box_drill',88:'box_glue',89:'junction',90:'kup',91:'media'}
    W = {w['key']: w for w in res['works']}
    for r, k in wkeys.items():
        if not close(ws[f'D{r}'].value, W[k]['sum']): errs.append(f'works {k}: xl {ws[f"D{r}"].value} vs {W[k]["sum"]}')
    if not close(ws['D92'].value, res['works_total']): errs.append(f"works_total {ws['D92'].value} vs {res['works_total']}")
    if not close(ws['D99'].value, res['finishing_total']): errs.append('finishing')
    mkeys = {104:'vvg15',105:'vvg25',106:'vvg25_cust',107:'vvg54',108:'vvg36',109:'pugv6',110:'pugv4',111:'twisted',112:'box',113:'box_cap',114:'junction',115:'kup_box',116:'sleeve',117:'corr_pvc',118:'corr_pnd',119:'corr_clip',120:'pad',121:'tape',122:'dowel',123:'chase_clips',124:'wago',125:'consum'}
    M = {m['key']: m for m in res['materials']}
    for r, k in mkeys.items():
        if not close(ws[f'D{r}'].value, M[k]['sum']) or not close(ws[f'B{r}'].value, M[k]['qty']): errs.append(f'mat {k}: xl {ws[f"B{r}"].value}×{ws[f"C{r}"].value}={ws[f"D{r}"].value} vs {M[k]["qty"]}×{M[k]["price"]}')
    if not close(ws['D132'].value, res['materials_total']): errs.append(f"mat_total {ws['D132'].value} vs {res['materials_total']}")
    dkeys = ['main','relay','master_mcb','contactor','light','sock_mcb','sock_rcd','sock_dif','kitchen_rcd','kitchen_mcb','kitchen_dif','fridge','appliances','tp_rcd','tp_mcb','tp_dif','ac','hob','flow','boiler','router','neptun','busbar']
    for pname, qcol, scol in (('std','B','E'),('basic','F','G')):
        D = {x['key']: x for x in res['panel'][pname]['devices']}
        for j, k in enumerate(dkeys):
            r = 138 + j
            if not close(ws[f'{qcol}{r}'].value, D[k]['qty']) or not close(ws[f'{scol}{r}'].value, D[k]['sum']) or not close(ws[f'C{r}'].value, D[k]['mod']):
                errs.append(f'{pname} {k}: xl q={ws[f"{qcol}{r}"].value} mod={ws[f"C{r}"].value} s={ws[f"{scol}{r}"].value} vs q={D[k]["qty"]} mod={D[k]["mod"]} s={D[k]["sum"]}')
        mcol = 'B' if pname == 'std' else 'F'
        if not close(ws[f'{mcol}161'].value, res['panel'][pname]['modules']): errs.append(f'{pname} modules xl {ws[f"{mcol}161"].value} vs {res["panel"][pname]["modules"]}')
        if not close(ws[f'{mcol}174'].value, res['panel'][pname]['assembly_qty']): errs.append(f'{pname} assembly qty xl {ws[f"{mcol}174"].value} vs {res["panel"][pname]["assembly_qty"]}')
        tcol = 'E' if pname == 'std' else 'G'
        if not close(ws[f'{tcol}173'].value, res['panel'][pname]['materials_sum']): errs.append(f'{pname} panel mat xl {ws[f"{tcol}173"].value} vs {res["panel"][pname]["materials_sum"]}')
    for t, col in TN.items():
        T = res['tariffs'][t]
        for r, k in ((178,'works_nopanel'),(179,'assembly'),(180,'surcharge'),(181,'finishing'),(182,'works_total'),(183,'materials_nopanel'),(184,'materials_panel'),(185,'materials_total'),(186,'taping'),(187,'trash'),(189,'price')):
            if not close(ws[f'{col}{r}'].value, T[k]): errs.append(f'tariff {t} {k}: xl {ws[f"{col}{r}"].value} vs {T[k]}')
    kp = wb['КП']
    for t, col in (('basic','C'),('std','E'),('turnkey','G')):
        if not close(kp[f'{col}9'].value, res['kp'][t]['price'], 0.5): errs.append(f'kp {t} price xl {kp[f"{col}9"].value} vs {res["kp"][t]["price"]}')
        xw = kp[f'{col}11'].value; xm = kp[f'{col}12'].value; xpm = kp[f'{col}13'].value
        mine_w = 'работы ' + calc.fmt_int(res['kp'][t]['works']) + ' ₽'
        mine_m = 'материалы ' + calc.fmt_int(res['kp'][t]['materials']) + ' ₽'
        if xw.replace('\xa0',' ') != mine_w: errs.append(f'kp {t} works "{xw}" vs "{mine_w}"')
        if xm.replace('\xa0',' ') != mine_m: errs.append(f'kp {t} mats "{xm}" vs "{mine_m}"')
        if xpm != f"{res['kp'][t]['per_m2']:g} ₽/м²" and res['inputs']['area']: errs.append(f'kp {t} per_m2 "{xpm}" vs {res["kp"][t]["per_m2"]}')
    sm = calc.smeta(res, c['tariff'])
    xs = wb['СметаДанные']['E85'].value
    if not close(xs, sm['total'], 0.02): errs.append(f'smeta total {c["tariff"]} xl {xs} vs {sm["total"]}')
    if errs:
        bad += 1
        print(f'--- case {i}: {len(errs)} расхождений'); [print('   ', e) for e in errs[:12]]
    fixtures.append({"inputs": c, "expected": {
        "works_total": ws['D92'].value, "materials_total": ws['D132'].value, "finishing_total": ws['D99'].value,
        "modules_std": ws['B161'].value, "modules_basic": ws['F161'].value,
        "tariffs": {t: {"price": ws[f'{col}189'].value, "works_total": ws[f'{col}182'].value, "materials_total": ws[f'{col}185'].value} for t, col in TN.items()},
        "smeta_total": xs, "kp": {t: kp[f'{col}9'].value for t, col in (('basic','C'),('std','E'),('turnkey','G'))}}})
json.dump(fixtures, open('fixtures.json','w'), ensure_ascii=False)
print(f'итого: {len(cases)} случаев, с расхождениями {bad}')
