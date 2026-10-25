"""Google Maps Platform · Weather API (https://developers.google.com/maps/documentation/weather). De pago, requiere clave.
  /currentConditions:lookup   condiciones actuales
  /history/hours:lookup       últimas 24 h hora por hora (máximo que ofrece Google)
  /forecast/days:lookup       pronóstico diario (hasta 10 días)

Proveedor de clima: cumple el contrato descrito en src/clima/comun.py. Se activa con GOOGLE_MAPS_API_KEY.
Como Google solo da 24 h de historial, actualizar_clima.py debe correr cada 12 h o menos para no perder horas."""
from config import GOOGLE_MAPS_API_KEY, GOOGLE_WEATHER_URL
from src.clima.comun import ErrorClima, get_json, v, maximo

NOMBRE, ETIQUETA = "google", "Google Weather"
ATRIBUCION = "Google Maps Platform Weather API."
HISTORIAL = "24 horas"

def configurado():
    return bool(GOOGLE_MAPS_API_KEY)

def _get(ruta, lat, lng, **extra):
    """Consulta un endpoint con coordenadas, unidades métricas y textos en español."""
    if not configurado(): raise ErrorClima("Falta la variable de entorno GOOGLE_MAPS_API_KEY")
    q = {"key": GOOGLE_MAPS_API_KEY, "location.latitude": lat, "location.longitude": lng, "unitsSystem": "METRIC", "languageCode": "es", **extra}
    return get_json("Google Weather", f"{GOOGLE_WEATHER_URL}{ruta}", q, secretos=[GOOGLE_MAPS_API_KEY])

def _paginas(ruta, lat, lng, campo, **extra):
    """Recorre la paginación de Google (nextPageToken). Máximo 10 páginas como protección."""
    out, token = [], None
    for _ in range(10):
        j = _get(ruta, lat, lng, **extra, **({"pageToken": token} if token else {}))
        out += j.get(campo, []); token = j.get("nextPageToken")
        if not token: break
    return out

def _fecha(dt):
    """displayDate / displayDateTime de Google ({year, month, day}) -> 'AAAA-MM-DD' (hora local de la obra)."""
    return f"{dt['year']:04d}-{dt['month']:02d}-{dt['day']:02d}"

def actual(lat, lng):
    j = _get("/currentConditions:lookup", lat, lng)
    return dict(hora=j.get("currentTime"), temp=v(j, "temperature", "degrees"), humedad=j.get("relativeHumidity"),
                condicion=v(j, "weatherCondition", "description", "text"), prob_lluvia=v(j, "precipitation", "probability", "percent"),
                lluvia_mm=v(j, "precipitation", "qpf", "quantity"), prob_tormenta=j.get("thunderstormProbability"),
                viento_kmh=v(j, "wind", "speed", "value"))

def historial_horas(lat, lng):
    """Últimas 24 horas observadas. qpf = lluvia acumulada en esa hora (mm)."""
    out = []
    for h in _paginas("/history/hours:lookup", lat, lng, "historyHours", hours=24, pageSize=24):
        dt = h.get("displayDateTime") or {}
        if not dt or not v(h, "interval", "startTime"): continue
        # La clave de la hora se arma en hora LOCAL ("AAAA-MM-DDTHH:00") igual que las demás fuentes
        out.append(dict(hora=f"{_fecha(dt)}T{dt.get('hours', 0):02d}:00", fecha=_fecha(dt),
                        lluvia_mm=v(h, "precipitation", "qpf", "quantity") or 0.0, temp=v(h, "temperature", "degrees"),
                        humedad=h.get("relativeHumidity"), prob_tormenta=h.get("thunderstormProbability"),
                        viento_kmh=v(h, "wind", "speed", "value"), condicion=v(h, "weatherCondition", "description", "text")))
    return out

def pronostico_dias(lat, lng, dias=10):
    """Google separa cada día en daytimeForecast y nighttimeForecast: se suman lluvias y se toman máximos."""
    out = []
    for d in _paginas("/forecast/days:lookup", lat, lng, "forecastDays", days=min(dias, 10), pageSize=min(dias, 10)):
        dia, noche = d.get("daytimeForecast") or {}, d.get("nighttimeForecast") or {}
        q = [x for x in (v(dia, "precipitation", "qpf", "quantity"), v(noche, "precipitation", "qpf", "quantity")) if x is not None]
        hum = [x for x in (dia.get("relativeHumidity"), noche.get("relativeHumidity")) if x is not None]
        out.append(dict(fecha=_fecha(d["displayDate"]), lluvia_mm=sum(q) if q else None,
                        temp_max=v(d, "maxTemperature", "degrees"), temp_min=v(d, "minTemperature", "degrees"),
                        humedad=sum(hum) / len(hum) if hum else None,
                        prob_lluvia=maximo(v(dia, "precipitation", "probability", "percent"), v(noche, "precipitation", "probability", "percent")),
                        prob_tormenta=maximo(dia.get("thunderstormProbability"), noche.get("thunderstormProbability")),
                        viento_kmh=maximo(v(dia, "wind", "speed", "value"), v(noche, "wind", "speed", "value")),
                        condicion=v(dia, "weatherCondition", "description", "text")))
    return out
