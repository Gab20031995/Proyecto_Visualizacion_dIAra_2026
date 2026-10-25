"""Seguimiento y análisis de las obras (Administración → Seguimiento).

Reúne por obra los indicadores para compararlas entre sí:
    avance previsto/observado y brecha        de metrics (registro diario de la IA)
    tendencia de la brecha (últimos 7 días)   negativa = la obra se atrasa más; positiva = recupera
    alertas por código (A-01..A-04)           de alerts
    días sin datos                            días desde el último registro de la cámara
    plazo consumido                           % del tiempo entre fecha de inicio y fin que ya pasó
    clima de los últimos 7 días               del registro consolidado (lluvia y días no aptos)
    pendientes                                observaciones abiertas y aportes por revisar
    empresa ejecutora                         avance que reporta en la bitácora, % del presupuesto ejecutado y
                                              días sin bitácora (src/contratista.py; las alertas C-xx van con las A-xx)
Las obras sin registro de la IA aparecen con los datos que tengan (estado, plazo, pendientes)."""
import csv, io
from collections import Counter
from datetime import date, timedelta
from src import metrics, proyectos, tablero, clima, contratista
from src.clima.comun import ahora_cr

def _plazo(p, hoy):
    """% del plazo contractual transcurrido y días restantes (None si faltan fechas)."""
    try: ini, fin = date.fromisoformat(p.get("fecha_inicio") or ""), date.fromisoformat(p.get("fecha_fin") or "")
    except ValueError: return None, None
    total = (fin - ini).days
    if total <= 0: return None, (fin - hoy).days
    return round(min(max((hoy - ini).days / total, 0), 1) * 100), (fin - hoy).days

def obra(p, hoy):
    """Fila de seguimiento de una obra."""
    t = tablero.tarjeta(p)
    plazo_pct, dias_restantes = _plazo(p, hoy)
    x = dict(id=p["id"], nombre=p["nombre"], institucion=p["institucion"], ubicacion=p["ubicacion"], estado_obra=p["estado"],
             datos=p["datos"], plazo_pct=plazo_pct, dias_restantes=dias_restantes, obs_abiertas=t.get("obs_abiertas", 0),
             aportes_pendientes=t["aportes_pendientes"], ultima_imagen=(t.get("imagen") or {}).get("fecha"),
             previsto=None, observado=None, brecha=None, tendencia_7d=None, productividad=None, alertas=0, alertas_altas=0,
             alertas_por_codigo={}, dias_sin_datos=None, ultima_actualizacion=None)
    cz = None
    if p["datos"]:
        r = metrics.resumen_obra(p["id"]); k = r["kpis"]; d = r["d"]; cz = r["cruce"]
        b = [round(o - v, 1) for o, v in zip(d.avance_observado, d.avance_previsto)] if k["avance_medido"] else []  # sin medición: sin tendencia
        x.update(previsto=k["previsto"], observado=k["observado"], brecha=k["brecha"], productividad=k["productividad"],
                 tendencia_7d=round(b[-1] - b[-8], 1) if len(b) >= 8 and b[-1] == b[-1] and b[-8] == b[-8] else None,  # brecha hoy - hace 7 registros (x == x descarta NaN)
                 alertas=len(r["alertas"]), alertas_altas=sum(a["gravedad"] == "ALTA" for a in r["alertas"]),
                 alertas_por_codigo=dict(Counter(a["codigo"] for a in r["alertas"])),
                 ultima_actualizacion=k["ultima_actualizacion"],
                 dias_sin_datos=(hoy - date.fromisoformat(k["ultima_actualizacion"])).days)
    cz = cz or contratista.cruce(p)  # obra sin IA: igual se muestra lo que cargó la empresa
    x.update(reportado=cz["reportado"], pct_financiero=cz["pct_financiero"], dias_sin_bitacora=cz["dias_sin_bitacora"],
             empresa_asignada=cz["asignado"])
    reg = [c for c in clima.registro(p["id"], 30) if c["fecha"] >= (hoy - timedelta(days=7)).isoformat()]
    x["lluvia_7d"] = round(sum(c["lluvia_mm"] or 0 for c in reg), 1) if reg else None
    x["no_aptos_7d"] = sum(c["apto_trabajo"] == 0 for c in reg) if reg else None
    return x

def resumen():
    """Todas las obras + totales por estado y alertas por código + últimos cambios de estado."""
    hoy = ahora_cr().date()
    filas = [obra(p, hoy) for p in proyectos.listar()]
    alertas = Counter()
    for f in filas: alertas.update(f["alertas_por_codigo"])
    return dict(hoy=hoy.isoformat(), obras=filas,
                por_estado=dict(Counter(f["estado_obra"] for f in filas)),
                alertas_por_codigo=dict(sorted(alertas.items())),
                historial=proyectos.historial(limite=15))

COLUMNAS_CSV = ["id", "nombre", "institucion", "ubicacion", "estado_obra", "previsto", "observado", "brecha", "tendencia_7d",
                "productividad", "reportado", "pct_financiero", "dias_sin_bitacora", "alertas", "alertas_altas", "dias_sin_datos", "plazo_pct", "dias_restantes", "lluvia_7d",
                "no_aptos_7d", "obs_abiertas", "aportes_pendientes", "ultima_actualizacion", "ultima_imagen"]

def csv_bytes():
    """La tabla de seguimiento en CSV (con BOM para que Excel lea bien los acentos)."""
    b = io.StringIO(); w = csv.DictWriter(b, fieldnames=COLUMNAS_CSV, extrasaction="ignore")
    w.writeheader(); w.writerows(resumen()["obras"])
    return b.getvalue().encode("utf-8-sig")
