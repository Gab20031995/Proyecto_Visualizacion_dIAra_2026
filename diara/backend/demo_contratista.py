"""Datos de EJEMPLO de la empresa ejecutora, para ver el perfil contratista y el cruce con la IA funcionando.

Uso (desde la raíz del proyecto): python backend/demo_contratista.py
Crea (solo si no existen):
    - la cuenta contratista ing.obra@constructora.cr (clave: variable CONTRATISTA_PASS o "demo"), empresa
      "Constructora Ejemplo S.A.", asignada a P-001 y P-002
    - P-001 Escuela Limoncito: cronograma, presupuesto, costos y bitácora PENSADOS PARA GENERAR ALERTAS DE CRUCE:
        · la bitácora declara maquinaria operando y más avance del que observa la IA       -> C-01 y C-03
        · los costos ejecutados (~62 % del presupuesto) superan el avance físico (~47 %)  -> C-02
        · dos días se justifican con "lluvia fuerte" cuando el clima registrado fue apto  -> C-04
        · los últimos 3 días con actividad en cámara no tienen bitácora                   -> C-05
    - P-002 Ruta Paraíso: datos coherentes con lo observado (sin alertas), para contrastar
Es idempotente: si una obra ya tiene bitácora, no le agrega nada. Los datos se insertan directo en la base (sin las
validaciones de src/contratista.py, que impiden fechas viejas o corregir después de 48 h) porque simulan semanas
de uso real. No usar en producción."""
import os
import pandas as pd
from config import OBRAS_DIR
from src import store, contratista, proyectos

CORREO, EMPRESA = "ing.obra@constructora.cr", "Constructora Ejemplo S.A."

def cuenta():
    """Crea la cuenta (o reutiliza la existente) y la asigna a P-001 y P-002 sin tocar a los auditores."""
    u = [x for x in store.usuarios("contratista") if x["correo"] == CORREO]
    uid = u[0]["id"] if u else store.crear_usuario(CORREO, "Ing. Laura Vargas", os.environ.get("CONTRATISTA_PASS", "demo"),
                                                      "contratista", EMPRESA, "8888-0000")
    for pid in ("P-001", "P-002"):
        actuales = [x["id"] for x in store.usuarios("contratista") if pid in x["proyectos"]]
        if uid not in actuales: store.asignar(pid, actuales + [uid], "contratista")
    return uid

def cronograma(pid, acts, version):
    """Inserta una versión de cronograma (pesos ya suman 100)."""
    cid = store._q("INSERT INTO cronogramas(project_id,version,notas,archivo,autor) VALUES(?,?,?,?,?)",
                   (pid, version, "Cronograma aprobado en la orden de inicio", "cronograma.xlsx", CORREO)).lastrowid
    for a in acts: store._q("INSERT INTO cronograma_actividades(cronograma_id,codigo,actividad,inicio,fin,peso) VALUES(?,?,?,?,?,?)", (cid, *a))

def presupuesto(pid, partidas, gastos):
    for cod, nom, monto in partidas:
        store._q("INSERT OR IGNORE INTO presupuesto_partidas(project_id,codigo,partida,monto,autor) VALUES(?,?,?,?,?)", (pid, cod, nom, monto, CORREO))
    for fecha, cod, tipo, desc, monto, doc in gastos:
        store._q("INSERT INTO costos(project_id,fecha,partida,tipo,descripcion,monto,documento,autor,creado) VALUES(?,?,?,?,?,?,?,?,?)",
                 (pid, fecha, cod, tipo, desc, monto, doc, CORREO, fecha + " 20:00:00"))

def entrada(pid, fecha, clima, personal, maq, operando, horas, actividades, avance, incidentes=""):
    """Entrada de bitácora registrada el mismo día a las 18:00 UTC (ya fuera de la ventana de corrección)."""
    store._q("""INSERT INTO bitacora(project_id,fecha,clima,personal,maquinaria,maquinaria_operando,horas_trabajo,actividades,
                avance_reportado,incidentes,autor,creado) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
             (pid, fecha, clima, personal, maq, operando, horas, actividades, avance, incidentes, CORREO, fecha + " 18:00:00"))

def p001():
    """Escuela Limoncito: la empresa declara más de lo que la IA observa (ver docstring del módulo)."""
    cronograma("P-001", [("1.1", "Preliminares y trazado", "2026-07-01", "2026-07-20", 6),
                         ("1.2", "Movimiento de tierras", "2026-07-15", "2026-08-20", 12),
                         ("2.1", "Cimentaciones", "2026-08-10", "2026-09-20", 18),
                         ("3.1", "Estructura y paredes", "2026-09-10", "2026-11-10", 30),
                         ("4.1", "Techos", "2026-11-01", "2026-12-05", 14),
                         ("5.1", "Instalaciones eléctricas y mecánicas", "2026-10-20", "2026-12-20", 10),
                         ("6.1", "Acabados y entrega", "2026-12-01", "2027-01-31", 10)], "v1 (orden de inicio)")
    presupuesto("P-001", [("1", "Obras preliminares", 14_000_000), ("2", "Movimiento de tierras", 28_000_000),
                          ("3", "Cimentaciones y estructura", 98_000_000), ("4", "Techos", 36_000_000),
                          ("5", "Instalaciones", 22_000_000), ("6", "Acabados", 27_000_000)],
                [("2026-07-31", "1", "Estimación de pago", "Estimación n.º 1: preliminares", 13_500_000, "EST-001"),
                 ("2026-08-31", "2", "Estimación de pago", "Estimación n.º 2: movimiento de tierras", 27_000_000, "EST-002"),
                 ("2026-09-15", "3", "Gasto", "Acero de refuerzo y concreto premezclado", 31_400_000, "FAC-88412"),
                 ("2026-09-30", "3", "Estimación de pago", "Estimación n.º 3: cimentaciones", 38_000_000, "EST-003"),
                 ("2026-10-10", "4", "Gasto", "Adelanto de estructura de techos", 22_000_000, "FAC-90217"),
                 ("2026-10-12", "3", "Gasto", "Bloques y mortero", 9_600_000, "FAC-90388")])
    d = pd.read_csv(OBRAS_DIR / "P-001" / "diario.csv")
    reg = d[d.hay_registro == 1]
    for i, r in enumerate(reg.itertuples()):
        if i >= len(reg) - 3: break  # últimos 3 días con registro sin bitácora -> C-05
        tarde = r.fecha >= "2026-10-01"  # desde octubre la bitácora "maquilla" la actividad
        clima = "Lluvia fuerte (trabajo detenido)" if r.fecha in ("2026-10-06", "2026-10-07") else ("Lluvia leve" if r.lluvia_mm > 0 else "Soleado")
        parado = clima.startswith("Lluvia fuerte")
        entrada("P-001", r.fecha, clima, 0 if parado else (r.personas_max + 6 if tarde else r.personas_max),
                "Excavadora, vagoneta" if tarde else (r.maquinaria if r.maquinaria != "Ninguna" else ""),
                0 if parado else (1 if tarde else r.maquinaria_operando), 0 if parado else 9,
                "Paro por lluvia" if parado else ("Armado de columnas y colado de vigas" if tarde else "Cimentaciones y relleno compactado"),
                round(r.avance_previsto - 1, 1) if tarde else round(r.avance_observado + 0.5, 1),
                "Lluvia intensa desde las 7:00, se suspenden labores" if parado else "")

def p002():
    """Ruta Paraíso: bitácora coherente con la IA (sin alertas)."""
    cronograma("P-002", [("1", "Señalización y desvíos", "2026-08-01", "2026-08-15", 5),
                         ("2", "Base y sub-base", "2026-08-10", "2026-10-30", 45),
                         ("3", "Carpeta asfáltica", "2026-10-15", "2026-12-15", 40),
                         ("4", "Demarcación y entrega", "2026-12-01", "2026-12-31", 10)], "v1")
    presupuesto("P-002", [("1", "Señalización", 6_000_000), ("2", "Base y sub-base", 60_000_000),
                          ("3", "Carpeta asfáltica", 70_000_000), ("4", "Demarcación", 9_000_000)],
                [("2026-08-31", "1", "Estimación de pago", "Estimación n.º 1", 5_800_000, "EST-001"),
                 ("2026-09-30", "2", "Estimación de pago", "Estimación n.º 2: base granular", 52_000_000, "EST-002")])
    d = pd.read_csv(OBRAS_DIR / "P-002" / "diario.csv")
    for r in d[d.hay_registro == 1].itertuples():
        entrada("P-002", r.fecha, "Lluvia leve" if r.lluvia_mm > 0 else "Soleado", r.personas_max,
                r.maquinaria if r.maquinaria != "Ninguna" else "", r.maquinaria_operando, 8,
                "Conformación y compactación de base", round(r.avance_observado, 1))

if __name__ == "__main__":
    uid = cuenta()
    for pid, f in (("P-001", p001), ("P-002", p002)):
        if store._filas("SELECT 1 FROM bitacora WHERE project_id=?", (pid,)): print(pid, "ya tiene datos de la empresa: no se modifica")
        else: f(); print(pid, "datos de ejemplo cargados")
    print(f"Cuenta: {CORREO} (empresa {EMPRESA}). Alertas de cruce en P-001:",
          [a["codigo"] for a in contratista.cruce(proyectos.obtener("P-001"))["alertas"]])
