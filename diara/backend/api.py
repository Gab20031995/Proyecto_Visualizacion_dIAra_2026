"""Punto de entrada del backend de dIAra (aplicación FastAPI).

Uso (desde la raíz del proyecto):
    uvicorn api:app --app-dir backend --port 8000

Qué hace este archivo:
  1. Registra todos los routers de la API (carpeta routes/):
       publico  -> sitio ciudadano (resumen de obras, aportes, suscripciones)
       sesion   -> login, logout, usuario actual y dependencias de permisos
       auditor  -> panel de cada proyecto (/api/auditor/{pid}/...), Home del auditor e imágenes de cámara
       admin    -> administración (proyectos, usuarios, clima, reportes)
       camaras  -> API máquina a máquina para que las cámaras envíen fotos
       contratista -> página de la empresa ejecutora (cronograma, bitácora, costos y presupuesto)
  2. Sirve los archivos estáticos del frontend (/assets).
  3. Sirve las páginas HTML y decide a dónde redirigir según la sesión y el rol.
  4. Al arrancar inicia el programador de reportes por correo (src/programador.py); al apagarse lo detiene.

Importante: proteger una PÁGINA aquí solo evita mostrar el esqueleto HTML. La protección real de los datos
está en la API (cada ruta de routes/ exige sesión, rol o proyecto asignado mediante dependencias)."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from config import FRONTEND_DIR, UPLOADS_DIR
from routes import publico, sesion, auditor, admin, camaras, contratista
from src import auth, programador

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)  # carpeta de fotos de aportes ciudadanos (debe existir al arrancar)
# /docs y /openapi.json describen TODAS las rutas del sistema: apagadas salvo que se pida (DIARA_DOCS=1 en desarrollo)
_DOCS = os.environ.get("DIARA_DOCS") == "1"
@asynccontextmanager
async def ciclo_de_vida(app):
    """Lo que corre al encender y al apagar el servidor."""
    programador.iniciar()   # envíos automáticos de reportes (no hace nada con REPORTES_AUTOMATICOS=0)
    yield
    programador.detener()

app = FastAPI(title="dIAra API", lifespan=ciclo_de_vida, docs_url="/docs" if _DOCS else None, redoc_url=None,
              openapi_url="/openapi.json" if _DOCS else None)
# auditor define tres routers: el del panel por proyecto, el del Home (/api/mis-proyectos) y el de imágenes (/camara/...)
for r in (publico.router, sesion.router, auditor.router, auditor.inicio, auditor.camara, admin.router, camaras.router, contratista.router):
    app.include_router(r)
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

@app.middleware("http")
async def sin_cache_vieja(request: Request, call_next):
    """CSS y JS con 'no-cache': el navegador revalida en cada carga (responde 304 si no cambió). Así, al actualizar el
    sistema nadie se queda con un JS viejo que no coincide con el HTML nuevo (síntoma: paneles vacíos)."""
    r = await call_next(request)
    if request.url.path.startswith("/assets/"): r.headers["Cache-Control"] = "no-cache"
    return r

def _pagina(nombre):
    """Devuelve una página HTML del frontend."""
    # no-store: tras cerrar sesión el navegador no debe mostrar los paneles desde su caché
    return FileResponse(FRONTEND_DIR / nombre, media_type="text/html", headers={"Cache-Control": "no-store"})

def _usuario(request):
    """Usuario de la cookie de sesión, o None si no hay sesión válida."""
    return auth.usuario(request.cookies.get(auth.COOKIE, ""))

# ---------- páginas ----------
@app.get("/")
def landing():
    """Sitio público (ciudadanía). No requiere sesión."""
    return _pagina("index.html")

@app.get("/login")
def login(request: Request):
    """Formulario de acceso. Si ya hay sesión, envía directo al Home de su rol."""
    u = _usuario(request)
    return RedirectResponse(sesion.destino(u), 303) if u else _pagina("login.html")

def _solo(request, rol, pagina):
    """Página reservada a un rol: sin sesión -> login; con otro rol -> el Home de su rol (sesion.destino)."""
    u = _usuario(request)
    if not u: return RedirectResponse("/login", 303)
    return _pagina(pagina) if u["rol"] in rol else RedirectResponse(sesion.destino(u), 303)

@app.get("/auditor")
def inicio_auditor(request: Request):
    """Home del auditor: sus proyectos asignados. El admin tiene su propio Home en /admin."""
    return _solo(request, ("auditor",), "auditor.html")

@app.get("/proyecto")
def panel_proyecto(request: Request):
    """Panel de un proyecto (?p=ID), auditor o admin. Los permisos por proyecto los valida la API."""
    return _solo(request, ("auditor", "admin"), "proyecto.html")

@app.get("/admin")
def panel_admin(request: Request):
    """Administración: solo rol admin."""
    return _solo(request, ("admin",), "admin.html")

@app.get("/contratista")
def panel_contratista(request: Request):
    """Empresa ejecutora: Home con sus proyectos y, con ?p=ID, la carga de cronograma, bitácora y costos."""
    return _solo(request, ("contratista",), "contratista.html")
