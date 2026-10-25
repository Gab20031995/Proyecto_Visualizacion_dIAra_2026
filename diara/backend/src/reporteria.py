"""Reportería automática: arma el reporte de cada auditor (todos sus proyectos), lo envía por correo según su
frecuencia (diario, semanal, quincenal) y deja registro de cada envío con copia del PDF.

Períodos (fecha de Costa Rica):
  diario     -> el día anterior                        (se envía todos los días)
  semanal    -> los 7 días anteriores                  (se envía el día de la semana configurado)
  quincenal  -> la quincena anterior (1-15 o 16-fin)   (se envía los dos días del mes configurados)
El calendario y la plantilla del PDF se configuran en Administración → Reportes (tabla `configuracion`).
Un mismo período nunca se envía dos veces a la misma persona (salvo envío manual).

Flujo de un envío (procesar):
    preparar()  reúne los datos de cada proyecto del período  ->  reporte_pdf.construir()  arma el PDF
    -> se guarda copia en data/reportes/AAAA/MM/  ->  se envía por SMTP (o "simulado" si no hay SMTP_HOST)
    -> se registra en reportes_envios (enviado | simulado | error)
Quién lo dispara: el programador interno del servidor (src/programador.py, cada 10 min desde la hora configurada),
la tarea enviar_reportes.py o los botones de Administración → Reportes. Los tres pasan por programador.ejecutar(),
que usa un bloqueo en la base para que nunca corran dos envíos a la vez.

Recuperación y reintentos (pendientes()):
  - semanal y quincenal: si el servidor estaba apagado el día de envío, se envía en la siguiente revisión (hasta 7 días)
  - diario: solo el del día (no se manda una ráfaga de diarios viejos; el semanal o quincenal los cubre)
  - un período que falla se reintenta en las revisiones siguientes, como máximo MAX_INTENTOS veces
Correo: texto + HTML con el PDF adjunto. Sin SMTP_HOST, modo "simulado" (el PDF se guarda pero no se envía).
Los errores de SMTP se traducen a mensajes con la causa probable (explicar_error)."""
import html, io, re, smtplib, socket, ssl, time
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from config import REPORTES, APP_URL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_SEGURIDAD
from src import metrics, store, proyectos, tablero, imagenes, clima, reporte_pdf, auth
from src.clima.comun import ahora_cr
from config import DATA_DIR
from PIL import Image as PILImage

FRECUENCIAS = store.FRECUENCIAS
# "proyecto" no es una frecuencia de envío: es el reporte de un solo proyecto que se descarga desde su panel
TITULOS = {"diario": "Reporte diario de fiscalización", "semanal": "Resumen semanal de fiscalización",
           "quincenal": "Resumen quincenal de fiscalización", "proyecto": "Reporte de proyecto"}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

def hoy_cr():
    return ahora_cr().date()

def _f(d):
    """date -> "24 de octubre de 2026"."""
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"

# ---------- ajustes editables (calendario + plantilla institucional) ----------
PLANTILLA_DIR = DATA_DIR / "plantilla"
# Valores de fábrica; lo guardado en la tabla `configuracion` los reemplaza (se guardan como texto)
DEFECTO = {"reporte_dia_semanal": str(REPORTES["dia_semanal"]), "reporte_dias_quincenal": ",".join(map(str, REPORTES["dias_quincenal"])),
           "plantilla_institucion": "Contraloría General de la República", "plantilla_unidad": "",
           "plantilla_color": "#0b5cab", "plantilla_pie": "Uso interno de fiscalización. La IA es un apoyo: validar con evidencia.",
           "plantilla_logo": "", "reporte_hora": str(REPORTES["hora"])}

class ErrorAjustes(Exception):
    """Ajuste no válido; el mensaje se muestra en el formulario (HTTP 400)."""
    pass

def ajustes():
    """Configuración vigente ya con tipos de Python (int, tupla) y la ruta absoluta del logo si existe."""
    c = {**DEFECTO, **{k: v for k, v in store.config_leer().items() if k in DEFECTO and v is not None}}
    logo = PLANTILLA_DIR / c["plantilla_logo"] if c["plantilla_logo"] else None
    return dict(dia_semanal=int(c["reporte_dia_semanal"]), dias_quincenal=tuple(int(x) for x in c["reporte_dias_quincenal"].split(",")), hora=int(c["reporte_hora"]),
                institucion=c["plantilla_institucion"], unidad=c["plantilla_unidad"], color=c["plantilla_color"], pie=c["plantilla_pie"],
                logo=str(logo) if logo and logo.is_file() else None)

def guardar_ajustes(dia_semanal=None, dias_quincenal=None, institucion=None, unidad=None, color=None, pie=None, hora=None):
    """Valida y guarda solo los campos recibidos (None = no cambiar). Devuelve la configuración resultante."""
    v = {}
    if hora is not None:
        if not (isinstance(hora, int) and 0 <= hora <= 23): raise ErrorAjustes("Hora de envío no válida (0 a 23)")
        v["reporte_hora"] = hora
    if dia_semanal is not None:
        if not (isinstance(dia_semanal, int) and 0 <= dia_semanal <= 6): raise ErrorAjustes("Día de la semana no válido")
        v["reporte_dia_semanal"] = dia_semanal
    if dias_quincenal is not None:
        d = sorted(set(int(x) for x in dias_quincenal))
        # Hasta 28 para que el día exista en todos los meses (febrero); separación mínima para que sean "quincenas"
        if len(d) != 2 or not all(1 <= x <= 28 for x in d): raise ErrorAjustes("Indique dos días distintos entre 1 y 28 (válidos en todos los meses)")
        if d[1] - d[0] < 10: raise ErrorAjustes("Los dos días quincenales deben estar separados al menos 10 días")
        v["reporte_dias_quincenal"] = ",".join(map(str, d))
    for clave, val, maxlen in (("plantilla_institucion", institucion, 90), ("plantilla_unidad", unidad, 120), ("plantilla_pie", pie, 160)):
        if val is not None:
            if len(val.strip()) > maxlen: raise ErrorAjustes(f"Texto demasiado largo (máx. {maxlen} caracteres)")
            v[clave] = val.strip()
    if institucion is not None and not institucion.strip(): raise ErrorAjustes("Indique el nombre de la institución")
    if color is not None:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color): raise ErrorAjustes("Color no válido (use formato #RRGGBB)")
        # Luminancia relativa aproximada: sobre colores muy claros el texto blanco del encabezado del PDF no se leería
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        if 0.2126 * r + 0.7152 * g + 0.0722 * b > 170: raise ErrorAjustes("Color demasiado claro: el texto blanco del encabezado no se leería")
        v["plantilla_color"] = color.lower()
    store.config_guardar(v)
    return ajustes()

def guardar_logo(datos: bytes):
    """Valida la imagen, la normaliza a PNG (máx. 600 px de ancho) y la guarda como logo de la plantilla."""
    if len(datos) > 2_000_000: raise ErrorAjustes("El logo supera 2 MB")
    try:
        PILImage.open(io.BytesIO(datos)).verify(); im = PILImage.open(io.BytesIO(datos))
    except Exception: raise ErrorAjustes("El archivo no es una imagen válida") from None
    if im.format not in ("PNG", "JPEG"): raise ErrorAjustes("Use un logo PNG o JPG")
    im = im.convert("RGBA"); im.thumbnail((600, 600))
    # Nombre nuevo en cada carga (evita que el navegador muestre el logo anterior desde caché); el anterior se borra
    PLANTILLA_DIR.mkdir(parents=True, exist_ok=True); nombre = f"logo_{int(time.time())}.png"
    im.save(PLANTILLA_DIR / nombre, "PNG")
    viejo = store.config_leer().get("plantilla_logo")
    store.config_guardar({"plantilla_logo": nombre})
    if viejo and (PLANTILLA_DIR / viejo).is_file(): (PLANTILLA_DIR / viejo).unlink()
    return ajustes()

def quitar_logo():
    viejo = store.config_leer().get("plantilla_logo")
    store.config_guardar({"plantilla_logo": ""})
    if viejo and (PLANTILLA_DIR / viejo).is_file(): (PLANTILLA_DIR / viejo).unlink()
    return ajustes()

# ---------- calendario de envíos ----------
def periodo(frecuencia, hoy):
    """(desde, hasta) que cubre un reporte emitido en la fecha `hoy`. Nunca incluye `hoy` (el día aún no termina)."""
    if frecuencia == "diario": return hoy - timedelta(days=1), hoy - timedelta(days=1)
    if frecuencia in ("semanal", "proyecto"): return hoy - timedelta(days=7), hoy - timedelta(days=1)
    if frecuencia == "quincenal":
        # Cubre desde el envío quincenal anterior hasta el día anterior a hoy (con días 1 y 16: 1-15 o 16-fin de mes).
        a, b = ajustes()["dias_quincenal"]
        ultimo = date(hoy.year, hoy.month, b) if hoy.day >= b else date(hoy.year, hoy.month, a) if hoy.day >= a else None
        if ultimo is None or ultimo == hoy:  # buscar el envío anterior a hoy
            prev = hoy.replace(day=1) - timedelta(days=1)  # último día del mes anterior
            cands = [date(hoy.year, hoy.month, x) for x in (a, b) if x < hoy.day] + [date(prev.year, prev.month, x) for x in (a, b)]
            ultimo = max(cands)
        return ultimo, hoy - timedelta(days=1)
    return None

def toca_hoy(frecuencia, hoy, aj=None):
    """True si en la fecha `hoy` corresponde enviar esa frecuencia. `aj` evita releer la configuración en bucles."""
    aj = aj or ajustes()
    return (frecuencia == "diario" or (frecuencia == "semanal" and hoy.weekday() == aj["dia_semanal"])
            or (frecuencia == "quincenal" and hoy.day in aj["dias_quincenal"]))

def proximo_envio(frecuencia, hoy, aj=None):
    """Próxima fecha de envío desde `hoy` (incluido); None para 'ninguno'."""
    if frecuencia not in ("diario", "semanal", "quincenal"): return None
    aj = aj or ajustes()
    for i in range(0, 32):
        d = hoy + timedelta(days=i)
        if toca_hoy(frecuencia, d, aj): return d

def periodo_txt(desde, hasta):
    return _f(desde) if desde == hasta else f"{_f(desde)} al {_f(hasta)}"

def proyectos_de(u):
    """Proyectos que entran en el reporte de una persona (admin: todos; contratista: ninguno). Las obras Finalizadas o
    Canceladas ya no se reportan."""
    return [p for p in proyectos.listar() if auth.puede_ver(u, p["id"]) and proyectos.activo(p)]

# ---------- datos de cada proyecto para el período ----------
def _en(fecha, desde, hasta):
    """True si `fecha` (texto ISO, con o sin hora) cae dentro del período."""
    return bool(fecha) and desde.isoformat() <= str(fecha)[:10] <= hasta.isoformat()

def _monto(x):
    """Monto con separador de miles. Se usa "CRC" y no "₡" porque las fuentes estándar del PDF no tienen ese símbolo."""
    return None if x in (None, "") else "CRC " + f"{float(x):,.0f}".replace(",", " ")

def datos_proyecto(p, desde, hasta):
    """Todo lo de un proyecto que va al PDF. Los indicadores son al último dato disponible; observaciones, aportes y
    clima se filtran por el período (las observaciones sin resolver se incluyen siempre)."""
    pid = p["id"]; tj = tablero.tarjeta(p)
    x = dict(id=pid, nombre=p["nombre"], ubicacion=p["ubicacion"], institucion=p["institucion"],
             estado=tj.get("estado") or p["estado"], kpis=None, n_alertas=0, n_altas=0, alertas=[], resumen_ia=[], serie=[],
             obs_abiertas=tj.get("obs_abiertas", 0), aportes_pendientes=tj["aportes_pendientes"])
    x["ficha"] = dict(institucion=p["institucion"], contratista=p.get("contratista"), contratacion=p.get("contratacion"), monto=_monto(p.get("monto_crc")),
                      cronograma=p.get("cronograma"), camara=p.get("camara"),
                      plazo=" al ".join(date.fromisoformat(f).strftime("%d/%m/%Y") for f in (p.get("fecha_inicio"), p.get("fecha_fin")) if f) or None,
                      coordenadas=f"{p['lat']:.5f}, {p['lng']:.5f}" if p.get("lat") is not None else None)
    if p["datos"]:  # solo obras con registro diario de la IA
        r = metrics.resumen_obra(pid); k = r["kpis"]; al = r["alertas"]
        x.update(kpis=k, alertas=al, n_alertas=len(al), n_altas=sum(a["gravedad"] == "ALTA" for a in al),
                 resumen_ia=metrics.resumen_ia(r["d"], k, al), serie=metrics.serie(r["d"]),
                 datos_al=date.fromisoformat(k["ultima_actualizacion"]).strftime("%d/%m/%Y"), texto_estado=r["texto"])
    # clima del período (registro consolidado)
    reg = [c for c in clima.registro(pid, 1000) if _en(c["fecha"], desde, hasta)]
    if reg:
        lluvia = sum(c["lluvia_mm"] or 0 for c in reg); no_aptos = sum(c["apto_trabajo"] == 0 for c in reg)
        bajas = sum(c["confianza"] == "baja" for c in reg)
        res = f"Lluvia acumulada {lluvia:.1f} mm; {no_aptos} de {len(reg)} días no aptos para trabajar por lluvia."
        if bajas: res += f" {bajas} día(s) con confianza baja (fuentes discrepan o datos incompletos)."
    else:
        res = "Sin registro de clima en el período."
    apto = {1: "Sí", 0: "No (lluvia)"}
    x["clima"] = dict(dias=len(reg), resumen=res, filas=[[date.fromisoformat(c["fecha"]).strftime("%d/%m/%Y"), f"{c['lluvia_mm']} mm", c["fuente"],
                                                         c["confianza"].capitalize(), f"{c['temp_max']}° / {c['temp_min']}°", apto.get(c["apto_trabajo"], "Sin certeza")]
                                                        for c in reg[-16:]])  # tope de filas para que la tabla quepa en una página
    obs = store.listar(pid).fillna("")
    x["observaciones"] = [dict(fecha=date.fromisoformat(o.fecha[:10]).strftime("%d/%m/%Y") if o.fecha else "-", estado=o.estado, texto=o.texto, autor=o.autor)
                          for o in obs.itertuples() if _en(o.creada, desde, hasta) or _en(o.fecha, desde, hasta) or o.estado != "Resuelta"][:15]
    ap = store.aportes(pid).fillna("")
    x["aportes"] = [dict(fecha=a.creada[:10], tipo=a.tipo, texto=a.texto or "(foto sin texto)", estado="Publicado" if a.estado == "Revisado" else a.estado)
                    for a in ap.itertuples() if _en(a.creada, desde, hasta)][:15]
    im = imagenes.listar(pid, 1)
    x["imagen"] = None
    if im:
        ruta = proyectos.carpeta(pid) / "camara" / im[0]["archivo"]
        if ruta.is_file():
            det = "" if im[0].get("personas") is None else f" - {im[0]['personas']} persona(s), {'con' if im[0]['maquinaria'] else 'sin'} maquinaria"
            x["imagen"] = dict(ruta=str(ruta), pie=f"Cámara {p.get('camara') or ''} - {im[0]['fecha']} {im[0]['hora']}{det}")
    return x

def preparar(u, frecuencia, hoy=None, solo=None):
    """Reúne todo lo que va en el PDF. `solo`: lista de ids para limitar los proyectos (reporte de un proyecto)."""
    hoy = hoy or hoy_cr(); desde, hasta = periodo(frecuencia, hoy)
    ps = [p for p in proyectos_de(u) if not solo or p["id"] in solo]
    datos = [datos_proyecto(p, desde, hasta) for p in ps]
    # Orden de urgencia: más alertas altas, luego más alertas, luego mayor atraso
    datos.sort(key=lambda d: (-(d["n_altas"]), -(d["n_alertas"]), (d["kpis"]["brecha"] or 0) if d["kpis"] else 0))  # brecha None: avance sin medir
    atencion = []
    for d in datos:
        if d["n_altas"]:
            b = d["kpis"]["brecha"] if d["kpis"] else None
            atencion.append(f"{d['nombre']}: {d['n_altas']} alerta(s) de gravedad alta" + (f"; brecha de {b} pts." if b is not None else "."))
        if d["obs_abiertas"]: atencion.append(f"{d['nombre']}: {d['obs_abiertas']} observación(es) sin resolver.")
        if d["aportes_pendientes"]: atencion.append(f"{d['nombre']}: {d['aportes_pendientes']} aporte(s) ciudadano(s) por revisar.")
    tot = dict(proyectos=len(datos), atrasados=sum(1 for d in datos if d["kpis"] and d["kpis"]["brecha"] is not None and d["kpis"]["brecha"] <= -10),
               alertas_altas=sum(d["n_altas"] for d in datos), obs_abiertas=sum(d["obs_abiertas"] for d in datos),
               aportes_pendientes=sum(d["aportes_pendientes"] for d in datos))
    return dict(titulo=TITULOS[frecuencia], frecuencia=frecuencia, desde=desde, hasta=hasta, periodo_txt=periodo_txt(desde, hasta), plantilla=ajustes(),
                emitido_txt=hoy.strftime("%d/%m/%Y"), usuario=u, proyectos=datos, atencion=atencion, totales=tot)

def generar_pdf(u, frecuencia, hoy=None, solo=None):
    """(bytes del PDF, datos usados). No envía ni registra nada (lo usan la vista previa y la descarga)."""
    r = preparar(u, frecuencia, hoy, solo)
    return reporte_pdf.construir(r), r

# ---------- correo ----------
class ErrorCorreo(Exception):
    """Fallo al enviar un correo, con la causa probable en lenguaje claro (se muestra en Administración)."""
    pass

def smtp_configurado():
    return bool(SMTP_HOST)

def smtp_info():
    """Datos de conexión para mostrar en Administración (nunca la contraseña)."""
    return dict(host=SMTP_HOST, puerto=SMTP_PORT, seguridad=SMTP_SEGURIDAD, usuario=SMTP_USER, remitente=SMTP_FROM)

def explicar_error(e):
    """Traduce una excepción de SMTP o de red a la causa probable y qué revisar."""
    destino = f"{SMTP_HOST}:{SMTP_PORT}"
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return ("El servidor rechazó el usuario o la contraseña (SMTP_USER / SMTP_PASS). Gmail: use una contraseña de "
                "aplicación, no la de la cuenta. Microsoft 365: el buzón debe tener habilitado 'SMTP autenticado'.")
    if isinstance(e, smtplib.SMTPSenderRefused):
        return f"El servidor no permite enviar como '{SMTP_FROM}': use como remitente (SMTP_FROM) la misma cuenta de SMTP_USER."
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "El servidor rechazó la dirección de destino: revise el correo de la persona."
    if isinstance(e, smtplib.SMTPNotSupportedError) or isinstance(e, ssl.SSLError):
        return f"Falló el cifrado con {destino}: revise SMTP_SEGURIDAD (puerto 587 = starttls, 465 = ssl)."
    if isinstance(e, socket.gaierror):
        return f"No se encontró el servidor '{SMTP_HOST}': revise SMTP_HOST."
    if isinstance(e, (ConnectionRefusedError, TimeoutError, socket.timeout, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return (f"No se pudo conectar a {destino}: revise SMTP_HOST, SMTP_PORT y SMTP_SEGURIDAD, y que el firewall o la "
                "red permitan la salida por ese puerto.")
    return f"Error al enviar el correo ({type(e).__name__}: {e})"

def _enlace_panel(u):
    return f"{APP_URL}/admin" if u["rol"] == "admin" else f"{APP_URL}/auditor"

def _html(u, r):
    """Versión HTML del correo (estilos en línea, que es lo que respetan los clientes de correo)."""
    T, col, e = r["totales"], r["plantilla"]["color"], html.escape
    celdas = [("Proyectos", T["proyectos"]), ("Atrasados", T["atrasados"]), ("Alertas altas", T["alertas_altas"]),
              ("Obs. abiertas", T["obs_abiertas"]), ("Aportes por revisar", T["aportes_pendientes"])]
    atencion = "".join(f"<li style='margin:4px 0'>{e(a)}</li>" for a in r["atencion"]) or "<li>Sin asuntos pendientes en el período.</li>"
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;max-width:620px;color:#1c2430">
<div style="background:{col};color:#fff;padding:14px 18px;border-radius:8px 8px 0 0"><b style="font-size:17px">{e(r['titulo'])}</b><br>
<span style="font-size:13px">{e(r['periodo_txt'])} · {e(r['plantilla']['institucion'])}</span></div>
<div style="border:1px solid #dde3ea;border-top:0;padding:16px 18px;border-radius:0 0 8px 8px">
<p>Hola, {e(u['nombre'] or u['correo'])}:</p><p>Adjunto encontrará el reporte en PDF con el detalle de cada proyecto.</p>
<table style="border-collapse:collapse;width:100%;text-align:center;margin:8px 0 14px"><tr>
{''.join(f"<td style='border:1px solid #dde3ea;padding:8px'><b style='font-size:18px'>{v}</b><br><span style='font-size:12px;color:#5b6675'>{e(t)}</span></td>" for t, v in celdas)}
</tr></table><b>Requiere atención</b><ul style="padding-left:18px">{atencion}</ul>
<p style="margin:16px 0"><a href="{e(_enlace_panel(u))}" style="background:{col};color:#fff;padding:9px 16px;border-radius:6px;text-decoration:none">Abrir el panel</a></p>
<p style="font-size:12px;color:#5b6675">Mensaje automático de dIAra. Una alerta indica necesidad de revisión, no prueba de incumplimiento.
Para cambiar la frecuencia de este reporte, contacte a Administración.</p></div></div>"""

def _correo(u, pdf, r, nombre_pdf):
    """Mensaje con versión de texto y HTML, y el PDF adjunto."""
    m = EmailMessage()
    m["Subject"] = f"dIAra | {r['titulo']} - {r['periodo_txt']}"
    m["From"] = SMTP_FROM; m["To"] = u["correo"]; m["Message-ID"] = make_msgid(domain="diara.cgr.go.cr")
    T = r["totales"]
    lineas = [f"Hola, {u['nombre'] or u['correo']}:", "", f"Adjunto el {r['titulo'].lower()} ({r['periodo_txt']}).", "",
              f"Proyectos: {T['proyectos']} | Atrasados: {T['atrasados']} | Alertas de gravedad alta: {T['alertas_altas']} | "
              f"Observaciones abiertas: {T['obs_abiertas']} | Aportes por revisar: {T['aportes_pendientes']}", ""]
    lineas += [f"- {a}" for a in r["atencion"]] or ["Sin asuntos pendientes en el período."]
    lineas += ["", f"Panel: {_enlace_panel(u)}", "", "Mensaje automático de dIAra (CGR). Para cambiar la frecuencia de este reporte, contacte a Administración."]
    m.set_content("\n".join(lineas))
    m.add_alternative(_html(u, r), subtype="html")  # los clientes que muestran HTML usan esta versión; el resto, el texto
    m.add_attachment(pdf, maintype="application", subtype="pdf", filename=nombre_pdf)
    return m

def correo_prueba(destino):
    """Envía un correo corto para verificar la configuración SMTP. Lanza ErrorCorreo con la causa si falla."""
    if not smtp_configurado(): raise ErrorCorreo("El correo no está configurado: defina SMTP_HOST (y usuario, contraseña y remitente) en diara/.env y reinicie el servidor.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", destino or ""): raise ErrorCorreo("Correo de destino no válido")
    m = EmailMessage()
    m["Subject"] = "dIAra | Correo de prueba"; m["From"] = SMTP_FROM; m["To"] = destino; m["Message-ID"] = make_msgid(domain="diara.cgr.go.cr")
    m.set_content(f"Correo de prueba de dIAra.\n\nSi lo recibió, el envío de reportes está bien configurado.\n"
                  f"Servidor: {SMTP_HOST}:{SMTP_PORT} ({SMTP_SEGURIDAD}) · Remitente: {SMTP_FROM}\nEnviado: {ahora_cr():%d/%m/%Y %H:%M} (hora de Costa Rica)")
    try: _enviar_smtp(m)
    except Exception as e: raise ErrorCorreo(explicar_error(e)) from None
    return dict(ok=True, destino=destino, servidor=f"{SMTP_HOST}:{SMTP_PORT}")

def _enviar_smtp(m):
    """Envía según SMTP_SEGURIDAD: ssl (puerto 465), starttls (587, por defecto) o ninguna (solo pruebas locales)."""
    if SMTP_SEGURIDAD == "ssl":
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=30)
    else:
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        if SMTP_SEGURIDAD == "starttls": s.starttls(context=ssl.create_default_context())
    with s:
        if SMTP_USER: s.login(SMTP_USER, SMTP_PASS)
        s.send_message(m)

# ---------- proceso de envío ----------
MAX_INTENTOS = 3  # intentos fallidos por persona y período antes de dejar de reintentar automáticamente

def intentos(uid, frecuencia, desde, hasta):
    """Cuántas veces falló el envío de ese período a esa persona."""
    return store._filas("SELECT COUNT(*) n FROM reportes_envios WHERE usuario_id=? AND frecuencia=? AND desde=? AND hasta=? AND estado='error'",
                        (uid, frecuencia, desde.isoformat(), hasta.isoformat()))[0]["n"]

def ya_enviado(uid, frecuencia, desde, hasta):
    """Idempotencia: el mismo período ya se envió (o simuló) a esa persona. Los errores sí se reintentan."""
    return bool(store._filas("SELECT 1 FROM reportes_envios WHERE usuario_id=? AND frecuencia=? AND desde=? AND hasta=? AND estado IN ('enviado','simulado')",
                             (uid, frecuencia, desde.isoformat(), hasta.isoformat())))

def procesar(u, frecuencia, hoy=None, origen="programado", forzar=False):
    """Genera, guarda y envía (o simula) el reporte de una persona. Devuelve el registro del envío."""
    hoy = hoy or hoy_cr(); desde, hasta = periodo(frecuencia, hoy)
    base = dict(usuario=u["nombre"] or u["correo"], correo=u["correo"], frecuencia=frecuencia, desde=desde.isoformat(), hasta=hasta.isoformat())
    # "omitido" no se registra en la base: no es un envío
    if not forzar and ya_enviado(u["id"], frecuencia, desde, hasta): return dict(base, estado="omitido", detalle="Período ya enviado")
    if not proyectos_de(u): return dict(base, estado="omitido", detalle="Sin proyectos asignados")
    estado, error, ruta_rel, tam, pdf, r = "error", None, None, None, None, None
    try:
        pdf, r = generar_pdf(u, frecuencia, hoy)
        # Copia del PDF exactamente como se envió (auditoría); la ruta se guarda relativa y con "/" (portable Windows/Linux)
        carpeta = REPORTES["dir"] / f"{hoy:%Y}" / f"{hoy:%m}"; carpeta.mkdir(parents=True, exist_ok=True)
        nombre = f"dIAra_{frecuencia}_{desde:%Y%m%d}-{hasta:%Y%m%d}_u{u['id']}_{int(time.time())}.pdf"
        (carpeta / nombre).write_bytes(pdf); ruta_rel = (carpeta / nombre).relative_to(REPORTES["dir"]).as_posix(); tam = len(pdf)
        if smtp_configurado():
            try: _enviar_smtp(_correo(u, pdf, r, f"dIAra_{frecuencia}_{desde:%Y%m%d}-{hasta:%Y%m%d}.pdf"))
            except Exception as e: raise ErrorCorreo(explicar_error(e)) from None
            estado = "enviado"
        else:
            estado = "simulado"   # sin servidor de correo: el PDF queda guardado y registrado
    except Exception as e:
        # Se captura todo para que el fallo de una persona no detenga los envíos de las demás; queda en la bitácora
        error = (str(e) if isinstance(e, ErrorCorreo) else f"{type(e).__name__}: {e}")[:400]
    store._q("""INSERT INTO reportes_envios(usuario_id,correo,frecuencia,desde,hasta,proyectos,estado,origen,error,archivo,bytes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
             (u["id"], u["correo"], frecuencia, desde.isoformat(), hasta.isoformat(),
              ",".join(p["id"] for p in r["proyectos"]) if r else None, estado, origen, error, ruta_rel, tam))
    return dict(base, estado=estado, detalle=error or ("Enviado por correo" if estado == "enviado" else "Generado y guardado (correo no configurado)"))

def pendientes(hoy=None, aj=None):
    """[(persona, frecuencia, fecha de envío)] que corresponde enviar al revisar en `hoy` (ver reglas al inicio):
    diario solo el de hoy; semanal y quincenal la fecha de envío más reciente de los últimos 7 días si su período
    no se envió. Se excluyen contratistas, cuentas inactivas, 'ninguno' y períodos con MAX_INTENTOS fallos."""
    hoy = hoy or hoy_cr(); aj = aj or ajustes(); out = []
    for u in store.usuarios():
        f = u.get("frecuencia_reporte") or "ninguno"
        if u["rol"] == "contratista" or not u["activo"] or f == "ninguno": continue  # la empresa no recibe el análisis de la IA
        fechas = [hoy] if f == "diario" else [hoy - timedelta(days=i) for i in range(7)]
        fecha = next((d for d in fechas if toca_hoy(f, d, aj)), None)
        if fecha is None: continue
        desde, hasta = periodo(f, fecha)
        if ya_enviado(u["id"], f, desde, hasta) or intentos(u["id"], f, desde, hasta) >= MAX_INTENTOS: continue
        out.append((u, f, fecha))
    return out

def ejecutar_programados(hoy=None, origen="programado"):
    """Envía todo lo pendiente (incluye recuperar un semanal/quincenal no enviado). Usar a través de
    programador.ejecutar(), que evita dos ejecuciones simultáneas."""
    return [procesar(u, f, fecha, origen) for u, f, fecha in pendientes(hoy)]

# ---------- consultas para Administración ----------
def estado(hoy=None):
    """Datos de la sección Reportes: correo, calendario, plantilla y, por persona, frecuencia y próximo envío."""
    hoy = hoy or hoy_cr(); aj = ajustes()
    ult = {r["usuario_id"]: r for r in store._filas("""SELECT usuario_id, MAX(creado) creado, estado FROM reportes_envios
                                                       WHERE estado IN ('enviado','simulado') GROUP BY usuario_id""")}
    personas = []
    for u in store.usuarios():
        if u["rol"] == "contratista": continue  # la empresa fiscalizada no recibe el análisis de la IA
        f = u.get("frecuencia_reporte") or "ninguno"; px = proximo_envio(f, hoy, aj) if u["activo"] else None
        if px == hoy and ya_enviado(u["id"], f, *periodo(f, hoy)): px = proximo_envio(f, hoy + timedelta(days=1), aj)  # el de hoy ya salió
        pr = periodo(f, px) if px else None
        personas.append(dict(id=u["id"], nombre=u["nombre"], correo=u["correo"], rol=u["rol"], activo=u["activo"], frecuencia=f,
                             proyectos=len(proyectos_de(u)), proximo=px.isoformat() if px else None,
                             proximo_periodo=periodo_txt(*pr) if pr else None, ultimo=ult.get(u["id"], {}).get("creado")))
    from src import programador  # import local: programador importa este módulo
    return dict(smtp=smtp_configurado(), remitente=SMTP_FROM if smtp_configurado() else None, smtp_info=smtp_info() if smtp_configurado() else None,
                automatico=programador.estado(), hora=aj["hora"], pendientes=len(pendientes(hoy, aj)), dia_semanal=DIAS[aj["dia_semanal"]],
                dia_semanal_n=aj["dia_semanal"], dias_quincenal=list(aj["dias_quincenal"]), hoy=hoy.isoformat(), personas=personas,
                plantilla=dict(institucion=aj["institucion"], unidad=aj["unidad"], color=aj["color"], pie=aj["pie"], logo=bool(aj["logo"])))

def envios(limite=50):
    """Historial de envíos (más recientes primero) con el nombre de la persona."""
    return store._filas("""SELECT e.*, u.nombre FROM reportes_envios e LEFT JOIN usuarios u ON u.id=e.usuario_id
                           ORDER BY e.id DESC LIMIT ?""", (limite,))

def archivo(envio_id):
    """Ruta del PDF guardado de un envío, o None. Comprueba que la ruta quede dentro de data/reportes/."""
    f = store._filas("SELECT archivo FROM reportes_envios WHERE id=?", (envio_id,))
    if not f or not f[0]["archivo"]: return None
    ruta = (REPORTES["dir"] / f[0]["archivo"]).resolve()
    return ruta if ruta.is_file() and REPORTES["dir"].resolve() in ruta.parents else None
