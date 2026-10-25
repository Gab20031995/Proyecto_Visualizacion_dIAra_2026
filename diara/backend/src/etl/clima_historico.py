"""Clima horario HISTÓRICO para el cruce con las fotos (tabla etl_clima_horas).

Fuente: Open-Meteo Historical Weather API (https://open-meteo.com/en/docs/historical-weather-api), sin clave para uso
no comercial, licencia CC BY 4.0. Es un reanálisis (ERA5, celda de ~10-25 km): describe el clima de la ZONA, no lo
que marcaría un pluviómetro en la obra. Llega con ~5 días de atraso, por eso no sirve para el día en curso.

Por qué no se usa clima_horas de la aplicación: ahí solo se acumula desde que la tarea de clima empezó a correr
(octubre 2026) y las fotos son de septiembre 2025 a julio 2026. Esta tabla es independiente y no altera el registro
consolidado que usan las alertas.

Convención de horas: la lluvia de "17:00" es la acumulada entre 16:00 y 17:00; temperatura, humedad, nubosidad y
radiación son el valor de esa hora (la radiación es el promedio de la hora anterior)."""
from contextlib import closing
from datetime import date, timedelta
from src import store, etl, proyectos
from src.clima.comun import ErrorClima, get_json, ahora_cr, TZ_NOMBRE
from src.clima.openmeteo import WMO

URL = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = "precipitation,temperature_2m,relative_humidity_2m,cloud_cover,shortwave_radiation,weather_code"
ATRASO_DIAS = 5  # el reanálisis no tiene los últimos días

_SQL = """INSERT INTO etl_clima_horas(project_id,hora,fecha,lluvia_mm,temp,humedad,nubosidad,radiacion,codigo,condicion,fuente)
  VALUES(?,?,?,?,?,?,?,?,?,?,'openmeteo_historico')
  ON CONFLICT(project_id,hora) DO UPDATE SET lluvia_mm=excluded.lluvia_mm, temp=excluded.temp, humedad=excluded.humedad,
  nubosidad=excluded.nubosidad, radiacion=excluded.radiacion, codigo=excluded.codigo, condicion=excluded.condicion,
  actualizado=CURRENT_TIMESTAMP"""

def _meses(desde, hasta):
    """Parte el rango en tramos de un mes: cada llamada responde rápido (get_json tiene 20 s de límite)."""
    a = desde
    while a <= hasta:
        b = min(hasta, (a.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))  # fin de mes
        yield a, b; a = b + timedelta(days=1)

def descargar(pid, desde=None, hasta=None):
    """Paso 3: trae el clima horario de la obra para el rango de las fotos catalogadas (o el indicado) y lo guarda.
    Requiere que el proyecto tenga coordenadas (Administración → Proyectos)."""
    etl.preparar()
    p = proyectos.obtener(pid)
    if not p or p.get("lat") in ("", None): raise ErrorClima(f"{pid} no tiene coordenadas: complételas en Administración → Proyectos")
    if not (desde and hasta):  # por defecto: del primer al último día con fotos (sin la carpeta "otros")
        r = store._filas("SELECT min(fecha) a, max(fecha) b FROM etl_imagenes WHERE project_id=? AND origen<>'otros'", (pid,))[0]
        if not r["a"]: raise ErrorClima("El catálogo está vacío: ejecute primero el paso 'listar'")
        desde, hasta = desde or r["a"], hasta or r["b"]
    d1, d2 = date.fromisoformat(desde), min(date.fromisoformat(hasta), ahora_cr().date() - timedelta(days=ATRASO_DIAS))
    horas = 0
    for a, b in _meses(d1, d2):
        j = get_json("Open-Meteo (histórico)", URL, {"latitude": p["lat"], "longitude": p["lng"], "timezone": TZ_NOMBRE,
                     "start_date": a.isoformat(), "end_date": b.isoformat(), "hourly": VARIABLES})
        h = j.get("hourly") or {}
        col = lambda k, i: (h.get(k) or [None] * (i + 1))[i]
        filas = [(pid, t, t[:10], col("precipitation", i), col("temperature_2m", i), col("relative_humidity_2m", i),
                  col("cloud_cover", i), col("shortwave_radiation", i), col("weather_code", i), WMO.get(col("weather_code", i)))
                 for i, t in enumerate(h.get("time", [])) if col("precipitation", i) is not None]
        with closing(store._c()) as c, c: c.executemany(_SQL, filas)
        horas += len(filas)
    return dict(desde=d1.isoformat(), hasta=d2.isoformat(), horas=horas, lat=p["lat"], lng=p["lng"],
                atribucion="Datos meteorológicos de Open-Meteo.com (CC BY 4.0), reanálisis ERA5")
