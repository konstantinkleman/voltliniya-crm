"""Калькулятор чернового электромонтажа — перенос листов «Расчёт», «Смета», «КП» и «Щит» из Калькулятор_ВольтЛиния.xlsx.

Чистые функции без БД: на вход — данные замера (inputs) и справочник (P), на выход — словари для экрана и документов.
Арифметика повторяет Excel: float, ОКРУГЛВВЕРХ/ОКРВВЕРХ/ОКРУГЛ с округлением «от нуля». Сверка с файлом — tests/calc_excel.py.

Справочник P: {key: {"v1":…, "v2":…, "v3":…, "vtext":…, "cost1":…, "cost2":…}} — значения уже с учётом привязки к складу.
"""
import math

ROOM_TYPES = ["Комната", "Гостиная", "Кухня", "Кухня-гостиная", "Прихожая / коридор", "Санузел", "Гардеробная",
              "Балкон / лоджия", "Другое"]
TARIFFS = ["basic", "std", "turnkey"]
TARIFF_NAMES = {"basic": "Базовый", "std": "Стандарт", "turnkey": "Под ключ"}
MASTER = {"none": "нет", "light": "свет", "all": "свет + розетки"}
EPS = 1e-9


# ---------- округления как в Excel ----------
def ceiling(x: float, step: float) -> float:
    """ОКРВВЕРХ(x; шаг) для x ≥ 0."""
    if not step:
        return x
    return math.ceil(round(x / step, 9)) * step


def roundup(x: float, digits: int = 0) -> float:
    """ОКРУГЛВВЕРХ — от нуля."""
    k = 10 ** digits
    v = round(abs(x) * k, 9)
    return math.copysign(math.ceil(v) / k, x)


def xround(x: float, digits: int = 0) -> float:
    """ОКРУГЛ — половина от нуля (в Python round — банковское)."""
    k = 10 ** digits
    v = abs(x) * k
    r = math.floor(v + 0.5 + EPS)
    return math.copysign(r / k, x)


def num(v, default=0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return float(default)


def yes(v) -> bool:
    return v is True or v in ("да", "yes", "1", 1, "true", "on")


class Params:
    def __init__(self, P: dict):
        self.P = P

    def v(self, key, col="v1", default=0.0):
        row = self.P.get(key) or {}
        val = row.get(col)
        return float(val) if val not in (None, "") else float(default)

    def t(self, key, default=""):
        row = self.P.get(key) or {}
        return row.get("vtext") or default

    def cost(self, key, col="cost1"):
        row = self.P.get(key) or {}
        c = row.get(col)
        return None if c is None else float(c)


def default_inputs(P: dict | None = None) -> dict:
    p = Params(P or {})
    return {
        "object": "", "area": p.v("general.area", default=60) or 60,
        "sockets": 0, "lv": 0, "switches": 0, "lights": 0, "out220": 0, "junctions": 0,
        "cust_cable25": 0, "draw15": 0, "draw25": 0, "windows": 0,
        "chase": True, "route": "ceiling", "discount": False,
        "phase": "3", "main_a": 32, "brand": p.t("general.brand", "ABB") or "ABB", "case_type": "flush",
        "kup": None,
        "oven": False, "hob": False, "hob_len": None, "dishwasher": False, "washer": False, "dryer": False,
        "apron": False, "fridge": False, "flow": False, "flow_len": None, "boiler": False, "neptun": False,
        "master": "none", "router": False, "media": False,
        "rooms": [], "extra": [],
    }


def normalize(inp: dict, P: dict) -> dict:
    """Дополняет ввод значениями по умолчанию и приводит типы."""
    d = default_inputs(P)
    d.update({k: v for k, v in (inp or {}).items() if v is not None or k in ("kup", "hob_len", "flow_len")})
    p = Params(P)
    for k in ("area", "sockets", "lv", "switches", "lights", "out220", "junctions", "cust_cable25", "draw15", "draw25",
              "windows", "main_a"):
        d[k] = num(d.get(k))
    for k in ("chase", "discount", "oven", "hob", "dishwasher", "washer", "dryer", "apron", "fridge", "flow", "boiler",
              "neptun", "router", "media"):
        d[k] = yes(d.get(k))
    d["phase"] = "1" if str(d.get("phase")) in ("1", "1 фаза") else "3"
    d["route"] = "floor" if d.get("route") in ("floor", "по полу") else "ceiling"
    d["brand"] = "ABB" if str(d.get("brand")).upper() == "ABB" else "Dekraft"
    d["case_type"] = "surface" if d.get("case_type") in ("surface", "накладной") else "flush"
    m = d.get("master")
    d["master"] = {"свет": "light", "свет + розетки": "all"}.get(m, m if m in MASTER else "none")
    d["hob_len"] = num(d.get("hob_len"), p.v("norm.power_line_len")) if d.get("hob_len") not in (None, "") else p.v("norm.power_line_len")
    d["flow_len"] = num(d.get("flow_len"), p.v("norm.power_line_len")) if d.get("flow_len") not in (None, "") else p.v("norm.power_line_len")
    rooms = []
    for r in (d.get("rooms") or [])[:30]:
        t = (r or {}).get("type") or ""
        rooms.append({"name": str((r or {}).get("name") or "").strip(), "type": t if t in ROOM_TYPES else "",
                      "sockets": yes(r.get("sockets")), "floor": yes(r.get("floor")), "ac": yes(r.get("ac"))})
    d["rooms"] = rooms
    extra = []
    for e in (d.get("extra") or [])[:20]:
        extra.append({"name": str((e or {}).get("name") or "").strip(), "qty": num(e.get("qty")), "price": num(e.get("price"))})
    d["extra"] = extra
    return d


def room_label(r: dict) -> str:
    return r["name"] or r["type"]


def protect(n: int, L: int) -> tuple[int, int, int]:
    """Правило защиты группы: (УЗО, автоматов под УЗО, одиночных дифов)."""
    if n <= 0 or L <= 0:
        return 0, 0, 0
    rcd = n // L + (1 if n % L >= 2 else 0)
    dif = 1 if n % L == 1 else 0
    return rcd, n - dif, dif


def compute(inp: dict, P: dict) -> dict:
    p = Params(P)
    d = normalize(inp, P)
    disc_on = d["discount"]

    def disc(price: float) -> float:
        if not disc_on:
            return price
        return ceiling(price * (1 - p.v("disc.pct")), p.v("disc.round"))

    S = d["area"]
    rooms = [r for r in d["rooms"] if r["type"]]
    rooms_total = len(rooms)
    sock_rooms = [r for r in rooms if r["sockets"] and r["type"] not in ("Санузел", "Кухня")]
    su_rooms = [r for r in rooms if r["type"] == "Санузел"]
    tp_rooms = [r for r in rooms if r["floor"]]
    ac_rooms = [r for r in rooms if r["ac"]]
    tp = len(tp_rooms)
    su = len(su_rooms)
    ac = len(ac_rooms)
    kup = su if d.get("kup") in (None, "") else num(d["kup"])
    ph3 = d["phase"] == "3"

    # исполнение проточника
    if d["flow"]:
        flow_mode = "трёхфазный" if (ph3 and p.v("panel.flow_kw") * 1000 / 230 + p.v("panel.flow_reserve_a") > d["main_a"]) else "однофазный"
    else:
        flow_mode = "—"

    # ---------- объёмы ----------
    points = d["sockets"] + d["lv"] + d["switches"] + d["lights"] + d["out220"] + tp
    k_draw = p.v("norm.drawing_k")
    if d["draw15"] > 0:
        c15 = d["draw15"] * k_draw
    else:
        c15 = ((d["switches"] + d["lights"] + (1 if d["neptun"] else 0)) * p.v("norm.c15_per_light")
               + S * p.v("norm.c15_per_m2")) * k_draw * p.v("norm.c15_corr")
    if d["draw25"] > 0:
        c25 = d["draw25"] * k_draw
    else:
        c25 = ((d["sockets"] + tp + (1 if d["boiler"] else 0)) * p.v("norm.c25_per_socket")
               + S * p.v("norm.c25_per_m2")) * k_draw * p.v("norm.c25_corr")
    c25 += ac * p.v("norm.ac_cable")
    c54 = (d["hob_len"] if (d["hob"] and ph3) else 0) + (d["flow_len"] if flow_mode == "трёхфазный" else 0)
    c36 = (d["hob_len"] if (d["hob"] and not ph3) else 0) + (d["flow_len"] if flow_mode == "однофазный" else 0)
    power = c15 + c25 + c54 + c36
    drops = power * p.v("norm.drop_share")
    corr = power - drops
    floor = d["route"] == "floor"
    pvc = min(corr, p.v("mat.pvc_floor_max")) if floor else corr
    pnd = corr - pvc
    twisted = d["lv"] * p.v("norm.twisted_per_pt")
    pugv6 = kup * p.v("norm.pugv6_per_kup")
    pugv4 = kup * p.v("norm.pugv4_per_kup")
    boxes = d["sockets"] + d["lv"] + d["switches"] + tp

    volumes = {"points": points, "cable15": c15, "cable25": c25, "cable54": c54, "cable36": c36, "cable_power": power,
               "drops": drops, "in_corr": corr, "corr_pvc": pvc, "corr_pnd": pnd, "twisted": twisted, "pugv6": pugv6,
               "pugv4": pugv4, "boxes": boxes, "rooms_total": rooms_total, "sock_lines": len(sock_rooms), "su": su,
               "kup": kup, "ac": ac, "tp": tp, "flow_mode": flow_mode,
               "lines54": (1 if d["hob"] and ph3 else 0) + (1 if flow_mode == "трёхфазный" else 0),
               "lines36": (1 if d["hob"] and not ph3 else 0) + (1 if flow_mode == "однофазный" else 0)}

    # ---------- работы ----------
    def line(key, name, qty, price, **kw):
        return {"key": key, "name": name, "qty": qty, "price": price, "sum": qty * price, **kw}

    works = [
        line("chase", "Штробление", drops if d["chase"] else 0, disc(p.v("work.chase")), unit="м"),
        line("lay_drop", "Прокладка кабеля по спускам (без гофры)", drops, disc(p.v("work.lay_drop")), unit="м"),
        line("lay_corr", "Прокладка кабеля в гофре", corr, disc(p.v("work.lay_corr")), unit="м"),
        line("lv_cable", "Прокладка слаботочного кабеля", twisted, disc(p.v("work.lv_cable")), unit="м"),
    ]
    walls_base = sum(w["sum"] for w in works)
    works.append(line("walls", "Проходы через стены, мелочи (коэффициент)", p.v("work.walls_pct"), walls_base, unit="%"))
    works += [
        line("box_drill", "Высверливание подрозетников", boxes, disc(p.v("work.box_drill")), unit="шт"),
        line("box_glue", "Вклейка подрозетников", boxes, disc(p.v("work.box_glue")), unit="шт"),
        line("junction", "Расключение распредкоробок", d["junctions"], disc(p.v("work.junction")), unit="шт"),
        line("kup", "Монтаж КУП", kup, disc(p.v("work.kup")), unit="шт"),
        line("media", "Установка мультимедийного щита", 1 if d["media"] else 0, disc(p.v("work.media_panel")), unit="шт"),
    ]
    works_total = sum(w["sum"] for w in works)

    finishing = [
        line("fin_sockets", "Установка розеток 220 В", d["sockets"], p.v("fin.mech"), unit="шт"),
        line("fin_lv", "Установка интернет-розеток", d["lv"], p.v("fin.mech"), unit="шт"),
        line("fin_switches", "Установка выключателей (любого типа)", d["switches"], p.v("fin.mech"), unit="шт"),
        line("fin_thermo", "Установка термодатчиков", tp, p.v("fin.thermo"), unit="шт"),
    ]
    finishing_total = sum(f["sum"] for f in finishing)

    # ---------- материалы ----------
    res = p.v("mat.cable_reserve")
    rnd = p.v("mat.cable_round")
    chase = d["chase"]

    def mline(key, name, qty, pkey=None, price=None, unit="шт"):
        pr = p.v(pkey) if pkey else (price or 0)
        c = p.cost(pkey) if pkey else None
        return {"key": key, "name": name, "qty": qty, "price": pr, "sum": qty * pr, "unit": unit, "pkey": pkey,
                "cost": c}

    materials = [
        mline("vvg15", "ВВГнг-LS 3×1,5 (с запасом)", ceiling(c15 * (1 + res), rnd), "mat.vvg15", unit="м"),
        mline("vvg25", "ВВГнг-LS 3×2,5 (с запасом)", max(0, ceiling(c25 * (1 + res), rnd) - d["cust_cable25"]), "mat.vvg25", unit="м"),
        mline("vvg25_cust", "ВВГнг-LS 3×2,5 — материал Заказчика", d["cust_cable25"], price=0, unit="м"),
        mline("vvg54", "ВВГнг-LS 5×4 (плита / проточник)", c54, "mat.vvg54", unit="м"),
        mline("vvg36", "ВВГнг-LS 3×6 (плита / проточник)", c36, "mat.vvg36", unit="м"),
        mline("pugv6", "ПУгВ 1×6", pugv6, "mat.pugv6", unit="м"),
        mline("pugv4", "ПУгВ 1×4", pugv4, "mat.pugv4", unit="м"),
        mline("twisted", "Витая пара", twisted, "mat.twisted", unit="м"),
        mline("box", "Подрозетники", boxes, "mat.box"),
        mline("box_cap", "Заглушки для подрозетников", boxes, "mat.box_cap"),
        mline("junction", "Распредкоробки", d["junctions"], "mat.junction"),
        mline("kup_box", "Короб КУП", kup, "mat.kup_box"),
        mline("sleeve", "Гильзы", roundup(points * p.v("norm.sleeves_per_pt")), "mat.sleeve"),
        mline("corr_pvc", "Гофра ПВХ d=20", pvc, "mat.corr_pvc", unit="м"),
        mline("corr_pnd", "Гофра ПНД d=20", pnd, "mat.corr_pnd", unit="м"),
        mline("corr_clip", "Клипсы для гофры", roundup(pvc * p.v("norm.clips_per_m")), "mat.corr_clip"),
        mline("pad", "Площадки под стяжку", roundup(pvc * p.v("norm.pads_per_m")), "mat.pad"),
        mline("tape", "Нейлоновая монтажная лента (бухт по 100 м)",
              roundup(pnd / p.v("mat.tape_m")) if floor and p.v("mat.tape_m") else 0, "mat.tape", unit="бухт"),
        mline("dowel", "Дюбель-хомуты (пачек)", 0 if chase else (10 if S <= 70 else 15), "mat.dowel", unit="пач."),
        mline("chase_clips", "Клипсы для крепления кабеля в штробе (пачек)", (1 if drops <= 70 else 2) if chase else 0,
              "mat.chase_clips", unit="пач."),
        mline("wago", "Клеммники Wago (упак.)", roundup(d["switches"] / p.v("mat.wago_per")) if p.v("mat.wago_per") else 0,
              "mat.wago", unit="уп."),
        mline("consum", "Расходники на объект", 1, "mat.consum_small" if power <= p.v("mat.consum_threshold") else "mat.consum_big",
              unit="компл."),
    ]
    for i, e in enumerate(d["extra"]):
        if e["name"] or e["qty"] or e["price"]:
            materials.append({"key": f"extra{i}", "name": e["name"] or "Не учтённый материал", "qty": e["qty"],
                              "price": e["price"], "sum": e["qty"] * e["price"], "unit": "", "pkey": None, "cost": None})
    materials_total = sum(m["sum"] for m in materials)

    # ---------- щит ----------
    panel_std = build_panel(d, p, len(sock_rooms), tp, rooms_total, su, ac, flow_mode, basic=False)
    panel_basic = build_panel(d, p, len(sock_rooms), tp, rooms_total, su, ac, flow_mode, basic=True)
    for pn in (panel_std, panel_basic):
        pn["assembly_price"] = disc(p.v("work.panel_mod"))
        pn["assembly_sum"] = pn["assembly_qty"] * pn["assembly_price"]

    # ---------- тарифы ----------
    std_pct, tk_pct = p.v("tariff.std_pct"), p.v("tariff.turnkey_pct")
    taping_price = disc(p.v("tariff.taping"))
    trash_price = disc(p.v("tariff.trash"))
    tariffs = {}
    for t in TARIFFS:
        pn = panel_basic if t == "basic" else panel_std
        assembly = pn["assembly_sum"]
        pct = 0 if t == "basic" else (std_pct if t == "std" else tk_pct)
        surcharge = (works_total + assembly) * pct
        fin = finishing_total if t == "turnkey" else 0
        w_total = works_total + assembly + surcharge + fin
        m_panel = pn["materials_sum"]
        m_total = materials_total + m_panel
        taping = 0 if t == "basic" else d["windows"] * taping_price
        trash = trash_price if t == "turnkey" else 0
        price = w_total + m_total + taping + trash
        tariffs[t] = {
            "name": TARIFF_NAMES[t], "works_nopanel": works_total, "assembly": assembly, "surcharge": surcharge,
            "surcharge_pct": pct, "finishing": fin, "works_total": w_total, "materials_nopanel": materials_total,
            "materials_panel": m_panel, "materials_total": m_total, "taping": taping, "trash": trash, "price": price,
            "per_m2": price / S if S else 0, "per_point": price / points if points else 0,
            "works_per_m2": w_total / S if S else 0, "panel_modules": pn["modules"], "panel_case": pn["case_text"],
            "panel_nominal": pn["assembly_qty"],
        }

    res = {
        "inputs": d, "volumes": volumes, "works": works, "works_total": works_total, "finishing": finishing,
        "finishing_total": finishing_total, "materials": materials, "materials_total": materials_total,
        "panel": {"std": panel_std, "basic": panel_basic}, "tariffs": tariffs,
        "prices": {"add_point": disc(p.v("tariff.add_point")), "move_point": disc(p.v("tariff.move_point")),
                   "tour_option": S * p.v("tariff.tour_price"), "tour_cost": S * p.v("tariff.tour_cost"),
                   "taping": taping_price, "trash": trash_price},
        "margin": margin(materials, panel_std, panel_basic),
        "warnings": warnings(d, volumes, rooms),
    }
    res["kp"] = kp_numbers(res, S)
    return res


def shown(x) -> float:
    """Количество и цена строки сметы так, как они печатаются (до копеек)."""
    return xround(float(x or 0), 2)


def _ls(ln) -> float:
    return round(shown(ln["qty"]) * shown(ln["price"]), 2)


def smeta_price(sm: dict) -> float:
    """Итог = сумма строк сметы в напечатанном виде (кол-во и цена до копеек), с копейками — так сходятся КП и договор."""
    return round(sum(_ls(ln) for s in sm["sections"] for ln in s["lines"] + s.get("panel", []) if ln["qty"] > 0), 2)


def kp_numbers(res: dict, S: float) -> dict:
    """Цены КП без округления (решение владельца 16.11.2026): ровно та сумма, что попадёт в договор.
    В Excel КП округлял до тысяч; точная сумма тарифа без печатного округления строк — в res["tariffs"][t]["price"]."""
    out = {}
    for t in TARIFFS:
        sm = smeta(res, t)
        price = smeta_price(sm)
        ms = next(x for x in sm["sections"] if x["title"].endswith("Материалы"))
        mats = round(sum(_ls(ln) for ln in ms["lines"] + ms.get("panel", []) if ln["qty"] > 0), 2)
        out[t] = {"price": price, "works": round(price - mats, 2), "materials": mats, "per_m2": xround(price / S) if S else 0}
    return out


def margin(materials, panel_std, panel_basic) -> dict:
    """Себестоимость материалов по позициям, привязанным к складу (для руководителя)."""
    def calc(lines):
        known = [ln for ln in lines if ln.get("cost") is not None and ln["qty"]]
        cost = sum(ln["qty"] * ln["cost"] for ln in known)
        rev = sum(ln["sum"] for ln in known)
        return {"lines": len(known), "revenue": rev, "cost": cost, "profit": rev - cost}
    base = [m for m in materials if m["qty"]]
    return {"std": calc(base + panel_std["devices"] + panel_std["cases"]),
            "basic": calc(base + panel_basic["devices"] + panel_basic["cases"]),
            "priced_lines": sum(1 for m in base if m["qty"]) + sum(1 for x in panel_std["devices"] if x["qty"]) + len(panel_std["cases"])}


def warnings(d, v, rooms) -> list[str]:
    w = []
    if not rooms:
        w.append("Помещения не заполнены — щит считается без линий света и розеток комнат.")
    if d["area"] <= 0:
        w.append("Не указана площадь.")
    if not (d["sockets"] or d["switches"] or d["lights"]):
        w.append("Не заполнены точки (розетки, выключатели, выводы освещения).")
    if d["flow"] and v["flow_mode"] == "трёхфазный":
        w.append("Проточник при 3 фазах и вводном до 32 А считается трёхфазным (диф 3P+N 25 А, кабель 5×4).")
    return w


def build_panel(d, p: Params, n_sock: int, tp: int, rooms_total: int, su: int, ac: int, flow_mode: str, basic: bool) -> dict:
    brand_col = "v2" if d["brand"] == "ABB" else "v1"
    cost_col = "cost2" if d["brand"] == "ABB" else "cost1"
    ph3 = d["phase"] == "3"
    L = int(p.v("panel.lines_per_rcd")) or 4
    master = d["master"]
    devices = []

    def dev(key, name, qty, pkey, mods=None, price=None, cost=None):
        pr = p.v(pkey, brand_col) if price is None else price
        md = p.v(pkey, "v3") if mods is None else mods
        c = p.cost(pkey, cost_col) if cost is None and pkey and pkey.startswith("auto.") else cost
        devices.append({"key": key, "name": name, "qty": qty, "mod": md, "price": pr, "sum": qty * pr, "pkey": pkey,
                        "cost": c, "unit": "шт"})

    n = math.ceil(n_sock / 2) if basic else n_sock
    k = (1 if d["apron"] else 0) + (1 if d["oven"] else 0)
    s_rcd, s_mcb, s_dif = protect(n, L)
    t_rcd, t_mcb, t_dif = protect(tp, L)
    contactor = ("ABB ESB 40-40N" if master == "all" else "ABB ESB 20-20N") if d["brand"] == "ABB" else \
        ("Dekraft МК-103 4НО 40 А" if master == "all" else "Dekraft МК-103 2НО 20 А")

    dev("main", f"Вводной автомат {'3P' if ph3 else '2P'} {d['main_a']:g} А", 1, "auto.main3p" if ph3 else "auto.main2p")
    dev("relay", "Реле напряжения (по одному на фазу)", p.v("panel.relay_3ph") if ph3 else p.v("panel.relay_1ph"), None,
        mods=p.v("panel.relay_mod"), price=p.v("panel.relay_price"), cost=p.cost("panel.relay_price"))
    dev("master_mcb", "Автомат 1P 6 А — цепь мастер-выключателя", 1 if master != "none" else 0, "auto.mcb16")
    dev("contactor", f"Контактор мастер-выключателя «{'свет + розетки' if master == 'all' else 'свет'}» ({contactor})",
        1 if master != "none" else 0, "auto.contactor_all" if master == "all" else "auto.contactor_light")
    dev("light", "Автомат 1P 10 А — освещение", (1 if rooms_total > 0 else 0) if basic else rooms_total, "auto.mcb16")
    dev("sock_mcb", "Автомат 1P 16 А — розетки комнат (под УЗО)", s_mcb, "auto.mcb16")
    dev("sock_rcd", f"УЗО 2P 40 А 30 мА AC — розетки комнат (до {L} линий на УЗО)", s_rcd, "auto.rcd")
    dev("sock_dif", "Диф 1P+N 16 А 30 мА AC — розетки комнат (одна линия)", s_dif, "auto.dif16")
    dev("kitchen_rcd", "УЗО 2P 40 А 30 мА AC — кухня", 1 if k == 2 else 0, "auto.rcd")
    dev("kitchen_mcb", "Автомат 1P 16 А — кухня: фартук + розетки, духовка (под УЗО)", 2 if k == 2 else 0, "auto.mcb16")
    dev("kitchen_dif", "Диф 1P+N 16 А 30 мА AC — кухня (одна линия)", 1 if k == 1 else 0, "auto.dif16")
    dev("fridge", "Диф 1P+N 16 А 30 мА AC — холодильник + СВЧ", 1 if d["fridge"] else 0, "auto.dif16")
    dev("appliances", "Диф 1P+N 16 А 30 мА AC — ПММ, стиральная, сушильная, санузлы",
        (1 if d["dishwasher"] else 0) + (1 if d["washer"] else 0) + (1 if d["dryer"] else 0) + su, "auto.dif16")
    dev("tp_rcd", "УЗО 2P 40 А 30 мА AC — тёплые полы", t_rcd, "auto.rcd")
    dev("tp_mcb", "Автомат 1P 16 А — тёплые полы (под УЗО, на каждый регулятор)", t_mcb, "auto.mcb16")
    dev("tp_dif", "Диф 1P+N 16 А 30 мА AC — тёплый пол (одна линия)", t_dif, "auto.dif16")
    dev("ac", "Автомат 1P 16 А — кондиционеры (без УЗО)", ac, "auto.mcb16")
    dev("hob", "Автомат 3P 25 А — варочная панель" if ph3 else "Автомат 1P 40 А — варочная панель",
        1 if d["hob"] else 0, "auto.mcb3p25" if ph3 else "auto.mcb40")
    f3 = flow_mode == "трёхфазный"
    dev("flow", "Диф 3P+N 25 А 30 мА AC — проточный водонагреватель (трёхфазный)" if f3 else
        "Диф 1P+N 40 А 30 мА AC — проточный водонагреватель", 1 if d["flow"] else 0, "auto.dif3p25" if f3 else "auto.dif40")
    dev("boiler", "Автомат 1P 16 А — накопительный водонагреватель", 1 if d["boiler"] else 0, "auto.mcb16")
    dev("router", "Автомат 1P 6 А — роутер", 1 if d["router"] else 0, "auto.mcb16")
    dev("neptun", "Диф 1P+N 10 А 30 мА AC — Нептун", 1 if d["neptun"] else 0, "auto.dif10")
    dev("busbar", "Шины соединительные (гребёнки)", 1, None, mods=p.v("panel.fixed_mod"), price=p.v("panel.busbar"),
        cost=p.cost("panel.busbar"))

    modules = sum(x["qty"] * x["mod"] for x in devices)
    cases = pick_cases(p, d["case_type"], modules)
    case_name = "накладной ABB Mistral" if d["case_type"] == "surface" else "встраиваемый ABB UK600"
    case_lines = [{"key": f"case{i}", "name": f"Корпус щита {case_name} на {c['nominal']:g} модулей" + (" (второй щит)" if i else ""),
                   "qty": 1, "mod": 0, "price": c["price"], "sum": c["price"], "pkey": c["key"], "cost": c["cost"], "unit": "шт"}
                  for i, c in enumerate(cases)]
    cap = sum(c["capacity"] for c in cases)
    nominal = sum(c["nominal"] for c in cases)
    text = f"{modules:g} из {cap:g} мод." + (f" (2 щита: {cases[0]['nominal']:g} + {cases[1]['nominal']:g})" if len(cases) > 1
                                              else f" (щит на {nominal:g})")
    return {"devices": devices, "modules": modules, "cases": case_lines, "case_text": text, "capacity": cap,
            "assembly_qty": nominal, "case_name": case_name, "lines": {"sock": n, "kitchen": k, "tp": tp}, "L": L,
            "materials_sum": sum(x["sum"] for x in devices) + sum(c["sum"] for c in case_lines)}


def pick_cases(p: Params, case_type: str, modules: float) -> list[dict]:
    prefix = "case.surface." if case_type == "surface" else "case.flush."
    sizes = sorted(({"key": k, "nominal": float(v.get("v1") or 0), "capacity": float(v.get("v2") or 0),
                     "price": float(v.get("v3") or 0), "cost": (None if v.get("cost1") is None else float(v["cost1"]))}
                    for k, v in p.P.items() if k.startswith(prefix) and v.get("v1")), key=lambda s: s["capacity"])
    if not sizes:
        return []
    maxcap = sizes[-1]["capacity"]

    def smallest(need):
        idx = min(len(sizes), sum(1 for s in sizes if s["capacity"] < need) + 1)
        return sizes[idx - 1]
    out = [smallest(min(modules, maxcap))]
    if modules > maxcap:
        out.append(smallest(modules - maxcap))
    return out


# ---------- документы по выбранному тарифу ----------
def smeta(res: dict, tariff: str) -> dict:
    """Смета по тарифу: наценка тарифа разнесена по ценам работ (лист «СметаДанные»)."""
    p_pct = res["tariffs"][tariff]["surcharge_pct"]
    pn = res["panel"]["basic" if tariff == "basic" else "std"]
    brand = res["inputs"]["brand"]
    works = []
    for w in res["works"]:
        if w["key"] == "walls":
            qty = 1 if w["sum"] > 0 else 0
            price = xround(w["sum"] * (1 + p_pct), 2)
            works.append({"name": "Проходы через стены, мелочи", "qty": qty, "price": price, "sum": qty * price, "unit": ""})
        else:
            price = xround(w["price"] * (1 + p_pct), 2)
            works.append({"name": w["name"], "qty": w["qty"], "price": price, "sum": w["qty"] * price, "unit": w.get("unit", "")})
    a_price = xround(pn["assembly_price"] * (1 + p_pct), 2)
    works.append({"name": f"Сборка электрощита (автоматика {brand}), маркировка, схема в дверце — за модуль корпуса",
                  "qty": pn["assembly_qty"], "price": a_price, "sum": pn["assembly_qty"] * a_price, "unit": "мод."})
    mats = [dict(m) for m in res["materials"]]
    panel = [dict(x) for x in pn["devices"]] + [dict(c) for c in pn["cases"]]
    fin = [dict(f) for f in res["finishing"]] if tariff == "turnkey" else []
    t = res["tariffs"][tariff]
    cond = []
    taping_qty = 0 if tariff == "basic" else res["inputs"]["windows"]
    cond.append({"name": "Оклейка окон и дверей, уборка", "qty": taping_qty, "price": res["prices"]["taping"],
                 "sum": taping_qty * res["prices"]["taping"], "unit": "шт"})
    trash_qty = 1 if tariff == "turnkey" else 0
    cond.append({"name": "Вынос строительного мусора", "qty": trash_qty, "price": res["prices"]["trash"],
                 "sum": trash_qty * res["prices"]["trash"], "unit": ""})
    sections = [
        {"title": "1. Работы", "lines": works},
        {"title": "2. Материалы", "lines": mats, "panel_title": f"Электрощит, автоматика {brand}:", "panel": panel},
    ]
    if tariff == "turnkey":
        sections.append({"title": "3. Чистовая установка после отделки (этап 2)", "lines": fin})
    sections.append({"title": "4. Условия тарифа" if tariff == "turnkey" else "3. Условия тарифа", "lines": cond,
                     "note": TARIFF_NOTES[tariff]})
    for s in sections:
        s["lines"] = [ln for ln in s["lines"] if ln["qty"] > 0]
        if "panel" in s:
            s["panel"] = [ln for ln in s["panel"] if ln["qty"] > 0]
        s["total"] = sum(ln["sum"] for ln in s["lines"]) + sum(ln["sum"] for ln in s.get("panel", []))
    total = sum(s["total"] for s in sections)
    pr = res["prices"]
    if tariff == "basic":
        foot = (f"Тариф «Базовый»: итоговая сумма уточняется по факту замера после монтажа; добавление точки "
                f"{fmt_int(pr['add_point'])} ₽, перенос {fmt_int(pr['move_point'])} ₽.")
    else:
        foot = ("Все позиции рассчитаны по проекту. Итоговая сумма не изменится, даже если фактический метраж или объём "
                f"работ окажутся больше. Изменения сверх лимита: добавление точки {fmt_int(pr['add_point'])} ₽, "
                f"перенос {fmt_int(pr['move_point'])} ₽.")
    return {"tariff": tariff, "tariff_name": TARIFF_NAMES[tariff], "sections": sections, "total": total,
            "price": t["price"], "footer": [foot,
                                            "Материалы: кабель ВВГнг-LS ГОСТ, закупка и доставка наши, остаток забираем. Цены на материалы действительны 7 дней.",
                                            f"Расчёт для ввода: {'3 фазы' if res['inputs']['phase'] == '3' else '1 фаза'}, вводной автомат {res['inputs']['main_a']:g} А."]}


TARIFF_NOTES = {
    "basic": "Тариф «Базовый»: сумма предварительная, считается после монтажа по реальному метражу; добавления и переносы — по прайсу; старт по свободному окну бригады; гарантия 1 год",
    "std": "Пакет «Стандарт»: сумма закреплена в договоре и не изменится, дата старта в договоре, до 3 изменений бесплатно, проверка проекта, схема скрытых трасс с размерами, гарантия 3 года, 1 сервисный выезд в течение года",
    "turnkey": "Пакет «Под ключ»: сумма закреплена в договоре и не изменится, до 8 изменений бесплатно, проверка проекта, схема скрытых трасс с размерами, 3D-тур квартиры, гарантия 5 лет",
}

KP_ROWS = [
    ("Монтаж по проекту, кабель ВВГнг-LS ГОСТ, материалы наши с доставкой", "✓", "✓", "✓"),
    ("Группы в щите", "упрощённые: свет одной группой на квартиру, розетки — линия на 2 комнаты; УЗО 30 мА",
     "отдельная линия света и розеток на каждую комнату; УЗО и дифы 30 мА",
     "отдельная линия света и розеток на каждую комнату; УЗО и дифы 30 мА"),
    ("Старт работ", "по свободному окну бригады", "дата закрепляется в договоре", "дата закрепляется в договоре"),
    ("Итоговая сумма", "по реальному метражу после монтажа — может измениться", "закреплена в договоре — не изменится",
     "закреплена в договоре — не изменится"),
    ("Если решите добавить или перенести точки", "по прайсу", "до 3 изменений бесплатно", "до 8 изменений бесплатно"),
    ("Проверка проекта дизайнера на ошибки до начала работ", "—", "✓", "✓"),
    ("Сборка электрощита", "{brand}, маркировка, схема в дверце", "{brand}, маркировка, схема в дверце",
     "{brand}, маркировка, схема в дверце"),
    ("3D-тур квартиры с трассами кабеля", "опция", "опция", "включено"),
    ("Гарантия", "1 год", "3 года", "5 лет"),
    ("Установка розеток, интернет-розеток, выключателей и термодатчиков после отделки", "—", "—", "включено"),
    ("Сервис", "—", "1 бесплатный выезд в течение года", "выезды по гарантии"),
    ("После себя", "уборка", "оклейка + уборка", "оклейка + уборка + вывоз мусора"),
]


def kp(res: dict) -> dict:
    d = res["inputs"]
    v = res["volumes"]
    std_panel = res["panel"]["std"]
    rows = [(r[0], *[c.replace("{brand}", d["brand"]) for c in r[1:]]) for r in KP_ROWS]
    pr = res["prices"]
    return {
        "object": d["object"],
        "summary": f"{d['area']:g} м² · {v['points']:g} электроточек · кабель ~{xround(v['cable_power'], -1):g} м · щит {std_panel['assembly_qty']:g} модулей",
        "intro": "Ниже — полная стоимость во всех тарифах: работы и все материалы, включая кабель и автоматику щита. В «Базовом» сумма предварительная и уточняется после монтажа.",
        "tariffs": [{"key": t, "name": TARIFF_NAMES[t], **res["kp"][t], "recommended": t == "std"} for t in TARIFFS],
        "rows": rows,
        "tour_option": pr["tour_option"],
        "conditions": [
            f"Изменения сверх лимита: добавление точки {fmt_int(pr['add_point'])} ₽, перенос {fmt_int(pr['move_point'])} ₽.",
            f"Расчёт сделан для ввода: {'3 фазы' if d['phase'] == '3' else '1 фаза'}, вводной автомат {d['main_a']:g} А.",
            "Стоимость рассчитана по проекту и замеру. В «Стандарте» и «Под ключ» она фиксируется в договоре и не меняется; в «Базовом» уточняется по фактическому объёму после монтажа.",
            "Цены на материалы действительны 7 дней с даты предложения.",
        ],
    }


def panel_fill(res: dict, tariff: str) -> dict:
    """Наполнение щита для монтажника: нумерация с подгруппами, назначение линий, отметка мастер-выключателя."""
    d = res["inputs"]
    basic = tariff == "basic"
    pn = res["panel"]["basic" if basic else "std"]
    rooms = [r for r in d["rooms"] if r["type"]]
    L = pn["L"]
    # ширина аппаратов — из устройств щита
    mods = {x["key"]: x["mod"] for x in pn["devices"]}
    master = d["master"]
    f_light = "✓" if master != "none" else ""
    f_sock = "✓" if master == "all" else ("—" if master == "light" else "")
    f_never = "—" if master != "none" else ""
    ph3 = d["phase"] == "3"
    rows = []
    g = 0

    def top(device, purpose, mod=0, flag=""):
        nonlocal g
        g += 1
        rows.append({"no": str(g), "device": device, "purpose": purpose, "flag": flag, "mod": mod, "top": True})
        return g

    def sub(gi, k, device, purpose, mod, flag=""):
        rows.append({"no": f"{gi}.{k}", "device": device, "purpose": purpose, "flag": flag, "mod": mod, "top": False})

    m1 = mods.get("light", 1)
    top(f"Вводной автомат {'3P' if ph3 else '2P'} {d['main_a']:g} А", "Ввод", mods.get("main", 3))
    relays = next(x["qty"] for x in pn["devices"] if x["key"] == "relay")
    top(f"Реле напряжения × {relays:g}", "Защита от скачков напряжения (по одному на фазу)", relays * mods.get("relay", 2))
    if master != "none":
        gi = top("Мастер-выключатель", "режим «свет»" if master == "light" else "режим «свет + розетки»")
        sub(gi, 1, "Автомат 1P 6 А", "Цепь управления (кнопка мастер-выключателя)", mods.get("master_mcb", 1))
        cname = next(x["name"] for x in pn["devices"] if x["key"] == "contactor")
        cname = "Контактор " + cname[cname.find("(") + 1:-1]
        sub(gi, 2, cname, "Отключает всё освещение" if master == "light" else "Отключает всё, кроме холодильника + СВЧ, роутера и Нептуна",
            mods.get("contactor", 1))
    if rooms:
        gi = top("Освещение", "")
        if basic:
            sub(gi, 1, "Автомат 1P 10 А", "Свет: вся квартира", m1, f_light)
        else:
            for i, r in enumerate(rooms, 1):
                sub(gi, i, "Автомат 1P 10 А", "Свет: " + room_label(r), m1, f_light)
    # розетки комнат
    sock_rooms = [room_label(r) for r in rooms if r["sockets"] and r["type"] not in ("Санузел", "Кухня")]
    labels = [" + ".join(sock_rooms[i:i + 2]) for i in range(0, len(sock_rooms), 2)] if basic else sock_rooms
    _group(rows, labels, L, "Розетки комнат", "Розетки: ", f_sock, mods, top, sub)
    # кухня
    k = (1 if d["apron"] else 0) + (1 if d["oven"] else 0)
    if k == 2:
        gi = top("УЗО 2P 40 А 30 мА AC", "Кухня", mods.get("kitchen_rcd", 2))
        sub(gi, 1, "Автомат 1P 16 А", "Фартук + обычные розетки кухни", mods.get("kitchen_mcb", 1), f_sock)
        sub(gi, 2, "Автомат 1P 16 А", "Духовка", mods.get("kitchen_mcb", 1), f_sock)
    elif k == 1:
        top("Диф 1P+N 16 А 30 мА AC", "Фартук + обычные розетки кухни" if d["apron"] else "Духовка", mods.get("kitchen_dif", 2), f_sock)
    if d["fridge"]:
        top("Диф 1P+N 16 А 30 мА AC", "Холодильник + СВЧ", mods.get("fridge", 2), f_never)
    for key, name in (("dishwasher", "Посудомоечная машина"), ("washer", "Стиральная машина"), ("dryer", "Сушильная машина")):
        if d[key]:
            top("Диф 1P+N 16 А 30 мА AC", name, mods.get("appliances", 2), f_sock)
    for r in rooms:
        if r["type"] == "Санузел":
            top("Диф 1P+N 16 А 30 мА AC", room_label(r) + ": розетки + полотенцесушитель", mods.get("appliances", 2), f_sock)
    _group(rows, [room_label(r) for r in rooms if r["floor"]], L, "Тёплые полы", "Тёплый пол: ", f_sock, mods, top, sub)
    for r in rooms:
        if r["ac"]:
            top("Автомат 1P 16 А", "Кондиционер: " + room_label(r), mods.get("ac", 1), f_sock)
    if d["hob"]:
        top("Автомат 3P 25 А" if ph3 else "Автомат 1P 40 А", "Варочная панель (без УЗО)", mods.get("hob", 3 if ph3 else 1), f_sock)
    if d["flow"]:
        fm = res["volumes"]["flow_mode"]
        top("Диф 3P+N 25 А 30 мА AC" if fm == "трёхфазный" else "Диф 1P+N 40 А 30 мА AC",
            f"Проточный водонагреватель ({fm})", mods.get("flow", 2), f_sock)
    if d["boiler"]:
        top("Автомат 1P 16 А", "Накопительный водонагреватель", mods.get("boiler", 1), f_sock)
    if d["router"]:
        top("Автомат 1P 6 А", "Роутер / слаботочный щит", mods.get("router", 1), f_never)
    if d["neptun"]:
        top("Диф 1P+N 10 А 30 мА AC", "Нептун (защита от протечек)", mods.get("neptun", 2), f_never)
    total = sum(r["mod"] for r in rows)
    notes = ["Все УЗО и дифы — 30 мА, тип AC. Нули линий под каждым УЗО — только через это УЗО (своя шинка N на каждое УЗО)."]
    if master == "all":
        notes.append("Контактор 40 А 4НО: линии с ✓ распределить по 4 полюсам, не более 40 А на полюс; варочную панель, духовку и проточник — на разные полюса.")
    notes.append("Маркировка линий в щите и на схеме в дверце — по номерам и названиям из этой таблицы.")
    notes.append("Шины соединительные (гребёнки), нулевые и PE-шины — по месту, модулей на рейке не занимают.")
    return {
        "tariff": tariff, "tariff_name": TARIFF_NAMES[tariff], "rows": rows, "modules": total,
        "header": [f"Тариф: {TARIFF_NAMES[tariff]}   ·   Ввод: {'3 фазы' if ph3 else '1 фаза'}, вводной автомат {d['main_a']:g} А   ·   Автоматика: {d['brand']}",
                   f"Щит: {pn['case_name']} на {pn['assembly_qty']:g} мод. (вмещает {pn['capacity']:g}, занято {pn['modules']:g})",
                   "Мастер-выключатель: нет" if master == "none" else f"Мастер-выключатель: «{MASTER[master]}» — линии с отметкой ✓ заводятся через контактор"],
        "notes": notes,
    }


def _group(rows, labels, L, title, prefix, flag, mods, top, sub):
    n = len(labels)
    rcd, mcb, dif = protect(n, L)
    idx = 0
    for gnum in range(rcd):
        gi = top("УЗО 2P 40 А 30 мА AC", title + (f" — группа {gnum + 1}" if rcd > 1 else ""), mods.get("sock_rcd", 2))
        for k in range(1, L + 1):
            if idx >= mcb:
                break
            sub(gi, k, "Автомат 1P 16 А", prefix + labels[idx], mods.get("sock_mcb", 1), flag)
            idx += 1
    if dif:
        top("Диф 1P+N 16 А 30 мА AC", prefix + labels[n - 1], mods.get("sock_dif", 2), flag)


def fmt_int(x: float) -> str:
    return f"{xround(x):,.0f}".replace(",", " ")
