"""Preparación común de las pruebas automáticas (pytest la carga sola antes que cualquier archivo test_*.py).

REGLA PRINCIPAL: las pruebas NUNCA tocan los datos reales (data/diara.db, data/obras/...).
Para eso, ANTES de que se importe config.py, se define DIARA_DATA_DIR con una carpeta temporal nueva. config.py
toma de ahí DATA_DIR, la base, las fotos de las obras y los aportes. Por eso este archivo define las variables de
entorno en la parte de arriba, antes de cualquier "import config" o "from src import ...".

La carpeta temporal recibe una copia de data/proyectos.csv: al primer uso, la base de prueba se crea sola con los
mismos proyectos iniciales (P-001, P-002, ...) y los usuarios de ejemplo (admin y la auditora Ana, asignada a P-001).
Al terminar la sesión de pruebas la carpeta se borra.

Fixtures disponibles para las pruebas:
    cliente        función que crea un navegador simulado nuevo (cada uno con sus propias cookies de sesión)
    entrar         función entrar(cliente, correo, clave) que inicia sesión y verifica que funcionó
    contratista    cuenta de empresa ejecutora de prueba, asignada a P-001 (correo y clave)"""
import os, shutil, tempfile
from pathlib import Path

# ---------- 1. Entorno aislado (debe ir ANTES de importar cualquier módulo del backend) ----------
RAIZ = Path(__file__).resolve().parent.parent          # carpeta diara/
DATOS_PRUEBA = Path(tempfile.mkdtemp(prefix="diara_pruebas_"))
shutil.copy(RAIZ / "data" / "proyectos.csv", DATOS_PRUEBA / "proyectos.csv")

ADMIN = ("admin@prueba.cr", "clave-admin")
AUDITORA = ("ana@cgr.go.cr", "clave-auditora")         # config.AUDITOR_DEMO usa este correo; la clave sale de AUDITOR_PASS
os.environ.update({
    "DIARA_DATA_DIR": str(DATOS_PRUEBA),
    "ADMIN_EMAIL": ADMIN[0], "ADMIN_PASS": ADMIN[1], "AUDITOR_PASS": AUDITORA[1],
    "SECRET_KEY": "clave-solo-para-pruebas",
    "REPORTES_AUTOMATICOS": "0",   # sin el hilo que envía correos
    "SMTP_HOST": "",               # aunque el .env tenga un servidor de correo, en pruebas no se envía nada
    "OPEN_METEO_ACTIVO": "0",      # sin consultas de clima por internet
})

# ---------- 2. Recién ahora se puede importar el backend ----------
import pytest
from fastapi.testclient import TestClient
import config
from src import store

assert config.DB_PATH.parent == DATOS_PRUEBA, "Las pruebas deben usar la base temporal, nunca data/diara.db"


def pytest_sessionfinish(session, exitstatus):
    """Al terminar todas las pruebas se borra la carpeta temporal (base y fotos de prueba)."""
    shutil.rmtree(DATOS_PRUEBA, ignore_errors=True)


@pytest.fixture(scope="session")
def app():
    """La aplicación FastAPI real. Se usa sin "with TestClient(...)", así no arranca el programador de reportes."""
    from api import app as aplicacion
    return aplicacion


@pytest.fixture
def cliente(app):
    """Crea navegadores simulados independientes: cada uno guarda su propia cookie de sesión."""
    return lambda: TestClient(app)


@pytest.fixture
def entrar():
    """entrar(cliente, correo, clave): inicia sesión y devuelve la respuesta del login (falla si no entra)."""
    def _entrar(c, correo, clave):
        r = c.post("/api/login", json={"correo": correo, "clave": clave})
        assert r.status_code == 200, f"No se pudo iniciar sesión con {correo}: {r.text}"
        return r.json()
    return _entrar


@pytest.fixture(scope="session")
def contratista():
    """Cuenta de empresa ejecutora asignada a P-001 (se crea una sola vez por sesión de pruebas)."""
    correo, clave = "ing.prueba@constructora.cr", "clave-contratista"
    uid = store.crear_usuario(correo, "Ingeniería de prueba", clave, rol="contratista", empresa="Constructora de prueba")
    store.asignar("P-001", [uid], rol="contratista")
    return correo, clave
