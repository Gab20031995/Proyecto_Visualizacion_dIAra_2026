"""Utilidades compartidas por los proveedores de clima (google.py, openmeteo.py, meteoblue.py, meteosource.py).

CONTRATO de un proveedor: cada módulo de proveedor expone
    NOMBRE, ETIQUETA, ATRIBUCION, HISTORIAL      identificador interno, nombre visible, texto de licencia, alcance del historial
    configurado() -> bool                        si tiene lo necesario (clave) para consultarse
    actual(lat, lng) -> dict | None              condiciones actuales
    historial_horas(lat, lng) -> [dict]          horas YA OBSERVADAS: hora, fecha (local CR), lluvia_mm, temp, humedad,
                                                 prob_tormenta, viento_kmh, condicion
    pronostico_dias(lat, lng, dias) -> [dict]    fecha, lluvia_mm, temp_max, temp_min, humedad, prob_lluvia, prob_tormenta,
                                                 viento_kmh, condicion
Los valores que una fuente no ofrece van en None. Para agregar un proveedor: crear su módulo con este contrato y
sumarlo a PROVEEDORES en src/clima/__init__.py.

Se usa la librería estándar (urllib) para no agregar dependencias."""
import json, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

# Costa Rica: UTC-6 todo el año (sin horario de verano). Se evita depender de tzdata en Windows.
TZ_CR = timezone(timedelta(hours=-6))
TZ_NOMBRE = "America/Costa_Rica"   # nombre que se envía a las APIs que aceptan zona horaria

class ErrorClima(Exception):
    """Fallo al consultar una fuente (sin clave, HTTP de error, red). Mensaje sin secretos, listo para mostrar."""
    pass

def ahora_cr():
    """Fecha y hora actual de Costa Rica (sin tzinfo, para comparar con las horas locales que guardamos)."""
    return datetime.now(TZ_CR).replace(tzinfo=None)

def get_json(proveedor, url, params, secretos=(), headers=None):
    """GET con tiempo límite. Los valores de `secretos` (claves) nunca aparecen en los mensajes de error."""
    completo = f"{url}?{urllib.parse.urlencode(params)}"
    def limpiar(t):
        # Algunas APIs repiten la URL (con la clave) en su mensaje de error: se enmascara antes de propagarlo
        for s in secretos:
            if s: t = t.replace(s, "***")
        return t
    try:
        req = urllib.request.Request(completo, headers={"User-Agent": "dIAra/1.0 (CGR Costa Rica)", **(headers or {})})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try: cuerpo = e.read().decode("utf-8", "replace")[:300]
        except Exception: cuerpo = ""
        raise ErrorClima(limpiar(f"{proveedor} respondió {e.code}: {cuerpo}")) from None  # from None: no arrastra la URL en el traceback
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ErrorClima(limpiar(f"No se pudo consultar {proveedor}: {getattr(e, 'reason', e)}")) from None

def v(d, *ruta):
    """Lee un valor anidado sin fallar si falta algún nivel."""
    # Ej.: v(j, "precipitation", "qpf", "quantity") -> j["precipitation"]["qpf"]["quantity"] o None
    for k in ruta:
        if isinstance(d, dict): d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and -len(d) <= k < len(d): d = d[k]
        else: return None
    return d

def maximo(*vals):
    """Máximo ignorando None (None si todos son None)."""
    vals = [x for x in vals if x is not None]
    return max(vals) if vals else None
