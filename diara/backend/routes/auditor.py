"""Vista del auditor por proyecto: /api/auditor/{pid}/... Exige sesión y que el proyecto esté asignado (o ser admin).

Las consume frontend/proyecto.html (panel de un proyecto) y frontend/auditor.html (Home del auditor).
Este módulo define TRES routers que se registran en api.py:
    router  -> /api/auditor/{pid}/...   datos del panel de un proyecto
    inicio  -> /api/mis-proyectos       tarjetas del Home del auditor
    camara  -> /camara/{pid}/{archivo}  imágenes de la cámara (protegidas por sesión)

Permisos: la dependencia `proyecto_permitido` (routes/sesion.py) responde 404 si el proyecto no existe o no está
asignado al usuario, así que dentro de cada ruta `p` es siempre un proyecto que el usuario puede ver."""
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src import metrics, store, reports, proyectos, tablero, auth, clima, imagenes as imgs, reporteria, contratista
from routes.sesion import usuario_actual, proyecto_permitido

router = APIRouter(prefix="/api/auditor/{pid}")

def _con_datos(p):
    """Algunas rutas necesitan el registro diario de la IA (diario.csv); una obra nueva aún no lo tiene (409)."""
    if not p["datos"]: raise HTTPException(409, "Este proyecto aún no tiene cámara ni datos")
    return p


# ---------- resumen, imágenes y registros diarios ----------
@router.get("/resumen")
def resumen(p: dict = Depends(proyecto_permitido)):
    """Sección "Resumen" del panel: KPIs, estado, alertas, resumen de la IA y serie de avance."""
    _con_datos(p); r = metrics.resumen_obra(p["id"])
    return dict(obra=p, kpis=r["kpis"], estado=r["estado"], texto=r["texto"], alertas=r["alertas"],
                resumen_ia=metrics.resumen_ia(r["d"], r["kpis"], r["alertas"]), serie=metrics.serie(r["d"]))

@router.get("/imagenes")
def imagenes(n: int = 12, fecha: str | None = None, p: dict = Depends(proyecto_permitido)):
    """Últimas n imágenes (recibidas por API + sintéticas). n se limita a 1..200.
    Con ?fecha=AAAA-MM-DD devuelve las de ese día (detalle del calendario), en orden de hora."""
    return imgs.listar(p["id"], min(max(n, 1), 200), fecha)

@router.get("/diario")
def diario(p: dict = Depends(proyecto_permitido)):
    """Registros diarios (matriz, calendario y clima) + resumen del clima."""
    _con_datos(p); d = metrics.load(p["id"]); c = metrics.clima(d)
    d["fecha"] = d.fecha.dt.strftime("%Y-%m-%d"); d["maquinaria"] = d.maquinaria.fillna("")  # JSON no admite fechas ni NaN
    d = d.astype(object).where(d.notna(), None)  # datos reales: columnas no medidas (avance, confianza) -> null
    return dict(registros=d.to_dict("records"), clima=c)

# ---------- clima real ----------
@router.get("/clima-real")
def clima_real(p: dict = Depends(proyecto_permitido)):
    """Clima real consolidado: condiciones actuales (todas las fuentes), registro diario y pronóstico."""
    actual, error = None, None
    if clima.activos():
        # Las condiciones actuales se consultan en vivo (con caché de 15 min en src/clima); el resto viene de la base.
        try: actual = clima.actual(p)
        except clima.ErrorClima as e: error = str(e)
    else: error = "No hay fuentes de clima configuradas"
    return dict(actual=actual, error_actual=error, dias=clima.registro(p["id"]), pronostico=clima.pronostico(p["id"]),
                cambios=clima.cambios(p["id"], 30),
                fuentes=clima.ETIQUETAS,
                coordenadas=p.get("lat") is not None and p.get("lng") is not None,
                atribuciones=clima.atribuciones())  # textos de atribución que exigen las licencias de las fuentes

@router.get("/clima/registro.csv")
def clima_registro_csv(p: dict = Depends(proyecto_permitido)):
    """Registro diario consolidado de la obra en CSV (para análisis en Excel u otras herramientas)."""
    return Response(clima.exportar_csv("registro", p["id"]), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="clima_registro_{p["id"]}.csv"'})

# ---------- empresa ejecutora (lo que declara el contratista, cruzado con la IA) ----------
@router.get("/contratista")
def empresa_ejecutora(p: dict = Depends(proyecto_permitido)):
    """Sección "Empresa ejecutora" del panel: cronograma, bitácora y costos que cargó la empresa, el cruce con lo
    observado por la IA (src/contratista.py) y la bitácora de cambios (cargas, correcciones y anulaciones)."""
    empresas = [dict(nombre=u["nombre"], empresa=u.get("empresa"), correo=u["correo"], telefono=u.get("telefono"), activo=u["activo"])
                for u in store.usuarios("contratista") if p["id"] in u["proyectos"]]
    return dict(empresas=empresas, cruce=contratista.cruce(p), cronograma=contratista.cronograma(p["id"]),
                bitacora=contratista.bitacora(p["id"]), costos=contratista.costos(p), cambios=contratista.cambios(p["id"], 30))

# ---------- observaciones del auditor ----------
class Observacion(BaseModel):
    fecha: str                              # fecha de la evidencia (AAAA-MM-DD), no la de registro
    texto: str
    estado: str = "Pendiente de seguimiento"
    accion: str = ""
    alerta: str = ""                        # código de alerta relacionada (A-01...), opcional
    imagen: str | None = None               # archivo de cámara relacionado, opcional

class Estado(BaseModel):
    estado: str

@router.get("/observaciones")
def observaciones(p: dict = Depends(proyecto_permitido)):
    return store.listar(p["id"]).fillna("").to_dict("records")

@router.post("/observaciones")
def nueva_observacion(o: Observacion, p: dict = Depends(proyecto_permitido), u: dict = Depends(usuario_actual)):
    """El autor se toma de la sesión (no del cuerpo), para que nadie registre a nombre de otro."""
    if not o.texto.strip(): raise HTTPException(400, "La observación no puede estar vacía")
    store.add(p["id"], o.fecha, u["correo"], o.texto.strip(), o.estado, o.accion, o.alerta, o.imagen); return {"ok": True}

@router.patch("/observaciones/{i}")
def estado_observacion(i: int, e: Estado, p: dict = Depends(proyecto_permitido)):
    if e.estado not in ("Pendiente de seguimiento", "En revisión", "Resuelta"): raise HTTPException(400, "Estado no válido")
    # store.set_observacion filtra también por proyecto: no se puede cambiar una observación de otra obra
    if not store.set_observacion(p["id"], i, e.estado): raise HTTPException(404, "Observación no encontrada en este proyecto")
    return {"ok": True}

# ---------- aportes ciudadanos ----------
@router.get("/aportes")
def aportes(p: dict = Depends(proyecto_permitido)):
    """Todos los aportes de la obra (incluye contacto, que nunca se publica) y cuántas personas están suscritas."""
    ap = store.aportes(p["id"]).fillna("")
    return dict(aportes=[dict(r._asdict(), foto=f"/{r.foto}" if r.foto else "") for r in ap.itertuples(index=False)],
                suscripciones=len(store.suscripciones(p["id"])))

@router.post("/aportes/{i}")
def estado_aporte(i: int, e: Estado, p: dict = Depends(proyecto_permitido)):
    """Moderación: 'Revisado' publica el aporte en el sitio ciudadano; 'Descartado' lo oculta."""
    if e.estado not in ("Revisado", "Descartado", "Pendiente"): raise HTTPException(400, "Estado no válido")
    if not store.set_aporte(p["id"], i, e.estado): raise HTTPException(404, "Aporte no encontrado en este proyecto")
    return {"ok": True}

# ---------- descargas ----------
@router.get("/reporte.pdf")
def reporte_pdf(p: dict = Depends(proyecto_permitido), u: dict = Depends(usuario_actual)):
    """Reporte del proyecto (últimos 7 días) con el mismo formato del envío automático por correo."""
    pdf, r = reporteria.generar_pdf(u, "proyecto", solo=[p["id"]])
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="reporte_{p["id"]}.pdf"'})

@router.get("/matriz.xlsx")
def matriz_xlsx(p: dict = Depends(proyecto_permitido)):
    """Matriz de recursos de la última semana en Excel (src/reports.py)."""
    _con_datos(p)
    return Response(reports.matriz_xlsx(metrics.load(p["id"])), headers={"Content-Disposition": f'attachment; filename="matriz_{p["id"]}.xlsx"'},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# Home del auditor: resumen de los proyectos asignados (admin: todos).
inicio = APIRouter()

@inicio.get("/api/mis-proyectos")
def mis_proyectos(u: dict = Depends(usuario_actual)):
    """Una tarjeta por proyecto visible (src/tablero.py; Administración usa la misma función). Las tarjetas traen el
    análisis de la IA, por eso el contratista queda fuera (403)."""
    if u["rol"] == "contratista": raise HTTPException(403, "Solo para auditoría")
    return [tablero.tarjeta(p) for p in proyectos.listar() if auth.puede_ver(u, p["id"])]

# Imágenes de la cámara: solo con sesión y acceso al proyecto (se piden desde <img>, por eso la cookie).
camara = APIRouter()

@camara.get("/camara/{pid}/{archivo}")
def imagen_camara(archivo: str, p: dict = Depends(proyecto_permitido)):
    base = proyectos.carpeta(p["id"]) / "camara"; ruta = base / archivo
    # Solo archivos de imagen dentro de la carpeta de la obra (evita rutas como "../../diara.db")
    if ruta.parent != base or ruta.suffix not in (".jpg", ".png") or not ruta.is_file(): raise HTTPException(404)
    return FileResponse(ruta)
