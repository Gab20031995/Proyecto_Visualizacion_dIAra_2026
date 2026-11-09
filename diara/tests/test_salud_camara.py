"""Pruebas de la salud de la cámara y las alertas S-01..S-06 (src/salud_camara.py, ítems EDA-01 y ALE-03).

Cada prueba crea su propia obra en la base temporal e inserta las fotos que necesita, con un reloj FIJO (AHORA) para
que los resultados no dependan del día en que se corren. Los umbrales se leen de config.SALUD_CAMARA."""
import itertools
from datetime import datetime, timedelta
import pytest
from config import SALUD_CAMARA as U
from src import proyectos, salud_camara, store, tablero, etl
from src.etl import encuadre
from conftest import AUDITORA

AHORA = datetime(2026, 3, 20, 10, 30)   # viernes 20/03/2026, 10:30 (hora de Costa Rica)
HOY = AHORA.replace(hour=0, minute=0)
_n = itertools.count(1)


def obra(estado="En ejecución", intervalo=60, desde="08:00", hasta="12:00", **extra):
    """Crea una obra nueva (5 fotos esperadas por día con los valores por defecto) y devuelve el proyecto."""
    datos = dict(nombre=f"Obra cámara {next(_n)}", institucion="MEP", provincia="Limón", canton="Limón", lat=9.98, lng=-83.04,
                 estado="En ejecución", camara="CAM-PRUEBA", captura_intervalo_min=intervalo,
                 captura_desde=desde if intervalo else None, captura_hasta=hasta if intervalo else None) | extra
    pid = proyectos.crear(datos)
    if estado != "En ejecución": proyectos.cambiar_estado(pid, estado, "Prueba automática", "pruebas")
    return proyectos.obtener(pid)


def foto_api(pid, ts, retraso_min=0):
    """Foto recibida por la API de cámaras. recibida se guarda en UTC, como lo hace SQLite (CURRENT_TIMESTAMP)."""
    recibida = ts + timedelta(hours=6, minutes=retraso_min)
    store._q("INSERT INTO imagenes(project_id, archivo, fecha, hora, tomada, recibida, fuente) VALUES(?,?,?,?,?,?, 'api')",
             (pid, f"{ts:%Y%m%d_%H%M%S}.jpg", f"{ts:%Y-%m-%d}", f"{ts:%H:%M}", ts.isoformat(), f"{recibida:%Y-%m-%d %H:%M:%S}"))


def foto_etl(pid, ts, apta=1, motivo=None, origen="camara"):
    """Foto del catálogo del ETL (Drive), ya curada."""
    etl.preparar()
    store._q("""INSERT INTO etl_imagenes(drive_id, project_id, origen, archivo, fecha, hora, curada, apta_ia, motivo_ia)
                VALUES(?,?,?,?,?,?,?,?,?)""", (f"{pid}-{origen}-{ts:%Y%m%d%H%M%S}", pid, origen, f"{ts:%H%M%S}.jpg",
                                               f"{ts:%Y-%m-%d}", f"{ts:%H:%M:%S}", "2026-03-20", apta, motivo))


def dias_completos(pid, dias, fotos_por_dia=5, inicio=8, **kw):
    """Fotos cada hora desde las `inicio` h en los `dias` días anteriores a hoy (5 = día completo con el horario 08-12)."""
    for d in range(dias, 0, -1):
        for h in range(fotos_por_dia): foto_api(pid, HOY - timedelta(days=d) + timedelta(hours=inicio + h), **kw)


def codigos(p):
    return [a["codigo"] for a in salud_camara.resumen(p, AHORA)["alertas"]]


# ---------- funciones puras ----------
def test_minutos_en_horario_no_cuenta_la_noche():
    t0, t1 = datetime(2026, 3, 19, 12, 0), datetime(2026, 3, 20, 7, 0)   # de mediodía a las 7 a. m. del día siguiente
    assert salud_camara.minutos_en_horario(t0, t1, "08:00", "12:00") == 1   # solo el minuto 12:00-12:01
    assert salud_camara.minutos_en_horario(datetime(2026, 3, 20, 8), datetime(2026, 3, 20, 10, 30), "08:00", "12:00") == 150


def test_horario_observado_cuando_no_se_configuro():
    p = obra(intervalo=None)
    dias_completos(p["id"], 10, fotos_por_dia=10, inicio=7)   # fotos de 07:00 a 16:00
    r = salud_camara.resumen(p, AHORA)
    assert r["horario"] == dict(desde="07:00", hasta="16:59", origen="observado") and r["esperadas_dia"] is None


# ---------- cámara sana ----------
def test_camara_sana_no_tiene_alertas_y_cobertura_completa():
    p = obra()
    dias_completos(p["id"], 10)
    for h in (8, 9, 10): foto_api(p["id"], HOY + timedelta(hours=h))
    r = salud_camara.resumen(p, AHORA)
    assert r["alertas"] == [] and r["cobertura_7d"] == 100 and r["esperadas_dia"] == 5
    assert r["dias"][-1]["fecha"] == "2026-03-20" and r["dias"][-1]["cobertura"] is None   # hoy no terminó: sin cobertura
    assert r["dias"][-1]["horas"][8:11] == [1, 1, 1]


# ---------- S-01 y S-06: la cámara deja de enviar ----------
def test_s01_horas_del_horario_sin_fotos():
    p = obra(desde="06:00", hasta="18:00", intervalo=60)
    dias_completos(p["id"], 3, fotos_por_dia=13, inicio=6)   # días completos de 06:00 a 18:00
    foto_api(p["id"], HOY + timedelta(hours=6))   # última foto hoy a las 06:00; son las 10:30
    a = salud_camara.resumen(p, AHORA)
    assert a["horas_sin_fotos"] == 4.5 and codigos(p) == ["S-01"]


def test_una_camara_de_dia_no_se_cae_de_noche():
    p = obra()
    dias_completos(p["id"], 3)                     # última foto ayer a las 12:00
    temprano = AHORA.replace(hour=7, minute=0)     # hoy a las 7 a. m., antes del horario de captura
    assert salud_camara.resumen(p, temprano)["alertas"] == []


def test_s06_dias_sin_fotos_reemplaza_a_s01_y_s02():
    p = obra()
    for d in range(10, U["dias_sin_fotos"] - 1, -1):   # fotos hasta hace dias_sin_fotos días
        for h in range(5): foto_api(p["id"], HOY - timedelta(days=d) + timedelta(hours=8 + h))
    r = salud_camara.resumen(p, AHORA)
    assert [a["codigo"] for a in r["alertas"]] == ["S-06"] and r["alertas"][0]["gravedad"] == "ALTA"
    assert r["huecos"][0] == dict(desde="2026-03-18", hasta="2026-03-20", dias=3)


def test_s06_si_nunca_llego_una_foto():
    assert codigos(obra()) == ["S-06"]


def test_obra_sin_camara_configurada_no_alerta():
    assert codigos(obra(camara=None, intervalo=None)) == []


def test_s06_con_la_fecha_de_fin_vencida_sugiere_cerrar_la_obra():
    p = obra(fecha_inicio="2025-01-01", fecha_fin="2026-01-31")
    dias_completos(p["id"], 10)
    store._q("DELETE FROM imagenes WHERE project_id=? AND fecha>='2026-03-15'", (p["id"],))
    assert "ciérrela" in salud_camara.resumen(p, AHORA)["alertas"][0]["descripcion"]


@pytest.mark.parametrize("estado", ["Suspendido", "Planificado"])
def test_obra_suspendida_o_planificada_no_alerta_por_falta_de_fotos(estado):
    if estado == "Planificado":
        p = obra(); store._q("UPDATE proyectos SET estado='Planificado' WHERE id=?", (p["id"],)); p = proyectos.obtener(p["id"])
    else:
        p = obra(estado=estado)
    assert codigos(p) == []


# ---------- S-02: cobertura baja ----------
def test_s02_varios_dias_con_pocas_fotos():
    p = obra()
    dias_completos(p["id"], 7, fotos_por_dia=2)    # 2 de 5 = 40 %
    foto_api(p["id"], HOY + timedelta(hours=9, minutes=30))
    r = salud_camara.resumen(p, AHORA)
    assert [a["codigo"] for a in r["alertas"]] == ["S-02"] and r["cobertura_7d"] == 40


def test_s02_no_aplica_sin_frecuencia_configurada():
    p = obra(intervalo=None)
    dias_completos(p["id"], 7, fotos_por_dia=2)
    foto_api(p["id"], HOY + timedelta(hours=9))
    assert "S-02" not in codigos(p)


# ---------- S-03: cambio de encuadre por revisar ----------
def test_s03_mientras_el_cambio_este_por_revisar():
    p = obra(); dias_completos(p["id"], 3); foto_api(p["id"], HOY + timedelta(hours=10))
    encuadre.preparar()
    store._q("""INSERT INTO etl_encuadre_cambios(project_id, fecha, ultima_fecha_antes, dias_sin_fotos, disimilitud,
                desplazamiento_x, desplazamiento_y, pico, clasificacion) VALUES(?,?,?,?,?,?,?,?,?)""",
             (p["id"], "2026-03-18", "2026-03-17", 0, 0.18, 0, -100, 0.03, "Movimiento de la cámara"))
    assert codigos(p) == ["S-03"]
    assert encuadre.revisar(p["id"], "2026-03-18", "Descartado", "ana@cgr.go.cr")
    assert codigos(p) == []
    assert salud_camara.resumen(p, AHORA)["cambios_encuadre"][0]["revisado_por"] == "ana@cgr.go.cr"


# ---------- S-04: fotos que llegan pero no sirven ----------
def test_s04_dias_seguidos_sin_fotos_aptas():
    p = obra(intervalo=None)
    for d in range(U["dias_no_aptas"], 0, -1):
        for h in (9, 10): foto_etl(p["id"], HOY - timedelta(days=d) + timedelta(hours=h), apta=0, motivo="borrosa o lente empañado")
    foto_etl(p["id"], HOY + timedelta(hours=10), apta=0, motivo="borrosa o lente empañado")
    a = [x for x in salud_camara.resumen(p, AHORA)["alertas"] if x["codigo"] == "S-04"]
    assert len(a) == 1 and "lente empañado" in a[0]["descripcion"]


def test_un_dia_con_alguna_foto_apta_corta_la_racha():
    p = obra(intervalo=None)
    for d in range(4, 0, -1): foto_etl(p["id"], HOY - timedelta(days=d) + timedelta(hours=9), apta=0, motivo="oscura")
    foto_etl(p["id"], HOY + timedelta(hours=9), apta=1)
    assert "S-04" not in codigos(p)


# ---------- S-05: desfase entre captura y llegada ----------
def test_s05_las_fotos_llegan_tarde():
    p = obra()
    dias_completos(p["id"], 3, retraso_min=U["desfase_min"] + 15)
    for h in (8, 9, 10): foto_api(p["id"], HOY + timedelta(hours=h), retraso_min=U["desfase_min"] + 15)
    assert codigos(p) == ["S-05"]


def test_sin_desfase_no_hay_s05():
    p = obra()
    dias_completos(p["id"], 3, retraso_min=2)
    for h in (8, 9, 10): foto_api(p["id"], HOY + timedelta(hours=h), retraso_min=2)
    assert "S-05" not in codigos(p)


# ---------- conteo de fotos ----------
def test_cada_instante_de_captura_se_cuenta_una_sola_vez():
    # Como en el Puente: la misma captura está en "camara" (original) y en "historico" (copia tratada)
    p = obra(intervalo=None)
    t = HOY - timedelta(days=1) + timedelta(hours=9)
    foto_etl(p["id"], t, origen="camara"); foto_etl(p["id"], t, origen="historico")
    assert salud_camara.resumen(p, AHORA)["total_fotos"] == 1


# ---------- API y tarjetas ----------
def test_api_salud_camara_y_permisos(cliente, entrar, contratista):
    c = cliente(); entrar(c, *AUDITORA)   # Ana está asignada a P-001 (usuarios de ejemplo de la base de prueba)
    r = c.get("/api/auditor/P-001/salud-camara")
    assert r.status_code == 200 and {"alertas", "dias", "horario", "cambios_encuadre"} <= set(r.json())
    assert c.get("/api/auditor/P-001/encuadre/..%2F..%2Fdiara.db").status_code == 404   # no se piden otros archivos
    assert c.patch("/api/auditor/P-001/encuadre/2026-01-01", json={"estado": "Aprobadísimo"}).status_code == 400
    assert c.patch("/api/auditor/P-001/encuadre/2026-01-01", json={"estado": "Confirmado"}).status_code == 404
    k = cliente(); entrar(k, *contratista)
    assert k.get("/api/auditor/P-001/salud-camara").status_code == 404   # la empresa no ve la salud de la cámara


def test_la_tarjeta_trae_el_resumen_de_la_camara():
    p = obra()
    t = tablero.tarjeta(p)
    assert t["camara"]["alertas"] == 1 and t["camara"]["codigos"] == ["S-06"] and t["camara"]["ultima_foto"] is None
