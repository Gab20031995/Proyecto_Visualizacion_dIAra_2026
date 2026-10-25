"""Extracción desde una carpeta PÚBLICA de Google Drive ("cualquiera con el enlace"), sin clave de API.

Cómo funciona (solo biblioteca estándar):
  - Listado: https://drive.google.com/embeddedfolderview?id=<carpeta> es la vista "incrustada" que Drive ofrece para
    carpetas compartidas. Su HTML trae id, nombre y tipo (carpeta o archivo) de cada entrada; se recorre por niveles.
  - Descarga: https://drive.usercontent.google.com/download?id=<archivo>&export=download devuelve el archivo original.
Límites: depende del HTML de esa vista (si Google lo cambia, listar() falla con un mensaje claro) y de que la carpeta
siga pública. Para una carpeta privada se reemplaza este módulo por la API oficial de Drive (cuenta de servicio),
manteniendo las mismas funciones recorrer() y descargar(): el resto del ETL no cambia."""
import html, re, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

LISTADO = "https://drive.google.com/embeddedfolderview?id={}"
DESCARGA = "https://drive.usercontent.google.com/download?id={}&export=download"
# Cada entrada del HTML: <div ... id="entry-<id>"> ... <a href="<enlace>"> ... <div class="flip-entry-title"><nombre></div>
_ENTRADA = re.compile(r'id="entry-([\w-]+)".*?href="([^"]+)".*?flip-entry-title">([^<]*)<', re.S)

class ErrorDrive(Exception):
    """Fallo al listar o descargar (carpeta privada o inexistente, sin red, Drive limitando las solicitudes)."""

def _get(url, intentos=4):
    """GET con reintentos y espera creciente (1, 2, 4 s): Drive responde 429/5xx si se le piden muchos archivos seguidos."""
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (dIAra ETL; CGR Costa Rica)"})
            with urllib.request.urlopen(req, timeout=60) as r: return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404): raise ErrorDrive(f"Drive respondió {e.code}: el elemento no existe o no es público") from None
            if e.code not in (429, 500, 502, 503, 504) or i == intentos - 1: raise ErrorDrive(f"Drive respondió {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i == intentos - 1: raise ErrorDrive(f"Sin conexión con Google Drive: {getattr(e, 'reason', e)}") from None
        time.sleep(2 ** i)

def listar(carpeta_id):
    """Entradas directas de una carpeta: [{id, nombre, es_carpeta}]."""
    pagina = _get(LISTADO.format(carpeta_id)).decode("utf-8", "replace")
    if "flip-entries" not in pagina:  # Google devolvió una página de acceso o cambió el formato
        raise ErrorDrive(f"No se pudo leer la carpeta {carpeta_id}: ¿sigue compartida como 'cualquiera con el enlace'?")
    return [dict(id=i, nombre=html.unescape(n).strip(), es_carpeta="/drive/folders/" in u) for i, u, n in _ENTRADA.findall(pagina)]

def recorrer(raiz_id, hilos=8):
    """Todos los ARCHIVOS bajo la carpeta raíz, con `ruta`: tupla de nombres de carpeta desde la raíz.
    Recorre por niveles y lista en paralelo las carpetas de cada nivel (hay cientos de carpetas por día)."""
    nivel, archivos = [(raiz_id, ())], []
    with ThreadPoolExecutor(hilos) as ex:
        while nivel:
            siguiente = []
            for ruta, entradas in ex.map(lambda c: (c[1], listar(c[0])), nivel):
                for e in entradas:
                    if e["es_carpeta"]: siguiente.append((e["id"], ruta + (e["nombre"],)))
                    else: archivos.append({**e, "ruta": ruta})
            nivel = siguiente
    return archivos

def descargar(archivo_id):
    """Contenido (bytes) de un archivo. Si Drive devuelve su página HTML en vez del archivo, es un error."""
    datos = _get(DESCARGA.format(archivo_id))
    if datos[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise ErrorDrive("Drive devolvió una página en lugar del archivo (¿límite de descargas o archivo no público?)")
    return datos
