"""Meteoblue Free Weather API (https://docs.meteoblue.com). Clave gratuita para uso NO comercial (1 año, créditos limitados).
Paquetes basic-1h + basic-day en una sola llamada: horas pasadas (history_days, hasta 4 días en el plan gratuito)
y pronóstico (hasta 14 días).

Proveedor de clima: cumple el contrato descrito en src/clima/comun.py. Se activa con METEOBLUE_API_KEY.
Formato de respuesta: columnas en arreglos paralelos (data_1h.time[i], data_1h.precipitation[i], ...)."""
from config import METEOBLUE_API_KEY, METEOBLUE_URL, CLIMA
from src.clima.comun import ErrorClima, get_json, ahora_cr, TZ_NOMBRE, v

NOMBRE, ETIQUETA = "meteoblue", "Meteoblue"
ATRIBUCION = "Datos meteorológicos de meteoblue.com."
HISTORIAL = "3 días"

def configurado():
    return bool(METEOBLUE_API_KEY)

_cache = {}  # misma estrategia que openmeteo.py: una llamada por obra y hora

def _consulta(lat, lng):
    if not configurado(): raise ErrorClima("Falta la variable de entorno METEOBLUE_API_KEY")
    clave = (round(lat, 4), round(lng, 4), ahora_cr().strftime("%Y%m%d%H"))
    if clave in _cache: return _cache[clave]
    q = {"lat": lat, "lon": lng, "apikey": METEOBLUE_API_KEY, "format": "json", "tz": TZ_NOMBRE, "windspeed": "kmh",
         "temperature": "C", "precipitationamount": "mm", "history_days": 3, "forecast_days": min(CLIMA["pronostico_dias"], 14)}
    j = get_json("Meteoblue", f"{METEOBLUE_URL}/packages/basic-1h_basic-day", q, secretos=[METEOBLUE_API_KEY])
    if j.get("error"): raise ErrorClima(f"Meteoblue: {j.get('error_message') or j.get('error')}")
    _cache.clear(); _cache[clave] = j
    return j

def _hora(t):  # "2026-10-24 14:00" -> "2026-10-24T14:00"
    return str(t).replace(" ", "T")[:16]

def actual(lat, lng):
    """El plan gratuito no incluye 'current': se toma la hora en curso del pronóstico horario."""
    h = _consulta(lat, lng).get("data_1h") or {}; ahora = ahora_cr().strftime("%Y-%m-%dT%H:00")
    for i, t in enumerate(h.get("time", [])):
        if _hora(t) == ahora:
            col = lambda k: v(h, k, i)
            return dict(hora=_hora(t), temp=col("temperature"), humedad=col("relativehumidity"), lluvia_mm=col("precipitation"),
                        prob_lluvia=col("precipitation_probability"), viento_kmh=col("windspeed"), condicion=None, prob_tormenta=None)
    return None

def historial_horas(lat, lng):
    """Solo horas anteriores a la hora en curso (criterio conservador: no se asume a qué hora corresponde la lluvia)."""
    h = _consulta(lat, lng).get("data_1h") or {}; limite = ahora_cr().strftime("%Y-%m-%dT%H:00"); out = []
    for i, t in enumerate(h.get("time", [])):
        hora = _hora(t)
        if hora >= limite: break
        if v(h, "precipitation", i) is None: continue
        out.append(dict(hora=hora, fecha=hora[:10], lluvia_mm=v(h, "precipitation", i), temp=v(h, "temperature", i),
                        humedad=v(h, "relativehumidity", i), prob_tormenta=None, viento_kmh=v(h, "windspeed", i), condicion=None))
    return out

def pronostico_dias(lat, lng, dias=10):
    d = _consulta(lat, lng).get("data_day") or {}; hoy = ahora_cr().strftime("%Y-%m-%d"); out = []
    for i, f in enumerate(d.get("time", [])):
        f = str(f)[:10]
        if f < hoy: continue  # también trae los días de history_days
        out.append(dict(fecha=f, lluvia_mm=v(d, "precipitation", i), temp_max=v(d, "temperature_max", i), temp_min=v(d, "temperature_min", i),
                        humedad=v(d, "relativehumidity_mean", i), prob_lluvia=v(d, "precipitation_probability", i), prob_tormenta=None,
                        viento_kmh=v(d, "windspeed_max", i), condicion=None))
    return out[:dias]
