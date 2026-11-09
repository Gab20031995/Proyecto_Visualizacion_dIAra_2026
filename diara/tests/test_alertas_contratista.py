"""Pruebas de las alertas C-01..C-05 del cruce entre lo que declara la empresa ejecutora y lo que observa la IA
(src/contratista._alertas).

Se prueba la función que aplica las reglas con datos ya resumidos, sin base de datos: así cada regla y su umbral se
verifican por separado. Los umbrales se leen de config.UMBRALES."""
from config import UMBRALES as U
from src import contratista

DIAS = ["2026-03-02", "2026-03-03", "2026-03-04"]


def resumen(**cambios):
    """Datos resumidos del cruce de una obra en la que todo coincide (sin alertas), con los cambios que pida la prueba."""
    base = dict(corte="2026-03-10", reportado=None, observado=None, pct_financiero=None, dias_sin_bitacora=None)
    return base | cambios


def alertas(x, contra=(), clima_mal=(), sin=()):
    return contratista._alertas(x, list(contra), list(clima_mal), list(sin))


def por_codigo(lista):
    return {a["codigo"]: a for a in lista}


def test_sin_diferencias_no_hay_alertas():
    assert alertas(resumen(reportado=50, observado=50, pct_financiero=50, dias_sin_bitacora=0)) == []


# ---------- C-01: avance reportado por encima del observado ----------
def test_c01_diferencia_mayor_al_umbral_es_media():
    al = por_codigo(alertas(resumen(reportado=50 + U["reportado_vs_ia_pts"] + 1, observado=50)))
    assert al["C-01"]["gravedad"] == "MEDIA"


def test_c01_diferencia_del_doble_del_umbral_es_alta():
    al = por_codigo(alertas(resumen(reportado=50 + 2 * U["reportado_vs_ia_pts"], observado=50)))
    assert al["C-01"]["gravedad"] == "ALTA"


def test_c01_diferencia_igual_al_umbral_no_alerta():
    assert alertas(resumen(reportado=50 + U["reportado_vs_ia_pts"], observado=50)) == []


# ---------- C-02: avance financiero por encima del físico ----------
def test_c02_financiero_por_encima_del_fisico():
    al = por_codigo(alertas(resumen(pct_financiero=50 + U["financiero_vs_fisico_pts"] + 1, observado=50)))
    assert al["C-02"]["gravedad"] == "ALTA"


def test_c01_y_c02_no_aplican_mientras_la_ia_no_mida_el_avance():
    # Obras reales: observado es None. Aunque la empresa reporte mucho avance o gasto, no se puede comparar.
    assert alertas(resumen(reportado=90, pct_financiero=90, observado=None)) == []


# ---------- C-03 y C-04: contradicciones día a día ----------
def test_c03_gravedad_segun_cantidad_de_dias():
    assert por_codigo(alertas(resumen(), contra=DIAS[:1]))["C-03"]["gravedad"] == "MEDIA"
    assert por_codigo(alertas(resumen(), contra=DIAS))["C-03"]["gravedad"] == "ALTA"


def test_c04_lluvia_declarada_con_clima_apto():
    a = por_codigo(alertas(resumen(), clima_mal=DIAS[:2]))["C-04"]
    assert a["gravedad"] == "ALTA" and "02-Mar a 03-Mar" in a["periodo"]


# ---------- C-05: días con actividad en cámara sin bitácora ----------
def test_c05_alerta_desde_el_umbral():
    n = U["dias_sin_bitacora"]
    fechas = [f"2026-03-0{i + 1}" for i in range(n)]
    assert "C-05" in por_codigo(alertas(resumen(dias_sin_bitacora=n), sin=fechas))
    assert alertas(resumen(dias_sin_bitacora=n - 1), sin=fechas[:-1]) == []


def test_c05_no_aplica_sin_empresa_asignada():
    # dias_sin_bitacora es None cuando la obra no tiene empresa ejecutora: no se le puede exigir bitácora
    assert alertas(resumen(dias_sin_bitacora=None), sin=DIAS) == []
