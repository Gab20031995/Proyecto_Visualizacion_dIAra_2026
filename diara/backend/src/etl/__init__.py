"""ETL de imágenes de obra: Google Drive -> catálogo de metadatos -> cruce con el clima histórico.

Es una zona de PREPARACIÓN (staging): sus tablas etl_* están separadas de las que usa la aplicación (imagenes,
clima_horas, clima_registro). Nada de lo que hace el ETL cambia el panel, las alertas ni los reportes; cuando el
modelo de IA esté listo, las fotos validadas se pasarán a la aplicación por la API de cámaras.

Pasos (cada uno se puede repetir sin duplicar datos; ver backend/etl_imagenes.py para la línea de comandos):
    1. listar     drive.recorrer()       -> catalogo.listar()       -> etl_imagenes   (metadatos desde el NOMBRE, sin descargar)
    2. descargar  drive.descargar()      -> catalogo.descargar()    -> data/etl/drive/... + tamaño, huella, brillo
    3. clima      Open-Meteo histórico   -> clima_historico.descargar() -> etl_clima_horas
    4. curar      curacion.evaluar()     -> apta_ia + motivo, y versión enderezada en data/etl/curadas/...
    5. cruce      etl_imagenes + etl_clima_horas -> cruce.generar() -> data/etl/<proyecto>/*.csv (control cruzado)
    6. hojas      curacion.hojas()       -> data/etl/<proyecto>/hojas/<día>.jpg (miniaturas para revisar a ojo)

Origen de cada foto (columna `origen`), según la carpeta de Drive donde está:
    camara     <raíz>/<AAAA-MM-DD>/IMG_CAM_01_AAAAMMDD_HHMMSS.jpg     cámara fija, desde el 17/04/2026
    historico  <raíz>/imagenes_tratadas/<AAAA-MM-DD>/IMG_HH-MM-SS.jpg  etapa anterior (sep. 2025 - abr. 2026); la
               fecha sale de la carpeta y la hora del nombre; trae fotos de instalación/prueba de la cámara
    otros      cualquier otra carpeta (p. ej. imagenes_tratadas/Pruebas): se cataloga, pero no se descarga ni se cruza

Los originales se guardan TAL CUAL vienen de Drive (de cabeza, en el caso de CAM_01). La curación escribe aparte una
versión enderezada y sin metadatos de las fotos aptas: es la que usará la IA. Así siempre se puede volver al original."""
import json
from contextlib import closing
from src import store

# Tablas del ETL. Se crean al primer uso (preparar()); no requieren migración de la base de la aplicación.
_ESQUEMA = """
-- Una fila por archivo de Drive (clave: id del archivo en Drive, estable aunque lo muevan o renombren)
CREATE TABLE IF NOT EXISTS etl_imagenes(drive_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, origen TEXT, ruta_drive TEXT,
  carpeta TEXT, archivo TEXT, camara TEXT, fecha TEXT, hora TEXT, tomada TEXT, nombre_valido INTEGER, observacion TEXT,
  ruta_local TEXT, bytes INTEGER, ancho INTEGER, alto INTEGER, sha256 TEXT, brillo REAL, duplicado_de TEXT, error TEXT,
  listado TEXT DEFAULT CURRENT_TIMESTAMP, visto TEXT DEFAULT CURRENT_TIMESTAMP, descargado TEXT);
-- Clima horario histórico (Open-Meteo, reanálisis ERA5). Hora local de Costa Rica; la lluvia de "17:00" es la de 16:00-17:00
CREATE TABLE IF NOT EXISTS etl_clima_horas(project_id TEXT, hora TEXT, fecha TEXT, lluvia_mm REAL, temp REAL, humedad REAL,
  nubosidad REAL, radiacion REAL, codigo INTEGER, condicion TEXT, fuente TEXT, actualizado TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(project_id, hora));
-- Bitácora: una fila por paso ejecutado, con su resultado en JSON
CREATE TABLE IF NOT EXISTS etl_ejecuciones(id INTEGER PRIMARY KEY AUTOINCREMENT, paso TEXT, project_id TEXT, ok INTEGER,
  resultado TEXT, duracion_s REAL, ejecutado TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_etl_img_fecha ON etl_imagenes(project_id, fecha);
CREATE INDEX IF NOT EXISTS ix_etl_img_sha ON etl_imagenes(sha256);
"""
_listo = False
# Columnas agregadas por la curación (src/etl/curacion.py); se suman a bases donde etl_imagenes ya existía
_COLUMNAS_CURACION = (("contraste", "REAL"), ("nitidez", "REAL"), ("apta_ia", "INTEGER"), ("motivo_ia", "TEXT"),
                      ("ruta_curada", "TEXT"), ("curada", "TEXT"))

def preparar():
    """Crea las tablas etl_* si no existen y agrega las columnas nuevas (una vez por proceso)."""
    global _listo
    if not _listo:
        with closing(store._c()) as c, c:
            c.executescript(_ESQUEMA)
            cols = [r[1] for r in c.execute("PRAGMA table_info(etl_imagenes)")]
            for col, tipo in _COLUMNAS_CURACION:
                if col not in cols: c.execute(f"ALTER TABLE etl_imagenes ADD COLUMN {col} {tipo}")
        _listo = True

def registrar(paso, pid, ok, resultado, duracion_s):
    """Guarda el resultado de un paso en etl_ejecuciones."""
    store._q("INSERT INTO etl_ejecuciones(paso,project_id,ok,resultado,duracion_s) VALUES(?,?,?,?,?)",
             (paso, pid, int(ok), json.dumps(resultado, ensure_ascii=False, default=str), round(duracion_s, 1)))
