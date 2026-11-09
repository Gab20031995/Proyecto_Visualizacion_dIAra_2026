"""Alertas automáticas de una obra a partir de su registro diario (diario.csv) y sus KPIs.

Cada alerta es un dict: codigo, gravedad (ALTA | MEDIA), periodo, descripcion, regla (texto de la regla aplicada) y
clave: identifica la MISMA alerta de un día a otro aunque cambie su período (p. ej. la fecha de inicio de una racha), para
seguir su ciclo de vida (src/ciclo_alertas.py). Las alertas C-xx y S-xx siguen el mismo formato.
Los umbrales están en config.UMBRALES. Para agregar una alerta nueva: agregar su bloque aquí con un código
nuevo (A-05...) y, si tiene umbral, agregarlo a UMBRALES. La consumen el panel, las tarjetas y el PDF.

Una alerta indica necesidad de REVISIÓN, no prueba de incumplimiento (así se comunica en la interfaz).

A-05 (inactividad con datos REALES, ítem ALE-02 del backlog). A-01 depende de la maquinaria, que la IA actual no mide
en las obras reales; A-05 usa lo que sí se mide: personas detectadas y el índice de cambio entre fotos seguidas.
    Día hábil  = con fotos aptas (hay_registro), clima apto, lunes a sábado y no feriado (config.FERIADOS + Semana Santa)
    Día sin actividad visible = 0 personas detectadas y cambio_mediana < cambio_inactivo
    Alerta si la racha más reciente de días hábiles sin actividad llega a dias_inactividad (ALTA desde el doble).
    Los días NO hábiles (domingos, feriados, lluvia, sin fotos aptas) ni cuentan ni cortan la racha.
    Un día sin índice de cambio (fotos muy separadas, como en Ticabán) CORTA la racha: sin esa señal no se puede
    concluir que no hubo actividad (que el detector no vea personas no prueba que la obra esté parada).
    Solo aplica si diario.csv trae la columna cambio_mediana (datos reales publicados por src/etl/publicar.py).
    Límites conocidos: en zonas techadas u oscuras el detector no ve a los obreros (Limoncito desde abril 2026) y en
    obras con tránsito cuenta peatones (Puente): ahí A-05 tiende a no dispararse. Es una señal para revisar las fotos."""
from datetime import date, timedelta
from config import UMBRALES as U, FERIADOS


def _pascua(anio):
    """Domingo de Pascua (algoritmo anónimo gregoriano, de Meeus)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = divmod(b, 4); f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4); l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451; mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)

def feriados(anio):
    """Feriados de Costa Rica de un año: los fijos de config.FERIADOS más Jueves y Viernes Santo."""
    p = _pascua(anio)
    return {date(anio, int(f[:2]), int(f[3:])) for f in FERIADOS} | {p - timedelta(days=3), p - timedelta(days=2)}

def habil(dia):
    """Lunes a sábado y no feriado (en Costa Rica la construcción suele trabajar los sábados)."""
    return dia.weekday() < 6 and dia not in feriados(dia.year)

def inactividad(d):
    """Racha más reciente de días hábiles sin actividad visible (ver A-05 arriba): lista de fechas, la más antigua primero."""
    if "cambio_mediana" not in d.columns: return []
    racha = []
    for r in d[d.hay_registro == 1].itertuples():
        dia = r.fecha.date()
        if r.apto_trabajo != 1 or not habil(dia): continue          # no hábil: ni cuenta ni corta
        if r.personas_max == 0 and r.cambio_mediana == r.cambio_mediana and r.cambio_mediana < U["cambio_inactivo"]:
            racha.append(dia)                                         # (x == x descarta NaN: sin índice de cambio)
        else:
            racha = []                                                # actividad visible o sin evidencia suficiente
    return racha

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
        out.append(dict(codigo="A-01", gravedad="ALTA", periodo=f"{start:%d-%b} a {end:%d-%b}", clave=f"{start:%Y-%m-%d}",
            descripcion=f"{run} dias consecutivos sin maquinaria con clima apto.",
            regla=f">= {U['dias_sin_maquinaria']} dias sin maquinaria y clima apto"))
    # A-02: detecciones de la IA con confianza baja (posibles falsos positivos/negativos): una alerta por día
    for _, r in reg[reg.confianza_min < U["confianza_min"]].iterrows():
        out.append(dict(codigo="A-02", gravedad="MEDIA", periodo=f"{r.fecha:%d-%b}", clave=f"{r.fecha:%Y-%m-%d}",
            descripcion=f"Deteccion con confianza baja ({r.confianza_min:.0%}); posible falso positivo.",
            regla=f"Confianza < {U['confianza_min']:.0%}"))
    # A-03: brecha entre avance observado y previsto al corte actual (no aplica si el avance aún no se mide)
    if k["brecha"] is not None and k["brecha"] <= U["brecha_pts"]:
        out.append(dict(codigo="A-03", gravedad="ALTA", periodo="Corte actual", clave="vigente",
            descripcion=f"Brecha de {k['brecha']} pts entre avance observado y previsto.",
            regla=f"Brecha <= {U['brecha_pts']} pts"))
    # A-04: maquinaria encendida sin operar (tiempo muerto): una alerta por día
    for _, r in reg[reg.tiempo_muerto_h > U["tiempo_muerto_h"]].iterrows():
        out.append(dict(codigo="A-04", gravedad="MEDIA", periodo=f"{r.fecha:%d-%b}", clave=f"{r.fecha:%Y-%m-%d}",
            descripcion=f"Maquinaria encendida sin operar ({r.tiempo_muerto_h} h).",
            regla=f"Tiempo muerto > {U['tiempo_muerto_h']} h"))
    # A-05: días hábiles seguidos sin actividad visible (datos reales; ver docstring del módulo)
    racha = inactividad(d)
    if len(racha) >= U["dias_inactividad"]:
        out.append(dict(codigo="A-05", gravedad="ALTA" if len(racha) >= 2 * U["dias_inactividad"] else "MEDIA",
            periodo=f"{racha[0]:%d-%b} a {racha[-1]:%d-%b}", clave=racha[0].isoformat(),
            descripcion=f"{len(racha)} días hábiles seguidos con clima apto sin actividad visible: la IA no detectó personas "
                        "y la imagen casi no cambió. Revise las fotos: el detector puede no ver a los obreros en zonas oscuras o tapadas.",
            regla=f">= {U['dias_inactividad']} días hábiles sin personas y con índice de cambio < {U['cambio_inactivo']}"))
    return out
