"""Ciclo de vida de las alertas (ítem ALE-01 del backlog, docs/backlog_mejoras.md).

Las reglas (src/alerts.py A-xx, src/contratista.py C-xx, src/salud_camara.py S-xx) se calculan en cada consulta y no
tienen memoria. Este módulo les da memoria: guarda cada alerta en la tabla `alertas` para que el auditor la gestione y
quede constancia de qué se hizo con ella. Responde a la pregunta del Grupo 2 a la CGR: no existía un protocolo para
atender las alertas.

Identidad: (obra, código, clave). La clave la pone cada regla y no cambia mientras dure la situación (p. ej. la fecha de
inicio de una racha), así una racha que crece sigue siendo la misma alerta.

Estados (los cambia el auditor asignado o el admin; queda todo en alertas_historial):
    Abierta                   recién detectada (estado inicial)
    En revisión               el auditor la está mirando
    Justificación solicitada  se pidió explicación a la empresa ejecutora (la respuesta llegará con el ítem CON-01)
    Confirmada                el auditor verificó que el problema es real
    Descartada                falsa alarma: deja de contarse en tarjetas, Seguimiento y reportes
Confirmada, Descartada y Justificación solicitada exigen un motivo.

Reglas automáticas (sincronizar()):
    - una alerta que la regla deja de detectar queda con activa = 0 ("ya no se detecta"); si vuelve, activa = 1 y conserva
      su estado (una alerta confirmada sigue confirmada)
    - una alerta Descartada que SUBE de gravedad (MEDIA -> ALTA) se reabre sola: la situación empeoró
    - vencida: Abierta o En revisión por más de config.UMBRALES["plazo_atencion_dias"] días desde que el sistema la
      detectó por primera vez (no desde que empezó la situación: las alertas anteriores a este módulo cuentan desde su
      primera sincronización)"""
import sqlite3
from contextlib import closing
from datetime import date
from config import UMBRALES as U
from src import store
from src.clima.comun import ahora_cr

ESTADOS = ["Abierta", "En revisión", "Justificación solicitada", "Confirmada", "Descartada"]
CON_MOTIVO = {"Justificación solicitada", "Confirmada", "Descartada"}
EN_CURSO = {"Abierta", "En revisión"}            # las que pueden vencerse
FAMILIAS = {"obra": ("A-", "C-"), "camara": ("S-",)}   # se sincronizan por separado (las calculan módulos distintos)


class ErrorAlerta(ValueError):
    """Cambio de estado no válido: el mensaje se muestra tal cual (las rutas responden 400)."""


def _historial(c, alerta_id, antes, despues, motivo, usuario):
    c.execute("INSERT INTO alertas_historial(alerta_id, estado_anterior, estado_nuevo, motivo, usuario) VALUES(?,?,?,?,?)",
              (alerta_id, antes, despues, motivo, usuario))


def _con_plazo(r, hoy):
    """Agrega dias_abierta y vencida a una fila de `alertas`."""
    r["dias_abierta"] = (hoy - date.fromisoformat(r["primera_deteccion"])).days
    r["vencida"] = r["estado"] in EN_CURSO and r["dias_abierta"] > U["plazo_atencion_dias"]
    return r


def sincronizar(pid, alertas, familia, ahora=None):
    """Guarda las alertas recién calculadas de una obra y devuelve las que se deben MOSTRAR (todas menos las descartadas),
    con su id, estado, primera_deteccion, dias_abierta y vencida. familia: "obra" (A-xx y C-xx) o "camara" (S-xx):
    solo se marcan como "ya no se detecta" las de esa familia. ahora: para pruebas."""
    hoy = (ahora or ahora_cr()).date()
    prefijos = FAMILIAS[familia]
    with closing(store._c()) as c, c:
        c.row_factory = sqlite3.Row
        previas = {(r["codigo"], r["clave"]): dict(r) for r in c.execute("SELECT * FROM alertas WHERE project_id=?", (pid,))
                   if r["codigo"].startswith(prefijos)}
        vistas = []
        for a in alertas:
            clave = (a["codigo"], a.get("clave") or a["periodo"])
            vistas.append(clave)
            p = previas.get(clave)
            if p is None:
                c.execute("""INSERT INTO alertas(project_id, codigo, clave, gravedad, periodo, descripcion, regla,
                             primera_deteccion, ultima_deteccion) VALUES(?,?,?,?,?,?,?,?,?)""",
                          (pid, *clave, a["gravedad"], a["periodo"], a["descripcion"], a.get("regla"), hoy.isoformat(), hoy.isoformat()))
                continue
            estado = p["estado"]
            if estado == "Descartada" and p["gravedad"] != "ALTA" and a["gravedad"] == "ALTA":   # empeoró: se reabre
                estado = "Abierta"
                _historial(c, p["id"], "Descartada", "Abierta", "Reabierta automáticamente: la alerta subió a gravedad ALTA", "sistema")
            c.execute("""UPDATE alertas SET gravedad=?, periodo=?, descripcion=?, regla=?, ultima_deteccion=?, activa=1, estado=?
                         WHERE id=?""", (a["gravedad"], a["periodo"], a["descripcion"], a.get("regla"), hoy.isoformat(), estado, p["id"]))
        for clave, p in previas.items():   # ya no se detectan
            if clave not in vistas and p["activa"]:
                c.execute("UPDATE alertas SET activa=0 WHERE id=?", (p["id"],))
        filas = {(r["codigo"], r["clave"]): dict(r) for r in c.execute("SELECT * FROM alertas WHERE project_id=?", (pid,))}
    out = []
    for a, clave in zip(alertas, vistas):
        r = _con_plazo(filas[clave], hoy)
        if r["estado"] == "Descartada": continue
        out.append(a | dict(id=r["id"], estado=r["estado"], primera_deteccion=r["primera_deteccion"],
                            dias_abierta=r["dias_abierta"], vencida=r["vencida"]))
    return out


def listar(pid, ahora=None):
    """Todas las alertas guardadas de una obra (también descartadas y las que ya no se detectan), más recientes primero,
    con la cantidad de cambios en su historial."""
    hoy = (ahora or ahora_cr()).date()
    filas = store._filas("""SELECT a.*, (SELECT count(*) FROM alertas_historial h WHERE h.alerta_id=a.id) cambios
                            FROM alertas a WHERE project_id=? ORDER BY activa DESC, ultima_deteccion DESC, id DESC""", (pid,))
    return [_con_plazo(r, hoy) for r in filas]


def historial(pid, alerta_id):
    """Cambios de estado de una alerta (más recientes primero). [] si la alerta no es de esa obra."""
    return store._filas("""SELECT h.* FROM alertas_historial h JOIN alertas a ON a.id=h.alerta_id
                           WHERE a.project_id=? AND h.alerta_id=? ORDER BY h.id DESC""", (pid, alerta_id))


def cambiar_estado(pid, alerta_id, estado, motivo, usuario):
    """El auditor cambia el estado de una alerta. Devuelve la alerta actualizada; lanza ErrorAlerta si no corresponde."""
    if estado not in ESTADOS: raise ErrorAlerta(f"Estado no válido. Use: {', '.join(ESTADOS)}")
    motivo = (motivo or "").strip()
    if estado in CON_MOTIVO and len(motivo) < 5: raise ErrorAlerta(f"Indique el motivo para marcarla como «{estado}» (mínimo 5 caracteres)")
    f = store._filas("SELECT * FROM alertas WHERE id=? AND project_id=?", (alerta_id, pid))
    if not f: raise ErrorAlerta("Alerta no encontrada en este proyecto")
    if f[0]["estado"] == estado: raise ErrorAlerta(f"La alerta ya está «{estado}»")
    with closing(store._c()) as c, c:   # estado e historial en la misma transacción
        c.execute("UPDATE alertas SET estado=?, actualizado=CURRENT_TIMESTAMP WHERE id=?", (estado, alerta_id))
        _historial(c, alerta_id, f[0]["estado"], estado, motivo[:500] or None, usuario)
    return [r for r in listar(pid) if r["id"] == alerta_id][0]
