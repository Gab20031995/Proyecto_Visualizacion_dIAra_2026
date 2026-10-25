"""Publica los datos REALES de una obra en la aplicación (panel, tarjetas, sitio público, PDF): paso final del ETL.

Qué hace (python backend/etl_imagenes.py publicar; se puede repetir, deja siempre el mismo resultado):
  1. Respalda los datos sintéticos de la obra (diario.csv y camara/) en data/obras/_sintetico/<id>/ (solo la primera vez).
  2. Fotos: enlaza cada foto APTA y enderezada (data/etl/curadas/...) en data/obras/<id>/camara/<día>_<archivo> y la
     registra en la tabla `imagenes` (fuente='etl') con lo que detectó la IA (ia_actividad): personas, vehículos
     (columna maquinaria) y confianza máxima. Usa enlace duro (no ocupa espacio extra); si no se puede, copia.
  3. Registro diario: escribe data/obras/<id>/diario.csv desde las fotos, la IA y el clima histórico (etl_clima_horas):
       hay_registro       1 si hubo fotos aptas ese día
       fotos              fotos aptas del día
       fotos_total        fotos tomadas ese día (aptas o no)  ·  calidad: motivo principal si ninguna fue apta
                          (p. ej. "borrosa o lente empañado"): el día tuvo cámara, pero sus fotos no sirven
       personas_prom/max  personas detectadas en las fotos de la jornada (config.IA["jornada"])
       horas_sitio        horas entre la primera y la última foto de la jornada con personas (+ un intervalo de cámara)
       horas_efectivas    horas de reloj distintas con personas detectadas (como máximo, horas_sitio)
       lluvia_mm, apto_trabajo, temp_max, temp_min, humedad   clima real del día (Open-Meteo histórico)
     Columnas que la IA actual NO mide y quedan VACÍAS (nunca se inventan): maquinaria_operando y tiempo_muerto_h
     (COCO no reconoce maquinaria de obra), confianza_min, avance_previsto y avance_observado. Con eso:
       - metrics.kpis devuelve el avance en None ("Avance sin medición") y no hay alerta de brecha (A-03)
       - no se disparan A-01 (sin maquinaria), A-02 (confianza) ni A-04 (tiempo muerto) por falta de medición
  4. Escribe data/obras/<id>/origen.json: marca la obra como real (make_data.py ya no la sobrescribe).

Límite conocido: desde fines de abril 2026 el detector no ve a los obreros (área techada y oscura): esos días
aparecen con 0 personas. No significa obra parada; ver src/ia/actividad.py."""
import json, os, shutil
from contextlib import closing
from datetime import datetime
import pandas as pd
from config import CLIMA, DATA_DIR, IA, OBRAS_DIR
from src import store, etl

COLUMNAS = ["fecha", "hay_registro", "fotos", "personas_prom", "personas_max", "maquinaria", "maquinaria_operando",
            "horas_sitio", "horas_efectivas", "tiempo_muerto_h", "lluvia_mm", "apto_trabajo", "temp_max", "temp_min", "humedad",
            "confianza_min", "avance_previsto", "avance_observado",  # mismas columnas que espera src/metrics.py
            "fotos_total", "calidad", "fuente_clima"]  # extra de los datos reales: fotos tomadas (aptas o no), motivo si ninguna
                                                       # fue apta y origen del clima (src/clima.reemplazar_en_diario lo respeta)
INTERVALO_H = 21 / 60  # cada cuánto toma foto la cámara de Limoncito (~21 min)

def _respaldar(pid):
    """Mueve los sintéticos a data/obras/_sintetico/<id>/ antes de la primera publicación (se pueden restaurar a mano)."""
    carpeta, destino = OBRAS_DIR / pid, OBRAS_DIR / "_sintetico" / pid
    if (carpeta / "origen.json").exists() or destino.exists(): return False
    destino.mkdir(parents=True)
    for nombre in ("diario.csv", "camara"):
        if (carpeta / nombre).exists(): shutil.move(str(carpeta / nombre), str(destino / nombre))
    return True

def _enlazar(origen, destino):
    """Enlace duro (mismo disco: no duplica los ~150 KB por foto); si el sistema no lo permite, copia."""
    if destino.exists(): return
    try: os.link(origen, destino)
    except OSError: shutil.copy2(origen, destino)

def _fotos(pid):
    """Paso 2: archivos en camara/ y filas en `imagenes` (fuente='etl'). Quita las que dejaron de ser aptas."""
    cam = OBRAS_DIR / pid / "camara"; cam.mkdir(parents=True, exist_ok=True)
    filas = store._filas("""SELECT e.fecha, e.hora, e.tomada, e.archivo, e.ruta_curada, a.personas, a.vehiculos, a.conf_max
        FROM etl_imagenes e LEFT JOIN ia_actividad a ON a.drive_id=e.drive_id
        WHERE e.project_id=? AND e.apta_ia=1 AND e.ruta_curada IS NOT NULL ORDER BY e.tomada""", (pid,))
    registros = []
    for f in filas:
        nombre = f"{f['fecha']}_{f['archivo']}"  # el día al inicio: los nombres del histórico (IMG_07-55-26.jpg) se repiten entre días
        _enlazar(DATA_DIR / f["ruta_curada"], cam / nombre)
        registros.append((pid, nombre, f["fecha"], f["hora"][:5], f["tomada"], f["personas"], f["vehiculos"], f["conf_max"]))
    vigentes = {r[1] for r in registros}
    with closing(store._c()) as c, c:
        previas = [r[0] for r in c.execute("SELECT archivo FROM imagenes WHERE project_id=? AND fuente='etl'", (pid,))]
        c.execute("DELETE FROM imagenes WHERE project_id=? AND fuente='etl'", (pid,))
        c.executemany("""INSERT INTO imagenes(project_id,archivo,fecha,hora,tomada,personas,maquinaria,confianza,fuente)
                         VALUES(?,?,?,?,?,?,?,?,'etl')""", registros)
    for a in set(previas) - vigentes: (cam / a).unlink(missing_ok=True)  # ya no es apta (p. ej. cambió un umbral)
    return dict(fotos=len(registros), con_ia=sum(r[5] is not None for r in registros), retiradas=len(set(previas) - vigentes))

def _diario(pid):
    """Paso 3: una fila por día, del primer al último día con fotos DESCARGADAS (incluye días sin fotos: hay_registro 0)."""
    j0, j1 = IA["jornada"]
    fotos = store._df("""SELECT e.fecha, e.hora, a.personas FROM etl_imagenes e LEFT JOIN ia_actividad a ON a.drive_id=e.drive_id
        WHERE e.project_id=? AND e.apta_ia=1""", (pid,))
    # Todas las fotos descargadas (aptas o no): un día con fotos pero ninguna apta NO es "sin cámara", es "fotos no aptas"
    todas = store._df("""SELECT fecha, apta_ia, motivo_ia FROM etl_imagenes WHERE project_id=? AND ruta_local IS NOT NULL
        AND origen<>'otros' AND curada IS NOT NULL""", (pid,))
    todas["bloqueo"] = todas.motivo_ia.fillna("").str.split("; ").str[0].where(todas.apta_ia == 0)  # primer motivo de bloqueo
    clima = store._df("""SELECT fecha, round(sum(lluvia_mm),1) lluvia_mm, round(max(temp),1) temp_max, round(min(temp),1) temp_min,
        round(avg(humedad)) humedad FROM etl_clima_horas WHERE project_id=? GROUP BY fecha""", (pid,)).set_index("fecha")
    # Período DESCARGADO (no todo el catálogo): en obras con ventana (config.ETL["ventana_dias"]) solo el último mes
    rango = store._filas("""SELECT min(fecha) a, max(fecha) b FROM etl_imagenes WHERE project_id=? AND origen<>'otros'
                            AND ruta_local IS NOT NULL""", (pid,))[0]
    filas = []
    for f in pd.date_range(rango["a"], rango["b"]).strftime("%Y-%m-%d"):
        dia = fotos[fotos.fecha == f]; jor = dia[(dia.hora >= j0) & (dia.hora <= j1) & dia.personas.notna()]
        con = jor[jor.personas > 0]
        if len(con):
            t = pd.to_datetime(f + " " + con.hora)
            # + un intervalo de cámara (~21 min): una sola foto con personas cuenta como ese intervalo, no como 0 h
            sitio = round((t.max() - t.min()).total_seconds() / 3600 + INTERVALO_H, 1)
            efectivas = min(float(con.hora.str[:2].nunique()), sitio)  # nunca más horas efectivas que en sitio
        else:
            sitio = efectivas = 0.0
        c = clima.loc[f] if f in clima.index else None
        lluvia = None if c is None else c.lluvia_mm
        t_dia = todas[todas.fecha == f]
        calidad = None
        if len(t_dia) and not len(dia):  # hubo fotos, ninguna apta: el motivo más frecuente (lente empañado, sobreexpuesta...)
            calidad = t_dia.bloqueo.dropna().mode().iat[0] if t_dia.bloqueo.notna().any() else "no aptas"
        filas.append(dict(fecha=f, hay_registro=int(len(dia) > 0), fotos=len(dia), fotos_total=len(t_dia), calidad=calidad,
                          personas_prom=round(jor.personas.mean(), 1) if len(jor) else 0.0, personas_max=int(jor.personas.max()) if len(jor) else 0,
                          maquinaria="", maquinaria_operando=None, horas_sitio=sitio, horas_efectivas=efectivas,
                          tiempo_muerto_h=None, lluvia_mm=lluvia if lluvia is not None else 0.0,
                          apto_trabajo=int(lluvia is None or lluvia < CLIMA["lluvia_no_apto_mm"]),
                          temp_max=None if c is None else c.temp_max, temp_min=None if c is None else c.temp_min,
                          humedad=None if c is None else c.humedad, confianza_min=None, avance_previsto=None, avance_observado=None,
                          fuente_clima=None if c is None else "Open-Meteo histórico"))
    d = pd.DataFrame(filas, columns=COLUMNAS)
    d.to_csv(OBRAS_DIR / pid / "diario.csv", index=False)
    return dict(dias=len(d), dias_con_fotos=int(d.hay_registro.sum()), dias_fotos_no_aptas=int(d.calidad.notna().sum()), desde=rango["a"], hasta=rango["b"],
                dias_con_personas=int((d.personas_max > 0).sum()))

def publicar(pid):
    """Pasos 1 a 4 (ver docstring del módulo). Requiere haber corrido listar, descargar, clima y curar; la IA
    (backend/ia_actividad.py) es opcional: sin ella las fotos salen "Sin análisis de IA" y las personas en 0."""
    etl.preparar()
    from src.ia import actividad  # crea ia_actividad si aún no existe (no importa PyTorch)
    actividad.preparar()
    (OBRAS_DIR / pid).mkdir(parents=True, exist_ok=True)
    respaldo = _respaldar(pid)
    r = dict(respaldo_sinteticos=respaldo, **_fotos(pid), **_diario(pid))
    (OBRAS_DIR / pid / "origen.json").write_text(json.dumps(dict(
        fuente="etl", descripcion="Datos reales: fotos de la cámara (Google Drive), IA preentrenada y clima histórico (Open-Meteo)",
        publicado=datetime.now().isoformat(timespec="seconds"), **r), ensure_ascii=False, indent=2), encoding="utf-8")
    return r
