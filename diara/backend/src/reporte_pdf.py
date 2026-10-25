"""Arma el PDF del reporte de un auditor: portada con resumen ejecutivo y una sección por proyecto asignado.
Recibe datos ya preparados (src/reporteria.py) y solo se encarga del diseño. La plantilla institucional
(color, logo, institución, unidad y pie) se configura en Administración → Reportes.

Biblioteca: ReportLab (platypus). El documento es una lista de "flowables" (Paragraph, Table, Image, Drawing,
PageBreak...) que ReportLab reparte en páginas; el encabezado y pie se dibujan en cada página con _pie().
Estructura del PDF:
    _portada(r)     indicadores generales, resumen ejecutivo por proyecto, "requiere atención"
    _proyecto(p)    una sección (desde página nueva) por proyecto
Fuentes: se usan las estándar (Helvetica), que solo cubren Latin-1. Por eso todo texto pasa por limpio()/t()."""
import io, re, threading
from xml.sax.saxutils import escape
from reportlab.graphics.shapes import Drawing, Line, PolyLine, String, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

# Paleta. AZUL es el color principal y se reemplaza por el de la plantilla en construir() (ver _aplicar_color).
AZUL, TEXTO, GRIS, BORDE = colors.HexColor("#0b5cab"), colors.HexColor("#14202b"), colors.HexColor("#5b6b7a"), colors.HexColor("#dde3e9")
ROJO, VERDE, AMBAR, FONDO = colors.HexColor("#c0392b"), colors.HexColor("#2e7d4f"), colors.HexColor("#b07d00"), colors.HexColor("#f4f6f8")
ANCHO = A4[0] - 3.6 * cm  # ancho útil: página A4 menos márgenes izquierdo y derecho (1.8 cm cada uno)

# Estilos de texto
_ss = getSampleStyleSheet()
E = {
    "titulo": ParagraphStyle("t", parent=_ss["Title"], fontSize=22, leading=26, textColor=AZUL, alignment=0, spaceAfter=4),
    "sub": ParagraphStyle("s", parent=_ss["Normal"], fontSize=11, leading=15, textColor=GRIS),
    "h1": ParagraphStyle("h1", parent=_ss["Heading1"], fontSize=16, leading=20, textColor=TEXTO, spaceBefore=0, spaceAfter=4),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontSize=11.5, leading=15, textColor=AZUL, spaceBefore=10, spaceAfter=4),
    "n": ParagraphStyle("n", parent=_ss["Normal"], fontSize=9, leading=12, textColor=TEXTO),       # texto normal
    "mu": ParagraphStyle("mu", parent=_ss["Normal"], fontSize=8, leading=10.5, textColor=GRIS),    # texto secundario
    "kv": ParagraphStyle("kv", parent=_ss["Normal"], fontSize=15, leading=18, textColor=TEXTO, alignment=TA_CENTER),  # valor de indicador
    "kl": ParagraphStyle("kl", parent=_ss["Normal"], fontSize=7.5, leading=9, textColor=GRIS, alignment=TA_CENTER),   # etiqueta de indicador
    "cel": ParagraphStyle("c", parent=_ss["Normal"], fontSize=8, leading=10, textColor=TEXTO),     # celda de tabla
}

def limpio(x):
    """Texto apto para las fuentes estándar del PDF: sin emojis ni símbolos fuera de Latin-1."""
    s = "" if x is None else str(x)
    for a, b in (("≥", ">="), ("≤", "<="), ("→", "->"), ("·", "-"), ("–", "-"), ("—", "-")): s = s.replace(a, b)
    return re.sub(r"[^\x09\x0a\x0d\x20-\xff]", "", s).strip()

def t(x):
    """limpio() + XML escapado, para usar dentro de Paragraph."""
    # Paragraph interpreta un mini-HTML: un "&" o "<" en datos del usuario rompería el PDF si no se escapa
    return escape(limpio(x))

def _hex(c):
    """Color de ReportLab -> "#rrggbb" para usar en <font color=...>."""
    return "#" + c.hexval()[2:]

def P(x, estilo="n"):
    """Paragraph desde texto plano (lo escapa). Si ya es Paragraph, lo devuelve igual."""
    return x if isinstance(x, Paragraph) else Paragraph(t(x), E[estilo])

def _tabla(filas, anchos, cabecera=True, zebra=True):
    """Tabla estándar del reporte: cabecera con el color principal, filas alternas y celdas con ajuste de línea."""
    datos = []
    for i, f in enumerate(filas):
        # Todo se envuelve en Paragraph para que el texto largo haga salto de línea dentro de la celda
        datos.append([c if isinstance(c, (Paragraph, Image, Drawing)) else
                      Paragraph(f'<font color="white"><b>{t(c)}</b></font>', E["cel"]) if cabecera and i == 0 else P(c, "cel") for c in f])
    tb = Table(datos, colWidths=anchos, repeatRows=1 if cabecera else 0)  # repeatRows: repite la cabecera si la tabla cambia de página
    st = [("GRID", (0, 0), (-1, -1), 0.4, BORDE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if cabecera: st.append(("BACKGROUND", (0, 0), (-1, 0), AZUL))
    if zebra: st.append(("ROWBACKGROUNDS", (0, 1 if cabecera else 0), (-1, -1), [colors.white, FONDO]))
    tb.setStyle(TableStyle(st))
    return tb

def _kpis(items):
    """Fila de indicadores: [(etiqueta, valor, color o None)]."""
    celdas = [[Paragraph(f'<font color="{_hex(c or TEXTO)}"><b>{t(v)}</b></font>', E["kv"]) for _, v, c in items],
              [P(e, "kl") for e, _, _ in items]]
    tb = Table(celdas, colWidths=[ANCHO / len(items)] * len(items))
    tb.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.4, BORDE), ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDE),
                            ("BACKGROUND", (0, 0), (-1, -1), FONDO), ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, 1), (-1, 1), 7)]))
    return tb

def _v(k, campo, unidad):
    """Valor de un KPI con su unidad, o "-" si la obra no tiene registro (k None) o el dato no se mide (None)."""
    return "-" if not k or k[campo] is None else f"{k[campo]}{unidad}"

def _grafico_avance(serie, ancho=ANCHO, alto=150):
    """Avance previsto (línea continua) vs. observado por la IA (discontinua)."""
    # Dibujo vectorial: coordenadas con origen ABAJO a la izquierda (al revés que en SVG)
    d = Drawing(ancho, alto); x0, x1, y0, y1 = 32, ancho - 8, 18, alto - 10
    serie = [r for r in serie if r["prev"] is not None and r["obs"] is not None]  # datos reales: avance aún sin medir
    if len(serie) < 2: return d
    X = lambda i: x0 + (x1 - x0) * i / (len(serie) - 1); Y = lambda v: y0 + (y1 - y0) * v / 100  # índice -> x · porcentaje -> y
    for v in (0, 50, 100):  # líneas guía y etiquetas del eje Y
        d.add(Line(x0, Y(v), x1, Y(v), strokeColor=BORDE, strokeWidth=0.5)); d.add(String(2, Y(v) - 3, f"{v}%", fontSize=7, fontName="Helvetica", fillColor=GRIS))
    for i in (0, len(serie) // 2, len(serie) - 1):  # tres fechas en el eje X: inicio, medio y fin
        f = serie[i]["f"]; d.add(String(X(i) - 12, 4, f"{f[8:10]}/{f[5:7]}", fontSize=7, fontName="Helvetica", fillColor=GRIS))
    d.add(PolyLine([c for i, r in enumerate(serie) for c in (X(i), Y(r["prev"]))], strokeColor=AZUL, strokeWidth=1.8))
    d.add(PolyLine([c for i, r in enumerate(serie) for c in (X(i), Y(r["obs"]))], strokeColor=AMBAR, strokeWidth=1.8, strokeDashArray=[4, 3]))
    u = serie[-1]; d.add(Line(X(len(serie) - 1), Y(u["prev"]), X(len(serie) - 1), Y(u["obs"]), strokeColor=ROJO, strokeWidth=1.5))  # brecha al cierre
    d.add(Rect(x0 + 4, y1 - 12, 8, 3, fillColor=AZUL, strokeColor=None)); d.add(String(x0 + 15, y1 - 13, "Previsto (cronograma)", fontSize=7, fontName="Helvetica", fillColor=GRIS))
    d.add(Rect(x0 + 110, y1 - 12, 8, 3, fillColor=AMBAR, strokeColor=None)); d.add(String(x0 + 121, y1 - 13, "Observado (IA)", fontSize=7, fontName="Helvetica", fillColor=GRIS))
    return d

def _color_estado(estado):
    """Color según el texto del estado (metrics.estado_texto)."""
    e = estado or ""
    return ROJO if "Atrasada" in e else AMBAR if "leve" in e else VERDE if "previsto" in e else GRIS

def _estado(p):
    return Paragraph(f"<font color='{_hex(_color_estado(p['estado']))}'><b>{t(p['estado'])}</b></font>", E["cel"])

def _pie(c, doc, info):
    """Encabezado (franja de color con título y período) y pie (institución, texto del pie y número de página).
    Se dibuja directamente en el lienzo de cada página (canvas), fuera del flujo de contenido."""
    c.saveState()
    c.setFillColor(AZUL); c.rect(0, A4[1] - 1.1 * cm, A4[0], 1.1 * cm, fill=1, stroke=0)
    pl = info.get("plantilla") or {}
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 10); c.drawString(1.8 * cm, A4[1] - 0.72 * cm, "dIAra")  # la institución va en portada y pie
    c.setFont("Helvetica", 8.5); c.drawRightString(A4[0] - 1.8 * cm, A4[1] - 0.72 * cm, limpio(f"{info['titulo']} - {info['periodo_txt']}"))
    c.setFillColor(GRIS); c.setFont("Helvetica", 7)
    c.drawString(1.8 * cm, 1.0 * cm, limpio(" - ".join(x for x in (pl.get("institucion"), pl.get("pie")) if x))[:150])
    c.drawRightString(A4[0] - 1.8 * cm, 1.0 * cm, f"Página {doc.page}")
    c.restoreState()

# ---------- secciones ----------
def _encabezado_institucional(pl):
    """Logo (si se cargó) + institución y unidad, a la izquierda de la portada."""
    texto = Paragraph(f"<b>{t(pl.get('institucion'))}</b>" + (f"<br/><font color='#5b6b7a'>{t(pl.get('unidad'))}</font>" if pl.get("unidad") else ""),
                      ParagraphStyle("inst", parent=E["n"], fontSize=11, leading=14))
    if not pl.get("logo"): return [texto, Spacer(1, 14)]
    try:
        # Alto fijo de 1.6 cm conservando la proporción; si queda muy ancho, se limita a 6 cm
        img = Image(pl["logo"]); alto = 1.6 * cm; img.drawWidth = img.imageWidth * alto / img.imageHeight; img.drawHeight = alto
        if img.drawWidth > 6 * cm: img.drawHeight *= 6 * cm / img.drawWidth; img.drawWidth = 6 * cm
    except Exception:
        return [texto, Spacer(1, 14)]  # logo dañado o ilegible: el reporte se genera igual, sin logo
    tb = Table([[img, texto]], colWidths=[img.drawWidth + 10, ANCHO - img.drawWidth - 10])
    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return [tb, Spacer(1, 14)]

def _portada(r):
    """Primera página: identificación, indicadores de todos los proyectos, resumen ejecutivo y pendientes."""
    e = [Spacer(1, 4)] + _encabezado_institucional(r.get("plantilla") or {}) + [P(r["titulo"], "titulo"),
         P(f"Período: {r['periodo_txt']}  |  Emitido: {r['emitido_txt']}", "sub"),
         P(f"Para: {r['usuario']['nombre']} ({r['usuario']['correo']})", "sub"), Spacer(1, 12)]
    T = r["totales"]
    e.append(_kpis([("Proyectos", T["proyectos"], None), ("Atrasados", T["atrasados"], ROJO if T["atrasados"] else VERDE),
                    ("Alertas de gravedad alta", T["alertas_altas"], ROJO if T["alertas_altas"] else VERDE),
                    ("Observaciones abiertas", T["obs_abiertas"], None), ("Aportes por revisar", T["aportes_pendientes"], AMBAR if T["aportes_pendientes"] else VERDE)]))
    e.append(P("Resumen ejecutivo", "h2"))
    filas = [["Proyecto", "Estado", "Previsto", "Observado", "Brecha", "Alertas", "Obs. abiertas", "Aportes por revisar"]]
    for p in r["proyectos"]:
        k = p["kpis"]  # None si la obra no tiene registro de la IA: se muestran guiones
        filas.append([Paragraph(f"<b>{t(p['nombre'])}</b><br/><font color='#5b6b7a' size='7'>{t(p['ubicacion'])} - {t(p['institucion'])}</font>", E["cel"]),
                      _estado(p), _v(k, "previsto", "%"), _v(k, "observado", "%"), _v(k, "brecha", " pts"),
                      f"{p['n_alertas']} ({p['n_altas']} altas)" if k else "-", p["obs_abiertas"], p["aportes_pendientes"]])
    e.append(_tabla(filas, [4.3 * cm, 2.2 * cm, 1.7 * cm, 2.0 * cm, 1.8 * cm, 2.0 * cm, 1.8 * cm, ANCHO - 15.8 * cm]))
    e.append(P("Requiere atención", "h2"))
    e += [P(f"- {x}") for x in r["atencion"]] or [P("Sin asuntos pendientes en el período.")]
    e += [Spacer(1, 10), P("Cómo leer este reporte: el avance observado es una estimación de la IA a partir de las imágenes de la cámara; "
                           "una alerta indica necesidad de revisión, no prueba de incumplimiento. El clima es la mediana de varias fuentes "
                           "meteorológicas y se indica su nivel de confianza.", "mu")]
    return e

def _proyecto(p):
    """Sección de un proyecto (p: dict de reporteria.datos_proyecto). Siempre empieza en página nueva."""
    e = [PageBreak(), P(p["nombre"], "h1"),
         Paragraph(f"<font color='{_hex(_color_estado(p['estado']))}'><b>{t(p['estado'])}</b></font>"
                   f"<font color='#5b6b7a'>  |  {t(p['id'])} - {t(p['ubicacion'])}</font>", E["n"]), Spacer(1, 6)]
    # Ficha en 4 columnas: (etiqueta, valor, etiqueta, valor)
    f = p["ficha"]
    pares = [("Institución", f.get("institucion")), ("Contratista", f.get("contratista")), ("N.º contratación", f.get("contratacion")),
             ("Monto", f.get("monto")), ("Cronograma", f.get("cronograma")), ("Plazo", f.get("plazo")),
             ("Cámara", f.get("camara")), ("Coordenadas", f.get("coordenadas"))]
    filas = [[Paragraph(f"<b>{t(a)}</b>", E["cel"]), b or "-", Paragraph(f"<b>{t(c)}</b>", E["cel"]), d or "-"]
             for (a, b), (c, d) in zip(pares[::2], pares[1::2])]
    e.append(_tabla(filas, [2.8 * cm, ANCHO / 2 - 2.8 * cm, 2.8 * cm, ANCHO / 2 - 2.8 * cm], cabecera=False))
    k = p["kpis"]
    if k:  # bloques que dependen del registro diario de la IA
        b = k["brecha"]
        e += [Spacer(1, 8), _kpis([("Avance previsto", _v(k, "previsto", "%"), None), ("Avance observado (IA)", _v(k, "observado", "%"), None),
                                   ("Brecha", _v(k, "brecha", " pts"), None if b is None else ROJO if b <= -10 else VERDE if b > -3 else AMBAR),
                                   ("Productividad semanal", f"{k['productividad']}%", ROJO if k["productividad"] < 50 else None),
                                   ("Alertas activas", p["n_alertas"], ROJO if p["n_altas"] else None)]),
              P(f"Datos de cámara al {p['datos_al']}. {p['texto_estado']}", "mu"),
              *([P("Avance previsto vs. observado", "h2"), _grafico_avance(p["serie"])] if k["avance_medido"] else [])]
        e += [P("Resumen de la IA", "h2")] + [P(f"- {x}") for x in p["resumen_ia"]]
        e.append(P("Alertas activas", "h2"))
        e.append(_tabla([["Código", "Gravedad", "Período", "Descripción"]] +
                        [[a["codigo"], a["gravedad"], a["periodo"], a["descripcion"]] for a in p["alertas"]],
                        [1.5 * cm, 1.8 * cm, 2.8 * cm, ANCHO - 6.1 * cm]) if p["alertas"] else P("Sin alertas activas."))
    else:
        e += [Spacer(1, 6), P("Esta obra aún no tiene registro diario de la IA (avance y recursos detectados).", "mu")]
    c = p["clima"]
    e += [P(f"Clima del período ({c['dias']} días con registro)", "h2"), P(c["resumen"])]
    if c["filas"]:
        e.append(_tabla([["Fecha", "Lluvia", "Origen", "Confianza", "Máx / Mín", "Día apto"]] + c["filas"],
                        [2.3 * cm, 1.6 * cm, 4.3 * cm, 2.0 * cm, 2.4 * cm, ANCHO - 12.6 * cm]))
    e.append(P("Observaciones del auditor", "h2"))
    e.append(_tabla([["Fecha", "Estado", "Observación", "Autor"]] + [[o["fecha"], o["estado"], o["texto"], o["autor"]] for o in p["observaciones"]],
                    [2.0 * cm, 3.0 * cm, ANCHO - 9.2 * cm, 4.2 * cm]) if p["observaciones"] else P("Sin observaciones registradas en el período ni abiertas."))
    e.append(P("Aportes ciudadanos del período", "h2"))
    e.append(_tabla([["Fecha", "Tipo", "Aporte", "Estado"]] + [[a["fecha"], a["tipo"], a["texto"], a["estado"]] for a in p["aportes"]],
                    [2.0 * cm, 2.6 * cm, ANCHO - 7.0 * cm, 2.4 * cm]) if p["aportes"] else P("No se recibieron aportes en el período."))
    if p["imagen"]:
        try:
            img = Image(p["imagen"]["ruta"], width=ANCHO * 0.62, height=ANCHO * 0.62 * 400 / 640)  # proporción 16:10 de las capturas
            e.append(KeepTogether([P("Última imagen de la cámara", "h2"), img, P(p["imagen"]["pie"], "mu")]))  # título e imagen en la misma página
        except Exception:
            e.append(P("No se pudo incluir la última imagen de la cámara.", "mu"))
    return e

# El color de la plantilla modifica variables globales del módulo (AZUL y estilos). El candado evita que dos PDF
# generados al mismo tiempo (FastAPI atiende peticiones en varios hilos) se mezclen los colores.
_tema = threading.Lock()

def _aplicar_color(hexcolor):
    """Cambia el color principal de la plantilla (encabezado, títulos, cabeceras de tabla y gráfico)."""
    global AZUL
    AZUL = colors.HexColor(hexcolor)
    E["titulo"].textColor = AZUL; E["h2"].textColor = AZUL

def construir(r):
    """r: dict armado por reporteria.preparar(). Devuelve los bytes del PDF."""
    with _tema:  # el color de la plantilla es global al módulo: un PDF a la vez
        _aplicar_color((r.get("plantilla") or {}).get("color") or "#0b5cab")
        return _construir(r)

def _construir(r):
    b = io.BytesIO()
    doc = BaseDocTemplate(b, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.7 * cm, bottomMargin=1.6 * cm,
                          title=limpio(r["titulo"]), author="dIAra - CGR", subject=limpio(r["periodo_txt"]))
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")],
                                       onPage=lambda c, d: _pie(c, d, r))])
    e = _portada(r)
    for p in r["proyectos"]: e += _proyecto(p)
    doc.build(e)
    return b.getvalue()
