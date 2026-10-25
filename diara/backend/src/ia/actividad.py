"""Actividad en obra a partir de las fotos curadas: dos señales independientes por foto, resumen diario y cruce con la lluvia.

1. Detección (YOLO11-s preentrenado en COCO, sin entrenar con fotos de la obra):
       personas y vehículos (auto, bus, camión) con puntaje >= config.IA["confianza"].
       Antes de detectar se realza el contraste (autocontraste 1 %): mejora las fotos opacas de esta cámara.
   Límite conocido (probado en Limoncito): funciona con el patio abierto (feb.-abr. 2026); desde abril el área está
   techada, oscura y medio tapada por un muro y un andamio, y el modelo NO ve a los obreros (ni con puntaje 0.08).
   Para esa etapa hay que entrenar con fotos etiquetadas de esta cámara; estas detecciones sirven de pre-etiquetado.
   COCO no tiene maquinaria de obra (retroexcavadora, grúa): solo se cuentan vehículos.
2. Índice de cambio (no depende del detector): % de píxeles que cambiaron respecto de la foto ANTERIOR del mismo día
   (si están separadas por <= cambio_hueco_min). Gris 160x120, desenfoque y normalización por el brillo medio para
   que una nube o un cambio de luz general pese menos. Mide movimiento: personas, máquinas, material, pero también
   sombras y lluvia: es una señal de apoyo, no un conteo.

Resultados: tabla ia_actividad (una fila por foto) y, en data/etl/<proyecto>/:
    actividad_fotos.csv    una fila por foto: personas, vehículos, cambio, lluvia de la hora
    actividad_diaria.csv   una fila por día: promedios en jornada (config.IA["jornada"]) y lluvia de la jornada
    ia_muestras/           hasta muestras_por_dia fotos anotadas con cajas por día (para revisar a ojo)"""
import json
from contextlib import closing
from datetime import datetime
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from config import IA, ETL, DATA_DIR
from src import store, etl

NOMBRE_MODELO = IA["modelo"].stem  # se guarda en cada fila: si se cambia el modelo, se reprocesa

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS ia_actividad(drive_id TEXT PRIMARY KEY, project_id TEXT, fecha TEXT, hora TEXT, modelo TEXT,
  personas INTEGER, vehiculos INTEGER, conf_max REAL, cajas TEXT, cambio_pct REAL, procesado TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_ia_act ON ia_actividad(project_id, fecha);
"""

def preparar():
    etl.preparar()
    with closing(store._c()) as c: c.executescript(_ESQUEMA)

def cargar_modelo():
    """YOLO desde data/ia/modelos/. Si el archivo no existe, Ultralytics lo descarga a esa ruta (≈19 MB)."""
    from ultralytics import YOLO  # import local: el resto de la app no necesita PyTorch
    IA["modelo"].parent.mkdir(parents=True, exist_ok=True)
    return YOLO(str(IA["modelo"]))

def _preparada(ruta):
    """Imagen curada con contraste realzado (lo que ve el detector)."""
    return ImageOps.autocontrast(Image.open(DATA_DIR / ruta).convert("RGB"), cutoff=1)

def detectar(modelo, imagen):
    """Detecciones de personas y vehículos: [{clase, conf, caja [x1,y1,x2,y2]}]."""
    r = modelo.predict(imagen, imgsz=IA["imgsz"], conf=IA["confianza"], classes=list(IA["clases"]), verbose=False)[0]
    return [dict(clase=IA["clases"][int(k)], conf=round(s, 3), caja=[round(v) for v in b])
            for b, s, k in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]

def _firma(ruta):
    """Versión reducida y normalizada de la foto para comparar con la siguiente (ver índice de cambio)."""
    g = Image.open(DATA_DIR / ruta).convert("L").resize((160, 120)).filter(ImageFilter.GaussianBlur(2))
    a = np.asarray(g, dtype=np.float32)
    return a * (128.0 / max(a.mean(), 1.0))

def _cambios(fotos):
    """% de píxeles cambiados de cada foto respecto de la anterior del mismo día (None si no hay anterior cercana)."""
    out, previa = {}, None
    for f in fotos:  # ordenadas por fecha y hora
        firma, t = _firma(f["ruta_curada"]), datetime.fromisoformat(f["tomada"])
        if previa and previa[0].date() == t.date() and (t - previa[0]).total_seconds() <= IA["cambio_hueco_min"] * 60:
            out[f["drive_id"]] = round(float((np.abs(firma - previa[1]) > IA["cambio_umbral"]).mean() * 100), 2)
        else:
            out[f["drive_id"]] = None
        previa = (t, firma)
    return out

def _muestra(pid, f, dets):
    """Guarda la foto con sus cajas (rojo persona, celeste vehículo) en data/etl/<proyecto>/ia_muestras/."""
    im = _preparada(f["ruta_curada"]); d = ImageDraw.Draw(im)
    for x in dets:
        d.rectangle(x["caja"], outline="red" if x["clase"] == "persona" else "cyan", width=3)
        d.text((x["caja"][0], x["caja"][1] - 12), f"{x['clase']} {x['conf']:.2f}", fill="yellow")
    salida = ETL["dir"] / pid / "ia_muestras"; salida.mkdir(parents=True, exist_ok=True)
    im.save(salida / f"{f['fecha']}_{f['archivo']}", quality=85)

def analizar(pid, desde=None, hasta=None, limite=None, avance=None):
    """Procesa las fotos aptas (apta_ia=1) que aún no tienen resultado con el modelo actual. Se puede interrumpir y
    retomar: guarda cada 50 fotos. El índice de cambio se calcula para todos los días tocados."""
    preparar()
    sql = """SELECT e.* FROM etl_imagenes e LEFT JOIN ia_actividad a ON a.drive_id=e.drive_id AND a.modelo=?
             WHERE e.project_id=? AND e.apta_ia=1 AND e.ruta_curada IS NOT NULL AND a.drive_id IS NULL"""
    args = [NOMBRE_MODELO, pid]
    if desde: sql += " AND e.fecha>=?"; args.append(desde)
    if hasta: sql += " AND e.fecha<=?"; args.append(hasta)
    pendientes = store._filas(sql + " ORDER BY e.fecha, e.hora" + (" LIMIT ?" if limite else ""), args + ([limite] if limite else []))
    modelo = cargar_modelo() if pendientes else None
    filas, muestras = [], {}
    def guardar():
        with closing(store._c()) as c, c:
            c.executemany("""INSERT OR REPLACE INTO ia_actividad(drive_id,project_id,fecha,hora,modelo,personas,vehiculos,conf_max,cajas)
                             VALUES(?,?,?,?,?,?,?,?,?)""", filas)
        filas.clear()
    for i, f in enumerate(pendientes, 1):
        dets = detectar(modelo, _preparada(f["ruta_curada"]))
        n = lambda clase: sum(1 for x in dets if x["clase"] == clase)
        filas.append((f["drive_id"], pid, f["fecha"], f["hora"], NOMBRE_MODELO, n("persona"), n("vehiculo"),
                      max((x["conf"] for x in dets), default=None), json.dumps(dets)))
        if dets and muestras.get(f["fecha"], 0) < IA["muestras_por_dia"]:
            _muestra(pid, f, dets); muestras[f["fecha"]] = muestras.get(f["fecha"], 0) + 1
        if len(filas) >= 50: guardar()
        if avance: avance(i, len(pendientes))
    guardar()
    # Índice de cambio: se recalcula para los días procesados (necesita la foto anterior, aunque ya estuviera hecha)
    dias = sorted({f["fecha"] for f in pendientes})
    for d in dias:
        fotos = store._filas("""SELECT e.drive_id, e.tomada, e.ruta_curada FROM etl_imagenes e JOIN ia_actividad a ON a.drive_id=e.drive_id
                                WHERE e.project_id=? AND e.fecha=? ORDER BY e.tomada""", (pid, d))
        with closing(store._c()) as c, c:
            c.executemany("UPDATE ia_actividad SET cambio_pct=? WHERE drive_id=?", [(v, k) for k, v in _cambios(fotos).items()])
    return dict(procesadas=len(pendientes), dias=len(dias), modelo=NOMBRE_MODELO)

def resumen(pid):
    """Escribe actividad_fotos.csv y actividad_diaria.csv y devuelve totales y la relación con la lluvia por mes.
    Correlación de Spearman (por rangos, resiste valores extremos) entre la lluvia de la jornada y la actividad del día:
    negativa = cuando llueve más, se ve menos actividad."""
    preparar()
    j0, j1 = IA["jornada"]
    fotos = store._df("""SELECT a.fecha, a.hora, e.origen, e.archivo, a.personas, a.vehiculos, a.conf_max, a.cambio_pct,
        c.lluvia_mm lluvia_hora_mm, e.motivo_ia FROM ia_actividad a JOIN etl_imagenes e ON e.drive_id=a.drive_id
        LEFT JOIN etl_clima_horas c ON c.project_id=a.project_id
             AND c.hora = strftime('%Y-%m-%dT%H:00', datetime(e.tomada, '+59 minutes', '+59 seconds'))
        WHERE a.project_id=? AND a.modelo=? ORDER BY a.fecha, a.hora""", (pid, NOMBRE_MODELO))
    if fotos.empty: raise ValueError("No hay resultados de IA: ejecute primero 'analizar'")
    salida = ETL["dir"] / pid; fotos.to_csv(salida / "actividad_fotos.csv", index=False, encoding="utf-8-sig")
    jornada = fotos[(fotos["hora"] >= j0) & (fotos["hora"] <= j1)]
    dia = jornada.groupby("fecha").agg(fotos=("archivo", "size"), personas_prom=("personas", "mean"), personas_max=("personas", "max"),
                                       fotos_con_personas=("personas", lambda s: int((s > 0).sum())),
                                       vehiculos_prom=("vehiculos", "mean"), cambio_mediana=("cambio_pct", "median"))
    lluvia = store._df(f"""SELECT fecha, round(sum(lluvia_mm),1) lluvia_jornada_mm, sum(lluvia_mm>=?) horas_lluvia_jornada
        FROM etl_clima_horas WHERE project_id=? AND substr(hora,12,5) > ? AND substr(hora,12,5) <= ? GROUP BY fecha""",
        (ETL["lluvia_hora_mm"], pid, j0, j1)).set_index("fecha")
    dia = dia.join(lluvia).round(2).reset_index()
    dia["mes"] = dia["fecha"].str[:7]
    dia.to_csv(salida / "actividad_diaria.csv", index=False, encoding="utf-8-sig")
    def corr(g, col):
        g = g.dropna(subset=[col, "lluvia_jornada_mm"])
        # Spearman = Pearson sobre los rangos (así no hace falta scipy, que pandas pide para method="spearman")
        if len(g) < 8 or g[col].nunique() < 2 or g["lluvia_jornada_mm"].nunique() < 2: return None
        return round(g[col].rank().corr(g["lluvia_jornada_mm"].rank()), 2)
    por_mes = [dict(mes=m, dias=len(g), personas_prom=round(g["personas_prom"].mean(), 2), cambio_mediana=round(g["cambio_mediana"].median(), 2),
                    lluvia_jornada_mm=round(g["lluvia_jornada_mm"].mean(), 1),
                    corr_lluvia_personas=corr(g, "personas_prom"), corr_lluvia_cambio=corr(g, "cambio_mediana"))
               for m, g in dia.groupby("mes")]
    return dict(fotos=len(fotos), fotos_con_personas=int((fotos["personas"] > 0).sum()), fotos_con_vehiculos=int((fotos["vehiculos"] > 0).sum()),
                dias=len(dia), corr_lluvia_personas=corr(dia, "personas_prom"), corr_lluvia_cambio=corr(dia, "cambio_mediana"),
                por_mes=por_mes, archivos=[str(salida / "actividad_fotos.csv"), str(salida / "actividad_diaria.csv")])
