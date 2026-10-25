"""Resumen por proyecto para las tarjetas del Home del auditor y de Administración.

Una sola función para ambas vistas, así siempre muestran los mismos números. Las obras sin registro diario
de la IA (p["datos"] = False) solo traen datos generales, imagen y aportes pendientes."""
from src import metrics, store, imagenes

def tarjeta(p):
    """p: proyecto (dict de proyectos.listar). Devuelve el dict que pinta cada tarjeta en el frontend."""
    x = dict(id=p["id"], nombre=p["nombre"], ubicacion=p["ubicacion"], institucion=p["institucion"], datos=p["datos"],
             estado_obra=p["estado"], imagen=ultima_imagen(p["id"]))  # estado_obra: administrativo (Planificado, En ejecución...)
    ap = store.aportes(p["id"])
    x["aportes_pendientes"] = int((ap.estado == "Pendiente").sum()) if len(ap) else 0
    if p["datos"]:
        # estado: según el avance (Atrasada, Según lo previsto...), distinto de estado_obra
        r = metrics.resumen_obra(p["id"]); k = r["kpis"]; obs = store.listar(p["id"])
        x.update(estado=r["estado"], texto=r["texto"], previsto=k["previsto"], observado=k["observado"], brecha=k["brecha"],
                 productividad=k["productividad"], ultima_actualizacion=k["ultima_actualizacion"],
                 alertas=len(r["alertas"]), alertas_altas=sum(a["gravedad"] == "ALTA" for a in r["alertas"]),
                 obs_abiertas=int((obs.estado != "Resuelta").sum()) if len(obs) else 0)
    return x

def ultima_imagen(pid):
    return imagenes.ultima(pid)
