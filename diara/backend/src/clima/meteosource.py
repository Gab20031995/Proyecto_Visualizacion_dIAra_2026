"""Meteosource Weather API (https://www.meteosource.com/documentation). Plan gratuito: 400 llamadas/día, requiere
mención y enlace a Meteosource. El plan gratuito NO incluye historial (time machine es de pago): aporta condiciones
actuales y pronóstico diario (7 días).

Proveedor de clima: cumple el contrato descrito en src/clima/comun.py. Se activa con METEOSOURCE_API_KEY.
Como no tiene historial, solo participa en el pronóstico y en las condiciones actuales (no en el registro diario)."""
from config import METEOSOURCE_API_KEY, METEOSOURCE_URL, CLIMA
from src.clima.comun import ErrorClima, get_json, ahora_cr, TZ_NOMBRE, v

NOMBRE, ETIQUETA = "meteosource", "Meteosource"
ATRIBUCION = "Datos meteorológicos de Meteosource (meteosource.com)."
HISTORIAL = "sin historial (plan gratuito)"

def configurado():
    return bool(METEOSOURCE_API_KEY)

_cache = {}  # una llamada por obra y hora (cuida el límite de 400 llamadas/día)

def _consulta(lat, lng):
    if not configurado(): raise ErrorClima("Falta la variable de entorno METEOSOURCE_API_KEY")
    clave = (round(lat, 4), round(lng, 4), ahora_cr().strftime("%Y%m%d%H"))
    if clave in _cache: return _cache[clave]
    q = {"lat": lat, "lon": lng, "sections": "current,daily", "timezone": TZ_NOMBRE, "language": "en", "units": "metric"}
    # La clave va SOLO en el encabezado X-API-Key: Meteosource rechaza (403) si se envía por dos vías a la vez
    j = get_json("Meteosource", f"{METEOSOURCE_URL}/point", q, secretos=[METEOSOURCE_API_KEY], headers={"X-API-Key": METEOSOURCE_API_KEY})
    if not isinstance(j, dict) or ("current" not in j and "daily" not in j): raise ErrorClima("Meteosource: respuesta sin datos")
    _cache.clear(); _cache[clave] = j
    return j

def actual(lat, lng):
    c = _consulta(lat, lng).get("current") or {}
    return dict(hora=ahora_cr().strftime("%Y-%m-%dT%H:%M"), temp=c.get("temperature"), humedad=c.get("humidity"),
                lluvia_mm=v(c, "precipitation", "total"), viento_kmh=_kmh(v(c, "wind", "speed")), condicion=c.get("summary"),
                prob_lluvia=None, prob_tormenta=None)

def historial_horas(lat, lng):
    return []  # no disponible en el plan gratuito

def _kmh(ms):  # unidades métricas de Meteosource: viento en m/s
    return None if ms is None else round(ms * 3.6, 1)

def pronostico_dias(lat, lng, dias=10):
    hoy = ahora_cr().strftime("%Y-%m-%d"); out = []
    for d in v(_consulta(lat, lng), "daily", "data") or []:
        f = str(d.get("day"))[:10]
        if f < hoy: continue
        a = d.get("all_day") or {}  # resumen del día completo (también existen morning/afternoon/evening)
        out.append(dict(fecha=f, lluvia_mm=v(a, "precipitation", "total"), temp_max=a.get("temperature_max"), temp_min=a.get("temperature_min"),
                        humedad=a.get("humidity"), prob_lluvia=v(a, "probability", "precipitation"), prob_tormenta=None,
                        viento_kmh=_kmh(v(a, "wind", "speed")), condicion=d.get("summary") or a.get("weather")))
    return out[:dias]
