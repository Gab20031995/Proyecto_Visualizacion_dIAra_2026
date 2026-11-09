"""Pruebas de la configuración de cámara y ETL por obra (ítems ADM-01 y ADM-03 del backlog, docs/backlog_mejoras.md).

Qué se verifica:
    - validación de los campos nuevos del formulario (src/proyectos.validar)
    - cálculo de las fotos esperadas por día (proyectos.fotos_esperadas_dia)
    - migración de una base EXISTENTE: se agregan las columnas y se copia UNA vez lo que había en config.ETL
    - ida y vuelta por la API de administración (crear, leer, editar) y lectura desde el ETL (proyectos.config_etl)"""
import json, sqlite3
import pytest
from config import ETL
from src import proyectos, store
from conftest import ADMIN

# Proyecto válido mínimo (como lo envía el formulario); cada prueba cambia solo lo que le interesa
VALIDO = dict(nombre="Obra de prueba", institucion="MEP", provincia="Limón", canton="Limón", lat=9.98, lng=-83.04,
              estado="En ejecución")


def validar(**cambios):
    return proyectos.validar(VALIDO | cambios)


# ---------- ADM-01: frecuencia y horario de captura ----------
def test_frecuencia_con_horario():
    x = validar(captura_intervalo_min="15", captura_desde="07:00", captura_hasta="17:00")
    assert (x["captura_intervalo_min"], x["captura_desde"], x["captura_hasta"]) == (15, "07:00", "17:00")


def test_frecuencia_sin_horario_asume_camara_de_24_horas():
    x = validar(captura_intervalo_min=5)
    assert (x["captura_desde"], x["captura_hasta"]) == ("00:00", "23:59")


def test_sin_frecuencia_todo_queda_vacio():
    x = validar()
    assert x["captura_intervalo_min"] is None and x["captura_desde"] is None


@pytest.mark.parametrize("cambios, mensaje", [
    (dict(captura_desde="07:00", captura_hasta="17:00"), "cada cuántos minutos"),   # horario sin frecuencia
    (dict(captura_intervalo_min=15, captura_desde="17:00", captura_hasta="07:00"), "posterior"),
    (dict(captura_intervalo_min=15, captura_desde="7am", captura_hasta="17:00"), "HH:MM"),
    (dict(captura_intervalo_min=0), "entre 1 y 1440"),
    (dict(captura_intervalo_min="2.5"), "entero"),
])
def test_captura_invalida(cambios, mensaje):
    with pytest.raises(proyectos.ErrorProyecto, match=mensaje): validar(**cambios)


@pytest.mark.parametrize("intervalo, desde, hasta, esperadas", [
    (15, "07:00", "17:00", 41),     # la primera a las 07:00 y la última a las 17:00
    (5, "00:00", "23:59", 288),     # como la cámara del Puente: una cada 5 min, todo el día
    (60, "08:00", "08:30", 1),
    (None, None, None, None),       # sin frecuencia no se puede saber
])
def test_fotos_esperadas_por_dia(intervalo, desde, hasta, esperadas):
    p = dict(captura_intervalo_min=intervalo, captura_desde=desde, captura_hasta=hasta)
    assert proyectos.fotos_esperadas_dia(p) == esperadas


# ---------- ADM-03: configuración del ETL ----------
def test_carpeta_de_drive_acepta_el_enlace_completo():
    enlace = "https://drive.google.com/drive/folders/1w6fWxTcVRGztNyb7f1TNcPwR2iOijZTr?usp=sharing"
    assert validar(drive_carpeta=enlace)["drive_carpeta"] == "1w6fWxTcVRGztNyb7f1TNcPwR2iOijZTr"


def test_periodos_excluidos_se_guardan_ordenados_como_json():
    x = validar(etl_excluir=[dict(desde="2026-02-01", hasta="2026-02-03", motivo="Lente tapado"),
                             dict(desde="2025-09-11", hasta="2025-09-12", motivo="Instalación")])
    assert json.loads(x["etl_excluir"]) == [["2025-09-11", "2025-09-12", "Instalación"],
                                            ["2026-02-01", "2026-02-03", "Lente tapado"]]


@pytest.mark.parametrize("cambios, mensaje", [
    (dict(drive_carpeta="no es un id"), "Carpeta de Drive"),
    (dict(etl_rotacion=45), "0, 90, 180 o 270"),
    (dict(etl_nitidez_min=0), "entre 0 y 50"),
    (dict(etl_ventana_dias=0), "Ventana de días"),
    (dict(etl_excluir=[dict(desde="11/09/2025", hasta="2025-09-12", motivo="Instalación")]), "AAAA-MM-DD"),
    (dict(etl_excluir=[dict(desde="2025-09-12", hasta="2025-09-11", motivo="Instalación")]), "anterior"),
    (dict(etl_excluir=[dict(desde="2025-09-11", hasta="2025-09-12", motivo="")]), "motivo"),
])
def test_etl_invalido(cambios, mensaje):
    with pytest.raises(proyectos.ErrorProyecto, match=mensaje): validar(**cambios)


# ---------- Migración de una base existente ----------
def base_antigua(tmp_path):
    """Base como la de producción antes de este cambio: tabla proyectos SIN las columnas nuevas, con las obras reales."""
    c = sqlite3.connect(tmp_path / "antigua.db")
    c.executescript("""CREATE TABLE proyectos(id TEXT PRIMARY KEY, nombre TEXT, institucion TEXT, camara TEXT);
        CREATE TABLE configuracion(clave TEXT PRIMARY KEY, valor TEXT, actualizado TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO proyectos(id, nombre, institucion) VALUES ('P-001','Escuela Limoncito','MEP'),
          ('P-002','Ruta (ejemplo)','Municipalidad'), ('P-004','Puente María Aguilar','MOPT'), ('P-005','Liceo Ticabán','MEP');""")
    return c


def fila(c, pid):
    c.row_factory = sqlite3.Row
    return dict(c.execute("SELECT * FROM proyectos WHERE id=?", (pid,)).fetchone())


def test_migracion_agrega_columnas_y_copia_la_configuracion_de_config_etl(tmp_path):
    c = base_antigua(tmp_path)
    store._agregar_columnas_proyecto(c); store._copiar_config_etl(c)
    p1, p2, p4, p5 = (fila(c, p) for p in ("P-001", "P-002", "P-004", "P-005"))
    assert p1["drive_carpeta"] == ETL["carpetas"]["P-001"]
    assert json.loads(p1["etl_excluir"]) == [list(e) for e in ETL["excluir"]["P-001"]]
    assert p4["etl_rotacion"] == ETL["rotacion_obra"]["P-004"] and p4["etl_ventana_dias"] == ETL["ventana_dias"]["P-004"]
    assert p5["etl_nitidez_min"] == ETL["nitidez_min_obra"]["P-005"]
    assert p2["drive_carpeta"] is None and p2["etl_rotacion"] == 0     # obra sin configuración en config.ETL


def test_migracion_se_hace_una_sola_vez_y_respeta_lo_editado(tmp_path):
    c = base_antigua(tmp_path)
    store._agregar_columnas_proyecto(c); store._copiar_config_etl(c)
    c.execute("UPDATE proyectos SET drive_carpeta=NULL WHERE id='P-001'")    # el admin la borró a propósito
    store._agregar_columnas_proyecto(c); store._copiar_config_etl(c)         # se reinicia el servidor
    assert fila(c, "P-001")["drive_carpeta"] is None


def test_base_nueva_trae_la_configuracion_de_fabrica():
    # La base temporal de las pruebas se creó desde cero: P-001 debe tener la carpeta y el período de instalación
    cfg = proyectos.config_etl("P-001")
    assert cfg["carpeta"] == ETL["carpetas"]["P-001"]
    assert cfg["excluir"] == [tuple(e) for e in ETL["excluir"]["P-001"]]
    assert proyectos.config_etl("P-002")["nitidez_min"] == ETL["nitidez_min"]   # sin umbral propio: el general


# ---------- Ida y vuelta por la API de administración ----------
def test_crear_y_editar_por_la_api(cliente, entrar):
    c = cliente(); entrar(c, *ADMIN)
    datos = VALIDO | dict(nombre="Obra con cámara configurada", captura_intervalo_min="15", captura_desde="07:00",
                          captura_hasta="17:00", drive_carpeta="https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp",
                          etl_rotacion="180", etl_nitidez_min="4.5", etl_ventana_dias="31",
                          etl_excluir=[dict(desde="2026-01-05", hasta="2026-01-06", motivo="Instalación")])
    r = c.post("/api/admin/proyectos", json=datos)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    p = c.get(f"/api/admin/proyectos/{pid}").json()
    assert p["fotos_esperadas_dia"] == 41 and p["drive_carpeta"] == "1AbCdEfGhIjKlMnOp"
    assert p["etl_excluir"] == [dict(desde="2026-01-05", hasta="2026-01-06", motivo="Instalación")]
    assert proyectos.config_etl(pid) == dict(carpeta="1AbCdEfGhIjKlMnOp", rotacion=180, nitidez_min=4.5, ventana_dias=31,
                                             excluir=[("2026-01-05", "2026-01-06", "Instalación")])

    # Editar: se vacían los períodos excluidos y el umbral propio, y se quita la frecuencia
    cambios = datos | dict(etl_excluir=[], etl_nitidez_min=None, captura_intervalo_min=None, captura_desde=None, captura_hasta=None)
    assert c.put(f"/api/admin/proyectos/{pid}", json=cambios).status_code == 200
    cfg = proyectos.config_etl(pid)
    assert cfg["excluir"] == [] and cfg["nitidez_min"] == ETL["nitidez_min"]
    assert proyectos.obtener(pid)["fotos_esperadas_dia"] is None


def test_error_de_validacion_llega_como_400_con_mensaje(cliente, entrar):
    c = cliente(); entrar(c, *ADMIN)
    r = c.post("/api/admin/proyectos", json=VALIDO | dict(nombre="Obra con rotación mala", etl_rotacion="45"))
    assert r.status_code == 400 and "0, 90, 180 o 270" in r.json()["detail"]
