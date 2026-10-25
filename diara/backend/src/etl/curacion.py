"""Curación de las fotos del ETL: decide cuáles sirven para la IA, las endereza y genera hojas de contacto para revisarlas.

Por qué hace falta (visto en las fotos de Limoncito, sep. 2025 - jul. 2026):
  - 11 y 12/09/2025: instalación, la cámara apunta a un monitor (se excluye a mano en config.ETL["excluir"]).
  - 22/09 al 28/10/2025: fotos quemadas, casi blancas (brillo ~254).
  - nov. 2025 a inicios de feb. 2026: lente empañado, todo se ve con neblina (nitidez <= 5).
  - desde el 11/02/2026 (12:27): imagen nítida, pero la cámara cambió de lugar (otro encuadre). En las carpetas por
    día CAM_01 llega de cabeza; en imagenes_tratadas ya viene enderezada.

Métricas (sobre una miniatura en gris de 400x300, para que no dependan del tamaño de la foto):
    contraste  desviación estándar del gris (0 = imagen plana, toda de un color)
    nitidez    promedio del filtro de bordes FIND_EDGES (cuánto detalle hay); separa muy bien empañadas/quemadas de nítidas
Reglas (motivo_ia; si hay al menos un BLOQUEO la foto queda apta_ia = 0). Umbrales en config.ETL:
    bloqueos  sin fecha · período excluido · duplicada · nocturna (radiación 0) · oscura · sobreexpuesta · borrosa/empañada
    avisos    lluvia durante la captura (la foto es apta: la IA debe aprender a ver con lluvia, pero conviene saberlo)
Versión curada (solo aptas): girada según la cámara (config.ETL["rotacion"]), lado mayor <= lado_max, JPEG sin
metadatos, en data/etl/curadas/<proyecto>/<día>/<archivo>. El original de Drive no se toca."""
import html
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat
from config import ETL, DATA_DIR
from src import store, etl

MINIATURA = (400, 300)  # tamaño fijo para medir: los umbrales de nitidez se calibraron con este tamaño

def medir(ruta):
    """Contraste y nitidez de una imagen (ver docstring del módulo)."""
    g = Image.open(ruta).convert("L"); g.thumbnail(MINIATURA)
    return round(ImageStat.Stat(g).stddev[0], 1), round(ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0], 1)

def decidir(f, contraste, nitidez, clima, excluir):
    """(apta, motivo) de una foto. `f` es la fila de etl_imagenes; `clima` = (radiación, lluvia) de su hora o None."""
    bloqueos, avisos = [], []
    if not f["tomada"]: bloqueos.append("sin fecha de captura")
    bloqueos += [motivo for desde, hasta, motivo in excluir if f["fecha"] and desde <= f["fecha"] <= hasta]
    if f["duplicado_de"]: bloqueos.append("duplicada")
    radiacion, lluvia = clima or (None, None)
    if radiacion == 0 or (radiacion is None and f["hora"] and not "05:30" <= f["hora"] <= "18:00"): bloqueos.append("nocturna")
    if f["brillo"] is not None and f["brillo"] < ETL["brillo_oscuro"]: bloqueos.append("oscura")
    if f["brillo"] is not None and f["brillo"] > ETL["brillo_quemado"]: bloqueos.append("sobreexpuesta")
    minimo = ETL["nitidez_min_obra"].get(f["project_id"], ETL["nitidez_min"])  # cámaras de menor resolución: umbral propio
    if nitidez < minimo and "sobreexpuesta" not in bloqueos: bloqueos.append("borrosa o lente empañado")
    if lluvia is not None and lluvia >= ETL["lluvia_hora_mm"]: avisos.append("aviso: lluvia durante la captura")
    return (0 if bloqueos else 1), ("; ".join(bloqueos + avisos) or None)

def _enderezada(f):
    """Imagen original girada según su cámara (lo que debe ver la IA). Solo se gira el origen 'camara': las fotos de
    imagenes_tratadas YA vienen enderezadas aunque desde feb. 2026 también se llamen IMG_CAM_01_... (girarlas las invertiría)."""
    im = Image.open(DATA_DIR / f["ruta_local"]).convert("RGB")
    # por cámara (CAM_01) y, si el nombre no trae cámara, por obra (config.ETL["rotacion_obra"])
    grados = (ETL["rotacion"].get(f["camara"] or "") or ETL["rotacion_obra"].get(f["project_id"], 0)) if f["origen"] == "camara" else 0
    return im.rotate(grados, expand=True) if grados else im

def _curar(pid, f, clima, excluir):
    """Mide, decide y (si es apta) escribe la versión curada. Devuelve los valores a guardar."""
    contraste, nitidez = medir(DATA_DIR / f["ruta_local"])
    apta, motivo = decidir(f, contraste, nitidez, clima, excluir)
    destino = ETL["dir"] / "curadas" / pid / f["fecha"] / f["archivo"] if f["fecha"] else None
    ruta = None
    if apta:
        im = _enderezada(f); im.thumbnail((ETL["lado_max"], ETL["lado_max"]))
        destino.parent.mkdir(parents=True, exist_ok=True); im.save(destino, "JPEG", quality=90)  # sin exif: no se copia
        ruta = destino.relative_to(DATA_DIR).as_posix()
    elif destino and destino.exists():
        destino.unlink()  # dejó de ser apta (p. ej. ahora es duplicada o cambió un umbral)
    return dict(contraste=contraste, nitidez=nitidez, apta=apta, motivo=motivo, ruta=ruta)

def evaluar(pid, rehacer=False, avance=None):
    """Paso 'curar': evalúa las fotos descargadas que aún no se curaron (todas con rehacer=True, p. ej. tras cambiar
    un umbral en config.ETL). Devuelve cuántas son aptas y el conteo de cada motivo."""
    etl.preparar()
    filas = store._filas("SELECT * FROM etl_imagenes WHERE project_id=? AND ruta_local IS NOT NULL AND origen<>'otros'"
                         + ("" if rehacer else " AND curada IS NULL"), (pid,))
    clima = {r["hora"]: (r["radiacion"], r["lluvia_mm"]) for r in store._filas(
        "SELECT hora, radiacion, lluvia_mm FROM etl_clima_horas WHERE project_id=?", (pid,))}
    excluir = ETL["excluir"].get(pid, [])
    def hora_clima(f):  # misma convención que cruce.py: la hora que contiene la foto (16:53 -> 17:00; 23:40 -> 00:00 del día siguiente)
        if not f["tomada"]: return None
        t = datetime.fromisoformat(f["tomada"]); h = t.replace(minute=0, second=0)
        return (h if h == t else h + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00")
    with ThreadPoolExecutor(ETL["hilos"]) as ex:
        resultados = ex.map(lambda f: (f, _curar(pid, f, clima.get(hora_clima(f)), excluir)), filas)
        valores = []
        for i, (f, r) in enumerate(resultados, 1):
            valores.append((r["contraste"], r["nitidez"], r["apta"], r["motivo"], r["ruta"], f["drive_id"]))
            if avance: avance(i, len(filas))
    with closing(store._c()) as c, c:
        c.executemany("UPDATE etl_imagenes SET contraste=?, nitidez=?, apta_ia=?, motivo_ia=?, ruta_curada=?, curada=CURRENT_TIMESTAMP WHERE drive_id=?", valores)
    return resumen(pid) | {"evaluadas_ahora": len(filas)}

def resumen(pid):
    """Aptas por origen y conteo de cada motivo de bloqueo o aviso (una foto puede tener varios)."""
    filas = store._filas("SELECT origen, apta_ia, motivo_ia FROM etl_imagenes WHERE project_id=? AND curada IS NOT NULL", (pid,))
    motivos = {}
    for f in filas:
        for mo in (f["motivo_ia"] or "").split("; "):
            if mo: motivos[mo] = motivos.get(mo, 0) + 1
    por_origen = {}
    for f in filas:
        o = por_origen.setdefault(f["origen"], {"evaluadas": 0, "aptas": 0}); o["evaluadas"] += 1; o["aptas"] += f["apta_ia"]
    return dict(por_origen=por_origen, motivos=dict(sorted(motivos.items(), key=lambda x: -x[1])))

# ---------- hojas de contacto ----------
CELDA, COLUMNAS = (200, 150), 8
COLOR = {"apta": (46, 160, 67), "aviso": (219, 160, 0), "no": (207, 34, 46)}

def _fuente(tam):
    """Arial (Windows) o DejaVu (Linux) para que salgan tildes y ñ; si no hay, la fuente básica de Pillow."""
    for nombre in ("arial.ttf", "DejaVuSans.ttf"):
        try: return ImageFont.truetype(nombre, tam)
        except OSError: pass
    try: return ImageFont.load_default(size=tam)  # Pillow >= 10.1
    except TypeError: return ImageFont.load_default()

def _hoja(pid, fecha, fotos, salida):
    """Una imagen con todas las fotos del día: borde verde = apta, amarillo = apta con aviso, rojo = no apta (con el motivo)."""
    filas = -(-len(fotos) // COLUMNAS); alto_txt = 34
    hoja = Image.new("RGB", (CELDA[0] * COLUMNAS, alto_txt + filas * (CELDA[1] + 18)), "white"); d = ImageDraw.Draw(hoja)
    aptas = sum(f["apta_ia"] or 0 for f in fotos)
    d.text((8, 8), f"{pid} · {fecha} · {len(fotos)} fotos · {aptas} aptas para IA", fill="black", font=_fuente(16))
    for i, f in enumerate(fotos):
        x, y = (i % COLUMNAS) * CELDA[0], alto_txt + (i // COLUMNAS) * (CELDA[1] + 18)
        im = _enderezada(f); im.thumbnail((CELDA[0] - 8, CELDA[1] - 8))
        tipo = "no" if not f["apta_ia"] else ("aviso" if f["motivo_ia"] else "apta")
        d.rectangle([x + 1, y + 1, x + CELDA[0] - 2, y + CELDA[1] - 2], outline=COLOR[tipo], width=4)
        hoja.paste(im, (x + 4, y + 4))
        texto = f["hora"][:5] + ("  " + f["motivo_ia"].replace("aviso: ", "")[:24] if f["motivo_ia"] else "")
        d.text((x + 4, y + CELDA[1]), texto, fill=COLOR[tipo] if tipo != "apta" else "black", font=_fuente(12))
    hoja.save(salida / f"{fecha}.jpg", quality=80)
    return aptas

def hojas(pid, desde=None, hasta=None):
    """Paso 'hojas': una hoja de contacto por día en data/etl/<proyecto>/hojas/ más un index.html para navegarlas."""
    etl.preparar()
    salida = ETL["dir"] / pid / "hojas"; salida.mkdir(parents=True, exist_ok=True)
    sql, args = "SELECT * FROM etl_imagenes WHERE project_id=? AND ruta_local IS NOT NULL AND origen<>'otros' AND fecha IS NOT NULL", [pid]
    if desde: sql += " AND fecha>=?"; args.append(desde)
    if hasta: sql += " AND fecha<=?"; args.append(hasta)
    por_dia = {}
    for f in store._filas(sql + " ORDER BY fecha, hora", args): por_dia.setdefault(f["fecha"], []).append(f)
    with ThreadPoolExecutor(ETL["hilos"]) as ex:
        aptas = dict(zip(por_dia, ex.map(lambda k: _hoja(pid, k, por_dia[k], salida), por_dia)))
    # Índice: tabla de días con enlace a su hoja (se regenera completo con todos los días que tienen hoja)
    dias = sorted(p.stem for p in salida.glob("*.jpg"))
    totales = {r["fecha"]: r for r in store._filas("""SELECT fecha, count(*) n, sum(apta_ia) a, group_concat(DISTINCT origen) o
        FROM etl_imagenes WHERE project_id=? AND ruta_local IS NOT NULL GROUP BY fecha""", (pid,))}
    filas = "".join(f"<tr><td><a href='{d}.jpg'>{d}</a></td><td>{html.escape(totales.get(d, {}).get('o') or '')}</td>"
                    f"<td>{totales.get(d, {}).get('n', 0)}</td><td>{totales.get(d, {}).get('a') or 0}</td></tr>" for d in dias)
    (salida / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Hojas de contacto " + pid + "</title>"
        "<style>body{font:14px system-ui;margin:24px}td,th{padding:3px 10px;text-align:left}</style>"
        f"<h1>{pid} · hojas de contacto</h1><p>Borde verde: apta para IA · amarillo: apta con aviso · rojo: no apta.</p>"
        "<table><tr><th>Día</th><th>Origen</th><th>Fotos</th><th>Aptas</th></tr>" + filas + "</table>", encoding="utf-8")
    return dict(carpeta=str(salida), hojas=len(aptas), indice=str(salida / "index.html"))
