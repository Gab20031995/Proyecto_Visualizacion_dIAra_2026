"""Diagnóstico de las fuentes de clima: dice cuáles están activas y, para cada una, si responde y por qué falla.

Uso (desde la raíz del proyecto): python backend/probar_clima.py
No guarda nada en la base: solo consulta las condiciones actuales y 3 días de pronóstico en las coordenadas de la
primera obra ubicada (o en San José si ninguna tiene coordenadas). Cada consulta gasta 1-2 llamadas de la cuota.

Las claves se leen de las variables de entorno o del archivo diara/.env (ver .env.ejemplo y config._cargar_env).
Código de salida: 0 si todas las fuentes configuradas respondieron; 1 si alguna falló."""
import re, sys
from config import ROOT
from src import clima, proyectos
from src.clima.comun import ErrorClima

VARIABLE = {"google": "GOOGLE_MAPS_API_KEY", "openmeteo": "OPEN_METEO_ACTIVO=1", "meteoblue": "METEOBLUE_API_KEY",
            "meteosource": "METEOSOURCE_API_KEY"}
# Pistas según el código HTTP que devolvió la fuente (el texto del error trae "respondió <código>")
PISTAS = {400: "Solicitud rechazada: en Google suele ser una clave inválida o mal copiada (API_KEY_INVALID); revise también "
               "que sea una clave del proyecto donde habilitó la Weather API.",
          401: "Clave inválida o mal copiada (revise espacios o comillas en el .env).",
          403: "Clave sin permiso: en Google, habilite 'Weather API' en el proyecto, active la facturación y revise las "
               "restricciones de la clave; en Meteoblue/Meteosource, verifique que la clave esté activa.",
          404: "Ruta no encontrada: revise que no haya cambiado la URL del servicio (variables *_URL).",
          429: "Cuota agotada (demasiadas llamadas): espere al día siguiente o revise el plan."}

def ubicacion():
    for p in proyectos.listar():
        if p.get("lat") is not None and p.get("lng") is not None: return p["nombre"], p["lat"], p["lng"]
    return "San José (referencia)", 9.9326, -84.0796

nombre, lat, lng = ubicacion()
print(f"Archivo .env: {'encontrado' if (ROOT / '.env').exists() else 'no existe (copie .env.ejemplo como .env)'}")
print(f"Prueba en: {nombre} ({lat}, {lng})\n")
fallas = 0
for prov in clima.PROVEEDORES:
    print(f"{prov.ETIQUETA:<16}", end="")
    if not prov.configurado():
        print(f"SIN CONFIGURAR  -> defina {VARIABLE[prov.NOMBRE]} en diara/.env y reinicie el servidor"); continue
    try:
        a = prov.actual(lat, lng); d = prov.pronostico_dias(lat, lng, 3)
        temp = a.get("temp") if a else None
        print(f"OK  actual: {temp if temp is not None else '—'} °C · pronóstico: {len(d)} días · historial: {prov.HISTORIAL}")
    except ErrorClima as e:
        fallas += 1
        m = re.search(r"respondió (\d{3})", str(e))
        print(f"ERROR  {' '.join(str(e).split())[:180]}")  # en una línea: algunas APIs responden JSON con saltos
        if m and int(m.group(1)) in PISTAS: print(f"{'':16}Pista: {PISTAS[int(m.group(1))]}")
        elif "No se pudo consultar" in str(e): print(f"{'':16}Pista: sin conexión a internet, firewall o proxy bloqueando la salida.")
print("\nCon 2 o más fuentes con historial (Google, Open-Meteo, Meteoblue) el registro diario tiene confianza 'alta'.")
sys.exit(1 if fallas else 0)
