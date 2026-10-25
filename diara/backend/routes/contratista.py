"""API de la empresa ejecutora (rol contratista): /api/contratista/...  La consume frontend/contratista.html.

Permisos: todas las rutas exigen rol contratista; las de un proyecto, además, que esté asignado a esa persona
(dependencia obra_contratista en routes/sesion.py: 404 si no). El autor de cada carga se toma de la sesión.
La empresa solo ve lo que ella misma cargó: nunca el análisis de la IA, las alertas ni las observaciones del auditor.
La lógica y las validaciones están en src/contratista.py; aquí solo se traducen sus errores a respuestas HTTP:
    ErrorContratista -> 400 (mensaje para la persona)    LookupError -> 404

Rutas:
    GET  /proyectos                          tarjetas del Home (proyectos asignados)
    GET  /catalogos                          listas para los formularios (climas, tipos de costo)
    GET  /plantilla/{cronograma|presupuesto}.csv
    GET  /{pid}                              datos generales de la obra + si acepta cargas
    GET/POST /{pid}/cronograma               versión vigente, curva e historial / cargar versión nueva (archivo)
    GET/POST /{pid}/bitacora                 entradas / registrar o corregir (48 h) la del día
    GET  /{pid}/costos                       presupuesto por partidas, costos y totales
    POST /{pid}/presupuesto                  cargar partidas (archivo)
    POST /{pid}/costos                       registrar costo
    POST /{pid}/costos/{id}/anular           anular costo con motivo"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from src import contratista as ct, proyectos, auth
from routes.sesion import contratista_actual, obra_contratista

router = APIRouter(prefix="/api/contratista")

def _ejecutar(f, *args):
    """Llama a src/contratista y convierte sus errores en respuestas HTTP."""
    try: return f(*args)
    except ct.ErrorContratista as e: raise HTTPException(400, str(e))
    except LookupError: raise HTTPException(404, "Registro no encontrado en este proyecto")

# ---------- generales ----------
@router.get("/proyectos")
def mis_proyectos(u: dict = Depends(contratista_actual)):
    return [ct.resumen(p) for p in proyectos.listar() if auth.puede_cargar(u, p["id"])]

@router.get("/catalogos")
def catalogos(u: dict = Depends(contratista_actual)):
    return dict(climas=ct.CLIMAS, tipos_costo=ct.TIPOS_COSTO, horas_edicion=ct.HORAS_EDICION)

@router.get("/plantilla/{nombre}.csv")
def plantilla(nombre: str, u: dict = Depends(contratista_actual)):
    """Plantillas CSV con las columnas que exige cada carga (con BOM para que Excel lea bien las tildes)."""
    txt = {"cronograma": ct.PLANTILLA_CRONOGRAMA, "presupuesto": ct.PLANTILLA_PRESUPUESTO}.get(nombre)
    if not txt: raise HTTPException(404)
    return Response(txt.encode("utf-8-sig"), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="plantilla_{nombre}.csv"'})

# Campos de la obra que puede ver la empresa (no se exponen el token de la cámara ni otros datos internos)
_CAMPOS = ("id", "nombre", "descripcion", "institucion", "contratista", "contratacion", "monto_crc", "ubicacion", "direccion",
           "fecha_inicio", "fecha_fin", "estado", "cronograma")

@router.get("/{pid}")
def obra(p: dict = Depends(obra_contratista)):
    return dict({k: p.get(k) for k in _CAMPOS}, editable=ct.editable(p))

# ---------- cronograma ----------
@router.get("/{pid}/cronograma")
def ver_cronograma(p: dict = Depends(obra_contratista)):
    return ct.cronograma(p["id"])

@router.post("/{pid}/cronograma")
async def cargar_cronograma(archivo: UploadFile = File(...), version: str = Form(""), notas: str = Form(""),
                            p: dict = Depends(obra_contratista), u: dict = Depends(contratista_actual)):
    data = await archivo.read(ct.MAX_ARCHIVO + 1)  # se lee 1 byte de más para detectar archivos demasiado grandes
    return _ejecutar(ct.cargar_cronograma, p, archivo.filename, data, version, notas, u["correo"])

# ---------- bitácora ----------
class EntradaBitacora(BaseModel):
    fecha: str
    clima: str
    personal: int | float | str | None = None
    maquinaria: str | None = None            # equipos presentes (texto libre: "Excavadora, vagoneta")
    maquinaria_operando: bool = False        # ¿la maquinaria trabajó? (se cruza con la detección de la IA)
    horas_trabajo: float | str | None = None
    actividades: str = ""
    avance_reportado: float | str | None = None  # % de avance ACUMULADO de la obra según la empresa
    incidentes: str | None = None

@router.get("/{pid}/bitacora")
def ver_bitacora(p: dict = Depends(obra_contratista)):
    return ct.bitacora(p["id"])

@router.post("/{pid}/bitacora")
def guardar_bitacora(e: EntradaBitacora, p: dict = Depends(obra_contratista), u: dict = Depends(contratista_actual)):
    return _ejecutar(ct.guardar_bitacora, p, e.model_dump(), u["correo"])

# ---------- presupuesto y costos ----------
class Costo(BaseModel):
    fecha: str
    partida: str
    tipo: str
    descripcion: str = ""
    monto: float | str | None = None
    documento: str | None = None             # n.º de factura o de estimación

class Anulacion(BaseModel):
    motivo: str

@router.get("/{pid}/costos")
def ver_costos(p: dict = Depends(obra_contratista)):
    return ct.costos(p)

@router.post("/{pid}/presupuesto")
async def cargar_presupuesto(archivo: UploadFile = File(...), p: dict = Depends(obra_contratista), u: dict = Depends(contratista_actual)):
    data = await archivo.read(ct.MAX_ARCHIVO + 1)
    return _ejecutar(ct.cargar_presupuesto, p, archivo.filename, data, u["correo"])

@router.post("/{pid}/costos")
def registrar_costo(c: Costo, p: dict = Depends(obra_contratista), u: dict = Depends(contratista_actual)):
    return _ejecutar(ct.registrar_costo, p, c.model_dump(), u["correo"])

@router.post("/{pid}/costos/{cid}/anular")
def anular_costo(cid: int, a: Anulacion, p: dict = Depends(obra_contratista), u: dict = Depends(contratista_actual)):
    _ejecutar(ct.anular_costo, p, cid, a.motivo, u["correo"]); return {"ok": True}
