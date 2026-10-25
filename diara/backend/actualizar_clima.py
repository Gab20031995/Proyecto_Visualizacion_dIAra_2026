"""Tarea programada: actualiza el clima de todas las obras.

Consulta todas las fuentes de clima activas (historial y pronóstico) para cada obra con coordenadas y lo guarda:
clima_horas, clima_dias, clima_pronosticos_hist, clima_registro (+ clima_registro_cambios) y clima_ejecuciones.
Programarlo al menos cada 12 h: Google solo conserva 24 h de historial (Open-Meteo recupera hasta 92 días).
Uso: python backend/actualizar_clima.py        (en Windows: tareas\\actualizar_clima.bat)
Fuentes: Open-Meteo (activa por defecto), GOOGLE_MAPS_API_KEY, METEOBLUE_API_KEY, METEOSOURCE_API_KEY.
La misma acción existe en Administración → Clima → "Actualizar ahora".
Código de salida: 0 si todas las obras obtuvieron datos de al menos una fuente; 1 si alguna falló (útil para monitoreo)."""
import sys
from src import clima

if not clima.activos():
    sys.exit("No hay fuentes de clima configuradas")
print("Fuentes activas:", ", ".join(p.ETIQUETA for p in clima.activos()))
res = clima.actualizar_todos(origen="programado")  # "programado" queda en la bitácora clima_ejecuciones
for r in res:
    g = r["registro"]
    print(f"{r['proyecto']}: registro {g['dias']} días ({g['nuevos']} nuevos, {g['cambiados']} con cambios)")
    for f in r["fuentes"]:
        print(f"   {f['fuente']}: " + (f"{f['horas']} horas, {f['pronostico']} días de pronóstico" if f["ok"] else f"ERROR {f['error']}"))
sys.exit(0 if all(r["ok"] for r in res) else 1)
