"""Indicadores de una obra a partir de su registro diario (data/obras/<id>/diario.csv).

Columnas que se esperan en diario.csv (hoy las genera make_data.py; mañana, el proceso de IA real):
    fecha, hay_registro, fotos, personas_prom, personas_max, maquinaria, maquinaria_operando,
    horas_sitio, horas_efectivas, tiempo_muerto_h, lluvia_mm, apto_trabajo, temp_max, temp_min, humedad,
    confianza_min, avance_previsto, avance_observado

Funciones principales:
    load(pid)          registro diario, con el clima reemplazado por el clima REAL donde exista
    kpis(d)            avance previsto/observado, brecha y productividad
    resumen_obra(pid)  todo junto (registro + KPIs + estado + alertas): lo usan el panel, tarjetas y PDF"""
import pandas as pd
from config import OBRAS_DIR, UMBRALES

def load(pid):
    """Registro diario de la obra; el clima se reemplaza por el registro consolidado real donde exista."""
    from src import clima  # import local: evita importación circular (clima importa proyectos/store)
    return clima.reemplazar_en_diario(pid, pd.read_csv(OBRAS_DIR / pid / "diario.csv", parse_dates=["fecha"]))

def _num(v):
    """float, o None si el valor falta (NaN): así el dato "no medido" llega como null al JSON y no como NaN."""
    return None if pd.isna(v) else float(v)

def kpis(d):
    """KPIs al último día del registro. Productividad = horas efectivas / horas en sitio de los últimos 7 días.
    Datos reales (src/etl/publicar.py): mientras la IA no mida el avance físico, avance_previsto/observado vienen
    vacíos; entonces previsto, observado y brecha son None y avance_medido es False (la interfaz muestra "—")."""
    reg = d[d.hay_registro == 1]
    u = d.iloc[-1]
    prev, obs = _num(u.avance_previsto), _num(u.avance_observado)
    sem = d.tail(7)
    hs, he = sem.horas_sitio.sum(), sem.horas_efectivas.sum()
    return dict(previsto=prev, observado=obs, brecha=round(obs - prev, 1) if prev is not None and obs is not None else None,  # negativa = atraso
                avance_medido=obs is not None,
                horas_sitio=float(hs), horas_efectivas=float(he),
                productividad=round(100 * he / hs) if hs else 0,
                ultima_actualizacion=reg.fecha.max().date())

def estado_texto(k):
    """Estado de la obra y frase explicativa según la brecha. Los emojis son parte del texto (la interfaz los usa
    para elegir el color; el PDF los quita porque sus fuentes no los soportan)."""
    b = k["brecha"]
    if b is None:
        return "⚪ Avance sin medición", ("La IA todavía no mide el avance físico de esta obra: se muestran las fotos reales de la cámara, "
                                         "las personas y vehículos detectados y el clima real.")
    if b <= -10: return "🔴 Atrasada", f"El avance observado ({k['observado']}%) está {abs(b)} puntos por debajo de lo previsto ({k['previsto']}%)."
    if b < -3: return "🟠 Con retraso leve", f"El avance observado ({k['observado']}%) está algo por debajo de lo previsto ({k['previsto']}%)."
    return "🟢 Según lo previsto", f"El avance observado ({k['observado']}%) coincide con lo previsto ({k['previsto']}%)."

def resumen_ia(d, k, alertas):
    """Resumen en lenguaje natural de lo que detectó la IA (reglas sobre los datos, no un modelo generativo)."""
    reg = d[d.hay_registro == 1]; sem = reg.tail(5); ant = reg.iloc[-10:-5]  # últimos 5 días con registro vs. los 5 anteriores
    if k["avance_medido"]:
        out = [f"Avance observado {k['observado']}% frente a {k['previsto']}% previsto (brecha de {k['brecha']} pts)."]
    else:
        out = ["Avance físico sin medir: la IA (modelo preentrenado) cuenta personas y vehículos en las fotos; medir el avance "
               "requiere entrenar un modelo con fotos etiquetadas de esta obra."]
    pa, pb = sem.personas_prom.mean(), ant.personas_prom.mean()
    if pb and pa < pb * 0.7:  # caída de personal mayor al 30 %
        out.append(f"El personal promedio bajó de {pb:.1f} a {pa:.1f} personas en los últimos 5 días con registro.")
    sin = sem[(sem.maquinaria_operando == 0) & (sem.apto_trabajo == 1)]
    if len(sin):
        out.append(f"Sin maquinaria operando {len(sin)} de {len(sem)} días recientes, con clima apto según el registro de clima.")
    out.append(f"Productividad semanal: {k['productividad']}% ({k['horas_efectivas']:.1f} h efectivas de {k['horas_sitio']:.0f} h en sitio).")
    if not k["avance_medido"] and len(sem) and sem.personas_max.max() == 0:  # datos reales: el detector puede no ver a nadie
        out.append("En los últimos días con fotos el detector no encontró personas. Con el modelo preentrenado esto no implica "
                   "obra parada (área oscura o tapada): revisar las imágenes.")
    baja = reg[reg.confianza_min < UMBRALES["confianza_min"]]
    if len(baja):
        out.append(f"{len(baja)} día(s) con detecciones de baja confianza: validar con las imágenes antes de concluir.")
    altas = sum(a["gravedad"] == "ALTA" for a in alertas)
    out.append(f"{len(alertas)} alertas activas ({altas} de gravedad alta). Una alerta indica revisión, no incumplimiento.")
    return out

def clima(d):
    """Resumen del clima del PERÍODO del registro de cámara (sección "Periodo del registro" del panel).
    No confundir con src/clima (paquete de clima real); este solo resume las columnas de diario.csv."""
    reg = d[d.hay_registro == 1]
    return dict(dias=len(d), dias_lluvia=int((d.lluvia_mm > 0).sum()), lluvia_total=float(d.lluvia_mm.sum()),
                dias_aptos=int(reg.apto_trabajo.sum()), dias_habiles=len(reg),
                temp_max_prom=round(float(d.temp_max.mean()), 1), temp_min_prom=round(float(d.temp_min.mean()), 1),
                humedad_prom=round(float(d.humedad.mean())),
                texto=(f"En el periodo llovió {int((d.lluvia_mm > 0).sum())} día(s) ({d.lluvia_mm.sum():.0f} mm en total). "
                       f"{int(reg.apto_trabajo.sum())} de {len(reg)} días hábiles tuvieron clima apto para trabajar, "
                       "por lo que el clima no explica la inactividad reciente."
                       if reg.apto_trabajo.tail(5).all() else
                       f"En el periodo llovió {int((d.lluvia_mm > 0).sum())} día(s). Hubo días recientes no aptos por lluvia."))

def serie(d):
    """Serie para los gráficos de avance: [{f: fecha, prev: % previsto, obs: % observado}]."""
    return [dict(f=r.fecha.strftime("%Y-%m-%d"), prev=_num(r.avance_previsto), obs=_num(r.avance_observado)) for r in d.itertuples()]

def resumen_obra(pid):
    """Resumen compacto de una obra con datos: KPIs, estado y alertas.
    Las alertas son las de la IA (A-xx, src/alerts.py) más las del cruce con lo que declara la empresa ejecutora
    (C-xx, src/contratista.py); así el panel, las tarjetas, el seguimiento y el PDF las muestran todas."""
    from src import alerts, contratista, proyectos
    d = load(pid); k = kpis(d); est, txt = estado_texto(k)
    cz = contratista.cruce(proyectos.obtener(pid), d)
    al = alerts.evaluate(d, k) + cz["alertas"]
    k["ultima_actualizacion"] = k["ultima_actualizacion"].isoformat()  # date -> texto (apto para JSON)
    return dict(d=d, kpis=k, estado=est, texto=txt, alertas=al, cruce=cz)  # cruce: ver src/contratista.cruce
