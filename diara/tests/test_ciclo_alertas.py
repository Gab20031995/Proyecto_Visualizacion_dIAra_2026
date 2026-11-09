"""Pruebas del ciclo de vida de las alertas (src/ciclo_alertas.py, ítem ALE-01).

Se usan obras ficticias (ids "T-…": la tabla alertas no exige que la obra exista) y alertas armadas a mano con el
mismo formato que producen las reglas. El reloj se fija con `ahora` para probar el plazo de atención."""
import itertools
from datetime import datetime, timedelta
import pytest
from config import UMBRALES as U
from src import ciclo_alertas as ciclo, proyectos, salud_camara, tablero
from conftest import AUDITORA

AHORA = datetime(2026, 3, 20, 10, 0)
_n = itertools.count(1)


def obra():
    return f"T-CICLO-{next(_n)}"


def alerta(codigo="A-05", clave="2026-03-16", gravedad="MEDIA", periodo="16-Mar a 18-Mar"):
    return dict(codigo=codigo, clave=clave, gravedad=gravedad, periodo=periodo, descripcion="Prueba", regla="regla de prueba")


def sync(pid, alertas, familia="obra", dias=0):
    return ciclo.sincronizar(pid, alertas, familia, AHORA + timedelta(days=dias))


def guardada(pid, codigo="A-05"):
    return [a for a in ciclo.listar(pid, AHORA) if a["codigo"] == codigo][0]


# ---------- identidad y detección ----------
def test_una_alerta_nueva_queda_abierta_con_id():
    pid = obra()
    [a] = sync(pid, [alerta()])
    assert a["estado"] == "Abierta" and a["id"] and a["primera_deteccion"] == "2026-03-20" and not a["vencida"]


def test_la_misma_racha_que_crece_es_la_misma_alerta():
    pid = obra()
    [a] = sync(pid, [alerta()])
    [b] = sync(pid, [alerta(periodo="16-Mar a 19-Mar")], dias=1)
    assert a["id"] == b["id"] and b["periodo"] == "16-Mar a 19-Mar" and len(ciclo.listar(pid)) == 1


def test_si_deja_de_detectarse_queda_inactiva_y_conserva_su_estado_al_volver():
    pid = obra()
    [a] = sync(pid, [alerta()])
    ciclo.cambiar_estado(pid, a["id"], "Confirmada", "Verificado en las fotos", "ana@cgr.go.cr")
    assert sync(pid, [], dias=1) == [] and guardada(pid)["activa"] == 0
    [c] = sync(pid, [alerta()], dias=2)
    assert c["id"] == a["id"] and c["estado"] == "Confirmada" and guardada(pid)["activa"] == 1


def test_las_familias_se_sincronizan_por_separado():
    # Las S-xx las calcula salud_camara y las A-xx metrics: sincronizar una no debe "apagar" a la otra
    pid = obra()
    sync(pid, [alerta()], "obra")
    sync(pid, [alerta("S-06", "2026-03-01 10:00", "ALTA", "Desde 01/03/2026")], "camara")
    sync(pid, [], "camara", dias=1)
    assert guardada(pid, "A-05")["activa"] == 1 and guardada(pid, "S-06")["activa"] == 0


# ---------- estados ----------
def test_descartada_deja_de_mostrarse_y_queda_en_el_historial():
    pid = obra()
    [a] = sync(pid, [alerta()])
    ciclo.cambiar_estado(pid, a["id"], "Descartada", "Feriado local: la obra no trabajó", "ana@cgr.go.cr")
    assert sync(pid, [alerta()], dias=1) == []
    [h] = ciclo.historial(pid, a["id"])
    assert (h["estado_anterior"], h["estado_nuevo"], h["usuario"]) == ("Abierta", "Descartada", "ana@cgr.go.cr")


def test_descartada_se_reabre_sola_si_sube_a_alta():
    pid = obra()
    [a] = sync(pid, [alerta()])
    ciclo.cambiar_estado(pid, a["id"], "Descartada", "Falsa alarma por lluvia", "ana@cgr.go.cr")
    [b] = sync(pid, [alerta(gravedad="ALTA", periodo="16-Mar a 23-Mar")], dias=5)
    assert b["id"] == a["id"] and b["estado"] == "Abierta"
    assert ciclo.historial(pid, a["id"])[0]["usuario"] == "sistema"


@pytest.mark.parametrize("estado", sorted(ciclo.CON_MOTIVO))
def test_algunos_estados_exigen_motivo(estado):
    pid = obra(); [a] = sync(pid, [alerta()])
    with pytest.raises(ciclo.ErrorAlerta, match="motivo"): ciclo.cambiar_estado(pid, a["id"], estado, "", "ana@cgr.go.cr")


def test_en_revision_no_exige_motivo_y_no_se_repite_el_mismo_estado():
    pid = obra(); [a] = sync(pid, [alerta()])
    assert ciclo.cambiar_estado(pid, a["id"], "En revisión", "", "ana@cgr.go.cr")["estado"] == "En revisión"
    with pytest.raises(ciclo.ErrorAlerta, match="ya está"): ciclo.cambiar_estado(pid, a["id"], "En revisión", "", "ana@cgr.go.cr")
    with pytest.raises(ciclo.ErrorAlerta, match="no válido"): ciclo.cambiar_estado(pid, a["id"], "Archivada", "x" * 10, "ana")


def test_no_se_gestiona_una_alerta_de_otra_obra():
    pid = obra(); [a] = sync(pid, [alerta()])
    with pytest.raises(ciclo.ErrorAlerta, match="no encontrada"): ciclo.cambiar_estado(obra(), a["id"], "En revisión", "", "ana")


# ---------- plazo de atención ----------
def test_vencida_si_sigue_abierta_o_en_revision_mas_del_plazo():
    pid = obra(); sync(pid, [alerta()])
    assert not sync(pid, [alerta()], dias=U["plazo_atencion_dias"])[0]["vencida"]
    [a] = sync(pid, [alerta()], dias=U["plazo_atencion_dias"] + 1)
    assert a["vencida"] and a["dias_abierta"] == U["plazo_atencion_dias"] + 1
    ciclo.cambiar_estado(pid, a["id"], "Confirmada", "Verificado en visita de campo", "ana@cgr.go.cr")
    assert not sync(pid, [alerta()], dias=U["plazo_atencion_dias"] + 2)[0]["vencida"]   # ya se atendió


# ---------- integración: tarjetas y API ----------
def test_una_alerta_de_camara_descartada_no_cuenta_en_la_tarjeta():
    pid = proyectos.crear(dict(nombre=f"Obra ciclo {next(_n)}", institucion="MEP", provincia="Limón", canton="Limón",
                               lat=9.98, lng=-83.04, estado="En ejecución", camara="CAM-CICLO"))
    p = proyectos.obtener(pid)
    [s06] = salud_camara.resumen(p)["alertas"]          # nunca envió fotos: S-06
    assert tablero.tarjeta(p)["camara"]["alertas"] == 1
    ciclo.cambiar_estado(pid, s06["id"], "Descartada", "La cámara se instala la próxima semana", "ana@cgr.go.cr")
    assert tablero.tarjeta(p)["camara"]["alertas"] == 0


def test_api_gestionar_alertas(cliente, entrar, contratista):
    [a] = ciclo.sincronizar("P-001", [alerta("C-05", "vigente")], "obra")
    c = cliente(); entrar(c, *AUDITORA)
    r = c.patch(f"/api/auditor/P-001/alertas/{a['id']}", json={"estado": "Confirmada", "motivo": "Revisé la bitácora"})
    assert r.status_code == 200 and r.json()["estado"] == "Confirmada"
    assert c.patch(f"/api/auditor/P-001/alertas/{a['id']}", json={"estado": "Descartada"}).status_code == 400   # sin motivo
    assert [h["estado_nuevo"] for h in c.get(f"/api/auditor/P-001/alertas/{a['id']}/historial").json()] == ["Confirmada"]
    assert any(x["id"] == a["id"] for x in c.get("/api/auditor/P-001/alertas").json())
    k = cliente(); entrar(k, *contratista)   # la empresa ejecutora no ve ni gestiona alertas
    assert k.get("/api/auditor/P-001/alertas").status_code == 404
    assert k.patch(f"/api/auditor/P-001/alertas/{a['id']}", json={"estado": "Descartada", "motivo": "No nos parece"}).status_code == 404
