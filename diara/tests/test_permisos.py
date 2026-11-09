"""Pruebas de permisos por rol contra la API real (FastAPI TestClient, base temporal de conftest.py).

Verifican las reglas de seguridad documentadas en el README:
    - sin sesión no se entra; con clave incorrecta tampoco
    - el auditor solo ve sus proyectos asignados (404 en los demás, para no revelar qué existe)
    - solo el admin entra a /api/admin/* (403 para los demás)
    - la empresa ejecutora (contratista) NUNCA ve el análisis de la IA, ni siquiera de su propia obra
    - desactivar a una persona corta su sesión de inmediato
    - el sitio público no publica nada del análisis de auditoría
Usuarios: admin y la auditora Ana (asignada a P-001) se crean solos con la base; el contratista lo crea conftest.py."""
from src import store
from conftest import ADMIN, AUDITORA


def test_sin_sesion_no_hay_acceso(cliente):
    c = cliente()
    assert c.get("/api/yo").status_code == 401
    assert c.get("/api/auditor/P-001/observaciones").status_code == 401
    assert c.get("/api/admin/proyectos").status_code == 401


def test_clave_incorrecta_no_entra(cliente):
    r = cliente().post("/api/login", json={"correo": AUDITORA[0], "clave": "no-es-la-clave"})
    assert r.status_code == 401


def test_admin_entra_a_administracion_y_a_cualquier_proyecto(cliente, entrar):
    c = cliente()
    assert entrar(c, *ADMIN)["destino"] == "/admin"
    assert c.get("/api/admin/proyectos").status_code == 200
    assert c.get("/api/auditor/P-002/observaciones").status_code == 200


def test_auditor_solo_ve_sus_proyectos(cliente, entrar):
    c = cliente()
    assert entrar(c, *AUDITORA)["destino"] == "/auditor"
    assert c.get("/api/auditor/P-001/observaciones").status_code == 200   # asignado
    assert c.get("/api/auditor/P-002/observaciones").status_code == 404   # no asignado: 404, no 403
    assert c.get("/api/auditor/P-999/observaciones").status_code == 404   # inexistente: misma respuesta
    assert c.get("/api/admin/proyectos").status_code == 403
    assert [p["id"] for p in c.get("/api/mis-proyectos").json()] == ["P-001"]


def test_contratista_no_ve_el_analisis_de_su_propia_obra(cliente, entrar, contratista):
    c = cliente()
    assert entrar(c, *contratista)["destino"] == "/contratista"
    assert c.get("/api/auditor/P-001/observaciones").status_code == 404   # P-001 es suya, pero es la vista del auditor
    assert c.get("/api/auditor/P-001/aportes").status_code == 404
    assert c.get("/api/mis-proyectos").status_code == 403
    assert c.get("/api/admin/proyectos").status_code == 403
    assert c.get("/camara/P-001/cualquier.jpg").status_code == 404
    # /api/yo le muestra sus obras, pero sin la marca "datos" (no debe saber qué obras analiza la IA)
    yo = c.get("/api/yo").json()
    assert [p["id"] for p in yo["proyectos"]] == ["P-001"]
    assert all("datos" not in p for p in yo["proyectos"])


def test_desactivar_un_usuario_corta_su_sesion_activa(cliente, entrar):
    correo, clave = "temporal@cgr.go.cr", "clave-temporal"
    uid = store.crear_usuario(correo, "Auditor temporal", clave)
    store.asignar("P-002", [uid])
    c = cliente(); entrar(c, correo, clave)
    assert c.get("/api/auditor/P-002/observaciones").status_code == 200
    store.actualizar_usuario(uid, activo=False)
    assert c.get("/api/auditor/P-002/observaciones").status_code == 401   # misma cookie, ya no sirve


def test_sitio_publico_no_expone_el_analisis_de_auditoria(cliente):
    r = cliente().get("/api/resumen")
    assert r.status_code == 200
    permitidas = {"id", "n", "u", "i", "e", "foto", "d"}  # ver routes/publico.py: datos generales, foto y avance general
    for obra in r.json()["proyectos"]:
        assert set(obra) <= permitidas, f"El sitio público expone campos de más: {set(obra) - permitidas}"
