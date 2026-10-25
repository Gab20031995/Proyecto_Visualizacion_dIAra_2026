"""Sesión y permisos: login, logout, usuario actual y las DEPENDENCIAS de permisos que usan las demás rutas.

Cómo proteger una ruta nueva (FastAPI Depends):
    def ruta(u: dict = Depends(usuario_actual))          -> requiere sesión (cualquier rol)
    def ruta(u: dict = Depends(admin_actual))            -> requiere rol admin (403 si no)
    def ruta(p: dict = Depends(proyecto_permitido))      -> vista del auditor: {pid} asignado a un auditor (o ser admin)
    def ruta(u: dict = Depends(contratista_actual))      -> requiere rol contratista (empresa ejecutora)
    def ruta(p: dict = Depends(obra_contratista))        -> {pid} asignado al contratista de la sesión
Roles: admin (todo), auditor (fiscaliza sus proyectos), contratista (carga cronograma, bitácora y costos de sus
proyectos; nunca ve el análisis de la IA). Las reglas están en src/auth.py (puede_ver, puede_cargar).

La sesión es una cookie HttpOnly firmada (ver src/auth.py). JavaScript no puede leerla; el navegador la envía sola."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from config import SESION_HORAS
from src import auth, store, proyectos

router = APIRouter()

# ---------- dependencias de permisos ----------
def usuario_actual(request: Request):
    """Usuario de la sesión. 401 si no hay cookie, si venció o si el usuario fue desactivado."""
    u = auth.usuario(request.cookies.get(auth.COOKIE, ""))
    if not u: raise HTTPException(401, "Sesión no válida o vencida")
    return u

def admin_actual(u: dict = Depends(usuario_actual)):
    """Usuario de la sesión con rol admin (403 para auditores)."""
    if u["rol"] != "admin": raise HTTPException(403, "Solo para administradores")
    return u

def proyecto_permitido(pid: str, u: dict = Depends(usuario_actual)):
    """Valida que el proyecto exista y que el usuario lo tenga asignado (o sea admin)."""
    p = proyectos.obtener(pid)
    # Se responde 404 (no 403) también cuando no hay acceso: así no se revela qué proyectos existen.
    if not p or not auth.puede_ver(u, pid): raise HTTPException(404, "Proyecto no encontrado o sin acceso")
    return p

def contratista_actual(u: dict = Depends(usuario_actual)):
    """Usuario de la sesión con rol contratista (403 para los demás roles)."""
    if u["rol"] != "contratista": raise HTTPException(403, "Solo para la empresa ejecutora")
    return u

def obra_contratista(pid: str, u: dict = Depends(contratista_actual)):
    """Proyecto {pid} asignado al contratista de la sesión (404 si no existe o no está asignado, como proyecto_permitido)."""
    p = proyectos.obtener(pid)
    if not p or not auth.puede_cargar(u, pid): raise HTTPException(404, "Proyecto no encontrado o sin acceso")
    return p

def destino(u):
    """Página de inicio de cada rol después del login."""
    return {"admin": "/admin", "contratista": "/contratista"}.get(u["rol"], "/auditor")  # Home de cada rol

# ---------- rutas ----------
class Login(BaseModel):
    correo: str
    clave: str

@router.post("/api/login")
def login(datos: Login, request: Request, response: Response):
    """Valida credenciales y deja la cookie de sesión. Devuelve a qué página ir."""
    u = store.autenticar(datos.correo, datos.clave)
    if not u: raise HTTPException(401, "Correo o contraseña incorrectos")  # mismo mensaje si falla el correo o la clave
    # httponly: inaccesible desde JS · samesite=lax: protege de envíos desde otros sitios · secure: solo HTTPS en producción
    response.set_cookie(auth.COOKIE, auth.crear_token(u["id"]), max_age=SESION_HORAS * 3600,
                        httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return {"ok": True, "destino": destino(u)}

@router.post("/api/logout")
def logout(response: Response):
    """Borra la cookie. Nota: el token no se revoca en el servidor; deja de servir al vencer (pendiente conocido)."""
    response.delete_cookie(auth.COOKIE); return {"ok": True}

@router.get("/api/yo")
def yo(u: dict = Depends(usuario_actual)):
    """Usuario actual y los proyectos que puede ver (lo usan los paneles al cargar)."""
    visibles = [p for p in proyectos.listar() if auth.puede_ver(u, p["id"]) or auth.puede_cargar(u, p["id"])]
    return dict(correo=u["correo"], nombre=u["nombre"], rol=u["rol"], empresa=u.get("empresa"),
                # "datos" (si la obra tiene análisis de la IA) solo para auditoría: la empresa no debe saber qué se analiza
                proyectos=[dict(id=p["id"], nombre=p["nombre"], **({} if u["rol"] == "contratista" else dict(datos=p["datos"]))) for p in visibles])
