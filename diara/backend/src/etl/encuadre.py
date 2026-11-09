"""Detección de cambios de encuadre de la cámara (ítem EDA-02 del backlog, docs/backlog_mejoras.md).

Responde a la pregunta de la CGR "¿la cámara se movió, la giraron o la cambiaron?". Es la base de la futura alerta
S-03 (ALE-03). Adapta el notebook del profesor "PROERI_cambio_camara_v2_sin_interpolacion" a la aplicación:
mismo método, sin OpenCV (solo NumPy y Pillow, que ya usa el servidor) y con resultados guardados en la base.

Método (parámetros en config.ENCUADRE):
  1. Selección: por día, las fotos_por_dia fotos de día (horas) más cercanas al mediodía (hora_objetivo). Se usan
     también las fotos "borrosas o con lente empañado": aunque no sirvan para la IA, todavía muestran el encuadre
     (en Limoncito el lente estuvo empañado de nov. 2025 a feb. 2026). Se descartan nocturnas, oscuras, quemadas,
     duplicadas y los períodos excluidos a mano.
  2. Descriptor de cada foto: histogramas de orientación de bordes (Sobel) en una grilla de 6 x 8 celdas, 9 rangos de
     ángulo cada una (432 números). Describe DÓNDE están los bordes y hacia dónde apuntan: cambia mucho si la cámara se
     mueve y poco si solo cambia la luz. Se promedia por día, para que un día con más fotos no pese más.
  3. Disimilitud entre ventanas: para cada día, se compara el promedio de los dias_ventana días CON fotos anteriores
     con el de los dias_ventana siguientes (1 - coseno). Un cambio persistente produce un pico.
  4. Cambios: máximos locales que superan umbral_ventana, separados entre sí por más de dias_ventana días. Máximo
     local = mayor o igual que el día anterior y el siguiente (los dos con valor): evita marcar un cambio reciente un
     día antes de su fecha real, cuando todavía faltan días para completar la ventana.
  5. Verificación con dos fotos (la del último día antes y la del primer día después): correlación de fase, que
     estima cuántos píxeles se desplazó la imagen y qué tan bien calzan (pico). Reemplaza la verificación ORB del
     notebook (que requiere OpenCV).
       desplazamiento >= desplazamiento_px y pico >= pico_confiable  ->  "Movimiento de la cámara"
       desplazamiento >= desplazamiento_px y pico bajo               ->  "Probable movimiento de la cámara (fotos poco
                                                                          comparables)": también cambió la luz o el lente
       desplazamiento menor                                          ->  "Cambio en la imagen" (zoom, rotación, obra
                                                                          nueva, oclusión o lente): revisar las fotos
  6. Referencia: los primeros dias_referencia días de cada tramo entre cambios. dist_referencia mide cuánto se aleja
     cada día del encuadre de su tramo (sirve para graficar la serie, EDA-01).

Una diferencia visual NO prueba por sí sola que la cámara se movió: por eso se guarda un panel antes/después para que
una persona lo confirme. La fecha exacta puede estar en un intervalo sin fotos (se informa dias_sin_fotos).
Límite: un cambio se detecta cuando ya hay dias_ventana + 1 días con fotos después de él (aprox. una semana).

Resultados (se recalculan completos en cada ejecución; el estado de revisión de cada cambio se conserva):
    etl_encuadre_fotos    caché del descriptor de cada foto (no se vuelve a leer la imagen al repetir)
    etl_encuadre_dias     una fila por día: fotos usadas, dist_referencia, disimilitud_ventana, tramo
    etl_encuadre_cambios  una fila por cambio detectado, con la evidencia y el panel antes/después
    data/etl/<proyecto>/encuadre/   serie_diaria.csv, cambios.csv y cambio_<fecha>.jpg (paneles)
Uso: python backend/etl_imagenes.py encuadre --proyecto P-001   (después de "curar")."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFilter
from config import ENCUADRE as E, ETL, DATA_DIR
from src import store, etl, proyectos
from src.etl import curacion

VERSION = "hog6x8x9-640x480-v1"   # si cambia el descriptor, se cambia este texto y la caché se recalcula sola
GRILLA, RANGOS = (6, 8), 9
BLOQUEO_ADMITIDO = "borrosa o lente empañado"   # único bloqueo de la curación que no impide ver el encuadre

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS etl_encuadre_fotos(drive_id TEXT PRIMARY KEY, project_id TEXT, version TEXT, descriptor BLOB);
CREATE TABLE IF NOT EXISTS etl_encuadre_dias(project_id TEXT, fecha TEXT, fotos INTEGER, dist_referencia REAL,
  disimilitud_ventana REAL, tramo INTEGER, PRIMARY KEY(project_id, fecha));
CREATE TABLE IF NOT EXISTS etl_encuadre_cambios(project_id TEXT, fecha TEXT, ultima_fecha_antes TEXT, dias_sin_fotos INTEGER,
  disimilitud REAL, desplazamiento_x INTEGER, desplazamiento_y INTEGER, pico REAL, clasificacion TEXT,
  foto_antes TEXT, foto_despues TEXT, panel TEXT, estado TEXT DEFAULT 'Por revisar', detectado TEXT DEFAULT CURRENT_TIMESTAMP,
  revisado_por TEXT, revisado TEXT, PRIMARY KEY(project_id, fecha));
"""
ESTADOS = ("Por revisar", "Confirmado", "Descartado")   # revisión de un cambio por el auditor (panel → Salud de la cámara)

_listo = False   # True después de preparar las tablas (una vez por proceso: se llama en cada carga del panel)

def preparar():
    global _listo
    if _listo: return
    etl.preparar()
    _listo = True
    with closing(store._c()) as c, c:
        c.executescript(_ESQUEMA)
        cols = [r[1] for r in c.execute("PRAGMA table_info(etl_encuadre_cambios)")]
        for col in ("revisado_por", "revisado"):   # tablas creadas antes de la revisión por el auditor
            if col not in cols: c.execute(f"ALTER TABLE etl_encuadre_cambios ADD COLUMN {col} TEXT")

# ---------- 1. selección de fotos ----------
def usable(f, excluir=()):
    """True si la foto sirve para ver el encuadre: curada, de día, no duplicada, fuera de períodos excluidos y sin
    otro bloqueo que "borrosa o lente empañado" (ver docstring del módulo)."""
    if f["curada"] is None or f["duplicado_de"] or not f["fecha"] or not f["hora"]: return False
    if not E["horas"][0] <= f["hora"][:5] <= E["horas"][1]: return False
    if any(desde <= f["fecha"] <= hasta for desde, hasta, _ in excluir): return False
    bloqueos = [m for m in (f["motivo_ia"] or "").split("; ") if m and not m.startswith("aviso")]
    return f["apta_ia"] == 1 or all(m == BLOQUEO_ADMITIDO for m in bloqueos)

def seleccionar(fotos):
    """{fecha: [fotos]} con las fotos_por_dia más cercanas a hora_objetivo de cada día (orden: fecha ascendente)."""
    por_dia = {}
    for f in fotos: por_dia.setdefault(f["fecha"], []).append(f)
    distancia = lambda f: abs(int(f["hora"][:2]) + int(f["hora"][3:5]) / 60 - E["hora_objetivo"])
    return {d: sorted(v, key=lambda f: (distancia(f), f["hora"]))[:E["fotos_por_dia"]] for d, v in sorted(por_dia.items())}

# ---------- 2. descriptor ----------
def imagen_gris(f, rotacion_obra=0):
    """Foto original en gris, enderezada y reducida a config.ENCUADRE["tamano"]."""
    im = Image.open(DATA_DIR / f["ruta_local"])
    im.draft("L", E["tamano"])   # JPEG: decodifica directo a menor tamaño (mucho más rápido)
    im = im.convert("L")
    grados = curacion.grados_rotacion(f, rotacion_obra)
    if grados: im = im.rotate(grados, expand=True)
    return im.resize(E["tamano"], Image.Resampling.BOX)

def descriptor(im):
    """Vector de 432 valores (6 x 8 celdas x 9 orientaciones), con norma 1. Port del notebook (cv2.Sobel + cartToPolar)."""
    a = np.asarray(im.convert("L").filter(ImageFilter.GaussianBlur(1.1)), dtype=np.float32)
    p = np.pad(a, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])   # Sobel 3x3
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    magnitud, angulo = np.hypot(gx, gy), np.degrees(np.arctan2(gy, gx)) % 360
    v = []
    for ys in np.array_split(np.arange(a.shape[0]), GRILLA[0]):
        for xs in np.array_split(np.arange(a.shape[1]), GRILLA[1]):
            h = np.histogram(angulo[np.ix_(ys, xs)], bins=RANGOS, range=(0, 360), weights=magnitud[np.ix_(ys, xs)])[0]
            v.extend(h / (np.linalg.norm(h) + 1e-8))   # cada celda normalizada: un cambio de luz pesa poco
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-8)

def desplazamiento(a, b):
    """Correlación de fase entre dos imágenes: (dx, dy, pico). dx/dy en px de la imagen de config.ENCUADRE["tamano"]
    (cuánto hay que mover `b` para que calce con `a`); pico cerca de 1 = calzan perfecto, cerca de 0 = no se parecen."""
    w, h = E["tamano"][0] // 2, E["tamano"][1] // 2   # se mide a la mitad del tamaño: suficiente y 4 veces más rápido
    A, B = (np.asarray(x.convert("L").resize((w, h)), dtype=np.float32) for x in (a, b))
    ventana = np.outer(np.hanning(h), np.hanning(w))   # atenúa los bordes para que no generen un pico falso
    A, B = (A - A.mean()) * ventana, (B - B.mean()) * ventana
    R = np.fft.fft2(A) * np.conj(np.fft.fft2(B)); R /= np.abs(R) + 1e-8
    r = np.real(np.fft.ifft2(R)); y, x = np.unravel_index(int(r.argmax()), r.shape)
    if y > h // 2: y -= h
    if x > w // 2: x -= w
    return int(x * 2), int(y * 2), round(float(r.max()), 3)

def clasificar(dx, dy, pico):
    """Texto para la persona que revisa, según el desplazamiento estimado y qué tan bien calzan las dos fotos."""
    if max(abs(dx), abs(dy)) >= E["desplazamiento_px"]:
        if pico >= E["pico_confiable"]: return "Movimiento de la cámara"
        return "Probable movimiento de la cámara (fotos poco comparables: también cambió la luz o el lente)"
    return "Cambio en la imagen (zoom, rotación, obra nueva, oclusión o lente): revisar"

# ---------- 3 y 4. serie diaria y cambios (función pura: se prueba sin imágenes) ----------
def analizar_serie(diarios):
    """diarios: matriz (días x 432), un descriptor promedio por día con fotos, en orden de fecha.
    Devuelve (disimilitud_ventana, cambios, dist_referencia, tramo): arrays por día y la lista de índices de los días
    donde empieza un encuadre nuevo. Ver docstring del módulo (pasos 3, 4 y 6)."""
    d = np.asarray(diarios, dtype=np.float64)
    d = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1e-12)
    n, W = len(d), E["dias_ventana"]
    ventana = np.full(n, np.nan)
    for k in range(W, n - W + 1):
        izq, der = d[k - W:k].mean(axis=0), d[k:k + W].mean(axis=0)
        ventana[k] = 1 - izq @ der / (np.linalg.norm(izq) * np.linalg.norm(der) + 1e-12)
    def maximo_local(k):   # con valor a ambos lados: el pico ya está completo (ver docstring, paso 4)
        return 0 < k < n - 1 and np.isfinite(ventana[k - 1]) and np.isfinite(ventana[k + 1])             and ventana[k] >= ventana[k - 1] and ventana[k] >= ventana[k + 1]
    cambios = []
    candidatos = [k for k in np.flatnonzero(np.nan_to_num(ventana, nan=-1) >= E["umbral_ventana"]) if maximo_local(k)]
    for k in sorted(candidatos, key=lambda k: -ventana[k]):
        if all(abs(k - j) > W for j in cambios): cambios.append(int(k))   # el pico más alto de cada zona
    cambios.sort()
    dist, tramo = np.zeros(n), np.zeros(n, dtype=int)
    for t, (ini, fin) in enumerate(zip([0] + cambios, cambios + [n])):
        ref = d[ini:min(fin, ini + E["dias_referencia"])].mean(axis=0)
        ref /= np.linalg.norm(ref) + 1e-12
        dist[ini:fin] = np.clip(1 - d[ini:fin] @ ref, 0, None); tramo[ini:fin] = t
    return ventana, cambios, dist, tramo

# ---------- orquestación ----------
def _descriptores(pid, fotos, rotacion, rehacer, avance=None):
    """{drive_id: descriptor}, usando la caché de etl_encuadre_fotos y calculando solo lo que falta."""
    cache = {} if rehacer else {r["drive_id"]: np.frombuffer(r["descriptor"], dtype=np.float32) for r in store._filas(
        "SELECT drive_id, descriptor FROM etl_encuadre_fotos WHERE project_id=? AND version=?", (pid, VERSION))}
    faltan = [f for f in fotos if f["drive_id"] not in cache]
    with ThreadPoolExecutor(ETL["hilos"]) as ex:
        nuevos = []
        for i, (f, v) in enumerate(zip(faltan, ex.map(lambda f: descriptor(imagen_gris(f, rotacion)), faltan)), 1):
            cache[f["drive_id"]] = v; nuevos.append((f["drive_id"], pid, VERSION, v.tobytes()))
            if avance: avance(i, len(faltan))
    with closing(store._c()) as c, c:
        c.executemany("INSERT OR REPLACE INTO etl_encuadre_fotos VALUES(?,?,?,?)", nuevos)
    return cache

def _panel(pid, fecha, antes, despues, rotacion, cambio):
    """Imagen antes/después con la evidencia, en data/etl/<pid>/encuadre/cambio_<fecha>.jpg. Devuelve la ruta relativa."""
    salida = ETL["dir"] / pid / "encuadre"; salida.mkdir(parents=True, exist_ok=True)
    lado, alto_txt = (640, 480), 76
    panel = Image.new("RGB", (2 * lado[0] + 10, lado[1] + alto_txt), "white"); d = ImageDraw.Draw(panel)
    fuente = curacion._fuente(16)
    for i, (f, titulo) in enumerate(((antes, "ANTES"), (despues, "DESPUÉS"))):
        im = curacion._enderezada(f, rotacion); im.thumbnail(lado)
        panel.paste(im, (i * (lado[0] + 10), alto_txt))
        d.text((i * (lado[0] + 10) + 4, 52), f"{titulo}: {f['fecha']} {f['hora'][:5]}", fill="black", font=fuente)
    # Dos líneas: la conclusión y la evidencia (en una sola no entra en el ancho del panel)
    d.text((4, 4), f"{pid} · posible cambio de encuadre · {cambio['clasificacion']}", fill=(207, 34, 46), font=fuente)
    d.text((4, 26), f"Disimilitud {cambio['disimilitud']:.3f} (umbral {E['umbral_ventana']}) · desplazamiento estimado "
                    f"({cambio['desplazamiento_x']}, {cambio['desplazamiento_y']}) px · pico {cambio['pico']} · "
                    f"días sin fotos entre ambas: {cambio['dias_sin_fotos']}", fill=(90, 90, 90), font=fuente)
    ruta = salida / f"cambio_{fecha}.jpg"; panel.save(ruta, quality=85)
    return ruta.relative_to(DATA_DIR).as_posix()

def detectar(pid, rehacer=False, avance=None):
    """Paso "encuadre" del ETL: serie diaria, cambios detectados y paneles. rehacer=True recalcula también la caché de
    descriptores (por ejemplo, después de cambiar la rotación de la obra). Devuelve un resumen."""
    preparar()
    cfg = proyectos.config_etl(pid)
    fotos = [f for f in store._filas("""SELECT * FROM etl_imagenes WHERE project_id=? AND ruta_local IS NOT NULL
                 AND origen<>'otros' ORDER BY fecha, hora""", (pid,)) if usable(f, cfg["excluir"])]
    sel = seleccionar(fotos)
    if len(sel) < 2 * E["dias_ventana"]:
        return dict(dias=len(sel), cambios=[], aviso=f"Se necesitan al menos {2 * E['dias_ventana']} días con fotos de día "
                    "(¿se ejecutó el paso 'curar'?)")
    elegidas = [f for v in sel.values() for f in v]
    desc = _descriptores(pid, elegidas, cfg["rotacion"], rehacer, avance)
    fechas = list(sel)
    diarios = np.stack([np.mean([desc[f["drive_id"]] for f in sel[d]], axis=0) for d in fechas])
    ventana, cambios_idx, dist, tramo = analizar_serie(diarios)

    cambios = []
    for k in cambios_idx:
        antes, despues = sel[fechas[k - 1]][0], sel[fechas[k]][0]
        dx, dy, pico = desplazamiento(imagen_gris(antes, cfg["rotacion"]), imagen_gris(despues, cfg["rotacion"]))
        x = dict(project_id=pid, fecha=fechas[k], ultima_fecha_antes=fechas[k - 1],
                 dias_sin_fotos=(pd.Timestamp(fechas[k]) - pd.Timestamp(fechas[k - 1])).days - 1,
                 disimilitud=round(float(ventana[k]), 4), desplazamiento_x=dx, desplazamiento_y=dy, pico=pico,
                 clasificacion=clasificar(dx, dy, pico), foto_antes=antes["ruta_local"], foto_despues=despues["ruta_local"])
        x["panel"] = _panel(pid, fechas[k], antes, despues, cfg["rotacion"], x)
        cambios.append(x)

    dias = [(pid, f, len(sel[f]), round(float(dist[i]), 4), None if np.isnan(ventana[i]) else round(float(ventana[i]), 4),
             int(tramo[i])) for i, f in enumerate(fechas)]
    with closing(store._c()) as c, c:   # todo en una transacción: nunca queda una serie a medias
        c.execute("DELETE FROM etl_encuadre_dias WHERE project_id=?", (pid,))
        c.executemany("INSERT INTO etl_encuadre_dias VALUES(?,?,?,?,?,?)", dias)
        # Se borran los cambios que ya no se detectan, pero solo si nadie los revisó todavía
        # (ojo: "NOT IN (NULL)" no borra nada en SQL; por eso sin cambios detectados la condición es otra)
        fechas_cambio = [x["fecha"] for x in cambios]
        fuera = f" AND fecha NOT IN ({','.join('?' * len(fechas_cambio))})" if fechas_cambio else ""
        c.execute("DELETE FROM etl_encuadre_cambios WHERE project_id=? AND estado='Por revisar'" + fuera, (pid, *fechas_cambio))
        cols = list(cambios[0]) if cambios else []
        for x in cambios:   # upsert: actualiza la evidencia y conserva el estado de revisión
            c.execute(f"INSERT INTO etl_encuadre_cambios({','.join(cols)}) VALUES({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(project_id, fecha) DO UPDATE SET {', '.join(f'{k}=excluded.{k}' for k in cols[2:])}",
                      list(x.values()))
    salida = ETL["dir"] / pid / "encuadre"; salida.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(dias, columns=["project_id", "fecha", "fotos", "dist_referencia", "disimilitud_ventana", "tramo"]).to_csv(
        salida / "serie_diaria.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(cambios).to_csv(salida / "cambios.csv", index=False, encoding="utf-8-sig")
    return dict(dias=len(fechas), fotos=len(elegidas), desde=fechas[0], hasta=fechas[-1], carpeta=str(salida),
                cambios=[{k: x[k] for k in ("fecha", "ultima_fecha_antes", "dias_sin_fotos", "disimilitud",
                                            "desplazamiento_x", "desplazamiento_y", "pico", "clasificacion", "panel")} for x in cambios])

def cambios(pid):
    """Cambios guardados de una obra (más recientes primero), para el panel y las alertas S-03."""
    preparar()
    return store._filas("SELECT * FROM etl_encuadre_cambios WHERE project_id=? ORDER BY fecha DESC", (pid,))

def revisar(pid, fecha, estado, usuario):
    """El auditor confirma o descarta un cambio (o lo vuelve a "Por revisar"). Un cambio revisado deja de generar la
    alerta S-03 y se conserva aunque el paso "encuadre" ya no lo detecte. Devuelve False si el cambio no existe."""
    if estado not in ESTADOS: raise ValueError(f"Estado no válido: use {', '.join(ESTADOS)}")
    preparar()
    cur = store._q("UPDATE etl_encuadre_cambios SET estado=?, revisado_por=?, revisado=CURRENT_TIMESTAMP WHERE project_id=? AND fecha=?",
                   (estado, usuario, pid, fecha))
    return cur.rowcount > 0
