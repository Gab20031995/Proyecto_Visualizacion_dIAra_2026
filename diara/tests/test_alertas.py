"""Pruebas de las alertas A-01..A-04 (src/alerts.py) y de los indicadores de avance (src/metrics.py).

No usan la base ni archivos: arman un registro diario pequeño en memoria (como el diario.csv de una obra) y revisan
qué alertas salen. Sirven de red de seguridad para cuando agreguemos las alertas nuevas (A-05, S-01..S-06): si una
regla existente cambia sin querer, alguna de estas pruebas falla.

Los umbrales se leen de config.UMBRALES: si alguien cambia un umbral, las pruebas siguen siendo válidas."""
from datetime import date
import numpy as np
import pandas as pd
from config import UMBRALES as U
from src import alerts, metrics

UMBRAL_DIAS = U["dias_sin_maquinaria"]


def diario(dias):
    """Registro diario mínimo a partir de una lista de dicts. Cada día puede indicar solo lo que le interesa a la
    prueba; el resto toma valores "normales" (con registro, maquinaria operando, clima apto, buena confianza)."""
    base = dict(hay_registro=1, maquinaria_operando=1, apto_trabajo=1, confianza_min=0.9, tiempo_muerto_h=0.0)
    fechas = pd.date_range("2026-03-01", periods=len(dias), freq="D")   # un día por fila, consecutivos
    filas = [base | d | {"fecha": f} for d, f in zip(dias, fechas)]
    return pd.DataFrame(filas)


SIN_MAQ = dict(maquinaria_operando=0)                      # día sin maquinaria y con clima apto
LLUVIA = dict(maquinaria_operando=0, apto_trabajo=0)       # día sin maquinaria, pero no apto por lluvia
SIN_BRECHA = {"brecha": None}                              # KPIs de una obra cuyo avance no se mide


def codigos(lista):
    return [a["codigo"] for a in lista]


# ---------- A-01: días seguidos sin maquinaria con clima apto ----------
def test_a01_racha_que_llega_al_umbral_genera_alerta_alta():
    al = alerts.evaluate(diario([SIN_MAQ] * UMBRAL_DIAS), SIN_BRECHA)
    a01 = [a for a in al if a["codigo"] == "A-01"]
    assert len(a01) == 1 and a01[0]["gravedad"] == "ALTA"
    assert f"{UMBRAL_DIAS} dias" in a01[0]["descripcion"]


def test_a01_racha_corta_no_alerta():
    assert "A-01" not in codigos(alerts.evaluate(diario([SIN_MAQ] * (UMBRAL_DIAS - 1)), SIN_BRECHA))


def test_a01_un_dia_de_lluvia_corta_la_racha():
    # 2 días sin maquinaria, 1 de lluvia, 2 más: ninguna racha llega a 3
    dias = [SIN_MAQ] * (UMBRAL_DIAS - 1) + [LLUVIA] + [SIN_MAQ] * (UMBRAL_DIAS - 1)
    assert "A-01" not in codigos(alerts.evaluate(diario(dias), SIN_BRECHA))


def test_a01_una_racha_antigua_que_ya_termino_no_alerta():
    # la maquinaria volvió a operar el último día: la racha anterior ya no es actual
    dias = [SIN_MAQ] * (UMBRAL_DIAS + 2) + [{}]
    assert "A-01" not in codigos(alerts.evaluate(diario(dias), SIN_BRECHA))


def test_a01_los_dias_sin_registro_de_camara_no_cortan_ni_suman():
    # un día sin fotos en medio no interrumpe la racha (solo se miran los días con registro)
    dias = [SIN_MAQ, dict(hay_registro=0, maquinaria_operando=1)] + [SIN_MAQ] * (UMBRAL_DIAS - 1)
    assert "A-01" in codigos(alerts.evaluate(diario(dias), SIN_BRECHA))


# ---------- A-02: confianza baja de la IA ----------
def test_a02_una_alerta_por_cada_dia_con_confianza_baja():
    baja = dict(confianza_min=U["confianza_min"] - 0.1)
    al = alerts.evaluate(diario([baja, {}, baja]), SIN_BRECHA)
    a02 = [a for a in al if a["codigo"] == "A-02"]
    assert len(a02) == 2 and all(a["gravedad"] == "MEDIA" for a in a02)


def test_a02_confianza_igual_al_minimo_no_alerta():
    assert "A-02" not in codigos(alerts.evaluate(diario([dict(confianza_min=U["confianza_min"])]), SIN_BRECHA))


# ---------- A-03: brecha entre avance observado y previsto ----------
def test_a03_brecha_en_el_umbral_alerta():
    assert "A-03" in codigos(alerts.evaluate(diario([{}]), {"brecha": U["brecha_pts"]}))


def test_a03_brecha_menor_al_umbral_no_alerta():
    assert "A-03" not in codigos(alerts.evaluate(diario([{}]), {"brecha": U["brecha_pts"] + 0.1}))


def test_a03_no_aplica_si_el_avance_no_se_mide():
    assert "A-03" not in codigos(alerts.evaluate(diario([{}]), SIN_BRECHA))


# ---------- A-04: maquinaria encendida sin operar ----------
def test_a04_tiempo_muerto_mayor_al_umbral_alerta():
    al = alerts.evaluate(diario([dict(tiempo_muerto_h=U["tiempo_muerto_h"] + 0.5)]), SIN_BRECHA)
    assert codigos(al) == ["A-04"]


def test_a04_tiempo_muerto_igual_al_umbral_no_alerta():
    assert alerts.evaluate(diario([dict(tiempo_muerto_h=U["tiempo_muerto_h"])]), SIN_BRECHA) == []


# ---------- Datos reales: lo que no se mide queda vacío y no dispara alertas ----------
def test_datos_reales_sin_medicion_no_inventan_alertas():
    # Así llega una obra real publicada desde el ETL: confianza y tiempo muerto vacíos (NaN), avance sin medir
    vacio = dict(confianza_min=np.nan, tiempo_muerto_h=np.nan)
    assert alerts.evaluate(diario([vacio] * 5), SIN_BRECHA) == []


# ---------- A-05: inactividad con datos reales (personas + índice de cambio) ----------
QUIETO = dict(personas_max=0, cambio_mediana=U["cambio_inactivo"] - 2)     # día sin actividad visible
CON_GENTE = dict(personas_max=3, cambio_mediana=9.0)
LLUVIOSO = dict(QUIETO, apto_trabajo=0)
SIN_CAMBIO = dict(personas_max=0, cambio_mediana=np.nan)                   # fotos muy separadas: sin índice de cambio
DIAS_A05 = U["dias_inactividad"]


def diario_real(dias, inicio="2026-03-02"):
    """Registro como el de una obra real (publicado por el ETL): sin maquinaria medida y con cambio_mediana.
    2026-03-02 es lunes."""
    fechas = pd.date_range(inicio, periods=len(dias), freq="D")
    base = dict(hay_registro=1, apto_trabajo=1, maquinaria_operando=np.nan, confianza_min=np.nan, tiempo_muerto_h=np.nan,
                personas_max=3, cambio_mediana=9.0)
    return pd.DataFrame([base | d | {"fecha": f} for d, f in zip(dias, fechas)])


def a05(d):
    return [a for a in alerts.evaluate(d, SIN_BRECHA) if a["codigo"] == "A-05"]


def test_a05_dias_habiles_sin_actividad_visible():
    a = a05(diario_real([CON_GENTE] + [QUIETO] * DIAS_A05))
    assert len(a) == 1 and a[0]["gravedad"] == "MEDIA" and "03-Mar a 05-Mar" in a[0]["periodo"]


def test_a05_es_alta_desde_el_doble():
    assert a05(diario_real([QUIETO] * (2 * DIAS_A05)))[0]["gravedad"] == "ALTA"   # lun 02 a sáb 07: 6 días hábiles


def test_a05_racha_corta_no_alerta():
    assert a05(diario_real([QUIETO] * (DIAS_A05 - 1))) == []


def test_a05_un_dia_con_personas_corta_la_racha():
    assert a05(diario_real([QUIETO] * (DIAS_A05 - 1) + [CON_GENTE] + [QUIETO] * (DIAS_A05 - 1))) == []


def test_a05_sin_indice_de_cambio_no_concluye():
    # Ticabán: 0 personas pero sin índice de cambio. No prueba que la obra esté parada: corta la racha
    assert a05(diario_real([SIN_CAMBIO] * 6)) == []
    assert a05(diario_real([QUIETO, QUIETO, SIN_CAMBIO, QUIETO, QUIETO])) == []


def test_a05_domingo_y_lluvia_ni_cuentan_ni_cortan():
    # jue 05, vie 06, sáb 07: quieto · dom 08: quieto (no es hábil) · lun 09: lluvia (no apto) · mar 10: quieto
    d = diario_real([QUIETO, QUIETO, QUIETO, QUIETO, LLUVIOSO, QUIETO], inicio="2026-03-05")
    assert [x.isoformat() for x in alerts.inactividad(d)] == ["2026-03-05", "2026-03-06", "2026-03-07", "2026-03-10"]
    a = a05(d)
    assert len(a) == 1 and a[0]["periodo"] == "05-Mar a 10-Mar" and a[0]["descripcion"].startswith("4 días hábiles")


def test_a05_feriados_no_cuentan_como_dias_habiles():
    # Miércoles Santo 01/04/2026 quieto, Jueves y Viernes Santo (feriados) quietos, sábado 04 quieto:
    # solo 2 días hábiles (01 y 04)
    assert a05(diario_real([QUIETO] * 4, inicio="2026-04-01")) == []
    assert {date(2026, 4, 2), date(2026, 4, 3), date(2026, 9, 15)} <= alerts.feriados(2026)


def test_a05_no_aplica_a_registros_sin_indice_de_cambio():
    # Datos sintéticos (sin columna cambio_mediana): la inactividad la cubre A-01 con la maquinaria
    assert a05(diario([dict(personas_max=0)] * 6)) == []


# ---------- Indicadores (metrics.kpis y metrics.estado_texto) ----------
def registro_con_avance(previsto, observado):
    d = diario([{}] * 7)
    return d.assign(avance_previsto=previsto, avance_observado=observado, horas_sitio=8.0, horas_efectivas=6.0)


def test_kpis_calcula_brecha_y_productividad():
    k = metrics.kpis(registro_con_avance(50.0, 42.5))
    assert k["brecha"] == -7.5 and k["avance_medido"] is True
    assert k["productividad"] == 75   # 6 h efectivas de 8 h en sitio


def test_kpis_sin_medicion_de_avance_devuelve_none():
    k = metrics.kpis(registro_con_avance(np.nan, np.nan))
    assert k["previsto"] is None and k["observado"] is None and k["brecha"] is None
    assert k["avance_medido"] is False


def test_estado_texto_segun_la_brecha():
    assert metrics.estado_texto({"brecha": None})[0].endswith("Avance sin medición")
    assert metrics.estado_texto({"brecha": -10, "observado": 40, "previsto": 50})[0].endswith("Atrasada")
    assert metrics.estado_texto({"brecha": -5, "observado": 45, "previsto": 50})[0].endswith("Con retraso leve")
    assert metrics.estado_texto({"brecha": -3, "observado": 47, "previsto": 50})[0].endswith("Según lo previsto")
