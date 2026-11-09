"""Pruebas de la API de imágenes para las cámaras (routes/camaras.py + src/imagenes.py).

Es la puerta de entrada de las fotos que llegarán desde el Apps Script v2 (ítem CAM-01 / PIP-04 del backlog):
    - el token de una obra solo sirve para esa obra; un token revocado deja de servir
    - solo se aceptan JPEG o PNG válidos, con fecha ISO 8601 y confianza entre 0 y 1
    - el nombre del archivo lo pone el servidor a partir de la hora de captura ("tomada"), nunca el que manda la cámara
Las fotos se guardan en la carpeta temporal de las pruebas (conftest.py), no en data/obras/."""
import io
import pytest
from PIL import Image
import config
from src import proyectos


def imagen(formato="JPEG"):
    """Bytes de una imagen pequeña generada en memoria."""
    buf = io.BytesIO(); Image.new("RGB", (32, 24), (90, 120, 150)).save(buf, formato)
    return buf.getvalue()


@pytest.fixture
def token():
    """Token nuevo de la cámara de P-001 (se genera uno por prueba: cada uno invalida al anterior)."""
    return proyectos.generar_token("P-001")


def cabecera(t):
    return {"Authorization": f"Bearer {t}"}


def enviar(c, t, pid="P-001", datos=None, nombre="captura.jpg", **campos):
    return c.post(f"/api/camaras/{pid}/imagenes", headers=cabecera(t),
                  files={"foto": (nombre, datos if datos is not None else imagen(), "image/jpeg")}, data=campos)


# ---------- token ----------
def test_estado_con_token_correcto(cliente, token):
    r = cliente().get("/api/camaras/P-001/estado", headers=cabecera(token))
    assert r.status_code == 200 and r.json()["proyecto"] == "P-001"


def test_sin_token_o_con_token_falso_responde_401(cliente):
    c = cliente()
    assert c.get("/api/camaras/P-001/estado").status_code == 401
    assert c.get("/api/camaras/P-001/estado", headers=cabecera("dia_inventado")).status_code == 401


def test_el_token_de_una_obra_no_sirve_para_otra(cliente, token):
    assert cliente().get("/api/camaras/P-002/estado", headers=cabecera(token)).status_code == 401


def test_token_revocado_deja_de_servir(cliente, token):
    proyectos.revocar_token("P-001")
    assert cliente().get("/api/camaras/P-001/estado", headers=cabecera(token)).status_code == 401


# ---------- recepción de fotos ----------
def test_foto_valida_se_guarda_con_el_nombre_de_su_hora_de_captura(cliente, token):
    r = enviar(cliente(), token, tomada="2026-10-24T14:30:00", personas="2", confianza="0.8")
    assert r.status_code == 201
    reg = r.json()
    assert reg["archivo"] == "2026-10-24_143000.jpg" and reg["fecha"] == "2026-10-24" and reg["hora"] == "14:30"
    assert (config.OBRAS_DIR / "P-001" / "camara" / reg["archivo"]).is_file()


def test_dos_fotos_en_el_mismo_segundo_no_se_sobrescriben(cliente, token):
    c = cliente()
    a = enviar(c, token, tomada="2026-10-25T08:00:00").json()["archivo"]
    b = enviar(c, token, tomada="2026-10-25T08:00:00").json()["archivo"]
    assert a != b and b == "2026-10-25_080000-1.jpg"


def test_el_nombre_que_manda_la_camara_se_ignora(cliente, token):
    r = enviar(cliente(), token, nombre="../../diara.db", tomada="2026-10-26T09:00:00")
    assert r.status_code == 201 and r.json()["archivo"] == "2026-10-26_090000.jpg"


@pytest.mark.parametrize("datos, campos, mensaje", [
    (b"esto no es una imagen", {}, "no es una imagen"),
    (None, {"tomada": "24/10/2026 14:30"}, "ISO 8601"),
    (None, {"confianza": "1.5"}, "entre 0 y 1"),
])
def test_rechazos_con_mensaje_claro(cliente, token, datos, campos, mensaje):
    r = enviar(cliente(), token, datos=datos, **campos)
    assert r.status_code == 400 and mensaje in r.json()["detail"]


def test_formato_no_admitido(cliente, token):
    r = enviar(cliente(), token, datos=imagen("GIF"), nombre="captura.gif")
    assert r.status_code == 400 and "JPEG o PNG" in r.json()["detail"]
