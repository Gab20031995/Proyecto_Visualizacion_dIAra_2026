"""Sesión: token firmado (HMAC) con el id del usuario, guardado en una cookie HttpOnly.
En cada petición se vuelve a leer el usuario de la base, así un cambio de rol o una desactivación aplica de inmediato.

Formato del token:   base64("<id_usuario>|<vence_epoch>") + "." + HMAC-SHA256(SECRET_KEY, "<id_usuario>|<vence_epoch>")
No guarda datos sensibles: solo el id y la fecha de vencimiento. Sin la clave del servidor no se puede falsificar.
Si SECRET_KEY no está definida, se genera una al arrancar: reiniciar el servidor cierra todas las sesiones.
Las dependencias que usan esto en las rutas están en routes/sesion.py."""
import base64, hashlib, hmac, secrets, time
from config import SECRET_KEY, SESION_HORAS
from src import store

COOKIE = "diara_sesion"
_KEY = (SECRET_KEY or secrets.token_hex(32)).encode()

def _firma(datos):
    return hmac.new(_KEY, datos.encode(), hashlib.sha256).hexdigest()

def crear_token(uid):
    """Token de sesión para el usuario `uid`, válido SESION_HORAS horas."""
    datos = f"{uid}|{int(time.time()) + SESION_HORAS * 3600}"
    return base64.urlsafe_b64encode(datos.encode()).decode() + "." + _firma(datos)

def usuario(token):
    """Devuelve el usuario (dict) si el token es válido, no venció y el usuario sigue activo; si no, None."""
    try:
        b64, firma = token.split(".")
        datos = base64.urlsafe_b64decode(b64).decode()
        uid, vence = datos.split("|")
        # compare_digest compara en tiempo constante (no filtra información por tiempos de respuesta)
        if hmac.compare_digest(firma, _firma(datos)) and time.time() < int(vence):
            u = store.usuario(int(uid))
            return u if u and u["activo"] else None
    except Exception:
        pass  # token mal formado o manipulado: se trata igual que "sin sesión"
    return None

def puede_ver(u, pid):
    """Acceso a la VISTA DEL AUDITOR de un proyecto (análisis de la IA, observaciones, aportes): el admin ve todo; el
    auditor, solo lo que tiene asignado. El contratista NUNCA: es la parte fiscalizada y no debe ver el análisis."""
    return u["rol"] == "admin" or (u["rol"] == "auditor" and pid in u["proyectos"])

def puede_cargar(u, pid):
    """Acceso a la página de la empresa ejecutora (routes/contratista.py): solo contratistas con el proyecto asignado."""
    return u["rol"] == "contratista" and pid in u["proyectos"]
