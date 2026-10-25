"""Clima real por obra: consulta varias fuentes, guarda sus datos y los consolida en un registro limpio por día.

Fuentes (automáticas): Google Weather, Open-Meteo, Meteoblue y Meteosource (cada una se activa con su clave).

Registro consolidado por día (observado):
  1. Valor del día: la MEDIANA de las fuentes con el día completo (resiste a una fuente con un valor atípico).
  2. Confianza: alta si 2+ modelos coinciden (diferencia ≤ CLIMA['discrepancia_mm']), media con un solo modelo,
     baja si los modelos discrepan o solo hay datos parciales. Las discrepancias se marcan para revisión.

Flujo de datos (todo queda en la base, tablas clima_*):
    actualizar(p) ──> por cada fuente activa:
        historial_horas  ──> clima_horas             (upsert por obra+hora+fuente; conserva la fecha de primera captura)
        pronostico_dias  ──> clima_dias              (último pronóstico, upsert)
                         ──> clima_pronosticos_hist  (foto diaria, para medir precisión)
        resultado        ──> clima_ejecuciones       (bitácora)
    registrar_consolidado(pid) ──> cruce() ──> clima_registro (+ clima_registro_cambios si un día cambia)

Lectores: registro() (panel, PDF), pronostico(), actual() (en vivo con caché), precision(), exportar_csv().
metrics.load() usa reemplazar_en_diario() para que las alertas usen el clima real donde exista."""
import json, time, uuid
from contextlib import closing
from datetime import date
from statistics import median
import pandas as pd
from config import CLIMA
from src import store, proyectos
from src.clima import google, openmeteo, meteoblue, meteosource
from src.clima.comun import ErrorClima, ahora_cr

PROVEEDORES = [google, openmeteo, meteoblue, meteosource]  # para agregar una fuente: crear su módulo (ver comun.py) y sumarlo aquí
PRIORIDAD_CONDICION = ["google", "meteosource", "openmeteo", "meteoblue"]  # para el texto del estado del tiempo
ETIQUETAS = {p.NOMBRE: p.ETIQUETA for p in PROVEEDORES}

def activos():
    """Proveedores configurados (con clave, o Open-Meteo activo)."""
    return [p for p in PROVEEDORES if p.configurado()]

def _muchos(sql, filas):
    """executemany en una sola transacción."""
    with closing(store._c()) as c, c: c.executemany(sql, filas)

def _ubicada(p):
    return p.get("lat") not in ("", None) and p.get("lng") not in ("", None)

def _coords(p):
    if not _ubicada(p): raise ErrorClima(f"{p['id']} no tiene coordenadas: complételas en Administración → Proyectos")
    return float(p["lat"]), float(p["lng"])

def _med(vals, dec=1):
    """Mediana ignorando None/NaN, redondeada (None si no hay valores)."""
    vals = [float(x) for x in vals if x is not None and not pd.isna(x)]
    return round(median(vals), dec) if vals else None

# ---------- actualización ----------
# Upserts: ON CONFLICT ... DO UPDATE actualiza el valor (una fuente puede revisar su dato) sin tocar `creado`.
_SQL_HORAS = """INSERT INTO clima_horas(project_id,hora,fecha,fuente,lluvia_mm,temp,humedad,prob_tormenta,viento_kmh,condicion,creado,actualizado)
  VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
  ON CONFLICT(project_id,hora,fuente) DO UPDATE SET lluvia_mm=excluded.lluvia_mm, temp=excluded.temp, humedad=excluded.humedad,
  prob_tormenta=excluded.prob_tormenta, viento_kmh=excluded.viento_kmh, condicion=excluded.condicion, actualizado=CURRENT_TIMESTAMP"""
_SQL_PRON = """INSERT INTO clima_dias(project_id,fecha,fuente,tipo,lluvia_mm,temp_max,temp_min,humedad,prob_lluvia,prob_tormenta,viento_kmh,condicion,creado,actualizado)
  VALUES(?,?,?,'pronostico',?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
  ON CONFLICT(project_id,fecha,fuente,tipo) DO UPDATE SET lluvia_mm=excluded.lluvia_mm, temp_max=excluded.temp_max, temp_min=excluded.temp_min,
  humedad=excluded.humedad, prob_lluvia=excluded.prob_lluvia, prob_tormenta=excluded.prob_tormenta, viento_kmh=excluded.viento_kmh,
  condicion=excluded.condicion, actualizado=CURRENT_TIMESTAMP"""
# Historial de pronósticos: la clave incluye `emitido` (día de la consulta), así cada día queda su propia foto.
_SQL_HIST = """INSERT INTO clima_pronosticos_hist(project_id,fuente,emitido,fecha_objetivo,anticipacion_dias,lluvia_mm,temp_max,temp_min,prob_lluvia,viento_kmh,condicion)
  VALUES(?,?,?,?,?,?,?,?,?,?,?)
  ON CONFLICT(project_id,fuente,emitido,fecha_objetivo) DO UPDATE SET lluvia_mm=excluded.lluvia_mm, temp_max=excluded.temp_max,
  temp_min=excluded.temp_min, prob_lluvia=excluded.prob_lluvia, viento_kmh=excluded.viento_kmh, condicion=excluded.condicion, capturado=CURRENT_TIMESTAMP"""

def actualizar(p, lote=None, origen="manual"):
    """Consulta todas las fuentes activas para una obra y lo guarda todo. Un error en una fuente no detiene a las demás."""
    lat, lng = _coords(p); res = []; lote = lote or uuid.uuid4().hex[:12]  # lote: agrupa en la bitácora las filas de una misma corrida
    emitido = ahora_cr().date()
    for prov in activos():
        t0 = time.time()
        try:
            horas = prov.historial_horas(lat, lng)
            _muchos(_SQL_HORAS, [(p["id"], h["hora"], h["fecha"], prov.NOMBRE, h["lluvia_mm"], h["temp"], h["humedad"], h["prob_tormenta"], h["viento_kmh"], h["condicion"]) for h in horas])
            pron = prov.pronostico_dias(lat, lng, CLIMA["pronostico_dias"])
            _muchos(_SQL_PRON, [(p["id"], d["fecha"], prov.NOMBRE, d["lluvia_mm"], d["temp_max"], d["temp_min"], d["humedad"], d["prob_lluvia"], d["prob_tormenta"], d["viento_kmh"], d["condicion"]) for d in pron])
            _muchos(_SQL_HIST, [(p["id"], prov.NOMBRE, emitido.isoformat(), d["fecha"], (date.fromisoformat(d["fecha"]) - emitido).days,
                                 d["lluvia_mm"], d["temp_max"], d["temp_min"], d["prob_lluvia"], d["viento_kmh"], d["condicion"]) for d in pron])
            r = dict(fuente=prov.ETIQUETA, ok=True, horas=len(horas), pronostico=len(pron))
        except ErrorClima as e:
            r = dict(fuente=prov.ETIQUETA, ok=False, error=str(e))
        store._q("INSERT INTO clima_ejecuciones(lote,origen,project_id,fuente,ok,horas,pronostico,error,duracion_s) VALUES(?,?,?,?,?,?,?,?,?)",
                 (lote, origen, p["id"], prov.NOMBRE, int(r["ok"]), r.get("horas"), r.get("pronostico"), r.get("error"), round(time.time() - t0, 2)))
        res.append(r)
    reg = registrar_consolidado(p["id"], motivo=f"actualización {origen}")
    return res, reg

def actualizar_todos(origen="manual"):
    """Actualiza todas las obras con coordenadas. `ok` de cada obra: al menos una fuente respondió."""
    lote = uuid.uuid4().hex[:12]; out = []
    for p in proyectos.listar():
        if not _ubicada(p) or not proyectos.activo(p): continue  # Finalizadas y Canceladas ya no consumen consultas
        r, reg = actualizar(p, lote, origen)
        out.append(dict(proyecto=p["id"], ok=any(x["ok"] for x in r), fuentes=r, registro=reg))
    return out

# Condiciones actuales: se consultan en vivo y se guardan 15 min por obra (cada consulta consume cuota).
# Caché en memoria del proceso: se pierde al reiniciar el servidor (no hace falta persistirla).
_cache_actual = {}

def actual(p):
    """Condiciones actuales: mediana de las fuentes que respondan (lanza ErrorClima solo si ninguna respondió)."""
    lat, lng = _coords(p)
    t, dato = _cache_actual.get(p["id"], (0, None))
    if dato and time.time() - t < 900: return dato
    fuentes, errores = [], []
    for prov in activos():
        try:
            a = prov.actual(lat, lng)
            if a: fuentes.append(dict(a, fuente=prov.ETIQUETA, nombre=prov.NOMBRE))
        except ErrorClima as e: errores.append(str(e))
    if not fuentes: raise ErrorClima("; ".join(errores) or "No hay fuentes de clima configuradas")
    cond = next((f["condicion"] for n in PRIORIDAD_CONDICION for f in fuentes if f["nombre"] == n and f.get("condicion")), None)
    dato = dict(temp=_med([f["temp"] for f in fuentes]), humedad=_med([f["humedad"] for f in fuentes], 0),
                viento_kmh=_med([f["viento_kmh"] for f in fuentes], 0), prob_lluvia=_med([f.get("prob_lluvia") for f in fuentes], 0),
                prob_tormenta=_med([f.get("prob_tormenta") for f in fuentes], 0), condicion=cond, fuentes=fuentes, errores=errores)
    _cache_actual[p["id"]] = (time.time(), dato)
    return dato

# ---------- registro consolidado ----------
def dias_modelos(pid):
    """Agrega por día y por fuente las horas observadas guardadas."""
    h = store._df("SELECT * FROM clima_horas WHERE project_id=?", (pid,))
    if h.empty: return pd.DataFrame(columns=["fuente", "fecha", "lluvia_mm", "temp_max", "temp_min", "humedad", "prob_tormenta", "horas"])
    return h.groupby(["fuente", "fecha"]).agg(lluvia_mm=("lluvia_mm", "sum"), temp_max=("temp", "max"), temp_min=("temp", "min"),
                                             humedad=("humedad", "mean"), prob_tormenta=("prob_tormenta", "max"), horas=("hora", "count")).reset_index()

def _apto(lluvia, parcial):
    """1 apto, 0 no apto, None sin certeza. Con datos parciales solo se puede afirmar 'no apto'."""
    # Si con pocas horas la lluvia ya superó el umbral, el día seguro fue no apto; si llovió poco, pudo llover después.
    if lluvia is None: return None
    if lluvia >= CLIMA["lluvia_no_apto_mm"]: return 0
    return None if parcial else 1

def cruce(pid, dias=30):
    """Calcula (sin guardar) el registro consolidado de los últimos `dias` con datos. Ver reglas en el docstring del módulo."""
    m = dias_modelos(pid)
    fechas = sorted(set(m.fecha))[-dias:]
    U = CLIMA["discrepancia_mm"]; out = []
    for f in fechas:
        md = m[m.fecha == f]
        por_fuente = {r.fuente: dict(lluvia_mm=round(float(r.lluvia_mm), 1), horas=int(r.horas)) for r in md.itertuples()}
        comp = md[md.horas >= CLIMA["horas_dia_completo"]]  # solo fuentes con el día completo
        n = len(comp); consenso = _med(comp.lluvia_mm); disp = round(float(comp.lluvia_mm.max() - comp.lluvia_mm.min()), 1) if n >= 2 else None
        parcial = False
        if n:
            lluvia, fuente = consenso, f"Consenso de {n} modelos" if n > 1 else ETIQUETAS.get(comp.fuente.iloc[0], comp.fuente.iloc[0])
            discrep = disp is not None and disp > U
            confianza = "baja" if discrep else ("alta" if n >= 2 else "media")
        elif len(md):
            # Ninguna fuente completa (p. ej. el día de hoy): se toma el máximo parcial y solo puede afirmarse "no apto"
            lluvia, fuente, parcial = round(float(md.lluvia_mm.max()), 1), "Datos parciales", True
            discrep, confianza = False, "baja"
        else:
            continue
        base = comp if n else md
        out.append(dict(fecha=f, lluvia_mm=lluvia, fuente=fuente, confianza=confianza, discrepancia=bool(discrep),
                        consenso_modelos=consenso, dispersion_mm=disp, n_modelos=n, por_fuente=por_fuente,
                        temp_max=_med(base.temp_max), temp_min=_med(base.temp_min), humedad=_med(base.humedad, 0),
                        prob_tormenta=_med(md.prob_tormenta, 0), apto_trabajo=_apto(lluvia, parcial)))
    return out

def pronostico(pid):
    """Pronóstico consolidado: mediana de las fuentes por día y grado de acuerdo entre ellas."""
    hoy = ahora_cr().strftime("%Y-%m-%d")
    d = store._df("SELECT * FROM clima_dias WHERE project_id=? AND tipo='pronostico' AND fecha>=? ORDER BY fecha", (pid, hoy))
    out = []
    for f, g in d.groupby("fecha"):
        ll = [x for x in g.lluvia_mm if not pd.isna(x)]
        disp = round(max(ll) - min(ll), 1) if len(ll) >= 2 else None
        cond = next((r.condicion for n in PRIORIDAD_CONDICION for r in g.itertuples() if r.fuente == n and r.condicion), None)
        lluvia = _med(g.lluvia_mm)
        out.append(dict(fecha=f, lluvia_mm=lluvia, temp_max=_med(g.temp_max), temp_min=_med(g.temp_min), prob_lluvia=_med(g.prob_lluvia, 0),
                        viento_kmh=_med(g.viento_kmh, 0), condicion=cond, n_fuentes=len(g), dispersion_mm=disp,
                        acuerdo=None if disp is None else ("alto" if disp <= CLIMA["discrepancia_mm"] else "bajo"),
                        por_fuente={r.fuente: None if pd.isna(r.lluvia_mm) else round(float(r.lluvia_mm), 1) for r in g.itertuples()},
                        apto_previsto=None if lluvia is None else int(lluvia < CLIMA["lluvia_no_apto_mm"])))
    return out[:CLIMA["pronostico_dias"]]

# ---------- registro consolidado guardado (análisis y seguimiento) ----------
_SEGUIDOS = ["lluvia_mm", "fuente", "confianza", "apto_trabajo", "discrepancia"]  # cambios que se auditan
_COLS_REG = ["lluvia_mm", "fuente", "confianza", "discrepancia", "consenso_modelos", "dispersion_mm", "n_modelos",
             "temp_max", "temp_min", "humedad", "prob_tormenta", "apto_trabajo", "por_fuente"]

def _txt(x):
    """Normaliza para comparar valores de la base con los recalculados (bool -> "0"/"1", números -> texto)."""
    return None if x is None else str(int(x) if isinstance(x, bool) else x)

def registrar_consolidado(pid, motivo="recalculo", dias=None):
    """Recalcula el registro consolidado y lo guarda. Cada cambio sobre un día ya registrado queda en clima_registro_cambios."""
    filas = cruce(pid, dias or CLIMA["dias_recalculo"])
    previos = {r["fecha"]: r for r in store._filas("SELECT * FROM clima_registro WHERE project_id=?", (pid,))}
    nuevos = cambiados = 0
    with closing(store._c()) as c, c:  # todo en una transacción
        for d in filas:
            val = dict(d, discrepancia=int(d["discrepancia"]), por_fuente=json.dumps(d["por_fuente"], ensure_ascii=False))
            ant = previos.get(d["fecha"])
            if ant is None:
                c.execute(f"INSERT INTO clima_registro(project_id,fecha,{','.join(_COLS_REG)}) VALUES(?,?{',?' * len(_COLS_REG)})",
                          (pid, d["fecha"], *[val[k] for k in _COLS_REG])); nuevos += 1; continue
            # Se actualiza si cambió cualquier columna; en la auditoría solo se registran los campos de _SEGUIDOS
            difs = [(k, _txt(ant[k]), _txt(val[k])) for k in _SEGUIDOS if _txt(ant[k]) != _txt(val[k])]
            if difs or any(_txt(ant[k]) != _txt(val[k]) for k in _COLS_REG):
                c.execute(f"UPDATE clima_registro SET {', '.join(k + '=?' for k in _COLS_REG)}, actualizado=CURRENT_TIMESTAMP WHERE project_id=? AND fecha=?",
                          (*[val[k] for k in _COLS_REG], pid, d["fecha"]))
                c.executemany("INSERT INTO clima_registro_cambios(project_id,fecha,campo,antes,despues,motivo) VALUES(?,?,?,?,?,?)",
                              [(pid, d["fecha"], k, a, b, motivo) for k, a, b in difs])
                cambiados += bool(difs)
    return dict(dias=len(filas), nuevos=nuevos, cambiados=cambiados)

def registro(pid, dias=30):
    """Lee el registro consolidado guardado (más reciente al final)."""
    f = store._filas("SELECT * FROM clima_registro WHERE project_id=? ORDER BY fecha DESC LIMIT ?", (pid, dias))
    for r in f:
        r["por_fuente"] = json.loads(r["por_fuente"] or "{}"); r["discrepancia"] = bool(r["discrepancia"])
    return f[::-1]

def cambios(pid, limite=50):
    """Auditoría de cambios del registro de una obra (más recientes primero)."""
    return store._filas("SELECT fecha, campo, antes, despues, motivo, cambiado FROM clima_registro_cambios WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limite))

def ejecuciones(limite=40):
    return store._filas("SELECT * FROM clima_ejecuciones ORDER BY id DESC LIMIT ?", (limite,))

def precision(pid=None, max_anticipacion=5):
    """Compara lo pronosticado por cada fuente con lo registrado después. Error absoluto medio de lluvia (mm),
    sesgo (+ sobreestima) y acierto en predecir si el día sería apto para trabajar."""
    # Se excluyen días con confianza 'baja' del registro: no sirven como "verdad" para evaluar a las fuentes
    q = """SELECT h.fuente, h.anticipacion_dias a, h.lluvia_mm pron, r.lluvia_mm real, r.apto_trabajo apto
           FROM clima_pronosticos_hist h JOIN clima_registro r ON r.project_id=h.project_id AND r.fecha=h.fecha_objetivo
           WHERE h.lluvia_mm IS NOT NULL AND r.lluvia_mm IS NOT NULL AND r.confianza<>'baja' AND h.anticipacion_dias BETWEEN 0 AND ?""" + (" AND h.project_id=?" if pid else "")
    d = store._df(q, (max_anticipacion, pid) if pid else (max_anticipacion,))
    if d.empty: return []
    d["err"] = d.pron - d.real
    d["acierto"] = ((d.pron < CLIMA["lluvia_no_apto_mm"]).astype(int) == d.apto).where(d.apto.notna())
    g = d.groupby(["fuente", "a"]).agg(n=("err", "size"), mae=("err", lambda x: x.abs().mean()), sesgo=("err", "mean"), acierto=("acierto", "mean")).reset_index()
    return [dict(fuente=ETIQUETAS.get(r.fuente, r.fuente), anticipacion_dias=int(r.a), comparaciones=int(r.n), error_medio_mm=round(float(r.mae), 2),
                 sesgo_mm=round(float(r.sesgo), 2), acierto_apto=None if pd.isna(r.acierto) else round(float(r.acierto) * 100)) for r in g.itertuples()]

# Lista cerrada de tablas exportables: el nombre que llega por URL se traduce aquí, nunca se usa directo en el SQL.
EXPORTABLES = {"registro": "clima_registro", "horas": "clima_horas", "pronosticos": "clima_pronosticos_hist",
               "cambios": "clima_registro_cambios", "ejecuciones": "clima_ejecuciones"}

def exportar_csv(tabla, pid=None):
    t = EXPORTABLES[tabla]
    filtro = []
    if pid: filtro.append("project_id=?")
    d = store._df(f"SELECT * FROM {t}" + (" WHERE " + " AND ".join(filtro) if filtro else ""), (pid,) if pid else ())
    return d.to_csv(index=False).encode("utf-8-sig")  # con BOM para que Excel lea bien los acentos

def estado_fuentes():
    """Para Administración: fuentes configuradas y qué tiene guardado cada obra."""
    h = store._df("SELECT project_id, fuente, COUNT(*) horas, MAX(hora) ultima FROM clima_horas GROUP BY project_id, fuente")
    pr = store._df("SELECT project_id, fuente, COUNT(*) dias FROM clima_dias WHERE tipo='pronostico' GROUP BY project_id, fuente")
    obras = []
    for p in proyectos.listar():
        por = {}
        for prov in PROVEEDORES:
            hh = h[(h.project_id == p["id"]) & (h.fuente == prov.NOMBRE)]; pp = pr[(pr.project_id == p["id"]) & (pr.fuente == prov.NOMBRE)]
            por[prov.NOMBRE] = dict(horas=int(hh.horas.iloc[0]) if len(hh) else 0, ultima=hh.ultima.iloc[0] if len(hh) else None,
                                    pronostico=int(pp.dias.iloc[0]) if len(pp) else 0)
        obras.append(dict(id=p["id"], nombre=p["nombre"], ubicada=_ubicada(p), fuentes=por))
    return dict(proveedores=[dict(nombre=x.NOMBRE, etiqueta=x.ETIQUETA, configurado=x.configurado(), historial=x.HISTORIAL, atribucion=x.ATRIBUCION) for x in PROVEEDORES],
                proyectos=obras)

def atribuciones():
    """Textos de atribución de las fuentes activas (exigidos por sus licencias; se muestran en el panel)."""
    return [x.ATRIBUCION for x in activos()]

def reemplazar_en_diario(pid, d):
    """Sustituye en el registro diario (cámara) los datos de clima por los consolidados, donde sean concluyentes."""
    real = {c["fecha"]: c for c in registro(pid, dias=1000) if c["apto_trabajo"] is not None}  # solo días concluyentes del registro guardado
    if not real: return d
    d = d.copy()
    # columna informativa: de dónde salió el clima de cada día. Los datos reales (src/etl/publicar.py) ya la traen
    # ("Open-Meteo histórico"); en los sintéticos (make_data.py) no existe y se marca "sintético"
    if "fuente_clima" not in d: d["fuente_clima"] = "sintético"
    for idx, f in d.fecha.dt.strftime("%Y-%m-%d").items():
        c = real.get(f)
        if not c: continue
        d.loc[idx, ["lluvia_mm", "apto_trabajo", "fuente_clima"]] = [c["lluvia_mm"], c["apto_trabajo"], c["fuente"]]
        for col in ("temp_max", "temp_min", "humedad"):
            if c[col] is not None: d.loc[idx, col] = c[col]
    return d
