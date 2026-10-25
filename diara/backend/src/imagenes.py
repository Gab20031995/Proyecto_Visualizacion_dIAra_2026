"""Imágenes de cámara por obra: las recibidas por la API de cámaras (tabla `imagenes`) y las sintéticas
(data/obras/<id>/camara/indice.csv). Los archivos viven en data/obras/<id>/camara/.
Las fotos reales publicadas desde el ETL (src/etl/publicar.py) también van a la tabla `imagenes`, con fuente='etl'.

listar() mezcla ambas fuentes para que el panel no distinga de dónde vienen. Las imágenes recibidas por API
llegan sin análisis de IA (personas/maquinaria/confianza en None) salvo que la cámara los envíe.
Las imágenes se sirven por routes/auditor.py (/camara/{pid}/{archivo}), que exige sesión y acceso al proyecto.

Sitio público: solo se publica la ÚLTIMA foto de cada obra (publica()) y el time-lapse del ÚLTIMO día con fotos
(timelapse()), siempre en su VERSIÓN PÚBLICA, nunca la del auditor:
    - sintéticas: la escena sin los recuadros de detección (make_data.py la guarda en camara/publica/)
    - recibidas por la API: se reduce a 960 px y se vuelve a codificar, lo que elimina los metadatos (EXIF, GPS);
      se guarda en camara/publica/ la primera vez que se pide
Así la ciudadanía (y la empresa fiscalizada) ve la obra, pero no lo que la IA está detectando.
Pendiente antes de producción: difuminar rostros y placas en las fotos reales."""
import io
from datetime import datetime
import pandas as pd
from PIL import Image
from src import store, proyectos

MAX_BYTES = 10_000_000
COLS = ["archivo", "fecha", "hora", "personas", "maquinaria", "confianza"]

class ErrorImagen(Exception):
    """Imagen rechazada; el mensaje se devuelve a la cámara como HTTP 400."""
    pass

def listar(pid, n=12, fecha=None):
    """Últimas n imágenes de la obra (más recientes primero), con la URL para mostrarlas.
    Con `fecha` (AAAA-MM-DD): todas las de ese día (hasta n), en orden de hora, para el detalle del calendario."""
    partes = []
    f = proyectos.carpeta(pid) / "camara" / "indice.csv"
    if f.exists(): partes.append(pd.read_csv(f).assign(origen="sintética"))
    sql, args = "SELECT archivo, fecha, hora, personas, maquinaria, confianza FROM imagenes WHERE project_id=?", [pid]
    if fecha: sql += " AND fecha=?"; args.append(fecha)
    db = store._df(sql, args)
    if len(db): partes.append(db.assign(origen="cámara"))
    if not partes: return []
    d = pd.concat(partes)
    if fecha: d = d[d.fecha.astype(str) == fecha].sort_values("hora").head(n).astype(object)
    else: d = d.sort_values(["fecha", "hora"], ascending=False).head(n).astype(object)
    d = d.where(d.notna(), None)  # sin análisis de IA todavía: personas/maquinaria/confianza en None
    return [dict(r, url=f"/camara/{pid}/{r['archivo']}") for r in d.to_dict("records")]

def ultima(pid):
    """Última imagen (para la miniatura de las tarjetas y el PDF), o None."""
    l = listar(pid, 1)
    return dict(url=l[0]["url"], fecha=str(l[0]["fecha"]), hora=str(l[0]["hora"])) if l else None

def _version_publica(pid, im):
    """Ruta de la versión pública de una foto (la crea la primera vez), o None si no se puede publicar."""
    cam = proyectos.carpeta(pid) / "camara"; destino = cam / "publica" / im["archivo"]
    if not destino.exists():
        if im["origen"] == "sintética": return None  # sin versión limpia (datos generados antes de este cambio)
        try:
            with Image.open(cam / im["archivo"]) as f:
                f = f.convert("RGB"); f.thumbnail((960, 960))  # reduce y descarta EXIF al volver a guardar
                destino.parent.mkdir(exist_ok=True); f.save(destino, "JPEG", quality=80)
        except Exception: return None  # archivo dañado o inexistente: no se publica
    return destino

def publica(pid):
    """(ruta del archivo de la versión pública de la última foto, datos de la foto) o (None, None) si no hay versión publicable."""
    l = listar(pid, 1)
    if not l: return None, None
    destino = _version_publica(pid, l[0])
    return (destino, dict(fecha=str(l[0]["fecha"]), hora=str(l[0]["hora"]))) if destino else (None, None)

MAX_TIMELAPSE = 48  # cuadros como máximo (si el día tiene más fotos se toman repartidas en la jornada)
MIN_TIMELAPSE = 6   # fotos mínimas para que un día sirva de time-lapse (Ticabán: su último día tiene 1 sola foto apta)

def timelapse(pid):
    """Time-lapse público: las fotos de UN día (el más reciente con al menos MIN_TIMELAPSE fotos; si ninguno llega,
    el último con fotos), en versión pública y en orden de hora. Devuelve {fecha, fotos: [{archivo, hora, ruta}]} o
    None. Solo ese día: el resto del historial es parte del expediente de auditoría y no se publica
    (routes/publico.py valida que se pida un archivo de esta lista)."""
    recientes = listar(pid, 200)  # ~ últimos días; alcanza para encontrar uno con suficientes fotos
    if not recientes: return None
    por_dia = {}
    for im in recientes: por_dia[str(im["fecha"])] = por_dia.get(str(im["fecha"]), 0) + 1
    fecha = next((f for f in sorted(por_dia, reverse=True) if por_dia[f] >= MIN_TIMELAPSE), str(recientes[0]["fecha"]))
    ims = listar(pid, 200, fecha)
    if len(ims) > MAX_TIMELAPSE:  # repartidas: primera, última y las intermedias a intervalos iguales
        ims = [ims[round(i * (len(ims) - 1) / (MAX_TIMELAPSE - 1))] for i in range(MAX_TIMELAPSE)]
    fotos = [dict(archivo=im["archivo"], hora=str(im["hora"]), ruta=r) for im in ims if (r := _version_publica(pid, im))]
    return dict(fecha=fecha, fotos=fotos) if fotos else None

def guardar(pid, datos: bytes, tomada=None, personas=None, maquinaria=None, confianza=None):
    """Valida y guarda una imagen recibida de la cámara. Devuelve el registro creado."""
    if len(datos) > MAX_BYTES: raise ErrorImagen("La imagen supera 10 MB")
    # verify() valida la estructura del archivo; después hay que reabrirlo para leer el formato (verify lo deja inutilizable)
    try:
        im = Image.open(io.BytesIO(datos)); im.verify()
        formato = Image.open(io.BytesIO(datos)).format
    except Exception: raise ErrorImagen("El archivo no es una imagen válida") from None
    if formato not in ("JPEG", "PNG"): raise ErrorImagen("Formato no admitido (use JPEG o PNG)")
    # "tomada" es la hora de la captura según la cámara; si no viene, se usa la hora de recepción del servidor
    try: t = datetime.fromisoformat(tomada) if tomada else datetime.now()
    except ValueError: raise ErrorImagen("tomada debe ser fecha y hora ISO 8601, ej. 2026-10-24T14:30:00") from None
    if confianza is not None and not 0 <= confianza <= 1: raise ErrorImagen("confianza debe estar entre 0 y 1")
    base = proyectos.carpeta(pid) / "camara"; base.mkdir(parents=True, exist_ok=True)
    # El nombre lo genera el servidor (fecha y hora), nunca el que envía la cámara: evita rutas maliciosas
    raiz, ext = f"{t:%Y-%m-%d_%H%M%S}", "jpg" if formato == "JPEG" else "png"
    nombre, i = f"{raiz}.{ext}", 1
    while (base / nombre).exists(): nombre = f"{raiz}-{i}.{ext}"; i += 1  # varias fotos en el mismo segundo
    (base / nombre).write_bytes(datos)
    reg = dict(archivo=nombre, fecha=f"{t:%Y-%m-%d}", hora=f"{t:%H:%M}", tomada=t.isoformat(timespec="seconds"),
               personas=personas, maquinaria=maquinaria, confianza=confianza)
    store._q("INSERT INTO imagenes(project_id,archivo,fecha,hora,tomada,personas,maquinaria,confianza) VALUES(?,?,?,?,?,?,?,?)",
             (pid, *reg.values()))
    return reg
