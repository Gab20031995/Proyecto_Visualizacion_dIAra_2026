"""Programador interno de los reportes por correo: con el servidor encendido, los envíos ocurren solos.

Cómo funciona:
  - Al arrancar uvicorn se inicia un hilo en segundo plano (api.py, lifespan) que cada INTERVALO_S segundos llama a
    revisar(). Si ya pasó la hora de envío configurada (Administración → Reportes, hora de Costa Rica), envía todo lo
    pendiente: reporteria.pendientes() decide qué toca, recupera envíos perdidos y limita los reintentos.
  - Revisar varias veces al día es seguro: un período ya enviado nunca se repite.
  - Bloqueo en la base (tabla tareas_bloqueo): si corren varios procesos (varios workers de uvicorn, o el servidor y
    la tarea programada enviar_reportes.py), solo uno envía a la vez. El bloqueo vence solo a los BLOQUEO_S segundos,
    por si un proceso se cae a mitad de un envío.
  - Se apaga con REPORTES_AUTOMATICOS=0 (entonces hay que programar backend/enviar_reportes.py en el sistema).
Limitación: si el servidor está apagado no se envía nada; al encenderlo se recupera lo pendiente (ver reporteria)."""
import logging, threading, time
from contextlib import closing
from config import REPORTES_AUTOMATICOS
from src import store, reporteria
from src.clima.comun import ahora_cr

INTERVALO_S = 600     # cada 10 minutos
BLOQUEO_S = 1800      # un envío masivo no debería tardar más de 30 min; después el bloqueo se libera solo
_parar = threading.Event()
_hilo = None
log = logging.getLogger("diara.programador")

class Ocupado(Exception):
    """Otro proceso está enviando reportes en este momento."""

def _tomar():
    """Toma el bloqueo si está libre o vencido. Atómico: un UPDATE condicional solo lo gana un proceso."""
    ahora = time.time()
    with closing(store._c()) as c, c:
        c.execute("INSERT OR IGNORE INTO tareas_bloqueo(tarea, hasta) VALUES('reportes', 0)")
        return c.execute("UPDATE tareas_bloqueo SET hasta=? WHERE tarea='reportes' AND hasta<?", (ahora + BLOQUEO_S, ahora)).rowcount == 1

def _soltar():
    store._q("UPDATE tareas_bloqueo SET hasta=0 WHERE tarea='reportes'")

def ejecutar(origen, respetar_hora=False):
    """Envía lo pendiente con el bloqueo tomado. Devuelve la lista de resultados ([] si no había nada).
    respetar_hora=True (programador): antes de la hora configurada no hace nada y devuelve None.
    Lanza Ocupado si otro proceso está enviando."""
    ahora = ahora_cr()
    if respetar_hora and ahora.hour < reporteria.ajustes()["hora"]: return None
    if not _tomar(): raise Ocupado("Ya hay un envío de reportes en curso")
    try:
        res = reporteria.ejecutar_programados(ahora.date(), origen)
        cuenta = {e: sum(r["estado"] == e for r in res) for e in ("enviado", "simulado", "error")}
        store.config_guardar({"programador_ultima": ahora.isoformat(timespec="minutes"),
                              "programador_resultado": ", ".join(f"{n} {e}" for e, n in cuenta.items() if n) or "sin envíos pendientes"})
        return res
    finally:
        _soltar()

def revisar():
    """Una vuelta del programador (la llama el hilo)."""
    try: return ejecutar("automático", respetar_hora=True)
    except Ocupado: return None

def _bucle():
    _parar.wait(20)  # deja terminar el arranque del servidor antes de la primera revisión
    while not _parar.is_set():
        try: revisar()
        except Exception: log.exception("Error en el programador de reportes")  # nunca debe tumbar el hilo
        _parar.wait(INTERVALO_S)

def iniciar():
    """Arranca el hilo (una vez por proceso). No hace nada si REPORTES_AUTOMATICOS=0."""
    global _hilo
    if not REPORTES_AUTOMATICOS or (_hilo and _hilo.is_alive()): return
    _parar.clear(); _hilo = threading.Thread(target=_bucle, name="programador-reportes", daemon=True); _hilo.start()

def detener():
    _parar.set()

def estado():
    """Para Administración → Reportes: si está activo, cada cuánto revisa y el resultado de la última revisión."""
    c = store.config_leer()
    return dict(activo=REPORTES_AUTOMATICOS, corriendo=bool(_hilo and _hilo.is_alive()), intervalo_min=INTERVALO_S // 60,
                ultima=c.get("programador_ultima"), resultado=c.get("programador_resultado"))
