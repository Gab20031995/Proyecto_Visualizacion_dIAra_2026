"""API de imágenes para las cámaras de obra (máquina a máquina, sin sesión de usuario).

Cada proyecto tiene su propio token, generado en Administración → Proyectos → Editar → Cámara.
    POST /api/camaras/{proyecto}/imagenes      Authorization: Bearer <token>
         multipart/form-data: foto (JPEG/PNG, máx. 10 MB), tomada (ISO 8601, opcional),
         personas, maquinaria (0/1), confianza (0-1): opcionales, si la cámara ya ejecuta la IA
    GET  /api/camaras/{proyecto}/estado        Authorization: Bearer <token>   (probar la conexión)

Ejemplo:
    curl -H "Authorization: Bearer dia_xxx" -F foto=@captura.jpg -F tomada=2026-10-24T14:30:00 \\
         https://<servidor>/api/camaras/P-001/imagenes

El token es por proyecto: el de una obra no sirve para otra. En la base solo se guarda su hash (src/proyectos.py).
La validación y el guardado de la imagen están en src/imagenes.py."""
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from src import imagenes, proyectos

router = APIRouter(prefix="/api/camaras/{pid}")

def _autorizar(pid, authorization):
    """Valida el encabezado 'Authorization: Bearer <token>' contra el token del proyecto."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not proyectos.token_valido(pid, token): raise HTTPException(401, "Token de cámara no válido para este proyecto")
    return proyectos.obtener(pid)

@router.get("/estado")
def estado(pid: str, authorization: str | None = Header(None)):
    """Prueba de conexión para configurar la cámara: confirma que el token corresponde al proyecto."""
    p = _autorizar(pid, authorization)
    return {"ok": True, "proyecto": p["id"], "nombre": p["nombre"], "camara": p["camara"]}

@router.post("/imagenes", status_code=201)
async def recibir(pid: str, foto: UploadFile = File(...), tomada: str | None = Form(None), personas: int | None = Form(None),
                  maquinaria: int | None = Form(None), confianza: float | None = Form(None), authorization: str | None = Header(None)):
    """Recibe una captura. Devuelve el registro creado (nombre de archivo, fecha, hora y detecciones si vinieron)."""
    _autorizar(pid, authorization)
    try: return imagenes.guardar(pid, await foto.read(), tomada, personas, maquinaria, confianza)
    except imagenes.ErrorImagen as e: raise HTTPException(400, str(e))
