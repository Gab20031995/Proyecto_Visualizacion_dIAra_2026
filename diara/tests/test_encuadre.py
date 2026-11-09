"""Pruebas de la detección de cambios de encuadre (src/etl/encuadre.py, ítem EDA-02).

No usan fotos reales: generan una "escena" sintética (líneas, rectángulos y círculos sobre un fondo suave) y simulan
la cámara recortando una parte de ella. Mover la cámara = recortar unos píxeles más a la derecha.
    - partes puras: descriptor, correlación de fase, serie diaria y selección de fotos
    - de punta a punta: fotos en la base de prueba -> detectar() -> cambio en la fecha correcta, panel y CSV
Los umbrales se leen de config.ENCUADRE (calibrados con las fotos reales de Limoncito, Puente y Ticabán)."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter
import config
from config import ENCUADRE as E
from src import store, etl
from src.etl import encuadre

ESCENA_TAM, FOTO_TAM = (1100, 760), (800, 600)


def escena(semilla=7):
    """Imagen grande con estructuras en posiciones fijas (como edificios, grúas y andamios)."""
    rng = np.random.default_rng(semilla)
    fondo = np.add.outer(np.linspace(60, 180, ESCENA_TAM[1]), np.linspace(0, 40, ESCENA_TAM[0]))
    im = Image.fromarray(fondo.astype(np.uint8)); d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rng.integers(0, ESCENA_TAM[0]), rng.integers(0, ESCENA_TAM[1])
        tipo, tono = rng.integers(3), int(rng.integers(0, 255))
        if tipo == 0: d.line([x, y, x + rng.integers(-300, 300), y + rng.integers(-300, 300)], fill=tono, width=int(rng.integers(3, 12)))
        elif tipo == 1: d.rectangle([x, y, x + rng.integers(20, 160), y + rng.integers(20, 160)], fill=tono)
        else: d.ellipse([x, y, x + rng.integers(20, 120), y + rng.integers(20, 120)], outline=tono, width=5)
    return im.filter(ImageFilter.GaussianBlur(1))


def foto(base, x=100, y=80, brillo=1.0):
    """Lo que "ve" la cámara: un recorte de la escena (x, y = posición de la cámara) con un brillo dado."""
    im = base.crop((x, y, x + FOTO_TAM[0], y + FOTO_TAM[1]))
    return im.point(lambda v: min(255, int(v * brillo)))


def coseno(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


# ---------- descriptor ----------
def test_descriptor_tiene_432_valores_y_norma_1():
    v = encuadre.descriptor(foto(escena()))
    assert v.shape == (6 * 8 * 9,) and abs(np.linalg.norm(v) - 1) < 1e-5


def test_descriptor_cambia_poco_con_la_luz_y_mucho_si_la_camara_se_mueve():
    base = escena()
    original = encuadre.descriptor(foto(base))
    mas_oscura = encuadre.descriptor(foto(base, brillo=0.6))
    movida = encuadre.descriptor(foto(base, x=200))
    assert coseno(original, mas_oscura) > 0.97
    assert 1 - coseno(original, movida) > E["umbral_ventana"]   # un movimiento supera el umbral de cambio


# ---------- correlación de fase ----------
def test_desplazamiento_estima_cuanto_se_movio_la_camara():
    base = escena()
    a, b = foto(base).resize(E["tamano"]), foto(base, x=200).resize(E["tamano"])   # 100 px en 800 = 80 px en 640
    dx, dy, pico = encuadre.desplazamiento(a, b)
    assert abs(abs(dx) - 80) <= 4 and abs(dy) <= 4


def test_pico_alto_si_las_fotos_calzan_y_bajo_si_no_se_parecen():
    a = foto(escena()).resize(E["tamano"])
    assert encuadre.desplazamiento(a, a)[2] > 0.9
    assert encuadre.desplazamiento(a, foto(escena(semilla=99)).resize(E["tamano"]))[2] < E["pico_confiable"]


def test_clasificacion():
    assert encuadre.clasificar(80, 0, 0.6) == "Movimiento de la cámara"                      # se corrió y calza bien
    assert encuadre.clasificar(0, -100, 0.03).startswith("Probable movimiento")               # Limoncito 12/02/2026
    assert encuadre.clasificar(0, 0, 0.03).startswith("Cambio en la imagen")                  # no se desplazó
    assert encuadre.clasificar(E["desplazamiento_px"] - 1, 0, 0.9).startswith("Cambio en la imagen")


# ---------- serie diaria (función pura) ----------
def serie(n_antes, n_despues, ruido=0.002, semilla=1):
    """Descriptores diarios de dos encuadres distintos (A y luego B) con un poco de ruido (luz, nubes)."""
    rng = np.random.default_rng(semilla)
    A, B = rng.random(432), rng.random(432)
    return np.stack([(A if i < n_antes else B) + rng.normal(0, ruido, 432) for i in range(n_antes + n_despues)])


def test_detecta_un_cambio_en_el_dia_correcto():
    _, cambios, _, tramo = encuadre.analizar_serie(serie(12, 12))
    assert cambios == [12] and tramo[11] == 0 and tramo[12] == 1


def test_sin_cambio_no_detecta_nada():
    ventana, cambios, _, _ = encuadre.analizar_serie(serie(24, 0))
    assert cambios == [] and np.nanmax(ventana) < E["umbral_ventana"]


def test_cambio_reciente_se_detecta_recien_con_la_ventana_completa_y_en_su_fecha():
    # Límite documentado: hacen falta dias_ventana + 1 días con fotos después del cambio. Antes, nada (y nunca un día antes)
    for despues in range(1, E["dias_ventana"] + 1):
        assert encuadre.analizar_serie(serie(20, despues))[1] == [], f"con {despues} días después"
    assert encuadre.analizar_serie(serie(20, E["dias_ventana"] + 1))[1] == [20]


def test_la_referencia_se_reinicia_despues_de_cada_cambio():
    _, _, dist, _ = encuadre.analizar_serie(serie(12, 12))
    assert dist.max() < 0.05   # cada día está cerca de la referencia de SU tramo (no del encuadre inicial)


# ---------- selección de fotos ----------
def fila(**cambios):
    base = dict(drive_id="x", fecha="2026-03-01", hora="12:00:00", curada="2026-03-02", duplicado_de=None, apta_ia=1, motivo_ia=None)
    return base | cambios


@pytest.mark.parametrize("cambios, sirve", [
    ({}, True),
    (dict(apta_ia=0, motivo_ia="borrosa o lente empañado"), True),                  # empañada: igual muestra el encuadre
    (dict(apta_ia=1, motivo_ia="aviso: lluvia durante la captura"), True),
    (dict(apta_ia=0, motivo_ia="nocturna"), False),
    (dict(apta_ia=0, motivo_ia="borrosa o lente empañado; sobreexpuesta"), False),
    (dict(hora="06:30:00"), False),                                                 # fuera del horario
    (dict(curada=None), False),                                                     # todavía no pasó por "curar"
    (dict(duplicado_de="otra"), False),
])
def test_que_fotos_sirven_para_ver_el_encuadre(cambios, sirve):
    assert encuadre.usable(fila(**cambios)) is sirve


def test_periodo_excluido_no_sirve():
    assert not encuadre.usable(fila(), [("2026-03-01", "2026-03-01", "Instalación")])


def test_selecciona_las_mas_cercanas_al_mediodia():
    fotos = [fila(drive_id=h, hora=h) for h in ("08:10:00", "11:40:00", "12:30:00", "16:00:00")]
    # distancia al mediodía: 11:40 -> 20 min, 12:30 -> 30 min, 08:10 -> 3 h 50, 16:00 -> 4 h
    esperado = ["11:40:00", "12:30:00", "08:10:00", "16:00:00"][:E["fotos_por_dia"]]
    assert [f["drive_id"] for f in encuadre.seleccionar(fotos)["2026-03-01"]] == esperado


# ---------- de punta a punta con la base de prueba ----------
@pytest.fixture(scope="module")
def obra_con_cambio():
    """P-002 con 20 días de fotos: los 10 primeros con un encuadre y desde el 11/03/2026 la cámara movida 100 px."""
    etl.preparar(); encuadre.preparar()
    base, carpeta = escena(), config.DATA_DIR / "etl" / "drive" / "P-002" / "prueba"
    carpeta.mkdir(parents=True, exist_ok=True)
    filas = []
    for i in range(20):
        fecha = f"2026-03-{i + 1:02d}"
        for hora in ("11:30:00", "12:30:00"):
            ruta = carpeta / f"{fecha}_{hora[:2]}.jpg"
            foto(base, x=100 if i < 10 else 200, brillo=0.9 + 0.01 * (i % 5)).save(ruta, quality=90)
            filas.append((f"enc-{fecha}-{hora}", "P-002", "historico", ruta.name, fecha, hora,
                          ruta.relative_to(config.DATA_DIR).as_posix(), "2026-03-31", 1))
    store._q("DELETE FROM etl_imagenes WHERE project_id='P-002'")
    for f in filas:
        store._q("""INSERT INTO etl_imagenes(drive_id, project_id, origen, archivo, fecha, hora, ruta_local, curada, apta_ia)
                    VALUES(?,?,?,?,?,?,?,?,?)""", f)
    return encuadre.detectar("P-002")


def test_detectar_encuentra_el_movimiento_en_la_fecha_correcta(obra_con_cambio):
    r = obra_con_cambio
    assert r["dias"] == 20 and len(r["cambios"]) == 1
    c = r["cambios"][0]
    assert c["fecha"] == "2026-03-11" and c["ultima_fecha_antes"] == "2026-03-10" and c["dias_sin_fotos"] == 0
    assert c["clasificacion"] == "Movimiento de la cámara"
    assert (config.DATA_DIR / c["panel"]).is_file()
    assert (config.DATA_DIR / "etl" / "P-002" / "encuadre" / "cambios.csv").is_file()


def test_repetir_conserva_la_revision_y_usa_la_cache(obra_con_cambio):
    store._q("UPDATE etl_encuadre_cambios SET estado='Confirmado' WHERE project_id='P-002'")
    assert len(store._filas("SELECT * FROM etl_encuadre_fotos WHERE project_id='P-002'")) == 40   # 2 fotos x 20 días
    encuadre.detectar("P-002")
    assert [c["estado"] for c in encuadre.cambios("P-002")] == ["Confirmado"]
