"""Catálogo de obras: tabla `proyectos` de la base (administrada desde /admin) y carpeta de datos data/obras/<id>/.

Cada proyecto es un dict con las columnas de la tabla más estos campos calculados (ver _publico):
    ubicacion            "distrito, cantón, provincia" para mostrar (sin repetir nombres iguales seguidos: "Cieneguita, Limón")
    datos                True si existe data/obras/<id>/diario.csv (registro diario de la IA)
    camara_api           True si tiene token de cámara configurado
    fotos_esperadas_dia  fotos que debería enviar la cámara por día según su frecuencia y horario (None si no se definió)
    etl_excluir          se entrega como lista [{desde, hasta, motivo}] (en la base es texto JSON)

Configuración de la cámara y del ETL por obra (se edita en Administración → Proyectos → Editar):
    captura_intervalo_min, captura_desde, captura_hasta   frecuencia y horario de captura esperados (ítem ADM-01)
    drive_carpeta, etl_rotacion, etl_nitidez_min, etl_ventana_dias, etl_excluir   ETL desde Drive (ítem ADM-03);
        antes estaban escritos en config.ETL. El ETL los lee con config_etl(pid).

También contiene la validación de los formularios de proyecto y la gestión del token de la API de cámaras.
La primera carga de la tabla se hace desde data/proyectos.csv (ver store._sembrar_proyectos)."""
import hashlib, hmac, json, re, secrets
from contextlib import closing
from datetime import date
from config import OBRAS_DIR, ETL
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
          "direccion", "lat", "lng", "camara", "cronograma", "fecha_inicio", "fecha_fin", "estado",
          # captura esperada (ADM-01) y ETL desde Drive (ADM-03); detalle de cada columna en store.COLUMNAS_PROYECTO_NUEVAS
          "captura_intervalo_min", "captura_desde", "captura_hasta",
          "drive_carpeta", "etl_rotacion", "etl_nitidez_min", "etl_ventana_dias", "etl_excluir"]
ROTACIONES = (0, 90, 180, 270)   # grados antihorarios con que se endereza la foto (180 = cámara montada de cabeza)
HORARIO_COMPLETO = ("00:00", "23:59")  # horario de captura si se indica la frecuencia sin horario (cámara de 24 h)

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
    # etl_excluir se guarda como texto JSON; a la app se entrega como lista [{desde, hasta, motivo}]
    r["etl_excluir"] = [dict(desde=a, hasta=b, motivo=m) for a, b, m in json.loads(r.get("etl_excluir") or "[]")]
    r["fotos_esperadas_dia"] = fotos_esperadas_dia(r)
    return r

def fotos_esperadas_dia(p):
    """Fotos que la cámara debería enviar en un día completo según su frecuencia y horario (ADM-01), o None si la
    frecuencia no está definida. Ej.: cada 15 min de 07:00 a 17:00 = 41 fotos (la primera a las 07:00, la última a las 17:00).
    Es la base para medir la cobertura de la cámara (fotos recibidas ÷ esperadas, alerta S-02)."""
    if not p.get("captura_intervalo_min"): return None
    minutos = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:5])
    desde, hasta = p.get("captura_desde") or HORARIO_COMPLETO[0], p.get("captura_hasta") or HORARIO_COMPLETO[1]
    return (minutos(hasta) - minutos(desde)) // int(p["captura_intervalo_min"]) + 1

def config_etl(pid):
    """Configuración del ETL de imágenes de una obra (antes en config.ETL; ahora se edita en Administración):
        carpeta       id de la carpeta de Drive (None si no tiene)
        rotacion      grados para enderezar las fotos de la cámara
        nitidez_min   umbral de nitidez de la curación (el propio de la obra o el general)
        ventana_dias  solo los últimos N días (None = todo)
        excluir       [(desde, hasta, motivo)] períodos que se descartan a mano
    Lanza ErrorProyecto si la obra no existe."""
    p = obtener(pid)
    if not p: raise ErrorProyecto(f"No existe el proyecto {pid}")
    return dict(carpeta=p["drive_carpeta"], rotacion=p["etl_rotacion"] or 0,
                nitidez_min=p["etl_nitidez_min"] if p["etl_nitidez_min"] is not None else ETL["nitidez_min"],
                ventana_dias=p["etl_ventana_dias"],
                excluir=[(e["desde"], e["hasta"], e["motivo"]) for e in p["etl_excluir"]])

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
    _validar_captura(x)
    _validar_etl(x)
    return x

def _entero(v, campo, minimo, maximo):
    """Entero entre minimo y maximo, o None si viene vacío. Acepta texto ("15") porque así llega del formulario."""
    if v is None: return None
    try: n = float(v)
    except (TypeError, ValueError): raise ErrorProyecto(f"{campo}: debe ser un número") from None
    if n != int(n) or not minimo <= n <= maximo: raise ErrorProyecto(f"{campo}: debe ser un entero entre {minimo} y {maximo}")
    return int(n)

def _validar_captura(x):
    """Frecuencia y horario de captura esperados (ADM-01). Sin frecuencia no se acepta horario (no sabríamos cuántas
    fotos esperar). Con frecuencia y sin horario se asume una cámara de 24 h (HORARIO_COMPLETO)."""
    x["captura_intervalo_min"] = _entero(x["captura_intervalo_min"], "Frecuencia de captura (minutos)", 1, 1440)
    hay_horario = x["captura_desde"] or x["captura_hasta"]
    if not x["captura_intervalo_min"]:
        if hay_horario: raise ErrorProyecto("Indique cada cuántos minutos toma fotos la cámara, o deje el horario vacío")
        return
    if not hay_horario: x["captura_desde"], x["captura_hasta"] = HORARIO_COMPLETO
    for campo in ("captura_desde", "captura_hasta"):
        if not x[campo] or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x[campo]):
            raise ErrorProyecto("Horario de captura: indique inicio y fin en formato HH:MM (ej. 07:00 y 17:00)")
    if x["captura_hasta"] <= x["captura_desde"]:  # comparación de texto válida en formato HH:MM
        raise ErrorProyecto("Horario de captura: la hora de fin debe ser posterior a la de inicio")

def _validar_etl(x):
    """Configuración del ETL de imágenes (ADM-03)."""
    # Carpeta de Drive: se acepta el enlace completo (lo que copia la persona) y se guarda solo el id
    if x["drive_carpeta"]:
        m = re.search(r"/folders/([A-Za-z0-9_-]+)", x["drive_carpeta"])
        x["drive_carpeta"] = m.group(1) if m else x["drive_carpeta"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", x["drive_carpeta"]):
            raise ErrorProyecto("Carpeta de Drive: pegue el enlace de la carpeta (…/drive/folders/<id>) o solo su id")
    x["etl_rotacion"] = _entero(x["etl_rotacion"], "Rotación de las fotos", 0, 270) or 0
    if x["etl_rotacion"] not in ROTACIONES: raise ErrorProyecto("Rotación de las fotos: use 0, 90, 180 o 270 grados")
    if x["etl_nitidez_min"] is not None:
        try: x["etl_nitidez_min"] = float(x["etl_nitidez_min"])
        except (TypeError, ValueError): raise ErrorProyecto("Nitidez mínima: debe ser un número") from None
        if not 0 < x["etl_nitidez_min"] <= 50: raise ErrorProyecto("Nitidez mínima: debe estar entre 0 y 50")
    x["etl_ventana_dias"] = _entero(x["etl_ventana_dias"], "Ventana de días", 1, 3650)
    # Períodos excluidos: lista de {desde, hasta, motivo} -> se guarda como JSON [[desde, hasta, motivo], ...]
    periodos = []
    for e in x["etl_excluir"] or []:
        desde, hasta, motivo = (str(e.get(k) or "").strip() for k in ("desde", "hasta", "motivo"))
        try: date.fromisoformat(desde); date.fromisoformat(hasta)
        except ValueError: raise ErrorProyecto("Períodos excluidos: use fechas AAAA-MM-DD") from None
        if hasta < desde: raise ErrorProyecto(f"Períodos excluidos: {hasta} es anterior a {desde}")
        if len(motivo) < 3: raise ErrorProyecto("Períodos excluidos: indique el motivo de cada período (ej. instalación de la cámara)")
        periodos.append([desde, hasta, motivo[:200]])
    x["etl_excluir"] = json.dumps(sorted(periodos), ensure_ascii=False) if periodos else None

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
