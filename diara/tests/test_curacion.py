"""Pruebas de la curación del ETL: qué fotos sirven para la IA (src/etl/curacion.decidir).

decidir() recibe los metadatos de una foto ya medidos (brillo, nitidez, clima de su hora) y devuelve (apta, motivo).
No abre imágenes: se prueba con datos inventados. Los umbrales se leen de config.ETL, igual que en la curación real.
Estas pruebas protegen las reglas que se calibraron con las fotos de Limoncito (quemadas, empañadas, nocturnas)."""
import pytest
from config import ETL
from src.etl import curacion

NITIDA = ETL["nitidez_min"] + 4     # nitidez de una foto buena


def foto(**cambios):
    """Metadatos de una foto de día, nítida y sin problemas, con los cambios que pida la prueba."""
    base = dict(project_id="P-001", tomada="2026-03-01T10:00:00", fecha="2026-03-01", hora="10:00:00",
                duplicado_de=None, brillo=120)
    return base | cambios


def decidir(f=None, nitidez=NITIDA, clima=(500, 0.0), excluir=(), nitidez_min=None):
    """clima = (radiación W/m², lluvia mm) de la hora de la foto, o None si no hay dato de clima.
    nitidez_min = umbral propio de la obra (proyectos.config_etl); None = el general."""
    return curacion.decidir(f or foto(), 30, nitidez, clima, list(excluir), nitidez_min)


def test_foto_de_dia_nitida_es_apta_sin_motivo():
    assert decidir() == (1, None)


@pytest.mark.parametrize("f, clima, motivo", [
    (foto(tomada=None, fecha=None, hora=None), None, "sin fecha de captura"),
    (foto(duplicado_de="abc123"), (500, 0.0), "duplicada"),
    (foto(), (0, 0.0), "nocturna"),                                     # radiación 0 según el clima
    (foto(hora="22:15:00"), None, "nocturna"),                          # sin clima: se decide por la hora
    (foto(brillo=ETL["brillo_oscuro"] - 1), (500, 0.0), "oscura"),
    (foto(brillo=ETL["brillo_quemado"] + 1), (500, 0.0), "sobreexpuesta"),
])
def test_bloqueos(f, clima, motivo):
    apta, texto = decidir(f, clima=clima)
    assert apta == 0 and motivo in texto


def test_hora_de_dia_sin_dato_de_clima_es_apta():
    assert decidir(foto(hora="06:00:00"), clima=None) == (1, None)


def test_borrosa_o_lente_empanado():
    apta, texto = decidir(nitidez=ETL["nitidez_min"] - 1)
    assert apta == 0 and "empañado" in texto


def test_sobreexpuesta_no_se_marca_ademas_como_borrosa():
    # una foto quemada tampoco tiene bordes; basta con un motivo para no confundir al revisar
    _, texto = decidir(foto(brillo=ETL["brillo_quemado"] + 1), nitidez=1)
    assert "sobreexpuesta" in texto and "empañado" not in texto


def test_umbral_de_nitidez_propio_de_la_obra():
    # Una cámara de menor resolución (Ticabán: 4.5) tiene su propio umbral, más bajo que el general.
    # El umbral de cada obra se configura en Administración y llega a decidir() desde proyectos.config_etl.
    nitidez = 4.6
    assert nitidez < ETL["nitidez_min"]
    assert decidir(nitidez=nitidez, nitidez_min=4.5)[0] == 1      # obra con umbral propio
    assert decidir(nitidez=nitidez)[0] == 0                        # obra con el umbral general


def test_periodo_excluido_a_mano():
    apta, texto = decidir(excluir=[("2026-03-01", "2026-03-01", "Instalación de la cámara")])
    assert apta == 0 and texto == "Instalación de la cámara"


def test_lluvia_durante_la_captura_es_aviso_y_la_foto_sigue_apta():
    apta, texto = decidir(clima=(300, ETL["lluvia_hora_mm"] + 1))
    assert apta == 1 and texto.startswith("aviso:")
