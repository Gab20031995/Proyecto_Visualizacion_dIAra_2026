"""Salud de la cámara de cada obra: qué fotos llegaron, cuándo, con qué calidad, y alertas S-01..S-06.
Ítems EDA-01 (sección "Salud de la cámara" del panel) y ALE-03 (alertas de cámara) del backlog, docs/backlog_mejoras.md.

Responde a lo que preguntó la CGR con Limoncito: "¿la obra terminó o la cámara dejó de funcionar?". Una alerta S-xx
es de la CÁMARA, no de la obra: indica que la evidencia se está perdiendo o cambió, no que la obra esté atrasada.

Fotos que se cuentan (fotos()):
    - el catálogo del ETL (etl_imagenes): todo lo que llegó a Drive, se haya descargado o no
    - las fotos recibidas por la API de cámaras (tabla imagenes, fuente 'api')
    - las fotos sintéticas de las obras de ejemplo (data/obras/<id>/camara/indice.csv, las genera make_data.py), para
      que la demo sea coherente; las obras reales no tienen ese archivo
    Las de imagenes con fuente 'etl' NO se suman: son copias de las del catálogo. Se cuenta cada INSTANTE de captura una
    sola vez (en el Puente las carpetas "historico" y "camara" traen copias de las mismas capturas). Las duplicadas por
    contenido (misma huella) no cuentan. La calidad (apta / no apta y motivo) solo existe para las fotos ya curadas.

Horario de captura (horario()): el configurado en el proyecto (Administración, ADM-01); si no hay, el OBSERVADO en los
últimos 30 días con fotos (horas con fotos en al menos la mitad de los días); si tampoco, 24 h.

Alertas (umbrales en config.SALUD_CAMARA). Mismo formato que src/alerts.py: codigo, gravedad, periodo, descripcion, regla.
    S-01 MEDIA  horas_sin_fotos horas del horario de captura sin recibir fotos                     (obra en ejecución)
    S-02 MEDIA  dias_baja_cobertura de los últimos dias_cobertura días con menos de cobertura_min %
                de las fotos esperadas (requiere la frecuencia configurada)                       (obra en ejecución)
    S-03 MEDIA  cambio de encuadre detectado (src/etl/encuadre.py) y todavía "Por revisar"         (siempre)
    S-04 MEDIA  dias_no_aptas días seguidos con fotos, pero ninguna apta para la IA                (obra en ejecución)
    S-05 MEDIA  las fotos de la API llegan más de desfase_min minutos después de su hora de captura (siempre)
    S-06 ALTA   dias_sin_fotos días sin ninguna foto (o nunca llegó una) con la obra en ejecución.
                Si está activa, no se muestran S-01 ni S-02 (serían la misma noticia).
Una obra Planificada o Suspendida no genera S-01, S-02, S-04 ni S-06: ahí que no lleguen fotos puede ser lo esperado.
Las fechas y horas son de Costa Rica (UTC-6, sin horario de verano)."""
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from config import SALUD_CAMARA as U
from src import store, etl, proyectos, ciclo_alertas
from src.etl import encuadre
from src.clima.comun import ahora_cr

UTC_A_CR = pd.Timedelta(hours=-6)   # la columna imagenes.recibida la guarda SQLite en UTC (CURRENT_TIMESTAMP)


# ---------- fotos recibidas ----------
def fotos(pid):
    """DataFrame con una fila por instante de captura: fecha, hora, ts (datetime), apta_ia, motivo_ia, curada,
    recibida (solo API, UTC) y fuente ('drive' o 'api'). Ver docstring del módulo."""
    etl.preparar()
    d = store._df("""SELECT fecha, hora, apta_ia, motivo_ia, curada, NULL AS recibida, 'drive' AS fuente FROM etl_imagenes
            WHERE project_id=? AND origen<>'otros' AND fecha IS NOT NULL AND hora IS NOT NULL AND duplicado_de IS NULL
        UNION ALL
        SELECT fecha, CASE WHEN tomada IS NOT NULL THEN substr(tomada, 12, 8) ELSE hora || ':00' END,
               NULL, NULL, NULL, recibida, 'api' FROM imagenes
            WHERE project_id=? AND coalesce(fuente, 'api')='api' AND fecha IS NOT NULL AND hora IS NOT NULL""", (pid, pid))
    indice = proyectos.carpeta(pid) / "camara" / "indice.csv"
    if indice.is_file():   # obra de ejemplo con fotos sintéticas
        s = pd.read_csv(indice, usecols=["fecha", "hora"], dtype=str)
        d = pd.concat([d, s.assign(hora=s.hora.str[:5] + ":00", fuente="sintetica")], ignore_index=True)
    d["ts"] = pd.to_datetime(d.fecha + " " + d.hora.str[:8], errors="coerce")
    d = d.dropna(subset=["ts"])
    # Un instante, una foto: se prefiere la copia que ya pasó por la curación (trae la calidad)
    d = d.assign(_c=d.curada.notna()).sort_values(["ts", "_c"], ascending=[True, False]).drop_duplicates("ts")
    return d.drop(columns="_c").reset_index(drop=True)


def horario_efectivo(d, dias=30):
    """(desde, hasta) "HH:MM" de las horas con fotos en al menos la mitad de los días de los últimos `dias` días con
    fotos, o None si no hay fotos."""
    if not len(d): return None
    r = d[d.ts >= d.ts.max().normalize() - pd.Timedelta(days=dias - 1)]
    frac = r.groupby(r.ts.dt.hour).fecha.nunique() / r.fecha.nunique()
    horas = frac[frac >= 0.5].index if (frac >= 0.5).any() else frac.index
    return f"{min(horas):02d}:00", f"{max(horas):02d}:59"


def horario(p, d):
    """(desde, hasta, origen) del horario de captura: 'configurado', 'observado' o '24 h' (ver docstring del módulo)."""
    if p.get("captura_intervalo_min") and p.get("captura_desde") and p.get("captura_hasta"):
        return p["captura_desde"], p["captura_hasta"], "configurado"
    efectivo = horario_efectivo(d)
    return (*efectivo, "observado") if efectivo else ("00:00", "23:59", "24 h")


def minutos_en_horario(t0, t1, desde, hasta):
    """Minutos entre t0 y t1 que caen dentro del horario diario [desde, hasta] ("HH:MM"). Así, una cámara que solo
    trabaja de día no "se cae" de noche."""
    if t1 <= t0: return 0.0
    hd, md = map(int, desde.split(":")); hh, mh = map(int, hasta.split(":"))
    total, dia = 0.0, t0.date()
    while dia <= t1.date():
        a = datetime.combine(dia, datetime.min.time()).replace(hour=hd, minute=md)
        b = datetime.combine(dia, datetime.min.time()).replace(hour=hh, minute=mh) + timedelta(minutes=1)
        lo, hi = max(a, t0), min(b, t1)
        if hi > lo: total += (hi - lo).total_seconds() / 60
        dia += timedelta(days=1)
    return total


def _f(texto):
    """'2026-07-02' o '2026-07-02 14:43' -> '02/07/2026' o '02/07/2026 14:43' (formato de los textos de las alertas)."""
    return f"{texto[8:10]}/{texto[5:7]}/{texto[:4]}{texto[10:]}"

def _primer_bloqueo(motivo):
    """Primer motivo de bloqueo de la curación ("borrosa o lente empañado", "nocturna"...), sin los avisos."""
    return next((m for m in (motivo or "").split("; ") if m and not m.startswith("aviso")), None)


# ---------- serie diaria y huecos ----------
def _dias(p, d, hoy, esperadas, desde, hasta):
    """Una fila por día (para el mapa de calor y la tabla) y los intervalos de días sin fotos.
    El rango termina hoy si la obra sigue activa (así se ven los días recientes sin fotos) o el día de la última foto
    si está finalizada o cancelada. Como máximo los últimos config.SALUD_CAMARA["dias_mapa"] días."""
    fin = hoy if p.get("estado") in proyectos.ACTIVOS else d.ts.max().date()
    ini = max(d.ts.min().date(), fin - timedelta(days=U["dias_mapa"] - 1))
    d = d[(d.ts.dt.date >= ini) & (d.ts.dt.date <= fin)]
    # Cálculos por día de una sola vez (vectorizados): un bucle por día con pandas tardaba ~1 s en obras con 400 días
    horas = pd.crosstab(d.fecha, d.ts.dt.hour).reindex(columns=range(24), fill_value=0) if len(d) else pd.DataFrame()
    cur = d.assign(curada=d.curada.notna(), apta=(d.apta_ia == 1) & d.curada.notna(),
                   en_horario=(d.hora.str[:5] >= desde) & (d.hora.str[:5] <= hasta))
    por_dia = cur.groupby("fecha").agg(fotos=("ts", "size"), curadas=("curada", "sum"), aptas=("apta", "sum"),
                                        en_horario=("en_horario", "sum"))
    no_aptas = cur[cur.curada & ~cur.apta]
    motivos = (no_aptas.assign(m=no_aptas.motivo_ia.map(_primer_bloqueo)).dropna(subset=["m"])
               .groupby("fecha").m.agg(lambda x: x.value_counts().index[0]))   # motivo de bloqueo más frecuente del día
    filas, huecos, hueco = [], [], None
    for f in pd.date_range(ini, fin).strftime("%Y-%m-%d"):
        completo = f < hoy.isoformat()   # la cobertura solo se calcula en días completos (hoy todavía no terminó)
        if f not in por_dia.index:
            filas.append(dict(fecha=f, fotos=0, horas=[0] * 24, aptas=0, curadas=0, motivo=None,
                              cobertura=0 if esperadas and completo else None))
            hueco = hueco or [f, f]; hueco[1] = f
            continue
        if hueco: huecos.append(hueco); hueco = None
        x = por_dia.loc[f]
        filas.append(dict(fecha=f, fotos=int(x.fotos), horas=[int(v) for v in horas.loc[f]], aptas=int(x.aptas),
                          curadas=int(x.curadas), motivo=motivos.get(f),
                          cobertura=round(100 * int(x.en_horario) / esperadas) if esperadas and completo else None))
    if hueco: huecos.append(hueco)
    huecos = [dict(desde=a, hasta=b, dias=(pd.Timestamp(b) - pd.Timestamp(a)).days + 1) for a, b in huecos]
    return filas, huecos


# ---------- resumen completo ----------
def resumen(p, ahora=None):
    """Todo lo de la sección "Salud de la cámara" de una obra (p = proyecto de proyectos.obtener). ahora: para pruebas."""
    ahora = ahora or ahora_cr(); hoy = ahora.date()
    d = fotos(p["id"])
    esperadas = proyectos.fotos_esperadas_dia(p)
    desde, hasta, origen = horario(p, d)
    r = dict(hay_fotos=bool(len(d)), total_fotos=len(d), esperadas_dia=esperadas,
             horario=dict(desde=desde, hasta=hasta, origen=origen), ultima_foto=None, horas_sin_fotos=None,
             dias_sin_fotos=None, desde=None, hasta=None, cobertura_7d=None, dias=[], huecos=[], dias_sin_fotos_total=0,
             cambios_encuadre=[dict(c, url=f"/api/auditor/{p['id']}/encuadre/{Path(c['panel']).name}" if c.get("panel") else None)
                               for c in encuadre.cambios(p["id"])])
    if len(d):
        ult = d.ts.max()
        r.update(ultima_foto=ult.strftime("%Y-%m-%d %H:%M"), desde=d.fecha.min(), hasta=d.fecha.max(),
                 horas_sin_fotos=round(minutos_en_horario(ult.to_pydatetime(), ahora, desde, hasta) / 60, 1),
                 dias_sin_fotos=(hoy - ult.date()).days)
        r["dias"], huecos = _dias(p, d, hoy, esperadas, desde, hasta)
        r["dias_sin_fotos_total"] = sum(h["dias"] for h in huecos)
        r["huecos"] = sorted(huecos, key=lambda h: (-h["dias"], h["desde"]))[:10]   # los 10 más largos
        semana = [x["cobertura"] for x in r["dias"] if x["cobertura"] is not None
                  and x["fecha"] >= (hoy - timedelta(days=U["dias_cobertura"])).isoformat()]
        r["cobertura_7d"] = round(sum(semana) / len(semana)) if semana else None
    # Se guardan con su estado (src/ciclo_alertas.py): llegan solo las NO descartadas, con id, estado y vencida
    r["alertas"] = ciclo_alertas.sincronizar(p["id"], alertas(p, r, d, ahora), "camara", ahora)
    return r


# ---------- alertas S-01..S-06 ----------
def alertas(p, r, d, ahora):
    """Alertas de la cámara a partir del resumen r (ver docstring del módulo)."""
    out, hoy = [], ahora.date()
    activa = p.get("estado") == "En ejecución"
    tiene_camara = r["hay_fotos"] or bool(p.get("camara") or p.get("camara_api") or p.get("drive_carpeta"))
    s06 = False
    if activa and tiene_camara:
        if not r["hay_fotos"]:
            s06 = True
            out.append(dict(codigo="S-06", gravedad="ALTA", periodo="Sin fotos", clave="sin-fotos",
                descripcion="La obra está en ejecución y tiene cámara configurada, pero no se ha recibido ninguna foto.",
                regla="Obra en ejecución sin fotos recibidas"))
        elif r["dias_sin_fotos"] >= U["dias_sin_fotos"]:
            s06 = True
            vencida = p.get("fecha_fin") and hoy.isoformat() > p["fecha_fin"]
            out.append(dict(codigo="S-06", gravedad="ALTA", periodo=f"Desde {_f(r['ultima_foto'][:10])}", clave=r["ultima_foto"],
                descripcion=f"Sin fotos desde el {_f(r['ultima_foto'])} ({r['dias_sin_fotos']} días) con la obra en ejecución. " +
                    (f"La fecha de fin prevista ({_f(p['fecha_fin'])}) ya pasó: si la obra terminó, ciérrela en Administración."
                     if vencida else "Verifique si la cámara sigue instalada y enviando, o si falta actualizar la carga de fotos."),
                regla=f">= {U['dias_sin_fotos']} días sin fotos con la obra en ejecución"))
        if not s06 and r["horas_sin_fotos"] >= U["horas_sin_fotos"]:
            out.append(dict(codigo="S-01", gravedad="MEDIA", periodo=f"Desde {_f(r['ultima_foto'])}", clave=r["ultima_foto"],
                descripcion=f"{r['horas_sin_fotos']} h del horario de captura ({r['horario']['desde']} a "
                            f"{r['horario']['hasta']}) sin recibir fotos.",
                regla=f">= {U['horas_sin_fotos']} h del horario de captura sin fotos"))
        if not s06 and r["esperadas_dia"]:
            inicio = (hoy - timedelta(days=U["dias_cobertura"])).isoformat()
            dias = [x for x in r["dias"] if x["cobertura"] is not None and x["fecha"] >= inicio]
            bajos = [x for x in dias if x["cobertura"] < U["cobertura_min"]]
            if len(bajos) >= U["dias_baja_cobertura"]:
                out.append(dict(codigo="S-02", gravedad="MEDIA", periodo=f"{_f(bajos[0]['fecha'])} a {_f(bajos[-1]['fecha'])}", clave="vigente",
                    descripcion=f"{len(bajos)} de los últimos {len(dias)} días recibieron menos del {U['cobertura_min']} % de "
                                f"las {r['esperadas_dia']} fotos esperadas por día (cobertura media {r['cobertura_7d']} %).",
                    regla=f">= {U['dias_baja_cobertura']} días con cobertura < {U['cobertura_min']} %"))
        # S-04: racha más reciente de días con fotos curadas y ninguna apta (los días sin fotos no la cortan)
        racha = []
        for x in reversed(r["dias"]):
            if not x["curadas"]: continue
            if x["aptas"]: break
            racha.append(x)
        if len(racha) >= U["dias_no_aptas"]:
            motivo = Counter(x["motivo"] for x in racha).most_common(1)[0][0]
            out.append(dict(codigo="S-04", gravedad="MEDIA", periodo=f"{_f(racha[-1]['fecha'])} a {_f(racha[0]['fecha'])}", clave=racha[-1]["fecha"],
                descripcion=f"{len(racha)} días seguidos con fotos, pero ninguna sirve para la IA (motivo principal: {motivo}). "
                            "Revise el lente, la exposición o la orientación de la cámara.",
                regla=f">= {U['dias_no_aptas']} días seguidos sin fotos aptas"))
    for c in r["cambios_encuadre"]:
        if c.get("estado") == "Por revisar":
            out.append(dict(codigo="S-03", gravedad="MEDIA", periodo=_f(c["fecha"]), clave=c["fecha"],
                descripcion=f"{c['clasificacion']}: la imagen cambió entre el {_f(c['ultima_fecha_antes'])} y el {_f(c['fecha'])}. "
                            "Revise el panel antes/después y confirme o descarte el cambio.",
                regla=f"Disimilitud entre ventanas >= {encuadre.E['umbral_ventana']}"))
    # S-05: solo fotos de la API (traen la hora de llegada); se compara con la hora de captura que envía la cámara
    api = d[(d.fuente == "api") & d.recibida.notna() & (d.ts >= pd.Timestamp(ahora) - pd.Timedelta(days=7))] if len(d) else d
    if len(api) >= 5:
        desfase = ((pd.to_datetime(api.recibida) + UTC_A_CR - api.ts).dt.total_seconds() / 60).median()
        if abs(desfase) > U["desfase_min"]:
            out.append(dict(codigo="S-05", gravedad="MEDIA", periodo="Últimos 7 días", clave="vigente",
                descripcion=f"Las fotos llegan {abs(desfase):.0f} min {'después' if desfase > 0 else 'ANTES'} de su hora de "
                            f"captura (mediana de {len(api)} fotos). Revise el reloj de la cámara o su conexión.",
                regla=f"Desfase captura-llegada > {U['desfase_min']} min"))
    return out
