"""Pruebas de la salud de la cámara (alertas S-xx) en el reporte PDF y en el correo (src/reporteria.py, src/reporte_pdf.py).

Se arma el reporte de un auditor con una obra cuya cámara nunca envió fotos (alerta S-06, que no depende de la fecha
en que se corra la prueba) y se verifica que aparezca en la portada, en "Requiere atención", en la sección del
proyecto y en el correo (texto y HTML). No se envía ningún correo: solo se arma el mensaje."""
import itertools
import pytest
from reportlab.platypus import Paragraph
from src import proyectos, reporteria, reporte_pdf, store

_n = itertools.count(1)


@pytest.fixture
def auditor_con_camara_caida():
    """Auditor nuevo asignado a una obra en ejecución con cámara configurada y sin ninguna foto."""
    pid = proyectos.crear(dict(nombre=f"Obra del reporte {next(_n)}", institucion="MEP", provincia="Limón", canton="Limón",
                               lat=9.98, lng=-83.04, estado="En ejecución", camara="CAM-REP"))
    uid = store.crear_usuario(f"rep{next(_n)}@cgr.go.cr", "Auditor del reporte", "clave-reporte")
    store.asignar(pid, [uid])
    return store.usuario(uid), pid


def textos(flowables):
    """Texto de todos los párrafos (también los que están dentro de tablas) de una lista de elementos del PDF."""
    out = []
    for f in flowables:
        if isinstance(f, Paragraph): out.append(f.getPlainText())
        for fila in getattr(f, "_cellvalues", []):
            out += [c.getPlainText() for c in fila if isinstance(c, Paragraph)]
    return " | ".join(out)


def test_datos_del_reporte_incluyen_la_camara(auditor_con_camara_caida):
    u, pid = auditor_con_camara_caida
    r = reporteria.preparar(u, "semanal")
    assert r["totales"]["camaras_con_alertas"] == 1
    assert any("no se ha recibido ninguna foto de la cámara" in a for a in r["atencion"])
    c = r["proyectos"][0]["camara"]
    assert c["codigos"] == ["S-06"] and c["n_altas"] == 1 and c["hay_fotos"] is False


def test_el_pdf_muestra_la_salud_de_la_camara(auditor_con_camara_caida):
    u, pid = auditor_con_camara_caida
    pdf, r = reporteria.generar_pdf(u, "semanal")
    assert pdf.startswith(b"%PDF")
    portada, seccion = textos(reporte_pdf._portada(r)), textos(reporte_pdf._proyecto(r["proyectos"][0]))
    assert "Cámaras con alertas" in portada and "S-06" in portada
    assert "Salud de la cámara" in seccion and "S-06" in seccion and "no se ha recibido ninguna foto" in seccion.lower()


def test_el_correo_cuenta_las_camaras_con_alertas(auditor_con_camara_caida):
    u, pid = auditor_con_camara_caida
    pdf, r = reporteria.generar_pdf(u, "semanal")
    m = reporteria._correo(u, pdf, r, "reporte.pdf")
    texto, html = m.get_body(("plain",)).get_content(), m.get_body(("html",)).get_content()
    for cuerpo in (texto, html):
        assert "Cámaras con alertas" in cuerpo and "ninguna foto de la cámara" in cuerpo


def test_fotos_del_periodo_se_cuentan_solo_dentro_del_periodo():
    from datetime import date
    s = dict(alertas=[], hay_fotos=True, ultima_foto="2026-03-19 12:00", dias_sin_fotos=1, cobertura_7d=None, esperadas_dia=None,
             horario=dict(desde="08:00", hasta="12:59", origen="observado"), cambios_encuadre=[],
             dias=[dict(fecha=f"2026-03-{d:02d}", fotos=f) for d, f in ((10, 5), (16, 3), (17, 0), (18, 4))])
    c = reporteria._camara(s, date(2026, 3, 16), date(2026, 3, 22))
    assert (c["fotos_periodo"], c["dias_periodo"], c["dias_sin_fotos_periodo"]) == (7, 3, 1)
    assert c["ultima_foto"] == "19/03/2026 12:00"
