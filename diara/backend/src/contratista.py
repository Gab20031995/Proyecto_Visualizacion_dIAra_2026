"""Datos que carga la EMPRESA EJECUTORA (rol contratista) y su cruce con lo que interpreta la IA.

El ingeniero de la obra (cuenta de rol "contratista") carga tres cosas en cada proyecto que tiene asignado:
    cronograma   actividades con fecha de inicio, fin y peso (%). Cada carga es una VERSIÓN nueva (historial completo)
    bitácora     una entrada por día: clima, personal, maquinaria, horas, actividades, avance reportado e incidentes
    costos       presupuesto por partidas + costos ejecutados (gastos y estimaciones de pago)

El foco del sistema es el AUDITOR: estos datos son lo que la empresa DECLARA, y cruce() los compara con lo que la IA
OBSERVA en la cámara (data/obras/<id>/diario.csv, vía metrics.load) y con el clima real consolidado:
    C-01  avance reportado en la bitácora > avance observado por la IA          (umbral reportado_vs_ia_pts)
    C-02  % del presupuesto ejecutado > avance físico observado por la IA       (umbral financiero_vs_fisico_pts)
    C-03  la bitácora declara maquinaria operando o más personal del que vio la IA
    C-04  la bitácora atribuye el paro a lluvia fuerte, pero el clima registrado fue apto
    C-05  días con actividad en cámara sin entrada de bitácora                  (umbral dias_sin_bitacora, últimos 7)
Las alertas C-xx se suman a las A-xx en metrics.resumen_obra(): aparecen en el panel, las tarjetas, el seguimiento
y el PDF. Como toda alerta, indican necesidad de revisión, no prueban un incumplimiento. Umbrales en config.UMBRALES.

Reglas de integridad (para que lo cargado sirva como evidencia):
    - la bitácora solo se corrige dentro de las 48 h siguientes a su registro; cada corrección queda en
      contratista_cambios con el valor anterior y el nuevo
    - los costos no se eliminan: se anulan con motivo (el registro original se conserva)
    - el cronograma no se edita: se carga una versión nueva
    - en obras Finalizadas o Canceladas todo queda de solo lectura

La empresa NUNCA ve el análisis de la IA ni las alertas (independencia del control): sus rutas (routes/contratista.py)
solo devuelven lo que ella misma cargó."""
import io, json, math, unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import pandas as pd
from config import UMBRALES as U
from src import store, proyectos
from src.clima.comun import ahora_cr

class ErrorContratista(ValueError):
    """Dato inválido o acción no permitida: el mensaje se muestra tal cual a la persona (las rutas responden 400)."""

CLIMAS = ["Soleado", "Nublado", "Lluvia leve", "Lluvia fuerte (trabajo detenido)"]  # el último es el que cruza C-04
TIPOS_COSTO = ["Gasto", "Estimación de pago"]
HORAS_EDICION = 48                 # ventana para corregir una entrada de bitácora
MAX_ARCHIVO = 2 * 1024 * 1024      # 2 MB por archivo de cronograma o presupuesto

# Plantillas que se descargan desde la página del contratista (mismas columnas que exige la carga)
PLANTILLA_CRONOGRAMA = ("codigo,actividad,inicio,fin,peso\n"
                        "1.1,Preliminares y trazado,2026-08-01,2026-08-15,5\n"
                        "1.2,Movimiento de tierras,2026-08-10,2026-09-10,15\n"
                        "2.1,Cimentaciones,2026-09-01,2026-10-05,20\n"
                        "3.1,Estructura y paredes,2026-09-25,2026-11-30,35\n"
                        "4.1,Techos,2026-11-15,2026-12-20,15\n"
                        "5.1,Acabados y entrega,2026-12-10,2027-01-31,10\n")
PLANTILLA_PRESUPUESTO = ("codigo,partida,monto\n"
                         "1,Obras preliminares,12000000\n"
                         "2,Movimiento de tierras,30000000\n"
                         "3,Cimentaciones y estructura,95000000\n"
                         "4,Techos,40000000\n"
                         "5,Acabados,48000000\n")

# ---------- utilidades ----------
def hoy():
    """Fecha de hoy en Costa Rica (no la del servidor, que puede estar en UTC)."""
    return ahora_cr().date()

def _ahora_utc():
    """Hora actual UTC sin zona, comparable con CURRENT_TIMESTAMP de SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def editable(p):
    """Solo las obras activas (Planificado, En ejecución, Suspendido) aceptan cargas."""
    return proyectos.activo(p)

def _verificar_editable(p):
    if not editable(p): raise ErrorContratista(f"La obra está {p['estado'].lower()}: sus datos quedan de solo lectura")

def _vacio(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())

def _txt(v):
    """Texto limpio; vacío para None/NaN (las celdas vacías de pandas llegan como NaN)."""
    return "" if _vacio(v) else str(v).strip()

def _fecha(v, campo):
    """Acepta texto AAAA-MM-DD o fechas de Excel (Timestamp/datetime). Devuelve date."""
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    try: return date.fromisoformat(_txt(v)[:10])
    except ValueError: raise ErrorContratista(f"{campo}: fecha no válida (use AAAA-MM-DD)") from None

def _num(v, campo, minimo=None, maximo=None, entero=False, requerido=False):
    """Número validado. Acepta coma decimal. None si viene vacío y no es requerido."""
    if _vacio(v):
        if requerido: raise ErrorContratista(f"{campo}: dato obligatorio")
        return None
    try: x = float(str(v).replace(",", ".")) if isinstance(v, str) else float(v)
    except ValueError: raise ErrorContratista(f"{campo}: debe ser un número") from None
    if minimo is not None and x < minimo: raise ErrorContratista(f"{campo}: no puede ser menor que {minimo}")
    if maximo is not None and x > maximo: raise ErrorContratista(f"{campo}: no puede ser mayor que {maximo}")
    return int(round(x)) if entero else x

def _registrar_cambio(pid, tabla, rid, accion, antes, despues, usuario):
    """Bitácora de auditoría de todo lo que la empresa carga, corrige o anula."""
    store._q("INSERT INTO contratista_cambios(project_id,tabla,registro_id,accion,antes,despues,usuario) VALUES(?,?,?,?,?,?,?)",
             (pid, tabla, rid, accion, json.dumps(antes, ensure_ascii=False, default=str) if antes is not None else None,
              json.dumps(despues, ensure_ascii=False, default=str), usuario))

def cambios(pid, limite=50):
    """Últimas cargas, correcciones y anulaciones de la empresa en una obra (para el auditor)."""
    return store._filas("SELECT * FROM contratista_cambios WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limite))

# ---------- lectura de archivos (CSV o Excel) ----------
def _columna(c):
    """'Código ' -> 'codigo': minúsculas, sin tildes ni espacios, para no depender de cómo se escribió el encabezado."""
    c = unicodedata.normalize("NFKD", str(c)).encode("ascii", "ignore").decode().strip().lower()
    return c.replace(" ", "_")

def leer_tabla(nombre, data, requeridas):
    """CSV (coma o punto y coma, UTF-8 o Latin-1) o Excel .xlsx -> DataFrame con columnas normalizadas."""
    if not data: raise ErrorContratista("El archivo está vacío")
    if len(data) > MAX_ARCHIVO: raise ErrorContratista("El archivo supera 2 MB")
    ext = (nombre or "").lower().rsplit(".", 1)[-1]
    try:
        if ext == "csv":
            try: txt = data.decode("utf-8-sig")
            except UnicodeDecodeError: txt = data.decode("latin-1")  # CSV guardado desde Excel en Windows
            df = pd.read_csv(io.StringIO(txt), sep=None, engine="python", dtype=str)  # sep=None: detecta , o ;
        elif ext == "xlsx":
            df = pd.read_excel(io.BytesIO(data))
        else:
            raise ErrorContratista("Formato no admitido: use CSV o Excel (.xlsx)")
    except ErrorContratista: raise
    except Exception: raise ErrorContratista("No se pudo leer el archivo: revise que sea un CSV o Excel válido") from None
    df.columns = [_columna(c) for c in df.columns]
    faltan = [c for c in requeridas if c not in df.columns]
    if faltan: raise ErrorContratista("Faltan columnas: " + ", ".join(faltan) + ". Descargue la plantilla para ver el formato.")
    df = df.dropna(how="all")
    if df.empty: raise ErrorContratista("El archivo no tiene filas de datos")
    return df

# ---------- cronograma ----------
def cargar_cronograma(p, nombre, data, version, notas, autor):
    """Valida el archivo y lo guarda como versión nueva. Los pesos se normalizan para sumar 100 %."""
    _verificar_editable(p)
    df = leer_tabla(nombre, data, ["actividad", "inicio", "fin", "peso"])
    acts = []
    for i, r in enumerate(df.to_dict("records"), start=2):  # fila 2 = primera fila de datos en Excel
        act = _txt(r.get("actividad"))
        if not act: raise ErrorContratista(f"Fila {i}: falta el nombre de la actividad")
        ini, fin = _fecha(r.get("inicio"), f"Fila {i}, inicio"), _fecha(r.get("fin"), f"Fila {i}, fin")
        if fin < ini: raise ErrorContratista(f"Fila {i}: la fecha de fin es anterior a la de inicio")
        peso = _num(r.get("peso"), f"Fila {i}, peso", minimo=0, requerido=True)
        if peso <= 0: raise ErrorContratista(f"Fila {i}: el peso debe ser mayor que 0")
        acts.append((_txt(r.get("codigo")), act[:200], ini.isoformat(), fin.isoformat(), peso))
    total = sum(a[4] for a in acts)
    n = store._filas("SELECT COUNT(*) n FROM cronogramas WHERE project_id=?", (p["id"],))[0]["n"]
    version = _txt(version)[:40] or f"v{n + 1}"
    with closing(store._c()) as c, c:  # versión y actividades en una sola transacción
        cid = c.execute("INSERT INTO cronogramas(project_id,version,notas,archivo,autor) VALUES(?,?,?,?,?)",
                        (p["id"], version, _txt(notas)[:500], (nombre or "")[:120], autor)).lastrowid
        c.executemany("INSERT INTO cronograma_actividades(cronograma_id,codigo,actividad,inicio,fin,peso) VALUES(?,?,?,?,?,?)",
                      [(cid, a[0], a[1], a[2], a[3], round(a[4] * 100 / total, 3)) for a in acts])
    _registrar_cambio(p["id"], "cronogramas", cid, "carga", None, dict(version=version, actividades=len(acts), archivo=nombre), autor)
    return dict(id=cid, version=version, actividades=len(acts), pesos_normalizados=abs(total - 100) > 0.01)

def planificado(acts, dia):
    """% planificado acumulado a un día. Cada actividad aporta su peso en proporción lineal a los días transcurridos."""
    tot = 0.0
    for a in acts:
        ini, fin = date.fromisoformat(a["inicio"]), date.fromisoformat(a["fin"])
        dur = (fin - ini).days + 1
        tot += a["peso"] * min(max((dia - ini).days + 1, 0), dur) / dur
    return round(tot, 1)

def curva(acts, puntos=60):
    """Curva S del cronograma: [{f, v}] con ~60 puntos entre el inicio y el fin del cronograma."""
    if not acts: return []
    ini = min(date.fromisoformat(a["inicio"]) for a in acts); fin = max(date.fromisoformat(a["fin"]) for a in acts)
    paso = max(1, (fin - ini).days // puntos)
    dias = [ini + timedelta(days=k) for k in range(0, (fin - ini).days + 1, paso)]
    if dias[-1] != fin: dias.append(fin)
    return [dict(f=d.isoformat(), v=planificado(acts, d)) for d in dias]

def cronograma(pid):
    """Versión vigente (la última cargada) con sus actividades, curva S, avance planificado a hoy e historial de versiones."""
    vers = store._filas("""SELECT id, version, notas, archivo, autor, creado,
                             (SELECT COUNT(*) FROM cronograma_actividades a WHERE a.cronograma_id=cronogramas.id) actividades
                           FROM cronogramas WHERE project_id=? ORDER BY id DESC""", (pid,))
    if not vers: return dict(vigente=None, actividades=[], versiones=[], curva=[], planificado_hoy=None)
    acts = store._filas("SELECT codigo, actividad, inicio, fin, peso FROM cronograma_actividades WHERE cronograma_id=? ORDER BY inicio, id", (vers[0]["id"],))
    return dict(vigente=vers[0], actividades=acts, versiones=vers, curva=curva(acts), planificado_hoy=planificado(acts, hoy()))

# ---------- bitácora de obra ----------
def guardar_bitacora(p, d, autor):
    """Crea la entrada del día o la corrige si se registró hace menos de 48 h. Devuelve {id, corregida}."""
    _verificar_editable(p)
    f = _fecha(d.get("fecha"), "Fecha")
    if f > hoy(): raise ErrorContratista("No se puede registrar una fecha futura")
    if p.get("fecha_inicio") and f < date.fromisoformat(p["fecha_inicio"]): raise ErrorContratista("La fecha es anterior al inicio de la obra")
    if d.get("clima") not in CLIMAS: raise ErrorContratista("Seleccione el clima del día")
    fila = dict(clima=d["clima"],
                personal=_num(d.get("personal"), "Personal en sitio", 0, 5000, entero=True, requerido=True),
                maquinaria=_txt(d.get("maquinaria"))[:300],
                maquinaria_operando=1 if d.get("maquinaria_operando") else 0,
                horas_trabajo=_num(d.get("horas_trabajo"), "Horas trabajadas", 0, 24),
                actividades=_txt(d.get("actividades"))[:3000],
                avance_reportado=_num(d.get("avance_reportado"), "Avance acumulado", 0, 100),
                incidentes=_txt(d.get("incidentes"))[:2000])
    if not fila["actividades"]: raise ErrorContratista("Describa las actividades realizadas en el día")
    previa = store._filas("SELECT * FROM bitacora WHERE project_id=? AND fecha=?", (p["id"], f.isoformat()))
    if previa:
        prev = previa[0]
        if _ahora_utc() - datetime.fromisoformat(prev["creado"]) > timedelta(hours=HORAS_EDICION):
            raise ErrorContratista(f"La entrada del {f:%d/%m/%Y} se registró hace más de {HORAS_EDICION} h y ya no se puede "
                                   "corregir. Anote la aclaración en la bitácora de hoy.")
        store._q("UPDATE bitacora SET " + ",".join(f"{k}=?" for k in fila) + ", autor=?, actualizado=CURRENT_TIMESTAMP WHERE id=?",
                 (*fila.values(), autor, prev["id"]))
        _registrar_cambio(p["id"], "bitacora", prev["id"], "corrección", {k: prev[k] for k in fila}, fila, autor)
        return dict(id=prev["id"], corregida=True)
    rid = store._q("INSERT INTO bitacora(project_id,fecha," + ",".join(fila) + ",autor) VALUES(" + ",".join("?" * (len(fila) + 3)) + ")",
                   (p["id"], f.isoformat(), *fila.values(), autor)).lastrowid
    return dict(id=rid, corregida=False)

def bitacora(pid, limite=120):
    """Entradas más recientes primero. editable: aún dentro de las 48 h; dias_atraso: días entre la fecha y su registro."""
    filas = store._filas("SELECT * FROM bitacora WHERE project_id=? ORDER BY fecha DESC LIMIT ?", (pid, limite))
    ahora = _ahora_utc()
    for b in filas:
        creado = datetime.fromisoformat(b["creado"])
        b["editable"] = ahora - creado <= timedelta(hours=HORAS_EDICION)
        b["dias_atraso"] = max((creado.date() - date.fromisoformat(b["fecha"])).days, 0)
    return filas

# ---------- presupuesto y costos ----------
def cargar_presupuesto(p, nombre, data, autor):
    """Carga o actualiza partidas por código (las que no vienen en el archivo se conservan)."""
    _verificar_editable(p)
    df = leer_tabla(nombre, data, ["codigo", "partida", "monto"])
    filas, vistos = [], set()
    for i, r in enumerate(df.to_dict("records"), start=2):
        cod, nom = _txt(r.get("codigo")), _txt(r.get("partida"))
        if not cod or not nom: raise ErrorContratista(f"Fila {i}: faltan el código o el nombre de la partida")
        if cod in vistos: raise ErrorContratista(f"Fila {i}: el código {cod} está repetido")
        vistos.add(cod)
        filas.append((p["id"], cod[:20], nom[:200], _num(r.get("monto"), f"Fila {i}, monto", minimo=0, requerido=True), autor))
    antes = store._filas("SELECT COALESCE(SUM(monto),0) t FROM presupuesto_partidas WHERE project_id=?", (p["id"],))[0]["t"]
    with closing(store._c()) as c, c:
        c.executemany("""INSERT INTO presupuesto_partidas(project_id,codigo,partida,monto,autor) VALUES(?,?,?,?,?)
                         ON CONFLICT(project_id,codigo) DO UPDATE SET partida=excluded.partida, monto=excluded.monto,
                         autor=excluded.autor, actualizado=CURRENT_TIMESTAMP""", filas)
    total = store._filas("SELECT COALESCE(SUM(monto),0) t FROM presupuesto_partidas WHERE project_id=?", (p["id"],))[0]["t"]
    _registrar_cambio(p["id"], "presupuesto_partidas", None, "carga", dict(total=antes), dict(total=total, partidas=len(filas), archivo=nombre), autor)
    return dict(partidas=len(filas), total=total)

def registrar_costo(p, d, autor):
    """Registra un gasto o una estimación de pago imputada a una partida del presupuesto."""
    _verificar_editable(p)
    f = _fecha(d.get("fecha"), "Fecha")
    if f > hoy(): raise ErrorContratista("No se puede registrar una fecha futura")
    partida = _txt(d.get("partida"))
    if not store._filas("SELECT 1 FROM presupuesto_partidas WHERE project_id=? AND codigo=?", (p["id"], partida)):
        raise ErrorContratista("Seleccione una partida del presupuesto (cargue primero el presupuesto por partidas)")
    if d.get("tipo") not in TIPOS_COSTO: raise ErrorContratista("Seleccione el tipo de costo")
    monto = _num(d.get("monto"), "Monto", minimo=0, requerido=True)
    if monto <= 0: raise ErrorContratista("El monto debe ser mayor que 0")
    desc = _txt(d.get("descripcion"))[:500]
    if not desc: raise ErrorContratista("Describa el costo")
    rid = store._q("INSERT INTO costos(project_id,fecha,partida,tipo,descripcion,monto,documento,autor) VALUES(?,?,?,?,?,?,?,?)",
                   (p["id"], f.isoformat(), partida, d["tipo"], desc, monto, _txt(d.get("documento"))[:60], autor)).lastrowid
    return dict(id=rid)

def anular_costo(p, cid, motivo, autor):
    """Anula (no borra) un costo; el motivo queda guardado. LookupError si el costo no es de esta obra."""
    _verificar_editable(p)
    motivo = _txt(motivo)
    if len(motivo) < 5: raise ErrorContratista("Indique el motivo de la anulación (mínimo 5 caracteres)")
    f = store._filas("SELECT * FROM costos WHERE id=? AND project_id=?", (cid, p["id"]))
    if not f: raise LookupError
    if f[0]["estado"] == "Anulado": raise ErrorContratista("El costo ya estaba anulado")
    store._q("UPDATE costos SET estado='Anulado', motivo_anulacion=? WHERE id=?", (motivo, cid))
    _registrar_cambio(p["id"], "costos", cid, "anulación", dict(estado="Vigente", monto=f[0]["monto"]), dict(estado="Anulado", motivo=motivo), autor)

def costos(p):
    """Partidas con lo ejecutado en cada una, lista de costos y totales (solo cuentan los costos vigentes)."""
    pid = p["id"]
    partidas = store._filas("SELECT codigo, partida, monto FROM presupuesto_partidas WHERE project_id=? ORDER BY codigo", (pid,))
    lista = store._filas("SELECT * FROM costos WHERE project_id=? ORDER BY fecha DESC, id DESC", (pid,))
    por = {}
    for c in lista:
        if c["estado"] == "Vigente": por[c["partida"]] = por.get(c["partida"], 0) + c["monto"]
    for pa in partidas:
        pa["ejecutado"] = round(por.get(pa["codigo"], 0), 2)
        pa["pct"] = round(100 * pa["ejecutado"] / pa["monto"], 1) if pa["monto"] else None
    presupuesto = round(sum(pa["monto"] for pa in partidas), 2) or None
    ejecutado = round(sum(por.values()), 2)
    return dict(partidas=partidas, costos=lista, presupuesto=presupuesto, monto_contrato=p.get("monto_crc"), ejecutado=ejecutado,
                pct_ejecutado=round(100 * ejecutado / presupuesto, 1) if presupuesto else None,
                saldo=round(presupuesto - ejecutado, 2) if presupuesto else None)

# ---------- resumen para la página de la empresa (sin datos de la IA) ----------
def resumen(p):
    """Tarjeta de un proyecto en el Home del contratista: solo lo que la empresa cargó."""
    cr, co = cronograma(p["id"]), costos(p)
    ult = store._filas("SELECT fecha, avance_reportado FROM bitacora WHERE project_id=? ORDER BY fecha DESC LIMIT 1", (p["id"],))
    return dict(id=p["id"], nombre=p["nombre"], institucion=p["institucion"], ubicacion=p["ubicacion"], estado_obra=p["estado"],
                editable=editable(p), fecha_inicio=p.get("fecha_inicio"), fecha_fin=p.get("fecha_fin"),
                cronograma=cr["vigente"]["version"] if cr["vigente"] else None, planificado_hoy=cr["planificado_hoy"],
                ultima_bitacora=ult[0]["fecha"] if ult else None, avance_reportado=ult[0]["avance_reportado"] if ult else None,
                dias_sin_bitacora=(hoy() - date.fromisoformat(ult[0]["fecha"])).days if ult else None,
                pct_ejecutado=co["pct_ejecutado"], presupuesto=co["presupuesto"])

# ---------- cruce con la IA (para el auditor) ----------
def _contratista_asignado(pid):
    return bool(store._filas("""SELECT 1 FROM asignaciones a JOIN usuarios u ON u.id=a.usuario_id
                                WHERE a.project_id=? AND u.rol='contratista' AND u.activo=1""", (pid,)))

def cruce(p, d=None):
    """Compara lo declarado por la empresa con lo observado por la IA y el clima real.
    d: registro diario de metrics.load (se pasa cuando ya está cargado, para no leerlo dos veces).
    Devuelve los indicadores, la comparación día a día y las alertas C-01..C-05."""
    pid = p["id"]
    bit = store._filas("SELECT fecha, clima, personal, maquinaria, maquinaria_operando, avance_reportado FROM bitacora WHERE project_id=? ORDER BY fecha", (pid,))
    cr, co = cronograma(pid), costos(p)
    out = dict(asignado=_contratista_asignado(pid), tiene_datos=bool(bit or cr["vigente"] or co["partidas"]),
               cronograma=cr["vigente"]["version"] if cr["vigente"] else None, planificado_contratista=None,
               reportado=None, reportado_fecha=None, observado=None, corte=None, pct_financiero=co["pct_ejecutado"],
               dias=[], dias_contradiccion=0, dias_clima=0, dias_sin_bitacora=None, alertas=[])
    if d is None and p["datos"]:
        from src import metrics  # import local: metrics importa este módulo
        d = metrics.load(pid)
    if d is None or not len(d): return out
    reg = d[d.hay_registro == 1]
    if not len(reg): return out
    corte = reg.fecha.max().date(); obs = _o(reg.iloc[-1].avance_observado)
    out.update(corte=corte.isoformat(), observado=obs)
    if cr["actividades"]: out["planificado_contratista"] = planificado(cr["actividades"], corte)
    rep = [b for b in bit if b["avance_reportado"] is not None and b["fecha"] <= corte.isoformat()]
    if rep: out.update(reportado=rep[-1]["avance_reportado"], reportado_fecha=rep[-1]["fecha"])
    # Día a día: solo los días con bitácora Y registro de cámara
    por_dia = {r.fecha.date().isoformat(): r for r in reg.itertuples()}
    contra, clima_mal = [], []
    for b in bit:
        r = por_dia.get(b["fecha"])
        if r is None: continue
        motivos = []
        if b["maquinaria_operando"] == 1 and r.maquinaria_operando == 0:
            motivos.append("Declara maquinaria operando; la IA no detectó maquinaria en operación")
        if b["personal"] is not None and b["personal"] > r.personas_max + max(3, r.personas_max * 0.5):
            motivos.append(f"Declara {b['personal']} personas; la IA vio como máximo {int(r.personas_max)}")
        if motivos: contra.append(b["fecha"])
        if b["clima"] == CLIMAS[3] and r.apto_trabajo == 1:
            motivos.append("Atribuye el paro a lluvia fuerte, pero el clima registrado fue apto"); clima_mal.append(b["fecha"])
        out["dias"].append(dict(fecha=b["fecha"], clima=b["clima"], personal=b["personal"], personal_ia=int(r.personas_max),
                                maquinaria=b["maquinaria"], maquinaria_operando=b["maquinaria_operando"],
                                maquinaria_ia=None if pd.isna(r.maquinaria_operando) else int(r.maquinaria_operando), apto=int(r.apto_trabajo),
                                avance_reportado=b["avance_reportado"], avance_ia=_o(r.avance_observado), motivos=motivos))
    out.update(dias_contradiccion=len(contra), dias_clima=len(clima_mal))
    fechas_bit = {b["fecha"] for b in bit}
    sin = [r.fecha.date().isoformat() for r in reg.tail(7).itertuples() if r.personas_max > 0 and r.fecha.date().isoformat() not in fechas_bit]
    if out["asignado"]: out["dias_sin_bitacora"] = len(sin)  # sin empresa asignada no se le puede exigir bitácora
    out["alertas"] = _alertas(out, contra, clima_mal, sin)
    return out

def _o(v):
    """Avance observado como float, o None si la IA aún no lo mide (datos reales: columna vacía en diario.csv)."""
    return None if pd.isna(v) else float(v)

def _rango(fechas):
    a, b = date.fromisoformat(fechas[0]), date.fromisoformat(fechas[-1])
    return f"{a:%d-%b}" if a == b else f"{a:%d-%b} a {b:%d-%b}"

def _alertas(x, contra, clima_mal, sin):
    """Alertas C-xx con el mismo formato que src/alerts.py (codigo, gravedad, periodo, descripcion, regla)."""
    out, corte = [], f"Corte {date.fromisoformat(x['corte']):%d-%b}"
    # C-01 y C-02 comparan contra el avance observado: no aplican mientras la IA no lo mida (observado None)
    if x["reportado"] is not None and x["observado"] is not None and x["reportado"] - x["observado"] > U["reportado_vs_ia_pts"]:
        dif = round(x["reportado"] - x["observado"], 1)
        out.append(dict(codigo="C-01", gravedad="ALTA" if dif >= 2 * U["reportado_vs_ia_pts"] else "MEDIA", periodo=corte,
            descripcion=f"La empresa reporta {x['reportado']}% de avance; la IA observa {x['observado']}% ({dif} pts menos).",
            regla=f"Avance reportado - observado > {U['reportado_vs_ia_pts']} pts"))
    if x["pct_financiero"] is not None and x["observado"] is not None and x["pct_financiero"] - x["observado"] > U["financiero_vs_fisico_pts"]:
        out.append(dict(codigo="C-02", gravedad="ALTA", periodo=corte,
            descripcion=f"Se ha ejecutado el {x['pct_financiero']}% del presupuesto con {x['observado']}% de avance físico observado.",
            regla=f"% financiero - % físico > {U['financiero_vs_fisico_pts']} pts"))
    if contra:
        out.append(dict(codigo="C-03", gravedad="ALTA" if len(contra) >= 3 else "MEDIA", periodo=_rango(contra),
            descripcion=f"{len(contra)} día(s) en que la bitácora declara maquinaria o personal que la IA no observó.",
            regla="Bitácora con maquinaria operando o personal mayor al detectado por la IA"))
    if clima_mal:
        out.append(dict(codigo="C-04", gravedad="ALTA" if len(clima_mal) >= 2 else "MEDIA", periodo=_rango(clima_mal),
            descripcion=f"{len(clima_mal)} día(s) en que la bitácora justifica el paro por lluvia fuerte con clima registrado apto.",
            regla="Bitácora: lluvia fuerte · clima consolidado: apto"))
    if x["dias_sin_bitacora"] is not None and x["dias_sin_bitacora"] >= U["dias_sin_bitacora"]:
        out.append(dict(codigo="C-05", gravedad="MEDIA", periodo=_rango(sin),
            descripcion=f"{len(sin)} de los últimos 7 días con actividad en cámara no tienen entrada de bitácora.",
            regla=f">= {U['dias_sin_bitacora']} días sin bitácora en los últimos 7 con registro"))
    return out
