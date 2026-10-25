"""Control cruzado fotos x clima (paso 4 del ETL). Genera tres CSV en data/etl/<proyecto>/ (UTF-8 con BOM, abren en Excel):

  imagenes_metadatos.csv  el catálogo completo (todas las fotos, incluida la carpeta "otros")
  imagenes_clima.csv      una fila por foto con el clima de su hora y las banderas del cruce
  resumen_diario.csv      una fila por día del período: fotos, huecos, lluvia y temperatura del día

Cada foto se une a la hora de clima que la CONTIENE: una foto de las 16:53 usa el registro de las 17:00, cuya lluvia es
la de 16:00-17:00 (convención de Open-Meteo, ver clima_historico.py).

Banderas por foto (columna `banderas`, separadas por "; "); umbrales en config.ETL:
    lluvia durante la captura   lluvia de la hora >= lluvia_hora_mm (para la IA: gotas en el lente, poca visibilidad)
    oscura con sol              brillo < brillo_oscuro y radiación >= radiacion_dia (lente tapado, sucio o cámara fallando)
    nocturna                    radiación 0 (no hay luz natural: la IA no debería medir avance con esa foto)
    duplicada                   misma huella que otra foto anterior
    fecha distinta a la carpeta, sin clima                       (problemas de datos)
Por día: huecos (más de hueco_min minutos sin fotos entre la primera y la última del día) y días del período sin fotos."""
import pandas as pd
from config import ETL, CLIMA
from src import store, etl

_COLS_FOTO = ("drive_id, origen, ruta_drive, carpeta, archivo, camara, fecha, hora, tomada, nombre_valido, observacion, ruta_local, "
              "bytes, ancho, alto, sha256, brillo, contraste, nitidez, duplicado_de, apta_ia, motivo_ia, ruta_curada")  # *_ia: ver curacion.py

def _banderas(r):
    b = []
    if pd.isna(r["lluvia_mm"]): b.append("sin clima")
    else:
        if r["lluvia_mm"] >= ETL["lluvia_hora_mm"]: b.append("lluvia durante la captura")
        if r["radiacion"] == 0: b.append("nocturna")
        elif pd.notna(r["brillo"]) and r["brillo"] < ETL["brillo_oscuro"] and r["radiacion"] >= ETL["radiacion_dia"]: b.append("oscura con sol")
    if pd.notna(r["duplicado_de"]): b.append("duplicada")
    if isinstance(r["observacion"], str) and "no coincide" in r["observacion"]: b.append("fecha distinta a la carpeta")
    return "; ".join(b)

def _dia(g):
    """Resumen de un día de fotos: cantidad, primera/última, mayor hueco y cuántos huecos superan el umbral."""
    t = pd.to_datetime(g["tomada"]).sort_values()
    saltos = t.diff().dt.total_seconds().div(60).dropna()
    return pd.Series(dict(origen=g["origen"].mode().iat[0], fotos=len(g), primera=t.iat[0].strftime("%H:%M"), ultima=t.iat[-1].strftime("%H:%M"),
                          mayor_hueco_min=round(saltos.max()) if len(saltos) else 0, huecos=int((saltos > ETL["hueco_min"]).sum()),
                          fotos_con_lluvia=int(g["banderas"].str.contains("lluvia").sum()),
                          fotos_oscuras_con_sol=int(g["banderas"].str.contains("oscura").sum()),
                          fotos_nocturnas=int(g["banderas"].str.contains("nocturna").sum()),
                          brillo_medio=round(g["brillo"].mean(), 1) if g["brillo"].notna().any() else None))

def generar(pid):
    """Paso 4: une catálogo y clima, calcula las banderas y escribe los CSV. Devuelve un resumen con los totales."""
    etl.preparar()
    salida = ETL["dir"] / pid; salida.mkdir(parents=True, exist_ok=True)
    catalogo = store._df(f"SELECT {_COLS_FOTO} FROM etl_imagenes WHERE project_id=? ORDER BY tomada, archivo", (pid,))
    if catalogo.empty: raise ValueError("El catálogo está vacío: ejecute primero el paso 'listar'")
    catalogo = catalogo.astype({c: "Int64" for c in ("bytes", "ancho", "alto", "apta_ia")})  # enteros con vacíos (no 221676.0)
    catalogo.to_csv(salida / "imagenes_metadatos.csv", index=False, encoding="utf-8-sig")

    clima = store._df("SELECT hora AS hora_clima, lluvia_mm, temp, humedad, nubosidad, radiacion, condicion FROM etl_clima_horas WHERE project_id=?", (pid,))
    fotos = catalogo[(catalogo["origen"] != "otros") & catalogo["tomada"].notna()].copy()
    fotos["hora_clima"] = pd.to_datetime(fotos["tomada"]).dt.ceil("h").dt.strftime("%Y-%m-%dT%H:00")  # hora que contiene la foto
    fotos = fotos.merge(clima, on="hora_clima", how="left")
    fotos["banderas"] = fotos.apply(_banderas, axis=1) if len(fotos) else ""
    fotos.drop(columns=["ruta_drive", "sha256"]).to_csv(salida / "imagenes_clima.csv", index=False, encoding="utf-8-sig")

    # Resumen diario: todos los días del período (también los que no tienen fotos) con el clima completo del día
    dias = fotos.groupby("fecha").apply(_dia, include_groups=False) if len(fotos) else pd.DataFrame()
    rango = pd.date_range(fotos["fecha"].min(), fotos["fecha"].max()).strftime("%Y-%m-%d")
    clima_dia = store._df("""SELECT fecha, round(sum(lluvia_mm),1) lluvia_dia_mm, sum(lluvia_mm>=?) horas_con_lluvia,
        round(max(temp),1) temp_max, round(min(temp),1) temp_min, round(avg(nubosidad)) nubosidad_media
        FROM etl_clima_horas WHERE project_id=? GROUP BY fecha""", (ETL["lluvia_hora_mm"], pid)).set_index("fecha")
    resumen = dias.reindex(rango).join(clima_dia).rename_axis("fecha").reset_index()
    resumen["fotos"] = resumen["fotos"].fillna(0).astype(int)
    enteros = ["mayor_hueco_min", "huecos", "fotos_con_lluvia", "fotos_oscuras_con_sol", "fotos_nocturnas", "horas_con_lluvia"]
    resumen[enteros] = resumen[enteros].astype("Int64")  # los días sin fotos quedan vacíos, no 0.0
    resumen["estado"] = resumen.apply(lambda r: "sin fotos" if r["fotos"] == 0 else ("con huecos" if r["huecos"] > 0 else "completo"), axis=1)
    resumen.to_csv(salida / "resumen_diario.csv", index=False, encoding="utf-8-sig")

    cuenta = lambda txt: int(fotos["banderas"].str.contains(txt).sum())
    return dict(carpeta=str(salida), fotos_cruzadas=len(fotos), sin_clima=cuenta("sin clima"), con_lluvia=cuenta("lluvia"),
                oscuras_con_sol=cuenta("oscura"), nocturnas=cuenta("nocturna"), duplicadas=cuenta("duplicada"),
                dias=len(resumen), dias_sin_fotos=int((resumen["estado"] == "sin fotos").sum()),
                dias_con_huecos=int((resumen["estado"] == "con huecos").sum()),
                dias_no_aptos_por_lluvia=int((resumen["lluvia_dia_mm"].fillna(0) >= CLIMA["lluvia_no_apto_mm"]).sum()))
