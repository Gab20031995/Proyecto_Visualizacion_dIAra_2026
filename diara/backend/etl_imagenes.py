"""ETL de imágenes de obra desde Google Drive: catálogo de metadatos + clima histórico + control cruzado.

Uso (desde la carpeta diara/; el proyecto por defecto es P-001 y su carpeta de Drive está en config.ETL):
    python backend/etl_imagenes.py listar                 1. catálogo desde Drive (rápido: no descarga fotos)
    python backend/etl_imagenes.py descargar [opciones]   2. baja las fotos pendientes a data/etl/drive/...
    python backend/etl_imagenes.py clima                  3. clima horario histórico de Open-Meteo para ese período
    python backend/etl_imagenes.py curar [--rehacer]      4. aptas para IA + versión enderezada (rehacer: todas, tras cambiar umbrales)
    python backend/etl_imagenes.py cruce                  5. CSV del control cruzado en data/etl/<proyecto>/
    python backend/etl_imagenes.py hojas                  6. hojas de contacto por día en data/etl/<proyecto>/hojas/
    python backend/etl_imagenes.py todo                   1 a 6 seguidos
    python backend/etl_imagenes.py publicar               7. lleva las fotos aptas, la IA y el clima real al panel (src/etl/publicar.py)
                                                             (correr después de backend/ia_actividad.py analizar)
    python backend/etl_imagenes.py estado                 resumen del catálogo
Opciones:
    --proyecto P-001        obra (debe existir en dIAra y tener coordenadas para el paso "clima")
    --carpeta <id>          carpeta de Drive (por defecto la de config.ETL["carpetas"])
    --historico             "descargar" también baja imagenes_tratadas (sep. 2025 - abr. 2026; por defecto solo la cámara)
    --desde / --hasta AAAA-MM-DD   acotan "descargar" y "hojas";  --limite N  acota "descargar" (para probar)
Todos los pasos se pueden repetir: solo agregan o actualizan, nunca duplican. Cada ejecución queda en etl_ejecuciones.
Detalle de cada paso en src/etl/__init__.py."""
import argparse, json, sys, time
from config import ETL
from src import etl, proyectos
from src.etl import catalogo, clima_historico, cruce, curacion, drive, publicar
from src.clima.comun import ErrorClima

def _avance(hechas, total):
    """Barra de progreso simple en una sola línea."""
    if hechas == total or hechas % 25 == 0:
        print(f"\r   {hechas}/{total} fotos", end="\n" if hechas == total else "", flush=True)

def _mostrar(titulo, datos):
    print(f"\n== {titulo} ==\n" + json.dumps(datos, ensure_ascii=False, indent=2, default=str))

def main():
    ap = argparse.ArgumentParser(description="ETL de imágenes de obra (Google Drive -> metadatos -> cruce con clima)")
    ap.add_argument("paso", choices=["listar", "descargar", "clima", "curar", "cruce", "hojas", "todo", "estado", "publicar"])
    ap.add_argument("--rehacer", action="store_true")
    ap.add_argument("--proyecto", default="P-001")
    ap.add_argument("--carpeta")
    ap.add_argument("--historico", action="store_true")
    ap.add_argument("--desde"); ap.add_argument("--hasta"); ap.add_argument("--limite", type=int)
    a = ap.parse_args()
    pid = a.proyecto
    if not proyectos.obtener(pid): sys.exit(f"No existe el proyecto {pid}")
    carpeta = a.carpeta or ETL["carpetas"].get(pid)
    pasos = ["listar", "descargar", "clima", "curar", "cruce", "hojas"] if a.paso == "todo" else [a.paso]
    etl.preparar()
    for paso in pasos:
        t0 = time.time()
        try:
            if paso == "listar":
                if not carpeta: sys.exit(f"{pid} no tiene carpeta de Drive: use --carpeta o agréguela en config.ETL")
                print("Listando Drive (puede tardar 1-2 minutos)…"); r = catalogo.listar(pid, carpeta)
            elif paso == "descargar":
                origenes = ("camara", "historico") if a.historico else ("camara",)
                desde = a.desde or catalogo.inicio_ventana(pid)  # obras con ventana (config.ETL["ventana_dias"]): solo el último período
                print(f"Descargando fotos de: {', '.join(origenes)}" + (f" desde {desde}" if desde else ""))
                r = catalogo.descargar(pid, origenes, desde, a.hasta, a.limite, avance=_avance)
            elif paso == "clima": print("Consultando Open-Meteo histórico…"); r = clima_historico.descargar(pid)
            elif paso == "curar": print("Evaluando fotos para la IA…"); r = curacion.evaluar(pid, a.rehacer, avance=_avance)
            elif paso == "cruce": r = cruce.generar(pid)
            elif paso == "hojas": print("Generando hojas de contacto…"); r = curacion.hojas(pid, a.desde, a.hasta)
            elif paso == "publicar": print("Publicando datos reales en la aplicación…"); r = publicar.publicar(pid)
            else: r = catalogo.estado(pid)
        except (drive.ErrorDrive, ErrorClima, ValueError) as e:
            etl.registrar(paso, pid, False, {"error": str(e)}, time.time() - t0)
            sys.exit(f"ERROR en el paso '{paso}': {e}")
        if paso != "estado": etl.registrar(paso, pid, True, r, time.time() - t0)
        _mostrar(f"{paso} · {pid} · {time.time() - t0:.0f} s", r)

if __name__ == "__main__":
    main()
