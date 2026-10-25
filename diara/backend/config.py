"""Configuración central de dIAra.

Todo valor sensible (claves de API, contraseñas, SMTP) se lee de VARIABLES DE ENTORNO; nunca se escribe en el código.
Los valores por defecto permiten correr el MVP en local sin configurar nada.

Configuración que se cambia desde la interfaz (no aquí): el calendario de reportes y la plantilla del PDF se guardan
en la tabla `configuracion` (ver src/reporteria.py); los valores de REPORTES son solo los de fábrica."""
import os
from pathlib import Path

# Umbrales de las alertas automáticas (src/alerts.py) y del resumen de la IA (src/metrics.py).
UMBRALES = {"dias_sin_maquinaria": 3,   # A-01: días seguidos sin maquinaria con clima apto
            "confianza_min": 0.60,      # A-02: confianza mínima aceptable de una detección de la IA
            "brecha_pts": -10,          # A-03: brecha (observado - previsto) a partir de la cual se alerta
            "tiempo_muerto_h": 1.5,     # A-04: horas de maquinaria encendida sin operar
            # Cruce con lo que carga la empresa ejecutora (src/contratista.py, alertas C-01..C-05)
            "reportado_vs_ia_pts": 5,   # C-01: avance reportado en la bitácora por encima del observado por la IA
            "financiero_vs_fisico_pts": 10,  # C-02: % del presupuesto ejecutado por encima del avance físico observado
            "dias_sin_bitacora": 3}     # C-05: días con actividad registrada por la cámara sin bitácora (últimos 7)

# Rutas absolutas: los comandos funcionan desde cualquier carpeta.
ROOT = Path(__file__).resolve().parent.parent   # carpeta diara/
DATA_DIR = ROOT / "data"
OBRAS_DIR = DATA_DIR / "obras"          # data/obras/<project_id>/diario.csv y camara/
UPLOADS_DIR = DATA_DIR / "uploads"      # fotos de aportes ciudadanos
DB_PATH = DATA_DIR / "diara.db"         # base SQLite (se crea sola; esquema en src/store.py)
FRONTEND_DIR = ROOT / "frontend"

def _cargar_env(ruta):
    """Lee el archivo diara/.env (si existe) y define sus variables de entorno, para no tener que escribirlas en cada
    consola. Formato: una línea CLAVE=valor; las líneas vacías o que empiezan con # se ignoran; comillas opcionales.
    Una variable ya definida en el sistema o en la consola TIENE PRIORIDAD sobre el archivo (setdefault).
    El .env guarda claves: no se comparte ni se sube a repositorios (plantilla sin claves: .env.ejemplo)."""
    if not ruta.exists(): return
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea: continue
        clave, _, valor = linea.partition("=")
        valor = valor.strip().strip('"').strip("'")
        if valor: os.environ.setdefault(clave.strip(), valor)  # vacío = no definida (se usa el valor por defecto)

_cargar_env(ROOT / ".env")  # debe ir antes de leer cualquier variable de entorno (más abajo)

# Usuarios iniciales (se crean solo si la base no tiene usuarios). En producción definirlos como secretos.
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@cgr.go.cr")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin")
AUDITOR_DEMO = ("Ana Mora", "ana@cgr.go.cr", os.environ.get("AUDITOR_PASS", "demo"), ["P-001"])  # nombre, correo, clave, proyectos

SECRET_KEY = os.environ.get("SECRET_KEY", "")  # firma de las cookies; vacío: se genera uno al arrancar (las sesiones caducan al reiniciar)
SESION_HORAS = 8

# ---------- Clima: varias fuentes consolidadas ----------
# Las claves se leen SOLO de variables de entorno; nunca escribirlas en el código.
# Las *_URL se pueden cambiar para apuntar a servidores de prueba (así se probaron las fuentes sin clave real).
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")          # Google Weather (de pago)
GOOGLE_WEATHER_URL = os.environ.get("GOOGLE_WEATHER_URL", "https://weather.googleapis.com/v1")
OPEN_METEO_ACTIVO = os.environ.get("OPEN_METEO_ACTIVO", "1") == "1"      # Open-Meteo no requiere clave (uso no comercial)
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")            # solo para el plan comercial
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://customer-api.open-meteo.com/v1/forecast" if OPEN_METEO_API_KEY
                                else "https://api.open-meteo.com/v1/forecast")
METEOBLUE_API_KEY = os.environ.get("METEOBLUE_API_KEY", "")              # Meteoblue Free Weather API (no comercial)
METEOBLUE_URL = os.environ.get("METEOBLUE_URL", "https://my.meteoblue.com")
METEOSOURCE_API_KEY = os.environ.get("METEOSOURCE_API_KEY", "")          # Meteosource plan gratuito
METEOSOURCE_URL = os.environ.get("METEOSOURCE_URL", "https://www.meteosource.com/api/v1/free")
CLIMA = {"lluvia_no_apto_mm": 5.0,      # día no apto para trabajar si llueve esto o más (misma regla que los datos sintéticos)
         "discrepancia_mm": 5.0,        # diferencia de lluvia entre fuentes que se marca para revisión
         "horas_dia_completo": 20,      # horas observadas de una fuente para considerar el día completo
         "pronostico_dias": 10,
         "dias_historial": 7,           # días hacia atrás que se piden a Open-Meteo en cada actualización (máx. 92)
         "dias_recalculo": 120}         # días del registro consolidado que se recalculan en cada actualización

# ---------- Reportería automática por correo ----------
# Valores de fábrica: Administración → Reportes los puede cambiar (se guardan en la tabla `configuracion`).
REPORTES = {"dia_semanal": 0,             # 0 = lunes ... 6 = domingo (día de envío del resumen semanal)
            "dias_quincenal": (1, 16),    # días del mes en que se envía el resumen quincenal
            "hora": 6,                    # hora de Costa Rica a partir de la cual se envían los reportes del día
            "dir": DATA_DIR / "reportes"} # copia de cada PDF generado (auditoría de envíos)
APP_URL = os.environ.get("APP_URL", "http://localhost:8000")   # enlace al panel dentro del correo

# ---------- ETL de imágenes desde Google Drive (src/etl, backend/etl_imagenes.py) ----------
# Carpeta pública de Drive de cada obra (el id es la parte final del enlace .../drive/folders/<id>). No es un secreto,
# pero cualquiera con el id ve las fotos: cuando termine la carga conviene dejar la carpeta como "Restringida".
ETL = {"carpetas": {"P-001": os.environ.get("ETL_DRIVE_P001", "1w6fWxTcVRGztNyb7f1TNcPwR2iOijZTr"),   # Escuela Limoncito
                    "P-004": os.environ.get("ETL_DRIVE_P004", "1exZiyEb-kjdiXqWap2Cnwkv1h2Y09vlY"),   # Puente María Aguilar
                    "P-005": os.environ.get("ETL_DRIVE_P005", "1R_QU1kNdG6ph0yJvM9_PftHGAm2C1ufR")},  # Liceo Ticabán
       # Obras de las que solo se trae el ÚLTIMO período con datos (días hacia atrás desde la foto más reciente de la
       # cámara): el Puente tiene ~41 000 fotos (una cada 5 min). Se aplica en "descargar" si no se indica --desde.
       "ventana_dias": {"P-004": 31, "P-005": 31},
       "dir": DATA_DIR / "etl",          # data/etl/drive/<proyecto>/<origen>/<día>/<archivo> (originales, sin tocar) y los CSV
       "hilos": 8,                       # descargas simultáneas (más de ~10 hace que Drive responda 429)
       "brillo_oscuro": 35,              # brillo medio (0-255) por debajo del cual una foto se considera oscura
       "radiacion_dia": 150,             # W/m² de radiación solar a partir de los cuales "debería verse"
       "lluvia_hora_mm": 0.5,            # lluvia en la hora de la foto a partir de la cual se marca "lluvia durante la captura"
       "hueco_min": 60,                  # minutos sin fotos (entre la primera y la última del día) que se reportan
       # --- curación (src/etl/curacion.py): qué fotos sirven para la IA. Umbrales medidos en las fotos de Limoncito:
       #     nitidez de fotos quemadas o con lente empañado <= 5.4; fotos nítidas >= 11 ---
       "brillo_quemado": 235,            # brillo medio por encima del cual la foto está sobreexpuesta (casi blanca)
       "nitidez_min": 8,                 # borde medio (0-255) mínimo; por debajo: borrosa, empañada o sin detalle
       # Por obra cuando la cámara es distinta: Ticabán (640x480) da ~5-7 en fotos de día buenas
       "nitidez_min_obra": {"P-005": 4.5},
       "rotacion": {"CAM_01": 180},      # grados a girar por cámara (CAM_01 está montada de cabeza); solo origen "camara":
                                         # imagenes_tratadas ya viene enderezada
       "rotacion_obra": {"P-004": 180},  # para cámaras sin código en el nombre del archivo (Puente: llegan de cabeza)
       "lado_max": 1600,                 # lado mayor de la versión curada (las de la cámara ya miden 1600x1200)
       # Períodos que se excluyen a mano, por obra: (desde, hasta, motivo). Las fechas incluyen ambos extremos.
       "excluir": {"P-001": [("2025-09-11", "2025-09-12", "Instalación y pruebas de la cámara (apunta a un monitor)")]}}

# ---------- IA: actividad en obra (src/ia, backend/ia_actividad.py) ----------
# Requiere las dependencias de requirements-ia.txt (PyTorch + Ultralytics); el servidor web NO las necesita.
IA = {"modelo": DATA_DIR / "ia" / "modelos" / "yolo11s.pt",  # YOLO11-s preentrenado en COCO (se descarga solo si falta)
      "imgsz": 1280,                    # resolución de inferencia: las personas en estas fotos miden 20-60 px
      "confianza": 0.25,                # puntaje mínimo de una detección
      "clases": {0: "persona", 2: "vehiculo", 5: "vehiculo", 7: "vehiculo"},  # COCO: person, car, bus, truck
      "jornada": ("07:00", "17:00"),    # horario laboral para los promedios diarios y la lluvia "de jornada"
      "cambio_umbral": 20,              # diferencia de gris (0-255) para contar un píxel como "cambiado" entre fotos
      "cambio_hueco_min": 60,           # solo se comparan fotos consecutivas separadas por hasta estos minutos
      "muestras_por_dia": 3}            # fotos anotadas con cajas que se guardan por día (para revisar a ojo)
# Programador interno (src/programador.py): con el servidor encendido revisa cada 10 min y envía lo que toca.
# 0 = apagado (entonces hay que programar backend/enviar_reportes.py en el sistema operativo).
REPORTES_AUTOMATICOS = os.environ.get("REPORTES_AUTOMATICOS", "1") == "1"
# Servidor de correo. Sin SMTP_HOST los reportes se generan y guardan en modo "simulado" (no se envían).
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "dIAra <no-responder@cgr.go.cr>")
SMTP_SEGURIDAD = os.environ.get("SMTP_SEGURIDAD", "starttls")   # starttls | ssl | ninguna
