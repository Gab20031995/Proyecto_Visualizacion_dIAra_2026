"""Vista del administrador: resumen de todos los proyectos, gestión de auditores y asignaciones. Solo rol admin.

Todo el router exige rol admin (dependencies=[Depends(admin_actual)]): cualquier ruta nueva que se agregue aquí
queda protegida automáticamente. Lo consume frontend/admin.html.

Secciones:
    Proyectos     tarjetas, alta/edición, token de cámara, prueba de clima, asignación de auditores
    Usuarios      alta de auditores, activar/desactivar, contraseña, frecuencia de reporte
    Clima         estado de fuentes, actualizar, bitácora, precisión, exportación CSV
    Reportes      estado y calendario, envíos, vista previa, plantilla del PDF (ajustes y logo)

Patrón de errores: la lógica de negocio (src/) lanza excepciones propias (ErrorProyecto, ErrorAjustes...) y aquí se
traducen a HTTP 400 con el mensaje para el usuario."""
import re
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src import store, proyectos, tablero, clima, reporteria, seguimiento, programador
from routes.sesion import admin_actual

router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_actual)])

@router.get("/proyectos")
def resumen_proyectos():
    """Tarjeta de cada proyecto (misma función que el Home del auditor) + auditores y empresa ejecutora asignados."""
    us = store.usuarios(); out = []
    for p in proyectos.listar():
        x = tablero.tarjeta(p)
        x["auditores"] = [dict(id=u["id"], nombre=u["nombre"], activo=u["activo"]) for u in us if u["rol"] == "auditor" and p["id"] in u["proyectos"]]
        x["contratistas"] = [dict(id=u["id"], nombre=u["nombre"], empresa=u.get("empresa"), activo=u["activo"])
                             for u in us if u["rol"] == "contratista" and p["id"] in u["proyectos"]]
        out.append(x)
    return out

# ---------- Proyectos: alta, edición y cámara ----------
class DatosProyecto(BaseModel):
    """Campos del formulario. La validación de verdad (coordenadas en Costa Rica, fechas, etc.) está en src/proyectos.py."""
    nombre: str
    institucion: str
    provincia: str
    canton: str
    lat: float | str | None = None          # se aceptan texto o número: proyectos.validar() los convierte y valida
    lng: float | str | None = None
    estado: str = "En ejecución"
    descripcion: str | None = None
    contratista: str | None = None
    contratacion: str | None = None         # n.º de contratación SICOP
    monto_crc: float | str | None = None
    distrito: str | None = None
    direccion: str | None = None
    camara: str | None = None               # código de la cámara instalada
    cronograma: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None

@router.get("/catalogos")
def catalogos():
    """Listas cerradas para los selectores del formulario."""
    # transiciones: para cada estado, {estado destino: nombre de la acción}; la interfaz arma los botones con esto
    return dict(provincias=proyectos.PROVINCIAS, estados=proyectos.ESTADOS, transiciones=proyectos.TRANSICIONES)

@router.get("/proyectos/{pid}")
def detalle_proyecto(pid: str):
    p = proyectos.obtener(pid)
    if not p: raise HTTPException(404)
    return p

@router.post("/proyectos", status_code=201)
def crear_proyecto(d: DatosProyecto, yo: dict = Depends(admin_actual)):
    """Crea el proyecto con id correlativo (P-004, P-005...) y su carpeta de datos."""
    try: return {"ok": True, "id": proyectos.crear(d.model_dump(), yo["correo"])}
    except proyectos.ErrorProyecto as e: raise HTTPException(400, str(e))

class CambioEstado(BaseModel):
    estado: str
    motivo: str

@router.post("/proyectos/{pid}/estado")
def cambiar_estado(pid: str, c: CambioEstado, yo: dict = Depends(admin_actual)):
    """Iniciar, suspender, reanudar, cerrar, cancelar o reabrir (ver proyectos.TRANSICIONES). Motivo obligatorio."""
    try: return {"ok": True, "proyecto": proyectos.cambiar_estado(pid, c.estado, c.motivo, yo["correo"])}
    except proyectos.ErrorProyecto as e: raise HTTPException(400, str(e))

@router.get("/proyectos/{pid}/historial")
def historial_proyecto(pid: str):
    if not proyectos.obtener(pid): raise HTTPException(404)
    return proyectos.historial(pid)

@router.put("/proyectos/{pid}")
def editar_proyecto(pid: str, d: DatosProyecto):
    try: proyectos.actualizar(pid, d.model_dump()); return {"ok": True}
    except proyectos.ErrorProyecto as e: raise HTTPException(400, str(e))

@router.post("/proyectos/{pid}/token")
def nuevo_token(pid: str):
    """Genera el token de la API de imágenes. Se muestra UNA vez; el anterior deja de funcionar."""
    if not proyectos.obtener(pid): raise HTTPException(404)
    return {"token": proyectos.generar_token(pid), "endpoint": f"/api/camaras/{pid}/imagenes"}

@router.delete("/proyectos/{pid}/token")
def revocar_token(pid: str):
    proyectos.revocar_token(pid); return {"ok": True}

@router.post("/proyectos/{pid}/probar-clima")
def probar_clima(pid: str):
    """Valida la ubicación consultando el clima actual en esas coordenadas con las fuentes configuradas."""
    p = proyectos.obtener(pid)
    if not p: raise HTTPException(404)
    try: return {"ok": True, "actual": clima.actual(p)}
    except clima.ErrorClima as e: raise HTTPException(400, str(e))

# ---------- Usuarios y asignaciones ----------
@router.get("/usuarios")
def usuarios():
    return store.usuarios()

class NuevaCuenta(BaseModel):
    nombre: str                             # auditor: nombre completo · contratista: ingeniero responsable de la obra
    correo: str
    clave: str
    rol: str = "auditor"                    # "auditor" o "contratista" (desde la interfaz no se crean administradores)
    frecuencia: str = "semanal"             # frecuencia del reporte por correo (store.FRECUENCIAS); contratista: siempre "ninguno"
    empresa: str | None = None              # contratista: nombre de la empresa ejecutora (obligatorio)
    telefono: str | None = None

@router.post("/usuarios")
def crear(a: NuevaCuenta):
    """Crea una cuenta de AUDITOR o de CONTRATISTA (empresa ejecutora)."""
    if a.rol not in ("auditor", "contratista"): raise HTTPException(400, "Rol no válido")
    if not a.nombre.strip(): raise HTTPException(400, "Indique el nombre")
    if a.rol == "contratista" and not (a.empresa or "").strip(): raise HTTPException(400, "Indique la empresa ejecutora")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", a.correo.strip()): raise HTTPException(400, "Correo no válido")
    if len(a.clave) < 6: raise HTTPException(400, "La contraseña debe tener al menos 6 caracteres")
    if a.frecuencia not in store.FRECUENCIAS: raise HTTPException(400, "Frecuencia de reporte no válida")
    uid = store.crear_usuario(a.correo, a.nombre, a.clave, a.rol, a.empresa, a.telefono)
    if not uid: raise HTTPException(409, "Ya existe un usuario con ese correo")
    if a.rol == "auditor": store.actualizar_usuario(uid, frecuencia=a.frecuencia)
    return {"ok": True, "id": uid}

class Cambios(BaseModel):
    """Cambios parciales: solo se aplican los campos enviados (None = no tocar)."""
    correo: str | None = None
    nombre: str | None = None
    activo: bool | None = None
    clave: str | None = None
    frecuencia: str | None = None
    empresa: str | None = None
    telefono: str | None = None

@router.patch("/usuarios/{uid}")
def actualizar(uid: int, c: Cambios, yo: dict = Depends(admin_actual)):
    # Evita que el único administrador se quede fuera del sistema por error
    if uid == yo["id"] and c.activo is False: raise HTTPException(400, "No puede desactivar su propia cuenta")
    if c.clave is not None and len(c.clave) < 6: raise HTTPException(400, "La contraseña debe tener al menos 6 caracteres")
    u = store.usuario(uid)
    if not u: raise HTTPException(404)
    if u["rol"] == "contratista" and c.frecuencia not in (None, "ninguno"): raise HTTPException(400, "La empresa ejecutora no recibe reportes por correo")
    if u["rol"] == "contratista" and c.empresa is not None and not c.empresa.strip(): raise HTTPException(400, "Indique la empresa ejecutora")
    if c.frecuencia is not None and c.frecuencia not in store.FRECUENCIAS: raise HTTPException(400, "Frecuencia de reporte no válida")
    if c.nombre is not None and not c.nombre.strip(): raise HTTPException(400, "Indique el nombre")
    if c.correo is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", c.correo.strip()): raise HTTPException(400, "Correo no válido")
    try: store.actualizar_usuario(uid, c.nombre, c.activo, c.clave, c.frecuencia, c.correo, c.empresa, c.telefono)
    except ValueError as e: raise HTTPException(409, str(e))
    return {"ok": True}

class Asignacion(BaseModel):
    usuarios: list[int]

@router.put("/proyectos/{pid}/auditores")
def asignar(pid: str, a: Asignacion):
    """Reemplaza la lista COMPLETA de auditores del proyecto (no agrega uno a uno)."""
    if not proyectos.obtener(pid): raise HTTPException(404)
    validos = {u["id"] for u in store.usuarios() if u["rol"] == "auditor"}
    if not set(a.usuarios) <= validos: raise HTTPException(400, "Usuario no válido")
    store.asignar(pid, a.usuarios, "auditor"); return {"ok": True}

@router.put("/proyectos/{pid}/contratistas")
def asignar_contratistas(pid: str, a: Asignacion):
    """Reemplaza la lista COMPLETA de cuentas de la empresa ejecutora del proyecto (no toca a los auditores)."""
    if not proyectos.obtener(pid): raise HTTPException(404)
    validos = {u["id"] for u in store.usuarios("contratista")}
    if not set(a.usuarios) <= validos: raise HTTPException(400, "Usuario no válido")
    store.asignar(pid, a.usuarios, "contratista"); return {"ok": True}

# ---------- Clima: fuentes de datos ----------
@router.get("/clima")
def clima_estado():
    return clima.estado_fuentes()

@router.post("/clima/actualizar")
def clima_actualizar():
    """Consulta ahora todas las fuentes activas (historial y pronóstico) para las obras con coordenadas."""
    if not clima.activos(): raise HTTPException(400, "No hay fuentes de clima configuradas en el servidor")
    return clima.actualizar_todos(origen="administración")

@router.get("/clima/ejecuciones")
def clima_ejecuciones(limite: int = 40):
    """Bitácora de actualizaciones (qué fuente respondió, cuántos datos y cuánto tardó)."""
    return clima.ejecuciones(min(max(limite, 1), 500))

@router.get("/clima/precision")
def clima_precision(proyecto: str | None = None):
    """Precisión histórica del pronóstico de cada fuente frente al registro consolidado."""
    return clima.precision(proyecto)

@router.get("/clima/exportar/{tabla}.csv")
def clima_exportar(tabla: str, proyecto: str | None = None):
    """Exporta una tabla de clima. Solo las de clima.EXPORTABLES (lista cerrada: el nombre nunca va directo al SQL)."""
    if tabla not in clima.EXPORTABLES: raise HTTPException(404, "Tabla no exportable")
    return Response(clima.exportar_csv(tabla, proyecto), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="clima_{tabla}{"_" + proyecto if proyecto else ""}.csv"'})

# ---------- Reportería automática ----------
def _persona(uid):
    u = store.usuario(uid)
    if not u: raise HTTPException(404, "Usuario no encontrado")
    return u

def _frec(f):
    """Frecuencias con las que se puede generar un reporte ('ninguno' no genera nada)."""
    if f not in ("diario", "semanal", "quincenal"): raise HTTPException(400, "Frecuencia no válida")
    return f

@router.get("/reportes/estado")
def reportes_estado():
    """Configuración de correo, frecuencia y próximo envío de cada persona."""
    return reporteria.estado()

@router.get("/reportes/envios")
def reportes_envios(limite: int = 50):
    return reporteria.envios(min(max(limite, 1), 500))

@router.get("/reportes/archivo/{envio_id}")
def reportes_archivo(envio_id: int):
    """Copia guardada del PDF de un envío (auditoría de lo que se envió)."""
    ruta = reporteria.archivo(envio_id)
    if not ruta: raise HTTPException(404, "Archivo no disponible")
    return FileResponse(ruta, media_type="application/pdf", filename=ruta.name)

@router.get("/reportes/vista-previa/{uid}.pdf")
def reportes_vista_previa(uid: int, frecuencia: str = "semanal"):
    """Genera el PDF tal como lo recibiría la persona hoy, sin enviarlo ni registrarlo."""
    u = _persona(uid)
    if not reporteria.proyectos_de(u): raise HTTPException(400, "La persona no tiene proyectos asignados")
    pdf, r = reporteria.generar_pdf(u, _frec(frecuencia))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="vista_previa_{frecuencia}_u{uid}.pdf"'})

@router.post("/reportes/enviar/{uid}")
def reportes_enviar(uid: int, frecuencia: str | None = None):
    """Envía ahora el reporte a una persona (aunque el período ya se haya enviado)."""
    u = _persona(uid)
    return reporteria.procesar(u, _frec(frecuencia or u.get("frecuencia_reporte") or "semanal"), origen="manual", forzar=True)

@router.post("/reportes/ejecutar")
def reportes_ejecutar():
    """Envía ahora todo lo pendiente (sin esperar la hora configurada; nunca repite períodos ya enviados)."""
    try: return programador.ejecutar("administración")
    except programador.Ocupado as e: raise HTTPException(409, str(e))

class Prueba(BaseModel):
    destino: str

@router.post("/reportes/probar-correo")
def reportes_probar_correo(p: Prueba):
    """Envía un correo corto para comprobar la configuración SMTP; si falla, responde la causa probable."""
    try: return reporteria.correo_prueba(p.destino.strip())
    except reporteria.ErrorCorreo as e: raise HTTPException(400, str(e))

class Ajustes(BaseModel):
    """Calendario y plantilla del reporte. Campos en None no se modifican."""
    dia_semanal: int | None = None          # 0 = lunes ... 6 = domingo
    dias_quincenal: list[int] | None = None # dos días entre 1 y 28
    institucion: str | None = None
    unidad: str | None = None
    color: str | None = None                # #RRGGBB
    pie: str | None = None
    hora: int | None = None                 # hora de envío (Costa Rica, 0-23)

@router.get("/reportes/ajustes")
def reportes_ajustes():
    a = reporteria.ajustes(); a["logo"] = bool(a["logo"]); return a  # al navegador solo se le dice si hay logo, no la ruta del archivo

@router.put("/reportes/ajustes")
def reportes_guardar_ajustes(a: Ajustes):
    try: r = reporteria.guardar_ajustes(**a.model_dump()); r["logo"] = bool(r["logo"]); return r
    except (reporteria.ErrorAjustes, ValueError) as e: raise HTTPException(400, str(e))

@router.get("/reportes/logo")
def reportes_logo():
    ruta = reporteria.ajustes()["logo"]
    if not ruta: raise HTTPException(404, "Sin logo")
    return FileResponse(ruta, media_type="image/png", headers={"Cache-Control": "no-store"})

@router.post("/reportes/logo")
async def reportes_subir_logo(archivo: UploadFile = File(...)):
    try: reporteria.guardar_logo(await archivo.read()); return {"ok": True}
    except reporteria.ErrorAjustes as e: raise HTTPException(400, str(e))

@router.delete("/reportes/logo")
def reportes_quitar_logo():
    reporteria.quitar_logo(); return {"ok": True}

@router.get("/reportes/ejemplo.pdf")
def reportes_ejemplo(frecuencia: str = "semanal", yo: dict = Depends(admin_actual)):
    """PDF de ejemplo con la plantilla actual (resumen de todas las obras para quien administra)."""
    pdf, _ = reporteria.generar_pdf(yo, _frec(frecuencia))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="ejemplo_{frecuencia}.pdf"'})

# ---------- Seguimiento y análisis de las obras ----------
@router.get("/seguimiento")
def seguimiento_obras():
    """Tabla comparativa de todas las obras, totales por estado, alertas por código y últimos cambios de estado."""
    return seguimiento.resumen()

@router.get("/seguimiento.csv")
def seguimiento_csv():
    return Response(seguimiento.csv_bytes(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="seguimiento_obras.csv"'})
