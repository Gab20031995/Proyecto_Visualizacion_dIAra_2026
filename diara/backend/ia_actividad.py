"""Actividad en obra con IA sobre las fotos curadas del ETL (detalle en src/ia/actividad.py).

Requisitos: haber corrido el ETL (python backend/etl_imagenes.py todo) e instalar requirements-ia.txt.
Uso (desde la carpeta diara/):
    python backend/ia_actividad.py analizar [--desde AAAA-MM-DD] [--hasta AAAA-MM-DD] [--limite N]
        personas, vehículos e índice de cambio por foto (CPU: ~0,7 s por foto; se puede cortar y retomar)
    python backend/ia_actividad.py resumen
        actividad_fotos.csv, actividad_diaria.csv y relación con la lluvia por mes (data/etl/<proyecto>/)
    --proyecto P-001 (por defecto)"""
import argparse, json, sys, time
from src.ia import actividad

def main():
    ap = argparse.ArgumentParser(description="Actividad en obra con IA (YOLO + índice de cambio)")
    ap.add_argument("paso", choices=["analizar", "resumen"])
    ap.add_argument("--proyecto", default="P-001")
    ap.add_argument("--desde"); ap.add_argument("--hasta"); ap.add_argument("--limite", type=int)
    a = ap.parse_args(); t0 = time.time()
    def avance(i, n):
        if i == n or i % 100 == 0: print(f"   {i}/{n} fotos · {time.time() - t0:.0f} s", flush=True)
    try:
        r = actividad.analizar(a.proyecto, a.desde, a.hasta, a.limite, avance) if a.paso == "analizar" else actividad.resumen(a.proyecto)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    print(f"\n== {a.paso} · {a.proyecto} · {time.time() - t0:.0f} s ==\n" + json.dumps(r, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
