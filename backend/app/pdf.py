"""PDF документов расчёта одной страницей — без разрыва на листы A4.

Страница шириной 210 мм, высота — по содержимому: сначала вёрстка на очень длинной странице, по ней меряем
высоту документа, затем печать с этой высотой. Движок — WeasyPrint (в образе API стоят pango и шрифты Liberation)."""

MM = 25.4 / 96          # px → мм
BASE = ("body{background:#fff!important} .page{max-width:none!important;min-height:0!important} "
        ".print,.cta,.noprint{display:none!important}")


def _bottom(box) -> float:
    b = (getattr(box, "position_y", 0) or 0) + (box.margin_height() if hasattr(box, "margin_height") else 0)
    for c in getattr(box, "children", None) or []:
        b = max(b, _bottom(c))
    return b


def single_page(html: str, width_mm: float = 210) -> bytes:
    from weasyprint import CSS, HTML
    doc = HTML(string=html).render(stylesheets=[CSS(string=f"@page{{size:{width_mm}mm 5000mm;margin:0}} {BASE}")])
    if len(doc.pages) == 1:
        h = max((_bottom(c) for c in doc.pages[0]._page_box.children), default=0) * MM + 1   # сама страница не в счёт
    else:                                   # длиннее 5 м — оставляем постраничную печать
        return doc.write_pdf()
    return HTML(string=html).write_pdf(stylesheets=[CSS(string=f"@page{{size:{width_mm}mm {max(h, 50):.1f}mm;margin:0}} {BASE}")])
