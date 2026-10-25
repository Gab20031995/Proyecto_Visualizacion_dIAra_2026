"""Rutas públicas (ciudadanía, sin sesión): resumen de obras, aportes aprobados, suscripciones y envío de aportes.

Las usa frontend/index.html (assets/js/landing.js). Todo lo que se publica aquí debe ser apto para cualquier persona:
nunca se exponen datos de contacto ni aportes sin aprobar.

Regla de publicación: lo que la auditoría ESTÁ DETECTANDO no se publica (lo podría ver la empresa fiscalizada antes de
que el auditor lo revise). Por eso /api/resumen solo entrega el avance general observado y su fecha; nunca el estado
calculado (atrasada, con retraso...), la brecha, lo previsto, la serie para el gráfico, el texto de la IA ni las alertas.
La foto de cada obra es la última, en su versión pública: sin los recuadros de detección de la IA (/publico/foto).
El time-lapse (/api/timelapse) muestra solo las fotos del último día con registro, también en versión pública."""
import io
from fastapi import APIRouter, Form, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image
from config import UPLOADS_DIR
from src import metrics, store, auth, proyectos, imagenes

router = APIRouter()

@router.get("/api/resumen")
def resumen():
    """Lista de obras para la portada: datos generales, estado administrativo (En ejecución, Suspendido...) y, si la
    obra tiene cámara, el avance general observado redondeado y su fecha. Nada del análisis de auditoría (ver arriba).
    Claves cortas (n, u, i, e, d) porque así las espera landing.js."""
    obras = []
    for p in proyectos.listar():
        x = dict(id=p["id"], n=p["nombre"], u=p["ubicacion"], i=p["institucion"], e=p["estado"])
        ruta, foto = imagenes.publica(p["id"])
        if ruta:  # ?v= cambia con cada foto nueva: el navegador no muestra una versión vieja guardada
            x["foto"] = dict(url=f"/publico/foto/{p['id']}?v={ruta.stem}", fecha=foto["fecha"], hora=foto["hora"])
        if p["datos"]:
            k = metrics.kpis(metrics.load(p["id"]))  # solo los KPIs: no se calculan alertas ni cruces
            # obs None: la obra tiene cámara pero la IA aún no mide su avance (landing.js muestra "en medición")
            x["d"] = dict(obs=None if k["observado"] is None else round(k["observado"]), f=k["ultima_actualizacion"].strftime("%d-%m-%Y"))
        obras.append(x)
    return dict(monitoreadas=sum("d" in x for x in obras), proyectos=obras)

@router.get("/publico/foto/{pid}")
def foto_publica(pid: str):
    """Última foto de la obra, en su versión pública (sin detecciones de la IA ni metadatos). Solo la última: el
    historial de imágenes es parte del expediente de auditoría (ver src/imagenes.publica)."""
    if not proyectos.obtener(pid): raise HTTPException(404)
    ruta, _ = imagenes.publica(pid)
    if not ruta: raise HTTPException(404)
    return FileResponse(ruta, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=300"})

@router.get("/api/timelapse/{pid}")
def timelapse(pid: str):
    """Fotos del último día con registro de la obra (versión pública), para el time-lapse de la portada.
    {fecha, fotos: [{hora, url}]}; 404 si la obra no tiene fotos publicables."""
    if not proyectos.obtener(pid): raise HTTPException(404)
    t = imagenes.timelapse(pid)
    if not t: raise HTTPException(404, "Sin fotos para el time-lapse")
    return dict(fecha=t["fecha"], fotos=[dict(hora=f["hora"], url=f"/publico/timelapse/{pid}/{f['archivo']}") for f in t["fotos"]])

@router.get("/publico/timelapse/{pid}/{archivo}")
def foto_timelapse(pid: str, archivo: str):
    """Un cuadro del time-lapse. Solo se sirve si el archivo es del ÚLTIMO día (lista de imagenes.timelapse):
    pedir una foto de otro día responde 404 aunque exista (el historial no es público)."""
    t = imagenes.timelapse(pid) if proyectos.obtener(pid) else None
    f = next((x for x in (t or {}).get("fotos", []) if x["archivo"] == archivo), None)
    if not f: raise HTTPException(404)
    return FileResponse(f["ruta"], media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

@router.get("/api/aportes")
def aportes_publicos(proyecto: str):
    """Solo aportes aprobados por un auditor; sin datos de contacto."""
    ap = store.aportes(proyecto, solo_revisados=True)
    return [dict(tipo=r.tipo, fecha=r.creada[:10], nombre=r.nombre or "Anónimo", texto=r.texto,
                 foto=f"/{r.foto}" if r.foto else None) for r in ap.itertuples()]

@router.get("/uploads/{archivo}")
def foto_aporte(archivo: str, request: Request):
    """Fotos de aportes: públicas solo si el aporte fue aprobado. Las pendientes solo las ve quien puede abrir la vista
    del auditor de ESA obra (auditor asignado o admin); nunca un contratista ni otra sesión cualquiera."""
    ruta = UPLOADS_DIR / archivo
    # ruta.parent != UPLOADS_DIR evita salir de la carpeta con nombres como "../diara.db"
    if ruta.parent != UPLOADS_DIR or not ruta.is_file(): raise HTTPException(404)
    if not store.foto_publica(f"uploads/{archivo}"):
        u = auth.usuario(request.cookies.get(auth.COOKIE, ""))
        obra = store.proyecto_de_foto(f"uploads/{archivo}")
        if not (u and obra and auth.puede_ver(u, obra)): raise HTTPException(404)  # 404 y no 403: no se confirma que exista
    return FileResponse(ruta)

def _proyecto(pid):
    """Valida que el proyecto exista (los formularios envían el id)."""
    if not proyectos.obtener(pid): raise HTTPException(400, "Proyecto no válido")
    return pid

@router.post("/suscripciones")
def suscribir(proyecto: str = Form(...), contacto: str = Form(...), nombre: str = Form(""), canal: str = Form("Correo")):
    """Suscripción a avisos de una obra. Por ahora solo se guarda (el envío de avisos a ciudadanos aún no existe)."""
    if not contacto.strip(): raise HTTPException(400, "Contacto requerido")
    if canal not in ("WhatsApp", "Correo"): raise HTTPException(400, "Canal no válido")
    store.suscribir(_proyecto(proyecto), nombre, canal, contacto.strip()); return {"ok": True}

@router.post("/aportes")
async def aportar(proyecto: str = Form(...), tipo: str = Form("Comentario"), texto: str = Form(""),
                  nombre: str = Form(""), contacto: str = Form(""), foto: UploadFile | None = File(None)):
    """Aporte ciudadano (texto y/o foto). Queda 'Pendiente' hasta que un auditor lo apruebe en el panel del proyecto."""
    _proyecto(proyecto); ruta = None
    if foto and foto.filename:
        if foto.content_type not in ("image/jpeg", "image/png"): raise HTTPException(400, "Solo JPG o PNG")
        data = await foto.read()
        if len(data) > 5_000_000: raise HTTPException(400, "La foto supera 5 MB")
        # verify() comprueba que el contenido sea realmente una imagen (no basta con el content_type que manda el navegador)
        try: Image.open(io.BytesIO(data)).verify()
        except Exception: raise HTTPException(400, "El archivo no es una imagen válida")
        ruta = store.guardar_foto(foto.filename, data)
    if not texto.strip() and not ruta: raise HTTPException(400, "Escriba un comentario o adjunte una foto")
    store.add_aporte(proyecto, tipo, nombre, contacto, texto.strip(), ruta); return {"ok": True}
