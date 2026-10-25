"""Catálogo de imágenes del ETL (tabla etl_imagenes): metadatos desde el nombre, descarga y métricas de cada foto.

Metadatos desde el NOMBRE del archivo (no hace falta descargar; las fotos no traen EXIF):
    IMG_CAM_01_20260630_165347.jpg   -> cámara CAM_01, fecha 2026-06-30, hora 16:53:47 (hora de Costa Rica)
    20260210-132429.jpg              -> sin cámara en el nombre; fecha 2026-02-10, hora 13:24:29 (histórico)
    IMG_07-55-26.jpg                 -> sin cámara en el nombre; hora 07:55:26 y fecha de la carpeta (2025-09-11)
Carpetas por día: "AAAA-MM-DD" o "AAAAMMDD" (la fecha se guarda siempre como AAAA-MM-DD; `carpeta` conserva el nombre real).
Validaciones (quedan en `nombre_valido` y `observacion`, nunca se descarta una foto en silencio):
    - nombre que no sigue ninguno de los dos formatos
    - fecha del nombre distinta a la de la carpeta (foto guardada en el día equivocado)
Al descargar se agregan: tamaño, ancho x alto, huella SHA-256 (detecta la misma foto subida dos veces, aunque tenga
otro nombre) y brillo medio 0-255 (sirve para el cruce con el clima: foto oscura en pleno día = lente tapado o falla)."""
import csv, hashlib, io, re
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from PIL import Image, ImageStat
from config import ETL, DATA_DIR
from src import store, etl
from src.etl import drive

NOMBRE_CAMARA = re.compile(r"^IMG_(CAM_\d+)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.jpe?g$", re.I)
NOMBRE_FECHA_HORA = re.compile(r"^()(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\.jpe?g$", re.I)  # sin cámara (grupo 1 vacío)
NOMBRE_HISTORICO = re.compile(r"^IMG_(\d{2})-(\d{2})-(\d{2})\.jpe?g$", re.I)
CARPETA_DIA = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})$")  # "2026-06-30" (Limoncito) o "20260417" (Puente, Ticabán)
HISTORICO = "imagenes_tratadas"  # carpeta de Drive con la etapa anterior de la cámara
ORIGENES = ("camara", "historico", "otros")

def interpretar(nombre, ruta):
    """Metadatos de un archivo a partir de su nombre y de la ruta de carpetas. Devuelve un dict con las columnas
    origen, carpeta, camara, fecha, hora, tomada (AAAA-MM-DDTHH:MM:SS), nombre_valido y observacion."""
    carpeta = ruta[-1] if ruta else ""
    dia = "-".join(c.groups()) if (c := CARPETA_DIA.match(carpeta)) else None  # siempre AAAA-MM-DD
    if len(ruta) == 1 and dia: origen = "camara"
    elif len(ruta) == 2 and ruta[0] == HISTORICO and dia: origen = "historico"
    else: origen = "otros"
    m = dict(origen=origen, carpeta=carpeta, camara=None, fecha=dia, hora=None, tomada=None, nombre_valido=0, observacion=None)
    # "IMG_09-25-34 (1).jpg": copia que Drive o Windows renombró; se interpreta sin el sufijo y se avisa (la huella dirá si es duplicada)
    base = re.sub(r" \(\d+\)(?=\.\w+$)", "", nombre)
    copia = "Posible copia (sufijo en el nombre). " if base != nombre else ""
    nombre = base
    if (r := NOMBRE_CAMARA.match(nombre) or NOMBRE_FECHA_HORA.match(nombre)):
        cam, a, me, d, h, mi, s = r.groups()
        m.update(camara=cam.upper() or None, fecha=f"{a}-{me}-{d}", hora=f"{h}:{mi}:{s}", nombre_valido=1)
        if dia and dia != m["fecha"]: m["observacion"] = f"La fecha del nombre ({m['fecha']}) no coincide con la carpeta ({dia})"
    elif (r := NOMBRE_HISTORICO.match(nombre)):
        m.update(hora=":".join(r.groups()), nombre_valido=1 if dia else 0)
        m["observacion"] = "Fecha tomada de la carpeta (el nombre solo trae la hora)" if dia else "Sin fecha: el nombre solo trae la hora y la carpeta no es un día"
    else:
        m["observacion"] = "Nombre con formato desconocido: no se puede saber cuándo se tomó"
    if m["fecha"] and m["hora"]:
        try: datetime.strptime(f"{m['fecha']} {m['hora']}", "%Y-%m-%d %H:%M:%S"); m["tomada"] = f"{m['fecha']}T{m['hora']}"
        except ValueError: m.update(nombre_valido=0, observacion="Fecha u hora imposible en el nombre")
    if copia: m["observacion"] = (copia + (m["observacion"] or "")).strip()
    return m

_SQL_UPSERT = """INSERT INTO etl_imagenes(drive_id,project_id,origen,ruta_drive,carpeta,archivo,camara,fecha,hora,tomada,nombre_valido,observacion,visto)
  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
  ON CONFLICT(drive_id) DO UPDATE SET origen=excluded.origen, ruta_drive=excluded.ruta_drive, carpeta=excluded.carpeta,
  archivo=excluded.archivo, camara=excluded.camara, fecha=excluded.fecha, hora=excluded.hora, tomada=excluded.tomada,
  nombre_valido=excluded.nombre_valido, observacion=excluded.observacion, visto=excluded.visto"""

def listar(pid, carpeta_id, hilos=None):
    """Paso 1: recorre Drive y actualiza el catálogo (sin descargar). Conserva lo ya descargado de cada foto.
    Devuelve totales por origen, nuevas, con problemas de nombre, las que ya no están en Drive y el control.csv."""
    etl.preparar()
    lote = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")  # marca de esta pasada (columna visto)
    previas = {r["drive_id"] for r in store._filas("SELECT drive_id FROM etl_imagenes WHERE project_id=?", (pid,))}
    archivos = drive.recorrer(carpeta_id, hilos or ETL["hilos"])
    filas, otros_archivos, control = [], [], None
    for a in archivos:
        if not re.search(r"\.(jpe?g|png)$", a["nombre"], re.I):  # control.csv u otros documentos: no son fotos
            otros_archivos.append("/".join(a["ruta"] + (a["nombre"],)))
            if a["nombre"].lower() == "control.csv" and not a["ruta"]: control = a["id"]
            continue
        m = interpretar(a["nombre"], a["ruta"])
        filas.append((a["id"], pid, m["origen"], "/".join(a["ruta"]), m["carpeta"], a["nombre"], m["camara"], m["fecha"],
                      m["hora"], m["tomada"], m["nombre_valido"], m["observacion"], lote))
    with closing(store._c()) as c, c: c.executemany(_SQL_UPSERT, filas)
    por_origen = {o: sum(1 for f in filas if f[2] == o) for o in ORIGENES}
    ausentes = store._filas("SELECT count(*) n FROM etl_imagenes WHERE project_id=? AND visto<>?", (pid, lote))[0]["n"]
    return dict(fotos=len(filas), por_origen=por_origen, nuevas=sum(1 for f in filas if f[0] not in previas),
                nombre_invalido=sum(1 for f in filas if not f[10]),
                fecha_distinta_carpeta=sum(1 for f in filas if f[11] and "no coincide" in f[11]),
                ya_no_estan_en_drive=ausentes, otros_archivos=otros_archivos,
                control_csv=_verificar_control(pid, control) if control else None)

def _verificar_control(pid, archivo_id):
    """Compara el control.csv de la carpeta raíz (bitácora del proceso que llenó imagenes_tratadas) con lo que hay
    en Drive: detecta fotos registradas que no aparecen y fotos en Drive que no están en la bitácora."""
    texto = drive.descargar(archivo_id).decode("utf-8-sig", "replace")
    # new_filename trae la ruta completa en Colab: .../imagenes_tratadas/<día>/<archivo>; interesan las dos últimas partes
    registradas = {tuple(r["new_filename"].replace("\\", "/").split("/")[-2:]) for r in csv.DictReader(io.StringIO(texto)) if r.get("new_filename")}
    en_drive = {(r["carpeta"], r["archivo"]) for r in store._filas(
        "SELECT carpeta, archivo FROM etl_imagenes WHERE project_id=? AND origen='historico'", (pid,))}
    faltan = sorted(registradas - en_drive)
    return dict(registradas=len(registradas), en_drive_historico=len(en_drive), coinciden=len(registradas & en_drive),
                registradas_no_encontradas=len(faltan), ejemplo_no_encontradas=["/".join(x) for x in faltan[:5]],
                en_drive_sin_registro=len(en_drive - registradas))

def metricas(datos):
    """Tamaño, dimensiones, huella y brillo medio de una imagen. Lanza ValueError si el archivo está dañado."""
    try:
        im = Image.open(io.BytesIO(datos)); im.load()
    except Exception as e:
        raise ValueError(f"Imagen dañada o con formato no soportado: {e}") from None
    gris = im.convert("L"); gris.thumbnail((160, 120))  # una miniatura basta para el brillo y es mucho más rápida
    return dict(bytes=len(datos), ancho=im.width, alto=im.height, sha256=hashlib.sha256(datos).hexdigest(),
                brillo=round(ImageStat.Stat(gris).mean[0], 1))

def _destino(pid, f):
    """data/etl/drive/<proyecto>/<origen>/<día>/<archivo> (el original de Drive, sin modificar)."""
    return ETL["dir"] / "drive" / pid / f["origen"] / (f["carpeta"] or "sin_carpeta") / f["archivo"]

def _bajar(pid, f):
    """Descarga una foto, calcula sus métricas y la guarda (escritura atómica: .part y luego renombrar)."""
    datos = drive.descargar(f["drive_id"]); m = metricas(datos)
    ruta = _destino(pid, f); ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".part"); tmp.write_bytes(datos); tmp.replace(ruta)
    return {**m, "ruta_local": ruta.relative_to(DATA_DIR).as_posix()}

def descargar(pid, origenes=("camara",), desde=None, hasta=None, limite=None, hilos=None, avance=None):
    """Paso 2: descarga las fotos del catálogo que aún no se bajaron (o que fallaron), en paralelo.
    Filtros: origen, rango de fechas y cantidad máxima. `avance(hechas, total)` permite mostrar el progreso."""
    etl.preparar()
    sql = f"SELECT * FROM etl_imagenes WHERE project_id=? AND descargado IS NULL AND origen IN ({','.join('?' * len(origenes))})"
    args = [pid, *origenes]
    if desde: sql += " AND fecha>=?"; args.append(desde)
    if hasta: sql += " AND fecha<=?"; args.append(hasta)
    sql += " ORDER BY fecha, hora" + (" LIMIT ?" if limite else "")
    pendientes = store._filas(sql, args + ([limite] if limite else []))
    ok = errores = 0; total_bytes = 0
    with ThreadPoolExecutor(hilos or ETL["hilos"]) as ex:
        tareas = {ex.submit(_bajar, pid, f): f for f in pendientes}
        for i, t in enumerate(as_completed(tareas), 1):
            f = tareas[t]
            try:
                m = t.result(); ok += 1; total_bytes += m["bytes"]
                store._q("""UPDATE etl_imagenes SET ruta_local=?, bytes=?, ancho=?, alto=?, sha256=?, brillo=?, error=NULL,
                            descargado=CURRENT_TIMESTAMP WHERE drive_id=?""",
                         (m["ruta_local"], m["bytes"], m["ancho"], m["alto"], m["sha256"], m["brillo"], f["drive_id"]))
            except (drive.ErrorDrive, ValueError, OSError) as e:  # se anota y se reintenta en la próxima ejecución
                errores += 1; store._q("UPDATE etl_imagenes SET error=? WHERE drive_id=?", (str(e)[:300], f["drive_id"]))
            if avance: avance(i, len(pendientes))
    return dict(pendientes=len(pendientes), descargadas=ok, errores=errores, mb=round(total_bytes / 1e6, 1),
                duplicadas=marcar_duplicados(pid))

def inicio_ventana(pid):
    """Primer día a descargar en obras con ventana (config.ETL["ventana_dias"]): N días hacia atrás desde la foto más
    reciente de la cámara. None si la obra no tiene ventana (se baja todo)."""
    dias = ETL.get("ventana_dias", {}).get(pid)
    if not dias: return None
    ult = store._filas("SELECT max(fecha) f FROM etl_imagenes WHERE project_id=? AND origen='camara'", (pid,))[0]["f"]
    return (date.fromisoformat(ult) - timedelta(days=dias - 1)).isoformat() if ult else None

def marcar_duplicados(pid):
    """Misma huella = misma foto. La primera (por fecha y hora) queda como original; las demás apuntan a ella."""
    store._q("UPDATE etl_imagenes SET duplicado_de=NULL WHERE project_id=?", (pid,))
    store._q("""UPDATE etl_imagenes AS e SET duplicado_de=(
                  SELECT o.drive_id FROM etl_imagenes o WHERE o.sha256=e.sha256 AND o.project_id=e.project_id
                  ORDER BY o.fecha, o.hora, o.drive_id LIMIT 1)
                WHERE e.project_id=? AND e.sha256 IS NOT NULL""", (pid,))
    store._q("UPDATE etl_imagenes SET duplicado_de=NULL WHERE project_id=? AND duplicado_de=drive_id", (pid,))
    return store._filas("SELECT count(*) n FROM etl_imagenes WHERE project_id=? AND duplicado_de IS NOT NULL", (pid,))[0]["n"]

def estado(pid):
    """Resumen del catálogo por origen: fotos, rango de fechas, descargadas, con error y duplicadas."""
    etl.preparar()
    return store._filas("""SELECT origen, count(*) fotos, min(fecha) desde, max(fecha) hasta, count(DISTINCT fecha) dias,
        sum(descargado IS NOT NULL) descargadas, sum(error IS NOT NULL AND descargado IS NULL) con_error,
        sum(duplicado_de IS NOT NULL) duplicadas, sum(nombre_valido=0) nombre_invalido, round(sum(bytes)/1e6,1) mb
        FROM etl_imagenes WHERE project_id=? GROUP BY origen ORDER BY origen""", (pid,))
