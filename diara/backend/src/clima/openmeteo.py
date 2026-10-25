"""Open-Meteo (https://open-meteo.com/en/docs). Sin clave para uso no comercial (< 10 000 llamadas/día), licencia CC BY 4.0.
Una sola llamada trae: condiciones actuales, horas pasadas (past_days, hasta 92) y pronóstico diario (hasta 16 días).
Para uso comercial se define OPEN_METEO_API_KEY y se usa el servidor customer-api.open-meteo.com.

Proveedor de clima: cumple el contrato descrito en src/clima/comun.py. Activo por defecto (OPEN_METEO_ACTIVO=1).
Es la fuente con más historial: permite reconstruir días anteriores aunque la tarea programada haya fallado."""
from config import OPEN_METEO_ACTIVO, OPEN_METEO_API_KEY, OPEN_METEO_URL, CLIMA
from src.clima.comun import ErrorClima, get_json, ahora_cr, TZ_NOMBRE

NOMBRE, ETIQUETA = "openmeteo", "Open-Meteo"
ATRIBUCION = "Datos meteorológicos de Open-Meteo.com (CC BY 4.0)."
HISTORIAL = f"{CLIMA['dias_historial']} días"

# Códigos WMO de estado del tiempo -> texto
WMO = {0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado", 45: "Niebla", 48: "Niebla con escarcha",
       51: "Llovizna débil", 53: "Llovizna", 55: "Llovizna intensa", 61: "Lluvia débil", 63: "Lluvia", 65: "Lluvia fuerte",
       80: "Chubascos débiles", 81: "Chubascos", 82: "Chubascos fuertes", 95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta fuerte con granizo"}

def configurado():
    return OPEN_METEO_ACTIVO

# Caché de una sola entrada: (lat, lng, hora actual) -> respuesta. actual(), historial_horas() y pronostico_dias()
# se llaman seguidos para la misma obra; así se hace UNA llamada HTTP por obra y actualización, no tres.
_cache = {}

def _consulta(lat, lng):
    """Una llamada por obra y actualización; se reutiliza para actual, historial y pronóstico."""
    clave = (round(lat, 4), round(lng, 4), ahora_cr().strftime("%Y%m%d%H"))
    if clave in _cache: return _cache[clave]
    q = {"latitude": lat, "longitude": lng, "timezone": TZ_NOMBRE, "past_days": CLIMA["dias_historial"], "forecast_days": min(CLIMA["pronostico_dias"], 16),
         "hourly": "precipitation,temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
         "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,weather_code",
         "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,weather_code"}
    if OPEN_METEO_API_KEY: q["apikey"] = OPEN_METEO_API_KEY
    j = get_json("Open-Meteo", OPEN_METEO_URL, q, secretos=[OPEN_METEO_API_KEY])
    if j.get("error"): raise ErrorClima(f"Open-Meteo: {j.get('reason')}")
    _cache.clear(); _cache[clave] = j
    return j

def actual(lat, lng):
    c = _consulta(lat, lng).get("current") or {}
    return dict(hora=c.get("time"), temp=c.get("temperature_2m"), humedad=c.get("relative_humidity_2m"), lluvia_mm=c.get("precipitation"),
                viento_kmh=c.get("wind_speed_10m"), condicion=WMO.get(c.get("weather_code")), prob_lluvia=None, prob_tormenta=None)

def historial_horas(lat, lng):
    """La respuesta horaria mezcla horas pasadas (past_days) y futuras (pronóstico): solo se devuelven las pasadas."""
    h = _consulta(lat, lng).get("hourly") or {}
    # "precipitation" de Open-Meteo es la suma de la hora ANTERIOR (el dato de 04:00 cubre 03:00-04:00):
    # se incluyen las horas hasta la actual inclusive; las siguientes son pronóstico.
    limite = ahora_cr().strftime("%Y-%m-%dT%H:00")
    out = []
    for i, t in enumerate(h.get("time", [])):
        if t > limite: break
        col = lambda k: (h.get(k) or [None] * (i + 1))[i]  # columna k en la posición i (None si la variable no vino)
        if col("precipitation") is None: continue
        out.append(dict(hora=t, fecha=t[:10], lluvia_mm=col("precipitation"), temp=col("temperature_2m"), humedad=col("relative_humidity_2m"),
                        prob_tormenta=None, viento_kmh=col("wind_speed_10m"), condicion=WMO.get(col("weather_code"))))
    return out

def pronostico_dias(lat, lng, dias=10):
    d = _consulta(lat, lng).get("daily") or {}
    hoy = ahora_cr().strftime("%Y-%m-%d"); out = []
    for i, f in enumerate(d.get("time", [])):
        if f < hoy: continue  # la respuesta diaria también incluye los días pasados de past_days
        col = lambda k: (d.get(k) or [None] * (i + 1))[i]
        out.append(dict(fecha=f, lluvia_mm=col("precipitation_sum"), temp_max=col("temperature_2m_max"), temp_min=col("temperature_2m_min"),
                        humedad=None, prob_lluvia=col("precipitation_probability_max"), prob_tormenta=None,
                        viento_kmh=col("wind_speed_10m_max"), condicion=WMO.get(col("weather_code"))))
    return out[:dias]
