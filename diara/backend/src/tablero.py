"""Resumen por proyecto para las tarjetas del Home del auditor y de Administración.

Una sola función para ambas vistas, así siempre muestran los mismos números. Las obras sin registro diario
de la IA (p["datos"] = False) solo traen datos generales, imagen, aportes pendientes y la salud de la cámara.
`camara` resume la salud de la cámara (src/salud_camara.py): sus alertas S-xx van APARTE de las de la obra (A-xx, C-xx)
porque hablan de la evidencia, no del avance.
`alertas_vencidas` cuenta las alertas (de la obra y de la cámara) abiertas o en revisión por más del plazo de atención
(src/ciclo_alertas.py). Las alertas descartadas por el auditor ya no llegan aquí."""
from src import metrics, store, imagenes, salud_camara

def tarjeta(p, salud=None):
    """p: proyecto (dict de proyectos.listar). Devuelve el dict que pinta cada tarjeta en el frontend.
    salud: resultado de salud_camara.resumen(p) si quien llama ya lo calculó (el reporte PDF), para no repetirlo."""
    x = dict(id=p["id"], nombre=p["nombre"], ubicacion=p["ubicacion"], institucion=p["institucion"], datos=p["datos"],
             estado_obra=p["estado"], imagen=ultima_imagen(p["id"]))  # estado_obra: administrativo (Planificado, En ejecución...)
    ap = store.aportes(p["id"])
    x["aportes_pendientes"] = int((ap.estado == "Pendiente").sum()) if len(ap) else 0
    s = salud or salud_camara.resumen(p)
    x["camara"] = dict(alertas=len(s["alertas"]), alertas_altas=sum(a["gravedad"] == "ALTA" for a in s["alertas"]),
                       codigos=sorted({a["codigo"] for a in s["alertas"]}), ultima_foto=s["ultima_foto"],
                       dias_sin_fotos=s["dias_sin_fotos"], cobertura_7d=s["cobertura_7d"])
    x["alertas_vencidas"] = sum(a.get("vencida", False) for a in s["alertas"])
    if p["datos"]:
        # estado: según el avance (Atrasada, Según lo previsto...), distinto de estado_obra
        r = metrics.resumen_obra(p["id"]); k = r["kpis"]; obs = store.listar(p["id"])
        x.update(estado=r["estado"], texto=r["texto"], previsto=k["previsto"], observado=k["observado"], brecha=k["brecha"],
                 productividad=k["productividad"], ultima_actualizacion=k["ultima_actualizacion"],
                 alertas=len(r["alertas"]), alertas_altas=sum(a["gravedad"] == "ALTA" for a in r["alertas"]),
                 obs_abiertas=int((obs.estado != "Resuelta").sum()) if len(obs) else 0)
        x["alertas_vencidas"] += sum(a.get("vencida", False) for a in r["alertas"])
    return x

def ultima_imagen(pid):
    return imagenes.ultima(pid)
