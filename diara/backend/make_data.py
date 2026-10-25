"""Genera datos SINTÉTICOS (ilustrativos) por obra, mientras no existan cámaras ni análisis de IA reales.

Uso: python backend/make_data.py   (se puede repetir: regenera los archivos)

Escribe en data/obras/<project_id>/:
  diario.csv          un registro por día: lo que "detectó la IA" (personas, maquinaria, horas), clima y avance
  camara/*.jpg        12 imágenes dibujadas con recuadros de detección (2 por día, últimos 6 días hábiles)
  camara/publica/*.jpg  las mismas escenas SIN las detecciones de la IA (las que se muestran en el sitio público)
  camara/indice.csv   metadatos de esas imágenes (personas, maquinaria, confianza)
Al regenerar solo se borran las imágenes sintéticas anteriores (las de indice.csv); las fotos recibidas por la API de
cámaras, que viven en la misma carpeta, se conservan.

Escenarios:
  P-001 Escuela Limoncito: se detiene desde el 12-oct (atrasada, dispara alertas).
  P-002 Ruta Paraíso: avanza según lo previsto (sirve de contraste).

Cuando haya IA real, este script se reemplaza por el proceso que produzca diario.csv con las mismas columnas
(las consume src/metrics.py, src/alerts.py y el panel)."""
import shutil
import pandas as pd, numpy as np
from PIL import Image, ImageDraw
from config import OBRAS_DIR

# Parámetros de cada obra simulada:
#   prev / obs       avance previsto y observado (%) al inicio y al final del período
#   parada           fecha desde la que la obra deja de trabajar (None = no se detiene)
#   lluvia           mm por fecha (>= 5 mm hace el día "no apto")
#   tiempo_muerto    horas de maquinaria encendida sin operar (dispara A-04)
#   baja_confianza   días con detecciones de confianza baja (dispara A-02)
ESCENARIOS = {
    "P-001": dict(semilla=7, tipo="edificio", maquina="Vagoneta", prev=(38, 62), obs=(36, 48),
                  parada="2026-10-12", lluvia={"2026-10-09": 2, "2026-10-13": 1}, tiempo_muerto={"2026-10-09": 2.0},
                  baja_confianza=["2026-10-14"]),
    "P-002": dict(semilla=11, tipo="via", maquina="Excavadora", prev=(20, 45), obs=(19, 44),
                  parada=None, lluvia={"2026-09-24": 14, "2026-10-02": 8, "2026-10-06": 12}, tiempo_muerto={},
                  baja_confianza=[]),
}
FECHAS = pd.date_range("2026-09-16", "2026-10-14")

def diario(e):
    """Construye el registro diario de una obra según su escenario."""
    rng = np.random.default_rng(e["semilla"]); n = len(FECHAS); rows = []  # semilla fija: mismos datos en cada ejecución
    for i, f in enumerate(FECHAS):
        dia = str(f.date()); lluvia = e["lluvia"].get(dia, 0); apto = int(lluvia < 5)
        reg = f.weekday() < 5                                   # la cámara solo registra de lunes a viernes
        inact = bool(e["parada"]) and f >= pd.Timestamp(e["parada"])
        trabaja = reg and not inact and apto
        prev = e["prev"][0] + (e["prev"][1] - e["prev"][0]) * i / (n - 1)  # avance previsto lineal
        # Si la obra está parada, el avance observado se congela en el último valor
        obs = e["obs"][0] + (e["obs"][1] - e["obs"][0]) * i / (n - 1) if not inact else rows[-1]["avance_observado"]
        rows.append(dict(fecha=f.date(), hay_registro=int(reg), fotos=24 if reg else 0,
            personas_prom=(int(rng.integers(5, 7)) if trabaja else 2 if reg else 0),
            personas_max=(int(rng.integers(8, 10)) if trabaja else 3 if reg else 0),
            maquinaria="" if not reg else (e["maquina"] if trabaja else "Ninguna"),
            maquinaria_operando=int(trabaja),
            horas_sitio=10.0 if reg else 0.0,
            horas_efectivas=(7.5 if trabaja else 1.5) if reg else 0.0,
            tiempo_muerto_h=e["tiempo_muerto"].get(dia, 0.0),
            lluvia_mm=lluvia, apto_trabajo=apto,
            temp_max=round(float(rng.normal(24, 1.2)) - min(lluvia, 4), 1), temp_min=round(float(rng.normal(15, 0.8)), 1),
            humedad=min(98, int(rng.integers(68, 80)) + 2 * lluvia),
            confianza_min=0.54 if dia in e["baja_confianza"] else 0.82,
            avance_previsto=round(prev, 1), avance_observado=round(obs, 1)))
    return pd.DataFrame(rows)

def captura(camara, tipo, maquina_nombre, fecha, hora, avance, personas, maquina, conf, lluvia):
    """Dibuja una captura de cámara simulada con los recuadros de detección de la IA.
    Devuelve (imagen con detecciones, imagen sin detecciones para el sitio público, personas detectadas, 1 si hay maquinaria)."""
    W, H = 640, 400; im = Image.new("RGB", (W, H)); g = ImageDraw.Draw(im)
    for y in range(230):  # cielo (gris si llueve)
        t = y / 230; c = (150, 160, 170) if lluvia else (110, 165, 220)
        g.line([(0, y), (W, y)], fill=tuple(int(v + (235 - v) * t * .6) for v in c))
    g.rectangle([0, 230, W, H], fill=(138, 112, 82))  # terreno
    if tipo == "edificio":  # estructura que crece en altura con el avance
        alto = int(40 + 150 * avance / 100)
        g.rectangle([170, 230 - alto, 470, 230], fill=(178, 178, 172))
        for x in range(170, 471, 60): g.rectangle([x, 230 - alto - 25, x + 10, 230], fill=(120, 120, 118))
    else:  # vía: el asfalto avanza hacia el fondo con el avance
        fin = int(230 - 120 * avance / 100)
        g.polygon([(150, H), (490, H), (330, fin), (310, fin)], fill=(70, 70, 75))
        g.line([(320, H), (320, fin)], fill=(240, 220, 90), width=3)
    dets = []  # detecciones: (clase, recuadro)
    for k in range(personas):
        x = 60 + k * 85 % 520; y = 270 + (k * 37) % 60
        g.rectangle([x + 6, y, x + 18, y + 12], fill=(230, 190, 150)); g.rectangle([x, y + 12, x + 24, y + 50], fill=(245, 130, 30))
        dets.append(("persona", [x - 4, y - 4, x + 28, y + 54]))
    if maquina:
        g.rectangle([470, 290, 600, 340], fill=(230, 180, 20)); g.rectangle([560, 265, 600, 292], fill=(200, 150, 10))
        for cx in (495, 575): g.ellipse([cx - 14, 330, cx + 14, 358], fill=(40, 40, 40))
        dets.append(("maquinaria", [464, 260, 606, 362]))
    limpia = im.copy()  # la escena antes de dibujar las detecciones: es lo único que se publica a la ciudadanía
    ImageDraw.Draw(limpia).rectangle([0, 0, W, 22], fill=(0, 0, 0)); ImageDraw.Draw(limpia).text((8, 5), f"{camara} | {fecha} {hora}", fill=(255, 255, 255))
    # La primera detección usa la confianza mínima del día; recuadro rojo si es < 0.60 (igual que el umbral A-02)
    for j, (cls, b) in enumerate(dets):
        p = conf if j == 0 else min(.97, conf + .08 + .02 * j); col = (40, 220, 90) if p >= .6 else (255, 70, 70)
        g.rectangle(b, outline=col, width=3); g.rectangle([b[0], b[1] - 16, b[0] + 108, b[1]], fill=col)
        g.text((b[0] + 4, b[1] - 14), f"{cls} {p:.2f}", fill=(0, 0, 0))
    g.rectangle([0, 0, W, 22], fill=(0, 0, 0)); g.text((8, 5), f"{camara} | {fecha} {hora} | SINTETICO", fill=(255, 255, 255))
    return im, limpia, sum(c == "persona" for c, _ in dets), int(bool(maquina))

# ---------- ejecución ----------
from src import proyectos as catalogo  # se importa aquí para leer el código de cámara de la tabla proyectos
for pid, e in ESCENARIOS.items():
    carpeta = OBRAS_DIR / pid; cam = carpeta / "camara"
    if (carpeta / "origen.json").exists():  # obra con datos REALES (src/etl/publicar.py): nunca se reemplaza por sintéticos
        print(f"{pid}: tiene datos reales (origen.json), se omite"); continue
    # Solo se borran las imágenes sintéticas de la corrida anterior (listadas en indice.csv) y sus versiones públicas.
    # Las fotos recibidas por la API de cámaras comparten la carpeta y NO se tocan.
    if (cam / "indice.csv").exists():
        for a in pd.read_csv(cam / "indice.csv").archivo: (cam / a).unlink(missing_ok=True)
    shutil.rmtree(cam / "publica", ignore_errors=True); (cam / "publica").mkdir(parents=True)
    d = diario(e); d.to_csv(carpeta / "diario.csv", index=False)
    idx = []
    for r in d[d.hay_registro == 1].tail(6).itertuples():
        for hora, factor in (("08:00", 1.0), ("14:00", 0.7)):  # por la tarde hay menos personal
            pers = max(0, round(r.personas_prom * factor))
            im, limpia, p, m = captura((catalogo.obtener(pid) or {}).get("camara") or pid, e["tipo"], e["maquina"], r.fecha, hora, r.avance_observado,
                               pers, r.maquinaria_operando == 1, r.confianza_min, r.lluvia_mm)
            nombre = f"{r.fecha}_{hora.replace(':', '')}.jpg"; im.save(cam / nombre, quality=85); limpia.save(cam / "publica" / nombre, quality=80)
            idx.append(dict(archivo=nombre, fecha=r.fecha, hora=hora, personas=p, maquinaria=m, confianza=r.confianza_min))
    pd.DataFrame(idx).to_csv(cam / "indice.csv", index=False)
    print(f"{pid}: diario.csv + {len(idx)} imagenes en {carpeta} (SINTETICO)")
