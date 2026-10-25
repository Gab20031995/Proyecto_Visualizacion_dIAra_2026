"""Alertas automáticas de una obra a partir de su registro diario (diario.csv) y sus KPIs.

Cada alerta es un dict: codigo, gravedad (ALTA | MEDIA), periodo, descripcion y regla (texto de la regla aplicada).
Los umbrales están en config.UMBRALES. Para agregar una alerta nueva: agregar su bloque aquí con un código
nuevo (A-05...) y, si tiene umbral, agregarlo a UMBRALES. La consumen el panel, las tarjetas y el PDF.

Una alerta indica necesidad de REVISIÓN, no prueba de incumplimiento (así se comunica en la interfaz)."""
from config import UMBRALES as U

def evaluate(d, k):
    """d: registro diario (DataFrame de metrics.load), k: KPIs de metrics.kpis. Devuelve la lista de alertas activas."""
    out, run, start, end = [], 0, None, None
    reg = d[d.hay_registro == 1].reset_index(drop=True)  # solo días en que la cámara registró
    # A-01: racha de días SIN maquinaria operando y CON clima apto. Solo cuenta la racha más reciente
    # (una racha antigua que ya terminó no genera alerta). Un día no apto por lluvia corta la racha.
    for _, r in reg.iterrows():
        if r.maquinaria_operando == 0 and r.apto_trabajo == 1:
            run += 1; start = start or r.fecha; end = r.fecha
        else:
            run, start = 0, None
    if run >= U["dias_sin_maquinaria"]:
        out.append(dict(codigo="A-01", gravedad="ALTA", periodo=f"{start:%d-%b} a {end:%d-%b}",
            descripcion=f"{run} dias consecutivos sin maquinaria con clima apto.",
            regla=f">= {U['dias_sin_maquinaria']} dias sin maquinaria y clima apto"))
    # A-02: detecciones de la IA con confianza baja (posibles falsos positivos/negativos): una alerta por día
    for _, r in reg[reg.confianza_min < U["confianza_min"]].iterrows():
        out.append(dict(codigo="A-02", gravedad="MEDIA", periodo=f"{r.fecha:%d-%b}",
            descripcion=f"Deteccion con confianza baja ({r.confianza_min:.0%}); posible falso positivo.",
            regla=f"Confianza < {U['confianza_min']:.0%}"))
    # A-03: brecha entre avance observado y previsto al corte actual (no aplica si el avance aún no se mide)
    if k["brecha"] is not None and k["brecha"] <= U["brecha_pts"]:
        out.append(dict(codigo="A-03", gravedad="ALTA", periodo="Corte actual",
            descripcion=f"Brecha de {k['brecha']} pts entre avance observado y previsto.",
            regla=f"Brecha <= {U['brecha_pts']} pts"))
    # A-04: maquinaria encendida sin operar (tiempo muerto): una alerta por día
    for _, r in reg[reg.tiempo_muerto_h > U["tiempo_muerto_h"]].iterrows():
        out.append(dict(codigo="A-04", gravedad="MEDIA", periodo=f"{r.fecha:%d-%b}",
            descripcion=f"Maquinaria encendida sin operar ({r.tiempo_muerto_h} h).",
            regla=f"Tiempo muerto > {U['tiempo_muerto_h']} h"))
    return out
