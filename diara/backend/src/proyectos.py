"""Catálogo de obras: tabla `proyectos` de la base (administrada desde /admin) y carpeta de datos data/obras/<id>/.

Cada proyecto es un dict con las columnas de la tabla más tres campos calculados (ver _publico):
    ubicacion   "distrito, cantón, provincia" para mostrar (sin repetir nombres iguales seguidos: "Cieneguita, Limón")
    datos       True si existe data/obras/<id>/diario.csv (registro diario de la IA)
    camara_api  True si tiene token de cámara configurado

También contiene la validación de los formularios de proyecto y la gestión del token de la API de cámaras.
La primera carga de la tabla se hace desde data/proyectos.csv (ver store._sembrar_proyectos)."""
import hashlib, hmac, re, secrets
from contextlib import closing
from datetime import date
from config import OBRAS_DIR
from src import store

PROVINCIAS = ["San José", "Alajuela", "Cartago", "Heredia", "Guanacaste", "Puntarenas", "Limón"]
ESTADOS = ["Planificado", "En ejecución", "Suspendido", "Finalizado", "Cancelado"]
# Ciclo de vida de una obra: transiciones permitidas -> nombre de la acción en la interfaz.
# Cancelado es definitivo; Finalizado se puede reabrir (por si se cerró por error). Cada cambio queda en proyectos_historial.
TRANSICIONES = {
    "Planificado":  {"En ejecución": "Iniciar", "Cancelado": "Cancelar"},
    "En ejecución": {"Suspendido": "Suspender", "Finalizado": "Cerrar", "Cancelado": "Cancelar"},
    "Suspendido":   {"En ejecución": "Reanudar", "Finalizado": "Cerrar", "Cancelado": "Cancelar"},
    "Finalizado":   {"En ejecución": "Reabrir"},
    "Cancelado":    {},
}
ACTIVOS = ("Planificado", "En ejecución", "Suspendido")  # obras que se siguen monitoreando (clima y reportes)
# Límites de Costa Rica (territorio continental e Isla del Coco), para validar coordenadas.
# Es un rectángulo aproximado: detecta errores típicos (lat/lng invertidas, signo faltante), no valida la frontera exacta.
CR_CONTINENTAL = dict(lat=(8.0, 11.25), lng=(-86.0, -82.5))
CR_ISLA_COCO = dict(lat=(5.4, 5.65), lng=(-87.2, -86.9))
# Columnas editables desde el formulario (el orden importa: se usa para armar los INSERT/UPDATE)
CAMPOS = ["nombre", "descripcion", "institucion", "contratista", "contratacion", "monto_crc", "provincia", "canton", "distrito",
          "direccion", "lat", "lng", "camara", "cronograma", "fecha_inicio", "fecha_fin", "estado"]

class ErrorProyecto(Exception):
    """Error de validación con mensaje listo para mostrar al usuario (las rutas lo convierten en HTTP 400)."""
    pass

def _publico(r):
    """Fila de la base -> dict para la app (nunca incluye el hash del token)."""
    r = dict(r); r["camara_api"] = bool(r.pop("token_camara", None))
    partes = [x for x in (r.get("distrito"), r.get("canton"), r.get("provincia")) if x]
    # "Limón, Limón" o "Cartago, Cartago" no aportan: se omite un nombre igual al anterior
    r["ubicacion"] = ", ".join(x for i, x in enumerate(partes) if i == 0 or x != partes[i - 1])
    r["datos"] = tiene_datos(r["id"])
    return r

def listar():
    return [_publico(r) for r in store._filas("SELECT * FROM proyectos ORDER BY id")]

def obtener(pid):
    """Proyecto por id, o None si no existe."""
    f = store._filas("SELECT * FROM proyectos WHERE id=?", (pid,))
    return _publico(f[0]) if f else None

def carpeta(pid):
    """Carpeta de datos de la obra: diario.csv y camara/ (imágenes)."""
    return OBRAS_DIR / pid

def tiene_datos(pid):
    """La obra tiene registro diario de la IA (avance, recursos detectados)."""
    return (OBRAS_DIR / pid / "diario.csv").is_file()

# ---------- validación ----------
def en_costa_rica(lat, lng):
    dentro = lambda b: b["lat"][0] <= lat <= b["lat"][1] and b["lng"][0] <= lng <= b["lng"][1]
    return dentro(CR_CONTINENTAL) or dentro(CR_ISLA_COCO)

def validar(d):
    """Normaliza y valida los datos de un proyecto. Lanza ErrorProyecto con un mensaje para el usuario."""
    x = {k: (d.get(k).strip() if isinstance(d.get(k), str) else d.get(k)) for k in CAMPOS}
    x = {k: (None if v == "" else v) for k, v in x.items()}  # textos vacíos se guardan como NULL
    if not x["nombre"] or len(x["nombre"]) < 3: raise ErrorProyecto("Indique el nombre del proyecto")
    if not x["institucion"]: raise ErrorProyecto("Indique la institución responsable")
    if x["provincia"] not in PROVINCIAS: raise ErrorProyecto("Seleccione una provincia válida")
    if not x["canton"]: raise ErrorProyecto("Indique el cantón")
    if x["estado"] not in ESTADOS: raise ErrorProyecto("Estado no válido")
    # Coordenadas obligatorias: se usan para el clima real y el mapa
    try:
        x["lat"] = float(x["lat"]); x["lng"] = float(x["lng"])
    except (TypeError, ValueError):
        raise ErrorProyecto("Latitud y longitud son obligatorias y deben ser números (ej. 9.9795 y -83.0408)") from None
    if not en_costa_rica(x["lat"], x["lng"]):
        raise ErrorProyecto("Las coordenadas no están en Costa Rica. Revise el orden (latitud ≈ 8 a 11, longitud ≈ -86 a -82.5) y el signo negativo de la longitud")
    if x["monto_crc"] is not None:
        try: x["monto_crc"] = float(x["monto_crc"])
        except (TypeError, ValueError): raise ErrorProyecto("El monto debe ser un número") from None
        if x["monto_crc"] < 0: raise ErrorProyecto("El monto no puede ser negativo")
    for f in ("fecha_inicio", "fecha_fin"):
        if x[f]:
            try: date.fromisoformat(x[f])
            except ValueError: raise ErrorProyecto("Fecha no válida (use AAAA-MM-DD)") from None
    # Comparación de texto válida porque ambas fechas están en formato ISO (AAAA-MM-DD)
    if x["fecha_inicio"] and x["fecha_fin"] and x["fecha_fin"] < x["fecha_inicio"]:
        raise ErrorProyecto("La fecha de fin no puede ser anterior a la de inicio")
    # El código de cámara se imprime en imágenes y nombres de archivo: solo caracteres seguros
    if x["camara"] and not re.fullmatch(r"[A-Za-z0-9_-]{2,30}", x["camara"]):
        raise ErrorProyecto("El código de cámara solo admite letras, números, guion y guion bajo")
    return x

# ---------- altas y cambios ----------
def _siguiente_id():
    """Id correlativo: P-001, P-002... (ignora ids con otro formato)."""
    nums = [int(r["id"][2:]) for r in store._filas("SELECT id FROM proyectos") if re.fullmatch(r"P-\d+", r["id"])]
    return f"P-{max(nums, default=0) + 1:03d}"

def crear(d, usuario=None):
    """Valida, inserta y crea la carpeta de datos. Devuelve el id nuevo."""
    x = validar(d)
    if x["estado"] not in ("Planificado", "En ejecución"):
        raise ErrorProyecto("Un proyecto nuevo solo puede crearse como Planificado o En ejecución")
    if store._filas("SELECT 1 FROM proyectos WHERE lower(nombre)=lower(?)", (x["nombre"],)):
        raise ErrorProyecto("Ya existe un proyecto con ese nombre")
    pid = _siguiente_id()
    # Los nombres de columna vienen de CAMPOS (constante), nunca del usuario; los valores van como parámetros (?)
    store._q(f"INSERT INTO proyectos(id,{','.join(CAMPOS)}) VALUES(?{',?' * len(CAMPOS)})", (pid, *[x[k] for k in CAMPOS]))
    carpeta(pid).mkdir(parents=True, exist_ok=True)
    store._q("INSERT INTO proyectos_historial(project_id,estado_anterior,estado_nuevo,motivo,usuario) VALUES(?,?,?,?,?)",
             (pid, None, x["estado"], "Creación del proyecto", usuario))
    return pid

def actualizar(pid, d):
    """Reemplaza los campos editables del proyecto (el formulario siempre envía el conjunto completo).
    El ESTADO no se cambia aquí: se conserva el actual (los cambios de estado van por cambiar_estado, con motivo e historial)."""
    actual = obtener(pid)
    if not actual: raise ErrorProyecto("Proyecto no encontrado")
    x = validar({**d, "estado": actual["estado"]})
    if store._filas("SELECT 1 FROM proyectos WHERE lower(nombre)=lower(?) AND id<>?", (x["nombre"], pid)):
        raise ErrorProyecto("Ya existe otro proyecto con ese nombre")
    store._q(f"UPDATE proyectos SET {', '.join(k + '=?' for k in CAMPOS)}, actualizado=CURRENT_TIMESTAMP WHERE id=?",
             (*[x[k] for k in CAMPOS], pid))

def cambiar_estado(pid, nuevo, motivo, usuario):
    """Aplica una transición del ciclo de vida (ver TRANSICIONES). El motivo es obligatorio y queda en el historial."""
    p = obtener(pid)
    if not p: raise ErrorProyecto("Proyecto no encontrado")
    permitidas = TRANSICIONES.get(p["estado"], {})
    if nuevo not in permitidas:
        raise ErrorProyecto(f"No se puede pasar de «{p['estado']}» a «{nuevo}»"
                            + (f". Opciones: {', '.join(permitidas)}" if permitidas else ". El proyecto está cerrado definitivamente"))
    motivo = (motivo or "").strip()
    if len(motivo) < 5: raise ErrorProyecto("Indique el motivo del cambio (mínimo 5 caracteres)")
    with closing(store._c()) as c, c:  # estado e historial en la misma transacción
        c.execute("UPDATE proyectos SET estado=?, actualizado=CURRENT_TIMESTAMP WHERE id=?", (nuevo, pid))
        c.execute("INSERT INTO proyectos_historial(project_id,estado_anterior,estado_nuevo,motivo,usuario) VALUES(?,?,?,?,?)",
                  (pid, p["estado"], nuevo, motivo[:500], usuario))
    return obtener(pid)

def historial(pid=None, limite=100):
    """Cambios de estado (más recientes primero), de un proyecto o de todos."""
    sql = "SELECT h.*, p.nombre FROM proyectos_historial h LEFT JOIN proyectos p ON p.id=h.project_id"
    if pid: return store._filas(sql + " WHERE h.project_id=? ORDER BY h.id DESC LIMIT ?", (pid, limite))
    return store._filas(sql + " ORDER BY h.id DESC LIMIT ?", (limite,))

def activo(p):
    """True si la obra se sigue monitoreando (no está Finalizada ni Cancelada)."""
    return p.get("estado") in ACTIVOS

# ---------- token de la API de imágenes ----------
# Se guarda solo el SHA-256 del token (como una contraseña): si alguien lee la base, no obtiene tokens utilizables.
# token_pista guarda los últimos 4 caracteres para que el admin identifique cuál está activo.
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def generar_token(pid):
    """Crea un token nuevo para la cámara (invalida el anterior). Se devuelve una sola vez; en la base queda el hash."""
    token = "dia_" + secrets.token_urlsafe(32)  # el prefijo "dia_" ayuda a reconocerlo (p. ej. en escáneres de secretos)
    store._q("UPDATE proyectos SET token_camara=?, token_pista=?, actualizado=CURRENT_TIMESTAMP WHERE id=?", (_hash(token), token[-4:], pid))
    return token

def revocar_token(pid):
    store._q("UPDATE proyectos SET token_camara=NULL, token_pista=NULL WHERE id=?", (pid,))

def token_valido(pid, token):
    """True si `token` corresponde al proyecto `pid` (el token de una obra no sirve para otra)."""
    f = store._filas("SELECT token_camara FROM proyectos WHERE id=?", (pid,))
    return bool(f and f[0]["token_camara"] and token and hmac.compare_digest(f[0]["token_camara"], _hash(token)))
