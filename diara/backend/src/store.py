"""Acceso a la base de datos SQLite (data/diara.db): esquema, migraciones y consultas de usuarios, observaciones,
aportes, suscripciones y configuración.

Cómo funciona:
  - La base se crea sola. La PRIMERA conexión del proceso ejecuta _ESQUEMA (CREATE TABLE IF NOT EXISTS), aplica las
    migraciones de bases anteriores, carga los proyectos iniciales y crea los usuarios de ejemplo (ver _c()).
  - Cada consulta abre y cierra su propia conexión (closing): simple y seguro con los hilos de FastAPI.
  - Helpers internos que usan también otros módulos (proyectos, clima, reportería):
        _q(sql, args)      ejecuta y confirma (INSERT/UPDATE/DELETE); devuelve el cursor (lastrowid, rowcount)
        _filas(sql, args)  lista de dict (para devolver como JSON)
        _df(sql, args)     DataFrame de pandas (para análisis)
  - SIEMPRE usar parámetros (?) para los valores; nunca concatenar datos del usuario en el SQL.

Para producción con varios servidores, migrar a PostgreSQL (SQLite no se comparte entre instancias)."""
import sqlite3, re, time, hashlib, hmac, secrets, pandas as pd
from contextlib import closing
from config import DB_PATH, DATA_DIR, UPLOADS_DIR, ADMIN_EMAIL, ADMIN_PASS, AUDITOR_DEMO

# ---------- esquema ----------
# Tablas (resumen; el detalle de columnas está en el SQL de abajo):
#   observaciones            notas del auditor por proyecto (fecha de la evidencia, estado, alerta e imagen relacionadas)
#   aportes                  aportes ciudadanos (texto/foto); estado Pendiente -> Revisado (publicado) o Descartado
#   suscripciones            ciudadanos que piden avisos de una obra (WhatsApp o correo)
#   usuarios                 cuentas (rol admin|auditor|contratista), clave con PBKDF2, frecuencia del reporte por correo;
#                            empresa y teléfono se usan para las cuentas de la empresa ejecutora (contratista)
#   asignaciones             qué proyectos ve cada auditor o en cuáles carga datos cada contratista (el admin ve todos)
#   cronogramas, cronograma_actividades, bitacora, presupuesto_partidas, costos, contratista_cambios
#                            datos que carga la empresa ejecutora (ver src/contratista.py)
#   proyectos                catálogo de obras (ver src/proyectos.py)
#   imagenes                 fotos recibidas por la API de cámaras (fuente 'api') o publicadas desde el ETL (fuente 'etl')
#   configuracion            clave/valor editable desde Administración (calendario y plantilla de reportes)
#   reportes_envios          bitácora de reportes por correo (enviado/simulado/error) con ruta del PDF guardado
#   clima_*                  clima real: horas por fuente, pronósticos, registro consolidado, cambios y ejecuciones
#                            (ver src/clima/__init__.py)
# Fechas: texto ISO (AAAA-MM-DD). Los campos *_creado/actualizado usan CURRENT_TIMESTAMP de SQLite (UTC).
#   proyectos_historial      cambios de estado de cada obra (iniciar, suspender, reanudar, cerrar, cancelar, reabrir)
#   etl_*                    zona de preparación del ETL de imágenes desde Drive; las crea src/etl/__init__.py, no este archivo
# Columnas agregadas después de la primera versión (frecuencia_reporte, creado en clima_*) se crean en _c() con ALTER TABLE.
_ESQUEMA = """
CREATE TABLE IF NOT EXISTS observaciones(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT DEFAULT 'P-001', fecha TEXT,
  autor TEXT, texto TEXT, estado TEXT, accion TEXT, alerta TEXT, imagen TEXT, creada TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS aportes(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, tipo TEXT, nombre TEXT,
  contacto TEXT, texto TEXT, foto TEXT, estado TEXT DEFAULT 'Pendiente', creada TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS suscripciones(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, nombre TEXT,
  canal TEXT, contacto TEXT, creada TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS usuarios(id INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT UNIQUE NOT NULL, nombre TEXT,
  rol TEXT NOT NULL CHECK(rol IN ('admin','auditor','contratista')), clave TEXT NOT NULL, activo INTEGER DEFAULT 1,
  creado TEXT DEFAULT CURRENT_TIMESTAMP, frecuencia_reporte TEXT DEFAULT 'semanal', empresa TEXT, telefono TEXT);
-- ===== Datos de la empresa ejecutora (src/contratista.py) =====
-- Cronograma: cada carga es una VERSIÓN nueva (no se sobrescribe); la vigente es la de id mayor
CREATE TABLE IF NOT EXISTS cronogramas(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, version TEXT,
  notas TEXT, archivo TEXT, autor TEXT, creado TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS cronograma_actividades(id INTEGER PRIMARY KEY AUTOINCREMENT, cronograma_id INTEGER NOT NULL
  REFERENCES cronogramas(id) ON DELETE CASCADE, codigo TEXT, actividad TEXT NOT NULL, inicio TEXT NOT NULL, fin TEXT NOT NULL,
  peso REAL NOT NULL);
-- Bitácora de obra: una entrada por obra y día (lo que la empresa declara que pasó ese día)
CREATE TABLE IF NOT EXISTS bitacora(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, fecha TEXT NOT NULL,
  clima TEXT, personal INTEGER, maquinaria TEXT, maquinaria_operando INTEGER, horas_trabajo REAL, actividades TEXT,
  avance_reportado REAL, incidentes TEXT, autor TEXT, creado TEXT DEFAULT CURRENT_TIMESTAMP, actualizado TEXT,
  UNIQUE(project_id, fecha));
-- Presupuesto por partidas y costos ejecutados (los costos no se borran: se anulan con motivo)
CREATE TABLE IF NOT EXISTS presupuesto_partidas(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, codigo TEXT NOT NULL,
  partida TEXT NOT NULL, monto REAL NOT NULL, autor TEXT, actualizado TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, codigo));
CREATE TABLE IF NOT EXISTS costos(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, fecha TEXT NOT NULL,
  partida TEXT, tipo TEXT, descripcion TEXT, monto REAL NOT NULL, documento TEXT, estado TEXT DEFAULT 'Vigente',
  motivo_anulacion TEXT, autor TEXT, creado TEXT DEFAULT CURRENT_TIMESTAMP);
-- Auditoría de lo que modifica la empresa (valor anterior y nuevo en JSON)
CREATE TABLE IF NOT EXISTS contratista_cambios(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, tabla TEXT, registro_id INTEGER,
  accion TEXT, antes TEXT, despues TEXT, usuario TEXT, fecha TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS asignaciones(usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
  project_id TEXT, PRIMARY KEY(usuario_id, project_id));
-- Catálogo de obras (administrado desde /admin). token_camara guarda solo el hash SHA-256 del token de la cámara.
CREATE TABLE IF NOT EXISTS proyectos(id TEXT PRIMARY KEY, nombre TEXT NOT NULL, descripcion TEXT, institucion TEXT NOT NULL,
  contratista TEXT, contratacion TEXT, monto_crc REAL, provincia TEXT, canton TEXT, distrito TEXT, direccion TEXT,
  lat REAL, lng REAL, camara TEXT, cronograma TEXT, fecha_inicio TEXT, fecha_fin TEXT,
  estado TEXT DEFAULT 'En ejecución', token_camara TEXT, token_pista TEXT,
  creado TEXT DEFAULT CURRENT_TIMESTAMP, actualizado TEXT DEFAULT CURRENT_TIMESTAMP);
-- Imágenes recibidas por la API de cámaras (las sintéticas siguen en data/obras/<id>/camara/indice.csv)
CREATE TABLE IF NOT EXISTS imagenes(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, archivo TEXT NOT NULL,
  fecha TEXT, hora TEXT, tomada TEXT, personas INTEGER, maquinaria INTEGER, confianza REAL,
  recibida TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, archivo));
-- Historial de cambios de estado de las obras (quién, cuándo y por qué)
CREATE TABLE IF NOT EXISTS proyectos_historial(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, estado_anterior TEXT,
  estado_nuevo TEXT NOT NULL, motivo TEXT, usuario TEXT, fecha TEXT DEFAULT CURRENT_TIMESTAMP);
-- Bloqueo para tareas automáticas: evita que dos procesos (varios workers, o el servidor y la tarea programada)
-- envíen los reportes al mismo tiempo. hasta = epoch hasta el que la tarea está tomada (0 = libre).
CREATE TABLE IF NOT EXISTS tareas_bloqueo(tarea TEXT PRIMARY KEY, hasta REAL DEFAULT 0);
-- Configuración editable desde Administración (calendario de reportes, plantilla institucional del PDF)
CREATE TABLE IF NOT EXISTS configuracion(clave TEXT PRIMARY KEY, valor TEXT, actualizado TEXT DEFAULT CURRENT_TIMESTAMP);
-- Reportería automática: cada envío (o simulación) con su período y copia del PDF
CREATE TABLE IF NOT EXISTS reportes_envios(id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER, correo TEXT, frecuencia TEXT,
  desde TEXT, hasta TEXT, proyectos TEXT, estado TEXT, origen TEXT, error TEXT, archivo TEXT, bytes INTEGER,
  creado TEXT DEFAULT CURRENT_TIMESTAMP);
-- Clima observado por hora (Google solo guarda 24 h de historial: se acumula aquí en cada actualización)
CREATE TABLE IF NOT EXISTS clima_horas(project_id TEXT, hora TEXT, fecha TEXT, fuente TEXT, lluvia_mm REAL, temp REAL,
  humedad REAL, prob_tormenta REAL, viento_kmh REAL, condicion TEXT, actualizado TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(project_id, hora, fuente));
-- Clima diario: último pronóstico de cada fuente (tipo 'pronostico')
CREATE TABLE IF NOT EXISTS clima_dias(project_id TEXT, fecha TEXT, fuente TEXT, tipo TEXT, lluvia_mm REAL, temp_max REAL,
  temp_min REAL, humedad REAL, prob_lluvia REAL, prob_tormenta REAL, viento_kmh REAL, condicion TEXT,
  actualizado TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(project_id, fecha, fuente, tipo));
-- Registro diario consolidado (fuente única de verdad para análisis, alertas y reportes)
CREATE TABLE IF NOT EXISTS clima_registro(project_id TEXT, fecha TEXT, lluvia_mm REAL, fuente TEXT, confianza TEXT,
  discrepancia INTEGER, consenso_modelos REAL, dispersion_mm REAL, n_modelos INTEGER,
  temp_max REAL, temp_min REAL, humedad REAL, prob_tormenta REAL, apto_trabajo INTEGER, por_fuente TEXT,
  creado TEXT DEFAULT CURRENT_TIMESTAMP, actualizado TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(project_id, fecha));
-- Auditoría: cada cambio de un día ya registrado (p. ej. se completan horas o una fuente revisa su dato)
CREATE TABLE IF NOT EXISTS clima_registro_cambios(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, fecha TEXT,
  campo TEXT, antes TEXT, despues TEXT, motivo TEXT, cambiado TEXT DEFAULT CURRENT_TIMESTAMP);
-- Historial de pronósticos: una foto por día de emisión, fuente y día pronosticado (no se sobrescribe entre días)
CREATE TABLE IF NOT EXISTS clima_pronosticos_hist(project_id TEXT, fuente TEXT, emitido TEXT, fecha_objetivo TEXT,
  anticipacion_dias INTEGER, lluvia_mm REAL, temp_max REAL, temp_min REAL, prob_lluvia REAL, viento_kmh REAL, condicion TEXT,
  capturado TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(project_id, fuente, emitido, fecha_objetivo));
-- Bitácora de actualizaciones de clima (una fila por obra y fuente consultada)
CREATE TABLE IF NOT EXISTS clima_ejecuciones(id INTEGER PRIMARY KEY AUTOINCREMENT, lote TEXT, origen TEXT, project_id TEXT,
  fuente TEXT, ok INTEGER, horas INTEGER, pronostico INTEGER, error TEXT, duracion_s REAL, ejecutado TEXT DEFAULT CURRENT_TIMESTAMP);
"""
# Los índices van aparte porque algunos usan columnas que en bases antiguas recién existen después de las migraciones.
_INDICES = """
CREATE INDEX IF NOT EXISTS ix_obs_proyecto ON observaciones(project_id);
CREATE INDEX IF NOT EXISTS ix_aportes_proyecto ON aportes(project_id);
CREATE INDEX IF NOT EXISTS ix_susc_proyecto ON suscripciones(project_id);
CREATE INDEX IF NOT EXISTS ix_img_proyecto ON imagenes(project_id, fecha);
CREATE INDEX IF NOT EXISTS ix_horas_fecha ON clima_horas(project_id, fecha);
CREATE INDEX IF NOT EXISTS ix_cambios ON clima_registro_cambios(project_id, fecha);
CREATE INDEX IF NOT EXISTS ix_pron_obj ON clima_pronosticos_hist(project_id, fecha_objetivo);
CREATE INDEX IF NOT EXISTS ix_ejec ON clima_ejecuciones(ejecutado);
CREATE INDEX IF NOT EXISTS ix_envios ON reportes_envios(usuario_id, frecuencia, desde);
CREATE INDEX IF NOT EXISTS ix_hist_proy ON proyectos_historial(project_id);
CREATE INDEX IF NOT EXISTS ix_crono_proy ON cronogramas(project_id);
CREATE INDEX IF NOT EXISTS ix_acts_crono ON cronograma_actividades(cronograma_id);
CREATE INDEX IF NOT EXISTS ix_costos_proy ON costos(project_id, fecha);
CREATE INDEX IF NOT EXISTS ix_cambios_contr ON contratista_cambios(project_id);
"""
_listo = False  # True después de preparar la base en la primera conexión del proceso

def _c():
    """Abre una conexión. La primera vez en el proceso también crea/migra la base y los datos iniciales."""
    global _listo
    c = sqlite3.connect(DB_PATH); c.execute("PRAGMA foreign_keys=ON")
    if not _listo:
        c.executescript(_ESQUEMA)
        # --- migraciones de bases creadas con versiones anteriores (idempotentes: se pueden ejecutar siempre) ---
        cols = [r[1] for r in c.execute("PRAGMA table_info(observaciones)")]
        for col, tipo in (("imagen", "TEXT"), ("project_id", "TEXT DEFAULT 'P-001'")):  # bases creadas antes
            if col not in cols: c.execute(f"ALTER TABLE observaciones ADD COLUMN {col} {tipo}")
        for t in ("clima_horas", "clima_dias"):  # fecha de primera captura (bases creadas antes)
            if "creado" not in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]:
                c.execute(f"ALTER TABLE {t} ADD COLUMN creado TEXT"); c.execute(f"UPDATE {t} SET creado=actualizado")
        if "frecuencia_reporte" not in [r[1] for r in c.execute("PRAGMA table_info(usuarios)")]:  # bases creadas antes
            c.execute("ALTER TABLE usuarios ADD COLUMN frecuencia_reporte TEXT DEFAULT 'semanal'")
            c.execute("UPDATE usuarios SET frecuencia_reporte='ninguno' WHERE rol='admin'")
        if "fuente" not in [r[1] for r in c.execute("PRAGMA table_info(imagenes)")]:  # 'etl' = foto real publicada desde el ETL
            c.execute("ALTER TABLE imagenes ADD COLUMN fuente TEXT DEFAULT 'api'")
        _permitir_contratista(c)
        _quitar_imn(c)
        _migrar_obra_a_proyecto(c)
        _sembrar_proyectos(c)
        c.executescript(_INDICES)
        # --- datos iniciales: solo si la base no tiene ningún usuario (config.py: ADMIN_EMAIL, ADMIN_PASS, AUDITOR_DEMO) ---
        if not c.execute("SELECT 1 FROM usuarios").fetchone():  # usuarios iniciales
            c.execute("INSERT INTO usuarios(correo,nombre,rol,clave,frecuencia_reporte) VALUES(?,?,?,?,'ninguno')", (ADMIN_EMAIL, "Administración CGR", "admin", hash_clave(ADMIN_PASS)))
            nombre, correo, clave, obras = AUDITOR_DEMO
            uid = c.execute("INSERT INTO usuarios(correo,nombre,rol,clave) VALUES(?,?,?,?)", (correo, nombre, "auditor", hash_clave(clave))).lastrowid
            c.executemany("INSERT INTO asignaciones VALUES(?,?)", [(uid, p) for p in obras])
        c.commit(); _listo = True
    return c

def _permitir_contratista(c):
    """Bases anteriores: el CHECK de usuarios.rol solo aceptaba admin/auditor y no existían empresa ni teléfono.
    SQLite no modifica un CHECK con ALTER, así que se reconstruye la tabla conservando ids, claves y datos.
    Las claves foráneas se apagan durante el cambio: si no, borrar la tabla vieja borraría en cascada las asignaciones."""
    sql = c.execute("SELECT sql FROM sqlite_master WHERE name='usuarios'").fetchone()[0]
    if "contratista" in sql: return  # ya migrada (o creada con el esquema nuevo)
    c.commit(); c.execute("PRAGMA foreign_keys=OFF")
    cols = "id,correo,nombre,rol,clave,activo,creado,frecuencia_reporte"
    c.executescript(f"""BEGIN;
        CREATE TABLE usuarios_nueva(id INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT UNIQUE NOT NULL, nombre TEXT,
          rol TEXT NOT NULL CHECK(rol IN ('admin','auditor','contratista')), clave TEXT NOT NULL, activo INTEGER DEFAULT 1,
          creado TEXT DEFAULT CURRENT_TIMESTAMP, frecuencia_reporte TEXT DEFAULT 'semanal', empresa TEXT, telefono TEXT);
        INSERT INTO usuarios_nueva({cols}) SELECT {cols} FROM usuarios;
        DROP TABLE usuarios;
        ALTER TABLE usuarios_nueva RENAME TO usuarios;
        COMMIT;""")
    c.execute("PRAGMA foreign_keys=ON")

def _quitar_imn(c):
    """La fuente IMN se eliminó: borra sus datos y columnas en bases creadas antes (SQLite >= 3.35)."""
    c.execute("DELETE FROM clima_dias WHERE fuente='imn'")
    c.execute("DELETE FROM clima_registro_cambios WHERE campo='lluvia_imn'")
    for t, col in (("proyectos", "estacion_imn"), ("clima_registro", "lluvia_imn"), ("clima_registro", "estacion_imn"), ("clima_dias", "estacion")):
        if col in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]: c.execute(f"ALTER TABLE {t} DROP COLUMN {col}")

def _sembrar_proyectos(c):
    """Primera vez: carga la tabla proyectos desde data/proyectos.csv. Después la tabla es la fuente oficial."""
    f = DATA_DIR / "proyectos.csv"
    if c.execute("SELECT 1 FROM proyectos").fetchone() or not f.exists(): return
    p = pd.read_csv(f).astype(object).where(lambda x: x.notna(), None)  # NaN -> None (NULL en SQLite)
    for r in p.to_dict("records"):
        canton, _, provincia = str(r.get("ubicacion") or "").partition(",")  # el CSV trae "Cantón, Provincia"
        c.execute("""INSERT INTO proyectos(id,nombre,institucion,estado,camara,cronograma,canton,provincia,lat,lng)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (r["project_id"], r["nombre"], r["institucion"], r.get("estado") or "En ejecución", r.get("camara"), r.get("cronograma"),
                   canton.strip() or None, provincia.strip() or None, r.get("lat"), r.get("lng")))

def _migrar_obra_a_proyecto(c):
    """Bases anteriores vinculaban aportes y suscripciones por nombre de obra: se reconstruyen con project_id."""
    mapa = None
    for t, cols in (("aportes", "tipo,nombre,contacto,texto,foto,estado,creada"), ("suscripciones", "nombre,canal,contacto,creada")):
        if "obra" not in [r[1] for r in c.execute(f"PRAGMA table_info({t})")]: continue  # ya migrada
        if mapa is None:
            p = pd.read_csv(DATA_DIR / "proyectos.csv"); mapa = dict(zip(p.nombre, p.project_id))
        # SQLite no cambia columnas con ALTER: se renombra la tabla, se crea la nueva y se copian los datos
        c.execute(f"ALTER TABLE {t} RENAME TO {t}_viejo")
        c.executescript(_ESQUEMA)
        filas = c.execute(f"SELECT id, obra, {cols} FROM {t}_viejo").fetchall()
        marcas = ",".join("?" * (len(cols.split(",")) + 2))
        c.executemany(f"INSERT INTO {t}(id, project_id, {cols}) VALUES({marcas})",
                      [(f[0], mapa.get(f[1], f[1]), *f[2:]) for f in filas])  # nombre desconocido: se conserva tal cual
        c.execute(f"DROP TABLE {t}_viejo")

# ---------- helpers de consulta ----------
def _q(sql, args=()):
    """Ejecuta y confirma una sentencia; devuelve el cursor (para lastrowid / rowcount)."""
    with closing(_c()) as c, c: return c.execute(sql, args)

def _df(sql, args=()):
    """Resultado como DataFrame de pandas."""
    with closing(_c()) as c: return pd.read_sql(sql, c, params=args)

# ---------- usuarios y asignaciones ----------
def hash_clave(clave):
    """Hash de contraseña: PBKDF2-SHA256 con sal aleatoria y 200 000 iteraciones. Formato guardado: "<sal>$<hash>"."""
    sal = secrets.token_hex(16)
    return f"{sal}${hashlib.pbkdf2_hmac('sha256', clave.encode(), sal.encode(), 200_000).hex()}"

def _clave_ok(clave, guardada):
    sal, h = guardada.split("$")
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", clave.encode(), sal.encode(), 200_000).hex(), h)

def _filas(sql, args=()):
    """Resultado como lista de dict (tipos nativos de Python, aptos para JSON)."""
    with closing(_c()) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(sql, args)]

def _con_proyectos(u):
    """Agrega al usuario la lista de ids de proyectos asignados."""
    u["proyectos"] = [r["project_id"] for r in _filas("SELECT project_id FROM asignaciones WHERE usuario_id=? ORDER BY project_id", (u["id"],))]
    return u

def autenticar(correo, clave):
    """Usuario si correo y clave son correctos y la cuenta está activa; si no, None. El correo no distingue mayúsculas."""
    f = _filas("SELECT id, clave FROM usuarios WHERE lower(correo)=lower(?) AND activo=1", ((correo or "").strip(),))
    if not f or not _clave_ok(clave or "", f[0]["clave"]): return None
    return usuario(f[0]["id"])

def usuario(uid):
    """Usuario por id (sin el hash de la clave), con sus proyectos asignados."""
    f = _filas("SELECT id,correo,nombre,rol,activo,frecuencia_reporte,empresa,telefono FROM usuarios WHERE id=?", (int(uid),))
    return _con_proyectos(f[0]) if f else None

def usuarios(rol=None):
    """Todas las cuentas (o solo las de un rol), con sus proyectos asignados."""
    sql = "SELECT id,correo,nombre,rol,activo,frecuencia_reporte,empresa,telefono,creado FROM usuarios"
    return [_con_proyectos(u) for u in _filas(sql + (" WHERE rol=?" if rol else "") + " ORDER BY rol, nombre", (rol,) if rol else ())]

ROLES = ("admin", "auditor", "contratista")

def crear_usuario(correo, nombre, clave, rol="auditor", empresa=None, telefono=None):
    """Devuelve el id nuevo, o None si el correo ya existe (UNIQUE). Los contratistas no reciben reportes por correo."""
    try: return _q("INSERT INTO usuarios(correo,nombre,rol,clave,empresa,telefono,frecuencia_reporte) VALUES(?,?,?,?,?,?,?)",
                   (correo.strip().lower(), nombre.strip(), rol, hash_clave(clave), (empresa or "").strip() or None,
                    (telefono or "").strip() or None, "ninguno" if rol == "contratista" else "semanal")).lastrowid
    except sqlite3.IntegrityError: return None

FRECUENCIAS = ["ninguno", "diario", "semanal", "quincenal"]  # frecuencia del reporte por correo (src/reporteria.py)

def actualizar_usuario(uid, nombre=None, activo=None, clave=None, frecuencia=None, correo=None, empresa=None, telefono=None):
    """Cambios parciales: solo se actualiza lo que no es None. Si el correo ya lo usa otra cuenta, lanza ValueError."""
    if empresa is not None: _q("UPDATE usuarios SET empresa=? WHERE id=?", (empresa.strip() or None, uid))
    if telefono is not None: _q("UPDATE usuarios SET telefono=? WHERE id=?", (telefono.strip() or None, uid))
    if correo is not None:
        try: _q("UPDATE usuarios SET correo=? WHERE id=?", (correo.strip().lower(), uid))
        except sqlite3.IntegrityError: raise ValueError("Ya existe otra cuenta con ese correo") from None
    if frecuencia is not None:
        if frecuencia not in FRECUENCIAS: raise ValueError("Frecuencia no válida")
        _q("UPDATE usuarios SET frecuencia_reporte=? WHERE id=?", (frecuencia, uid))
    if nombre is not None: _q("UPDATE usuarios SET nombre=? WHERE id=?", (nombre.strip(), uid))
    if activo is not None: _q("UPDATE usuarios SET activo=? WHERE id=?", (int(activo), uid))
    if clave: _q("UPDATE usuarios SET clave=? WHERE id=?", (hash_clave(clave), uid))

def asignar(pid, usuario_ids, rol="auditor"):
    """Define el conjunto completo de personas de UN rol asignadas a un proyecto (auditores o contratistas).
    Solo borra las asignaciones de ese rol: asignar auditores no toca a la empresa ejecutora y viceversa."""
    with closing(_c()) as c, c:  # borrar e insertar en la misma transacción: nunca queda a medias
        c.execute("DELETE FROM asignaciones WHERE project_id=? AND usuario_id IN (SELECT id FROM usuarios WHERE rol=?)", (pid, rol))
        c.executemany("INSERT INTO asignaciones VALUES(?,?)", [(int(u), pid) for u in usuario_ids])

# ---------- observaciones del auditor ----------
def add(pid, fecha, autor, texto, estado, accion, alerta, imagen=None):
    _q("INSERT INTO observaciones(project_id,fecha,autor,texto,estado,accion,alerta,imagen) VALUES(?,?,?,?,?,?,?,?)",
       (pid, str(fecha), autor, texto, estado, accion, alerta, imagen))

def set_observacion(pid, i, estado):
    """Devuelve True si la observación existía en ese proyecto."""
    return _q("UPDATE observaciones SET estado=? WHERE id=? AND project_id=?", (estado, i, pid)).rowcount > 0

def listar(pid):
    """Observaciones de un proyecto, más recientes primero."""
    return _df("SELECT * FROM observaciones WHERE project_id=? ORDER BY id DESC", (pid,))

# ---------- aportes ciudadanos y suscripciones ----------
def guardar_foto(nombre, data):
    """Guarda la foto en data/uploads y devuelve la ruta relativa a data/ (ej. 'uploads/123_foto.jpg')."""
    # El nombre original se limpia (solo caracteres seguros) y se le antepone la hora para no pisar archivos
    nombre = f"{int(time.time())}_{re.sub(r'[^A-Za-z0-9._-]', '_', nombre)}"
    (UPLOADS_DIR / nombre).write_bytes(data); return f"uploads/{nombre}"

def add_aporte(pid, tipo, nombre, contacto, texto, foto=None):
    _q("INSERT INTO aportes(project_id,tipo,nombre,contacto,texto,foto) VALUES(?,?,?,?,?,?)",
       (pid, tipo, nombre, contacto, texto, foto))

def aportes(pid=None, solo_revisados=False):
    """Aportes (de un proyecto o de todos). solo_revisados=True: solo los publicados."""
    w, a = [], []
    if pid: w.append("project_id=?"); a.append(pid)
    if solo_revisados: w.append("estado='Revisado'")
    return _df("SELECT * FROM aportes" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY id DESC", a)

def foto_publica(ruta):
    """True si la foto pertenece a un aporte ya aprobado (las pendientes solo las ve el auditor)."""
    return not _df("SELECT 1 FROM aportes WHERE foto=? AND estado='Revisado'", (ruta,)).empty

def proyecto_de_foto(ruta):
    """Obra a la que pertenece la foto de un aporte (para validar quién puede verla mientras está pendiente)."""
    f = _filas("SELECT project_id FROM aportes WHERE foto=?", (ruta,))
    return f[0]["project_id"] if f else None

def set_aporte(pid, i, estado):
    """Devuelve True si el aporte existía en ese proyecto."""
    return _q("UPDATE aportes SET estado=? WHERE id=? AND project_id=?", (estado, i, pid)).rowcount > 0

def suscribir(pid, nombre, canal, contacto):
    _q("INSERT INTO suscripciones(project_id,nombre,canal,contacto) VALUES(?,?,?,?)", (pid, nombre, canal, contacto))

def suscripciones(pid=None):
    return _df("SELECT * FROM suscripciones" + (" WHERE project_id=?" if pid else "") + " ORDER BY id DESC", (pid,) if pid else ())

# ---------- configuración general (clave/valor) ----------
# Claves en uso: reporte_dia_semanal, reporte_dias_quincenal, plantilla_* (ver reporteria.DEFECTO)
def config_leer():
    return {r["clave"]: r["valor"] for r in _filas("SELECT clave, valor FROM configuracion")}

def config_guardar(valores: dict):
    """Inserta o actualiza varias claves en una sola transacción (upsert)."""
    with closing(_c()) as c, c:
        c.executemany("""INSERT INTO configuracion(clave, valor) VALUES(?, ?)
                         ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor, actualizado=CURRENT_TIMESTAMP""",
                      [(k, None if v is None else str(v)) for k, v in valores.items()])
