"""API калькулятора на SQLite: справочник → расчёт из заявки → правки → документы → ссылка клиенту → сумма в заявку."""
import json
import pathlib

from fastapi.testclient import TestClient

import app.main as main
from app import calc
from app.calc_defaults import DEFAULTS

fx = json.loads((pathlib.Path(__file__).parent / "calc_fixtures.json").read_text())
P0 = {k: {"v1": v1, "v2": v2, "v3": v3, "vtext": vt} for (k, s, l, u, v1, v2, v3, n, vt) in DEFAULTS}

c = TestClient(main.app)
with c:
    def ok(r):
        assert r.status_code == 200, (r.request.method, r.request.url, r.status_code, r.text)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text

    t = ok(c.post("/api/auth/login", data={"username": "d@test.ru", "password": "secret123"}))["access_token"]
    c.headers["Authorization"] = "Bearer " + t

    # справочник засеян с листа «Расценки»
    secs = ok(c.get("/api/calc/params"))["sections"]
    keys = {it["key"] for s in secs for it in s["items"]}
    assert {"work.chase", "auto.dif16", "case.flush.36", "mat.vvg25", "general.brand"} <= keys, keys
    auto = next(s for s in secs if s["section"] == "auto")
    assert auto["cols"] == ["Dekraft, ₽", "ABB, ₽", "Модулей"]

    # заявка → новый расчёт: объект и площадь из заявки
    lead = ok(c.post("/api/leads", json={"name": "Антон, ЖК Шагал", "source": "profi", "area_m2": 60, "address": "ЖК Шагал"}))
    e = ok(c.post("/api/estimates", json={"lead_id": lead["id"]}))
    assert e["lead_id"] == lead["id"] and e["result"]["inputs"]["area"] == 60 and e["result"]["inputs"]["object"] == "ЖК Шагал"

    # данные замера из примера Excel → цены как в файле
    ex = fx[0]
    e = ok(c.put(f"/api/estimates/{e['id']}", json={"inputs": ex["inputs"], "tariff": "turnkey"}))
    for tn in calc.TARIFFS:
        assert abs(e["result"]["tariffs"][tn]["price"] - ex["expected"]["tariffs"][tn]["price"]) < 0.02, (tn, e["result"]["tariffs"][tn]["price"])
    assert e["tariff"] == "turnkey" and abs(e["summary"]["std"]["price"] - ex["expected"]["kp"]["std"]) <= 505

    # документы
    kp = ok(c.get(f"/api/estimates/{e['id']}/doc/kp"))
    assert "Коммерческое предложение" in kp and "Стандарт" in kp
    sm = ok(c.get(f"/api/estimates/{e['id']}/doc/smeta?tariff=std"))
    assert "Смета — тариф «Стандарт»" in sm and "ИТОГО К ОПЛАТЕ" in sm
    pn = ok(c.get(f"/api/estimates/{e['id']}/doc/panel"))
    assert "Наполнение электрощита" in pn and "Свет: Спальня" in pn and "Розетки: Детская" in pn

    # ссылка для клиента — без входа
    sh = ok(c.post(f"/api/estimates/{e['id']}/share"))
    anon = TestClient(main.app)
    page = anon.get(sh["url"])
    assert page.status_code == 200 and "Коммерческое предложение" in page.text and "Позвонить" in page.text
    assert anon.get("/api/public/kp/" + "x" * 24).status_code == 404
    assert anon.get(f"/api/estimates/{e['id']}").status_code == 401

    # смена цен в справочнике не меняет сохранённый расчёт, пока не пересчитать
    ok(c.patch("/api/calc/params/work.chase", json={"v1": 500}))
    e2 = ok(c.get(f"/api/estimates/{e['id']}"))
    assert e2["params_outdated"] and abs(e2["result"]["tariffs"]["std"]["price"] - ex["expected"]["tariffs"]["std"]["price"]) < 0.02
    e3 = ok(c.put(f"/api/estimates/{e['id']}", json={"refresh_params": True}))
    assert e3["result"]["tariffs"]["std"]["price"] > e2["result"]["tariffs"]["std"]["price"] and not e3["params_outdated"]
    ok(c.patch("/api/calc/params/work.chase", json={"v1": 400}))

    # привязка цены к складу: цена клиенту позиции заменяет значение справочника
    wh = ok(c.get("/api/stock/warehouses"))[0]
    prod = ok(c.post("/api/stock/products", json={"name": "ВВГнг-LS 3×2,5 тест", "unit": "м", "client_price": 130,
                                                  "init_qty": 100, "init_cost": 90, "init_warehouse_id": wh["id"]}))
    assert c.patch("/api/calc/params/norm.c15_corr", json={"product_id": prod["id"]}).status_code == 400
    ok(c.patch("/api/calc/params/mat.vvg25", json={"product_id": prod["id"]}))
    e4 = ok(c.post("/api/estimates", json={"inputs": ex["inputs"]}))
    m25 = next(x for x in e4["result"]["materials"] if x["key"] == "vvg25")
    assert m25["price"] == 130 and abs(m25["cost"] - 90) < 0.01, m25
    assert e4["result"]["margin"]["std"]["lines"] >= 1
    ok(c.patch("/api/calc/params/mat.vvg25", json={"unlink": ["product_id"]}))

    # сумма КП в заявку
    ok(c.put(f"/api/estimates/{e['id']}", json={"tariff": "std"}))
    r = ok(c.post(f"/api/estimates/{e['id']}/to-lead"))
    L = ok(c.get(f"/api/leads/{lead['id']}"))
    assert float(L["offer_sum"]) == r["offer_sum"] and L["tariff"] == "Стандарт" and L["stage"] == "offer_sent", L

    # список, копия, удаление
    lst = ok(c.get(f"/api/estimates?lead_id={lead['id']}"))
    assert len(lst) == 1 and lst[0]["share_token"]
    cp = ok(c.post(f"/api/estimates/{e['id']}/copy"))
    ok(c.delete(f"/api/estimates/{cp['id']}"))
    ok(c.delete(f"/api/estimates/{e['id']}/share"))
    assert anon.get(sh["url"]).status_code == 404
    assert c.patch("/api/calc/params/general.brand", json={"vtext": "Schneider"}).status_code == 400
    ok(c.patch("/api/calc/params/general.brand", json={"vtext": "ABB"}))
    assert ok(c.get("/api/calc/defaults"))["inputs"]["brand"] == "ABB"

    # по умолчанию — ABB; разовая перестановка Dekraft → ABB не повторяется при перезапуске
    from app import calc_params as cp_
    from app.db import SessionLocal
    ok(c.patch("/api/calc/params/general.brand", json={"vtext": "Dekraft"}))
    with SessionLocal() as db:
        cp_.seed(db)
    assert ok(c.get("/api/calc/defaults"))["inputs"]["brand"] == "Dekraft"
    ok(c.patch("/api/calc/params/general.brand", json={"vtext": "ABB"}))

    # «ПРОВЕРИТЬ»: отметка видна, «Верно» снимает, пояснение остаётся; правка значения тоже снимает
    secs = ok(c.get("/api/calc/params"))["sections"]
    items = {it["key"]: it for s in secs for it in s["items"]}
    assert items["norm.power_line_len"]["check"] and items["work.kup"]["check"] and not items["work.chase"]["check"]
    ok(c.patch("/api/calc/params/norm.power_line_len", json={"confirm": True}))
    ok(c.patch("/api/calc/params/work.kup", json={"v1": 600}))
    items = {it["key"]: it for s in ok(c.get("/api/calc/params"))["sections"] for it in s["items"]}
    assert not items["norm.power_line_len"]["check"] and items["norm.power_line_len"]["note"] == "остальная техника уже внутри метража по точкам", items["norm.power_line_len"]
    assert not items["work.kup"]["check"] and items["work.kup"]["note"] == "цена не называлась, поставлена как у коробки"
    ok(c.patch("/api/calc/params/work.kup", json={"v1": 550}))

    # реквизиты исполнителя: текст, проверка цифр; в расчёт и снимок не попадают
    assert "contractor.account" in items and items["contractor.account"]["vtext"] is None
    assert items["contractor.bik"]["vtext"] == "044525411" and "ВТБ" in items["contractor.bank"]["vtext"]
    assert c.patch("/api/calc/params/contractor.account", json={"vtext": "123"}).status_code == 400
    ok(c.patch("/api/calc/params/contractor.account", json={"vtext": "4080 2810 0000 0000 0001"}))
    ok(c.patch("/api/calc/params/contractor.bik", json={"vtext": "044500001"}))
    ok(c.patch("/api/calc/params/contractor.address", json={"vtext": "Тестовый адрес ИП"}))
    e5 = ok(c.post("/api/estimates", json={"inputs": ex["inputs"], "lead_id": lead["id"]}))
    assert not ok(c.get(f"/api/estimates/{e5['id']}"))["params_outdated"]

    # PDF одной страницей: КП, смета, щит; КП по публичной ссылке
    from pypdf import PdfReader as _PR0
    import io as _io0
    for kind in ("kp", "smeta", "panel"):
        r = c.get(f"/api/estimates/{e5['id']}/pdf/{kind}", params={"tariff": "std"})
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf", (kind, r.status_code, r.text[:200])
        pr = _PR0(_io0.BytesIO(r.content))
        h_mm = float(pr.pages[0].mediabox.height) * 25.4 / 72
        assert len(pr.pages) == 1 and abs(float(pr.pages[0].mediabox.width) * 25.4 / 72 - 210) < 1, (kind, len(pr.pages))
        print(f"pdf {kind}: 1 страница, {h_mm:.0f} мм")
    assert c.get(f"/api/estimates/{e5['id']}/pdf/zzz").status_code == 404
    tok5 = ok(c.post(f"/api/estimates/{e5['id']}/share"))["token"]
    with TestClient(main.app) as anon:
        pub = anon.get(f"/api/public/kp/{tok5}")
        assert f"/api/public/kp/{tok5}/pdf" in pub.text and "Скачать PDF" in pub.text
        rp = anon.get(f"/api/public/kp/{tok5}/pdf")
        assert rp.status_code == 200 and rp.content[:4] == b"%PDF"
        assert anon.get("/api/public/kp/xxxxxxxxxxxxxxxxxxxxxxxx/pdf").status_code == 404
    ok(c.delete(f"/api/estimates/{e5['id']}/share"))

    # договор по расчёту (пакет ИП): данные по умолчанию из заявки, суммы = КП
    st = ok(c.get(f"/api/estimates/{e5['id']}/contract"))
    assert st["data"]["kind"] == "person" and st["data"]["address"] == "ЖК Шагал" and not st["saved"] and not st["ocr_ready"]
    assert st["data"]["end"] > st["data"]["date"] and not st["design"]
    assert "Фамилия Имя Отчество" in st["missing"] and "Реквизиты исполнителя: телефон" in st["missing"]
    ok(c.patch("/api/calc/params/contractor.phone", json={"vtext": "+7 900 000-00-01"}))
    ok(c.patch("/api/calc/params/contractor.email", json={"vtext": "ip@example.com"}))
    person = {"kind": "person", "number": "1611/26", "date": "2026-11-16", "end": "2026-12-14",
              "address": "Москва, ул. Тестовая, 1, кв. 2", "fio": "Иванов Иван Иванович", "birth": "1985-03-04",
              "pass_series": "4510", "pass_number": "123456", "pass_issued": "ГУ МВД РОССИИ ПО Г. МОСКВЕ", "pass_date": "2015-06-07",
              "pass_code": "770-001", "reg_address": "Москва, ул. Регистрационная, 1", "phone": "+7 900 000-00-00", "junk": "x"}
    st = ok(c.put(f"/api/estimates/{e5['id']}/contract", json={"data": person, "tariff": "turnkey"}))
    n = st["numbers"]
    assert st["saved"] and st["tariff"] == "turnkey" and "junk" not in st["data"] and n["M"]
    assert n["stage2_sum"] > 0 and n["warranty"] == 60 and n["limit"] == 8 and abs(n["total"] - n["works_sum"] - n["mat_sum"]) < 0.01
    kp = ok(c.get(f"/api/estimates/{e5['id']}"))["result"]["kp"]["turnkey"]["price"]
    assert abs(kp - n["total"]) < 0.005, (kp, n["total"])
    assert not st["missing"], st["missing"]
    lst = ok(c.get(f"/api/estimates/{e5['id']}/contract/list"))
    names = [f["name"] for f in lst]
    assert [x[:2] for x in names[:5]] == ["01", "02", "03", "04", "05"] and "этап_2" in names[4] and names[-1] == "Щит_для_монтажника.xlsx", names
    import io as _io, re as _re, zipfile as _zf
    import docx as _docx
    zr = c.get(f"/api/estimates/{e5['id']}/contract/files")
    assert zr.status_code == 200 and zr.headers["content-type"] == "application/zip"
    z = _zf.ZipFile(_io.BytesIO(zr.content))
    assert "Щит_для_монтажника.xlsx" not in z.namelist() and len(z.namelist()) == 5, z.namelist()
    d = _docx.Document(_io.BytesIO(z.read(names[0])))
    text = "\n".join([p.text for p in d.paragraphs] + [cl.text for t in d.tables for r in t.rows for cl in r.cells])
    assert "Иванов Иван Иванович" in text and "Тестовый адрес ИП" in text and "40802810000000000001" in text and "ip@example.com" in text
    assert "60 (шестьдесят) месяцев" in text and "до 8 (восемь) переносов" in text and "Второй этап Работ" in text
    assert "«16» ноября 2026 г." in text and "14 декабря 2026 г." in text and "гражданин РФ" in text
    assert "[___]" not in text and not _re.search(r"\{\w+\}", text)
    one = c.get(f"/api/estimates/{e5['id']}/contract/files", params={"name": names[1]})
    assert one.status_code == 200 and "spreadsheetml" in one.headers["content-type"]
    assert c.get(f"/api/estimates/{e5['id']}/contract/files", params={"name": "Щит_для_монтажника.xlsx"}).status_code == 200
    assert c.get(f"/api/estimates/{e5['id']}/contract/files", params={"name": "../x"}).status_code == 404
    # дизайн-проект PDF → Приложение № 3 со штампом
    from reportlab.pdfgen import canvas as _cv
    _b = _io.BytesIO(); _c = _cv.Canvas(_b); _c.drawString(100, 700, "plan"); _c.showPage(); _c.drawString(100, 700, "plan2"); _c.save()
    assert c.post(f"/api/estimates/{e5['id']}/contract/design", files={"file": ("x.png", b"\x89PNG", "image/png")}).status_code == 400
    st = ok(c.post(f"/api/estimates/{e5['id']}/contract/design", files={"file": ("p.pdf", _b.getvalue(), "application/pdf")}))
    assert st["design"] and "Дизайн-проект: какие листы" in st["missing"]
    ok(c.put(f"/api/estimates/{e5['id']}/contract", json={"data": {**person, "design_sheets": "листы 1–2", "design_pages": "2"}}))
    names = [f["name"] for f in ok(c.get(f"/api/estimates/{e5['id']}/contract/list"))]
    assert "Приложение_3_Дизайн-проект" in names[3], names
    pdf = c.get(f"/api/estimates/{e5['id']}/contract/files", params={"name": names[3]})
    from pypdf import PdfReader as _PR
    pr = _PR(_io.BytesIO(pdf.content))
    assert len(pr.pages) == 1 and "Приложение № 3" in pr.pages[0].extract_text() and "plan2" in pr.pages[0].extract_text()
    # в документы заявки; повтор заменяет прежний пакет
    ok(c.post(f"/api/estimates/{e5['id']}/contract/to-lead"))
    ok(c.post(f"/api/estimates/{e5['id']}/contract/to-lead"))
    L = ok(c.get(f"/api/leads/{lead['id']}"))
    docs = [d for d in L["documents"] if d["title"].endswith(f"расчёт {e5['id']}")]
    assert len(docs) == 6 and {d["kind"] for d in docs} == {"contract", "appendix", "act"}, docs
    ok(c.delete(f"/api/estimates/{e5['id']}/contract/design"))
    # распознавание: без ключа — понятная ошибка; с ключом — ответ OpenAI проверяется и нормализуется
    rr = c.post("/api/contract/recognize", files=[("files", ("p.jpg", b"\xff\xd8\xff", "image/jpeg"))])
    assert rr.status_code == 400 and "OPENAI_API_KEY" in rr.text, rr.text
    import io as _io2, json as _json
    from PIL import Image
    from app import doc_ocr
    from app.config import settings as _st
    buf = _io2.BytesIO(); Image.new("RGB", (40, 30), "white").save(buf, format="PNG")
    sent = {}

    class _R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": _json.dumps({"kinds": ["passport", "registration"], "fields": {
                "fio": "Иванов Иван Иванович", "birth": "04.03.1985", "pass_series": "45 10", "pass_number": "123456",
                "pass_issued": "ГУ МВД РОССИИ ПО Г. МОСКВЕ", "pass_date": "2015-06-07", "pass_code": "770001",
                "reg_address": "г. Москва, ул. Тестовая, д. 1, кв. 2", "inn": "123", "org_name": None}}, ensure_ascii=False)}}]}

    def _post(url, json=None, **kw):
        sent["url"], sent["n"] = url, len(json["messages"][1]["content"])
        return _R()
    _old = (doc_ocr.httpx.post, _st.OPENAI_API_KEY)
    doc_ocr.httpx.post, _st.OPENAI_API_KEY = _post, "test"
    try:
        rr = ok(c.post("/api/contract/recognize", files=[("files", ("a.png", buf.getvalue(), "image/png")),
                                                         ("files", ("b.png", buf.getvalue(), "image/png"))]))
        assert ok(c.get(f"/api/estimates/{e5['id']}/contract"))["ocr_ready"]
    finally:
        doc_ocr.httpx.post, _st.OPENAI_API_KEY = _old
    f = rr["fields"]
    assert sent["url"].endswith("/chat/completions") and sent["n"] == 3, sent
    assert f["kind"] == "person" and f["birth"] == "1985-03-04" and f["pass_series"] == "4510" and f["pass_code"] == "770-001"
    assert "inn" not in f and "org_name" not in f and rr["kinds"] == ["passport", "registration"], rr

print("CALC API OK")
