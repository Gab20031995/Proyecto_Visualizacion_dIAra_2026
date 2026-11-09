# dIAra · Propuesta de mejoras a partir de las respuestas de la CGR y los colabs del profesor

Fecha: 2026-11-09 · Insumos revisados:
1. El código del MVP en `diara/` (backend FastAPI, frontend, ETL, IA, clima y reportería).
2. El documento *Preguntas y respuestas de y para la Contraloría General de la República* (grupos 1 a 8 y sus anexos:
   Apps Script, prompt de Gemini y firmware de la ESP32-CAM).
3. Los notebooks `PROERI_cambio_camara_v2_sin_interpolacion.ipynb` y `Comparación_tres_proyectos_200_superposicion.ipynb`.

El backlog priorizado que sale de esta propuesta está en [`backlog_mejoras.md`](backlog_mejoras.md) (y en
[`backlog_mejoras.csv`](backlog_mejoras.csv) para importarlo a GitHub Projects, Jira o Trello).

---

## 1. Resumen ejecutivo

- **Mucho de lo que el equipo propuso ya existe en el MVP.** El administrador ya registra las fechas de inicio y fin,
  las coordenadas (obligatorias y validadas en Costa Rica), el número de SICOP, el monto y la cámara. El perfil de
  empresa ejecutora ya carga el cronograma, la bitácora y los costos y los cruza con la IA (alertas C-01 a C-05). Estas
  ideas no hay que construirlas de nuevo. Lo que sí falta es completarlas (ver §3).
- **La brecha más grande es la salud de las cámaras.** Hoy el ETL detecta fotos quemadas, el lente empañado, los
  huecos y el cambio de encuadre, pero **no alimenta el panel ni las alertas**. La CGR pidió esto explícitamente
  (Limoncito: "¿se acabó la obra o se cayó la cámara?"). Proponemos una familia de alertas **S-xx (salud de la
  cámara)** y reutilizar el código del colab de cambio de encuadre.
- **La foto lleva la fecha de llegada, no la de captura.** El Apps Script pone nombre con `new Date()` en el servidor
  de Google, así que la fecha es la de recepción. Esto contradice la respuesta de la CGR a la pregunta 1 del grupo 1.
  El firmware sí manda `folder` e `id` en la URL, pero el script los ignora y usa un `FOLDER_ID` fijo. Hay que
  estandarizar el script y el firmware antes de escalar a más obras.
- **El prompt de Gemini es caro y riesgoso.** Pide un JSON muy largo (EPP por trabajador) y un "dictamen
  técnico-contractual **vinculante**" a partir de una sola foto de baja resolución. Proponemos un prompt compacto
  con nivel de confianza, procesamiento selectivo (solo fotos que pasaron los filtros baratos) y en lote. Con eso
  bajan el costo y el riesgo institucional.
- **El enfoque de la CGR no es la obra individual: son 502 obras de PROERI.** El mayor valor de dIAra para la CGR es
  **priorizar qué obras visitar** con un índice de riesgo por obra. Así se abarata la fiscalización, que fue el
  problema que la CGR planteó. Esto debería guiar el foco del proyecto.

---

## 2. Diagnóstico del MVP actual (lo que ya está)

| Área | Estado | Comentario |
|---|---|---|
| Roles (admin, auditor, contratista, público) | ✅ Completo | Aislamiento por rol bien documentado y probado. |
| Alta de proyecto (fechas, coordenadas, SICOP, monto, cámara, token) | ✅ | Faltan: frecuencia esperada de captura, carpeta de Drive y códigos externos (PROERI, BPIP, CFIA). |
| Estados de la obra con motivo e historial | ✅ | Falta un estado propio de la **cámara** (instalada, confirmada, retirada). |
| Cronograma, bitácora y costos del contratista + cruce C-01..C-05 | ✅ | Responde a las preguntas de los grupos 3, 4, 5 y 8 sobre los cronogramas. |
| ETL de Drive, curación, hojas de contacto y clima histórico | ✅ (CLI) | Se ejecuta a mano y **no alimenta las alertas**. |
| IA: YOLO (personas/vehículos) + índice de cambio | 🟡 Investigación | No ve a los obreros en zonas techadas. COCO no tiene maquinaria de obra. Licencia AGPL. |
| Alertas A-01..A-04 | 🟡 | Dependen del avance y la maquinaria, que en datos reales **no se miden**, así que en las obras reales casi no se disparan. |
| Aportes ciudadanos | 🟡 | El auditor aprueba o descarta. No hay clasificación, derivación ni respuesta al ciudadano. |
| Reportes PDF por correo y programador interno | ✅ | |
| Clima con varias fuentes consolidadas | ✅ | |
| Persistencia | 🔴 | SQLite (no persiste en Cloud Run). No escala a 502 obras con varios procesos. |
| Seguridad | 🟡 | Falta un límite de intentos de login, la revocación de sesión y el difuminado de rostros y placas. |

---

## 3. Propuestas por pregunta de la CGR

Formato: **Lo que dijo la CGR → Lo que ya tenemos → Propuesta**. El código entre corchetes remite al backlog.

### Grupo 1 · Captura, metadatos y procesamiento

**G1-P1 Metadatos.** Cada foto se asocia por carpeta y nombre. El nombre lleva la fecha "de captura".
- *Hallazgo:* en el Apps Script, `folderName` y `timestamp` salen de `new Date()` **en el servidor**, así que la fecha
  es la de **recepción**. Si la ESP32 reintenta o la red se atrasa, la hora queda corrida. Además, dos fotos en el
  mismo segundo producen el mismo nombre de archivo.
- *Ya tenemos:* el inventario por nombre (`src/etl/catalogo.py`) y la tabla `etl_imagenes`. La misma expresión
  regular del colab (`(20\d{2})(\d{2})(\d{2})[-_](\d{2})(\d{2})(\d{2})`) cubre los formatos.
- *Propuesta:* un **EDA automático por obra** dentro de la app (no en Colab), con el heatmap día × hora de los colabs
  y los días sin fotos, el horario efectivo de la cámara y los cambios de encuadre. [EDA-01, EDA-02]

**G1-P2 Frecuencia de captura.** No hay un estándar y depende de cada ESP32.
- *Propuesta:* en el alta del proyecto el admin define la **frecuencia esperada** (por ejemplo, cada 15 min de 07:00
  a 17:00) y el **volumen esperado** (fotos por día). Con esto se calcula la **cobertura** (fotos recibidas ÷
  esperadas) y se dispara S-02. El auditor recibe la obra nueva y **confirma la instalación de la cámara** (estado
  de la cámara: *Pendiente de instalación → Instalada → Confirmada por auditor → Retirada*). [ADM-01, ADM-02, CAM-05]
- *Ojo con el costo:* hoy el Puente toma una foto cada 5 min, las 24 h (~41 000 fotos). A ~200 KB por foto UXGA
  son ~58 MB por día y cámara. **Para 502 cámaras serían ~29 GB/día.** Capturar solo en jornada (07–17 h) cada
  15 min baja a ~40 fotos por día (~8 MB): unas 7 veces menos. *Cifras aproximadas, a validar con los archivos
  reales.* [CAM-03]

**G1-P3 Selección de imágenes.** Se analiza una muestra sin criterio.
- *Ya tenemos:* la curación (`apta_ia` + `motivo_ia`) descarta las fotos nocturnas, oscuras, quemadas, empañadas
  y duplicadas.
- *Propuesta:* un **muestreo reproducible** que tome de los colabs la estratificación por día, la semilla fija y la
  preferencia por las fotos cercanas a una hora objetivo. Además, una **selección por evento**: enviar a Gemini solo
  las fotos con índice de cambio alto o con personas o vehículos detectados, más N fotos "testigo" por día. [IA-01]

**G1-P4 Prompt de Gemini.** Las imágenes se procesan una por una.
- *Problemas del prompt actual:*
  1. Pide un "**dictamen técnico-contractual vinculante**" y "autoriza continuidad de fase". Una IA, a partir de una
     foto, no puede ni debe emitir eso: es un riesgo jurídico y reputacional para la CGR.
  2. Pide EPP **por trabajador**. En estas fotos las personas miden 20–60 px (según la medición del README), así que
     el resultado no es confiable y multiplica los tokens de salida, que son los más caros.
  3. No tiene campos de **confianza** ni de "no determinable". El modelo inventa en vez de abstenerse.
  4. Contiene una variable de plantilla sin resolver (`{{Inserta aquí la variable...}}`).
  5. Una llamada por foto repite el prompt largo en cada llamada.
- *Propuesta:* un prompt compacto (borrador abajo), con **salida estructurada** (`responseSchema`), **varias fotos
  del mismo día en una sola llamada** (por ejemplo, un mosaico o 4–6 imágenes), procesamiento **en lote** (Batch API,
  verificar el descuento vigente) y el modelo más liviano que alcance (por ejemplo, la variante Flash-Lite). Hay que
  medir la calidad contra un pequeño conjunto etiquetado a mano antes de elegir. [IA-02, IA-03, IA-04]

```text
Eres asistente de un equipo de fiscalización de obra pública. Describes SOLO lo visible en las fotos; no emites
dictámenes ni conclusiones legales. Si algo no se puede determinar, usa "no_determinable" y confianza baja.
Fotos: {n} imágenes de la obra {proyecto}, cámara {camara}, fecha {fecha}, horas {horas}.
Responde con el esquema JSON indicado.
```

```json
{
  "fotos": [{
    "hora": "HH:MM",
    "apta": true,
    "motivo_no_apta": null,
    "personas": {"n": 0, "confianza": 0.0},
    "maquinaria": [{"tipo": "retroexcavadora|camion|grua|mezcladora|otro", "operando": "si|no|no_determinable", "confianza": 0.0}],
    "actividad": "alta|media|baja|ninguna|no_determinable",
    "clima_visible": "seco|lluvia|suelo_mojado|no_determinable",
    "riesgo_sst_visible": [{"descripcion": "string", "confianza": 0.0}]
  }],
  "resumen_dia": "máx. 280 caracteres, solo hechos observables",
  "requiere_revision_humana": true
}
```

**G1-P5 Almacenamiento de resultados.** Los JSON están en otro repositorio, se incorporan a mano y nadie los revisa.
- *Propuesta:* una tabla `ia_resultados` vinculada a `etl_imagenes.drive_id`, con el modelo, la versión del prompt,
  el costo en tokens y el JSON. Una **cola de revisión del auditor** donde el auditor confirma o corrige el
  resultado. Lo que el auditor corrige se guarda como **etiqueta** y sirve después para entrenar o afinar el
  modelo local. La revisión la hace el **auditor**, no el admin: el auditor conoce la obra. El admin solo ve las
  métricas de la cola. [IA-05, IA-06]

**G1-P6 Seguimiento de errores.** No hay estado de procesamiento porque nada es automático.
- *Propuesta:* un **pipeline programado** que reutiliza el `programador.py` que ya existe (con su bloqueo en la base):
  listar → descargar → curar → detectar → (Gemini opcional) → publicar → evaluar las alertas. Cada foto lleva un
  estado: `pendiente | descargada | curada | analizada | error(motivo) | reintentos`. Se agrega una vista de
  administración "Pipeline" con los pendientes y los errores. [PIP-01, PIP-02, PIP-03]

**G1-P7 Apps Script.** Lo que se puede modificar: `FOLDER_ID`, la zona horaria y la estructura de carpetas.
- *Propuesta: Apps Script v2*
  - Usar los parámetros `id` (cámara) y `folder` que **ya envía** la ESP32, con una lista blanca de cámaras y
    carpetas y un token.
  - Usar `tomada` (la hora de captura que manda la cámara, tomada por NTP). La hora de recepción se guarda aparte.
  - Nombre estándar `{PROYECTO}_{CAMARA}_{AAAAMMDD}_{HHMMSS}.jpg` y `LockService` para evitar carpetas
    duplicadas.
  - Una fila por foto en una **Hoja de Google** de bitácora: recepción, captura, cámara, tamaño, RSSI, batería,
    versión del firmware y error. Esto alimenta el EDA sin tener que listar Drive.
  - **Reenvío opcional a la API de dIAra** (`POST /api/camaras/{pid}/imagenes`, que ya existe). Así dIAra deja de
    depender de que la carpeta de Drive sea pública.
  - Responder con un JSON `{ok, archivo, error}`. Hoy responde con el texto "Error: ..." y un código 200, y la
    cámara solo revisa el 302, así que cree que todo salió bien. Apps Script no permite devolver códigos HTTP de
    error, por eso es el firmware el que debe leer el campo `ok`. [CAM-01]

**G1-P8 Presupuesto.** Solo hay licencias Pro individuales y no hay estimación.
- *Propuesta:* una **estimación de costos por escenario** (10, 50 y 502 obras) que cubra el almacenamiento, las
  llamadas a la IA y el servidor. La palanca principal es **no mandar todo a la IA de pago**: filtros locales
  gratuitos (curación + YOLO en CPU) y luego Gemini solo sobre la muestra. Además, preparar un documento de
  solicitud de presupuesto para la CGR, con la fórmula `fotos/día × fotos enviadas a IA (%) × tokens por foto ×
  precio`. [GOB-01]

**G1-P9 Registro geográfico.** No existe.
- *Ya tenemos:* las coordenadas son obligatorias al crear la obra. *Falta:* el campo **carpeta de Drive** por
  proyecto (hoy está en `config.ETL["carpetas"]`, en el código). Se agrega al formulario del admin. [ADM-03]

### Grupo 2 · Protocolo ante inactividad prolongada (no existe)
- *Propuesta:* un **protocolo de alerta con ciclo de vida**:
  1. Se detecta la alerta.
  2. El auditor la clasifica en un plazo de N días hábiles.
  3. El auditor puede solicitar una justificación a la empresa, que responde desde su perfil.
  4. La alerta queda *Confirmada* o *Descartada*, con un motivo obligatorio.
  5. Si se confirma, se escala (oficio o visita).
- Cada transición queda en el historial. Esto da métricas reales: el tiempo de atención y la tasa de falsos
  positivos.
- Nueva alerta **A-05 inactividad con datos reales**: N días hábiles con clima apto y sin personas ni cambio
  significativo. Hoy A-01 depende de una "maquinaria" que no se mide en las obras reales. [ALE-01, ALE-02]

### Grupo 3 · Actividad detectada frente al avance físico real
- La CGR dice que solo un ingeniero lo puede determinar. *Ya tenemos* la curva planificada con el cronograma del
  contratista.
- *Propuesta:* no prometer "avance físico" desde la cámara. Mostrar **actividad observada** (días-persona y horas con
  actividad) frente a **avance declarado** (bitácora) frente a **avance planificado** (cronograma). La brecha entre
  los tres es la señal para que un ingeniero revise. Cambiar el rótulo "avance observado" por "actividad observada"
  donde corresponda. [UX-01]
- Timelapse/dron/POV: ya existe `/api/timelapse`. Sin presupuesto, la opción viable es un **timelapse automático
  semanal** generado a partir de las fotos aptas, más las fotos que suban los ciudadanos y el auditor en sus visitas
  (con GPS). [PUB-02]

### Grupo 4 · Cronogramas, continuidad e indicadores
- *Limoncito:* la cámara se retiró sin que el sistema lo supiera. *Propuesta:* las alertas de salud de la cámara
  (se dispara S-06 "cámara inactiva con la obra en ejecución antes de la fecha fin") y el estado *Retirada* de la
  cámara con motivo. [CAM-05, ALE-03]

Alertas **S-xx (salud de la cámara)** propuestas:

| Código | Regla | Fuente |
|---|---|---|
| S-01 | Sin fotos en más de N horas dentro del horario esperado | `imagenes` / bitácora del Apps Script |
| S-02 | Cobertura del día por debajo del X % de lo esperado (frecuencia configurada) | Alta del proyecto |
| S-03 | **Cambio de encuadre**: distancia del descriptor HOG frente a la referencia fija mayor que el umbral y ORB con pocas coincidencias | Colab PROERI v2 |
| S-04 | N días seguidos con fotos *no aptas* (empañada, quemada u oscura) | Curación |
| S-05 | Desfase entre la hora de captura y la hora de recepción mayor que M min (reloj o red) | Apps Script v2 |
| S-06 | Obra *En ejecución*, la cámara sin datos ≥ D días y la fecha fin sin alcanzar | Proyecto + imágenes |

**Indicadores de éxito** (la CGR respondió "todos" y pidió ayuda en el grupo 7). Ver §4.

### Grupo 5 · Empresa ejecutora y herramientas de fiscalización
- El perfil ya existe. La CGR pide una **finalidad única** para el perfil. *Propuesta:* documentar esa finalidad como
  "**aportar la versión oficial del contratista (cronograma, bitácora, costos) y responder a las solicitudes de
  justificación de las alertas**". El segundo punto es nuevo y conecta con el protocolo del grupo 2. [CON-01]
- **Integraciones** (investigar antes de construir) [INT-01..INT-04]:
  - **ePROERI / PROERI.** La mayoría de las obras fiscalizadas son de PROERI y **no pasan por SICOP**. Esta es la
    integración prioritaria: averiguar qué datos expone (cronogramas, avances, desembolsos) y con qué identificador.
  - **CFIA.** Las obras se registran en el CFIA y el CFIA lleva la **Bitácora Digital de Obra**. Si se pudiera
    consultar, evitaría que el contratista cargue dos veces la bitácora en dIAra.
  - **Banco de Proyectos de Inversión Pública (MIDEPLAN).** Código del proyecto, monto y etapa.
  - **SICOP.** Número de procedimiento (el campo ya existe). Sirve para las obras que no son de PROERI.
  - Acción inmediata y barata: agregar al proyecto los **campos de identificadores externos** (código PROERI, BPIP,
    CFIA), aunque al principio se llenen a mano. [ADM-04]
- **Capacidad de fiscalización:** la CGR no supervisa obras individuales. Fiscaliza recursos (por ejemplo, 502 obras
  de PROERI) mediante **auditorías**. *Propuesta de foco:* dIAra como herramienta de **selección de muestra basada en
  riesgo** para una auditoría o un seguimiento. Un **índice de riesgo por obra** (alertas activas, brecha del plazo,
  salud de la cámara, aportes ciudadanos, monto) ordena qué obras visitar y abarata las visitas. Hay que investigar
  qué productos de la CGR encajan: auditorías operativas o de cumplimiento, seguimiento de disposiciones. [GOB-02,
  SEG-01]

### Grupo 7 · Participación ciudadana
- Hoy el auditor aprueba o descarta el aporte y no pasa nada más.
- *Propuesta:* un **flujo de aportes**:
  1. La IA hace un **pre-triage** (clasifica el aporte en *avance, seguridad, abandono, daño, otro*, detecta si la
     foto corresponde a una obra y si contiene rostros o placas, y resume el texto).
  2. El auditor revisa.
  3. El auditor puede **vincular** el aporte a una alerta o a una observación.
  4. El auditor puede **derivar** el aporte a la institución responsable. La vía natural es la **Contraloría de
     Servicios** de esa institución (Ley 9158).
  5. Si es una **denuncia**, se redirige al formulario oficial de denuncias de la CGR. dIAra no la tramita.
  6. El ciudadano recibe un **número de seguimiento** y ve el estado (recibido, revisado, derivado).
- La IA solo sugiere: siempre decide el auditor. [CIU-01..CIU-04]

### Grupo 8 · SICOP, curvas y confianza
- *Confianza del modelo:* YOLO ya entrega una confianza (`conf_max`). Gemini no la entrega, y el prompt propuesto la
  agrega. Al ciudadano **no** se le muestra un porcentaje crudo. Se muestran un nivel (*alta, media, baja*) y la
  leyenda "información automatizada pendiente de verificación". Al auditor se le muestra la confianza completa.
  [IA-07]
- *Alertas prioritarias por equipo:*
  - **CGR:** inactividad (A-05), brecha entre el plazo y la actividad, salud de la cámara (S-xx), inconsistencias con
    el contratista (C-xx) y prórrogas o modificaciones presupuestarias (cuando haya integración).
  - **Ciudadanía:** "sin actividad visible en N días", "cámara sin transmitir" y "fecha de entrega cercana". Esta
    información es pública y no revela hallazgos de auditoría, según la regla que ya documenta `routes/publico.py`.
    [ALE-04]

### Anexo · Firmware de la ESP32-CAM (estandarización)
Problemas detectados en el código compartido:

| # | Problema | Propuesta |
|---|---|---|
| 1 | La contraseña WiFi, el ID de despliegue y el ID de carpeta están **escritos en el código** (y aparecen en el documento compartido) | `secrets.h` fuera del control de versiones, o configuración por portal cautivo (WiFiManager). **Cambiar la clave del MIFI y volver a desplegar el script, porque ya circularon.** |
| 2 | `client.setInsecure()` (TLS sin verificar) | Certificado raíz de Google embebido |
| 3 | `DEEP_SLEEP_INTERVAL_S 5` (una foto cada ~5 s más el arranque) | Intervalo configurable y ventana horaria (no capturar de noche) |
| 4 | No manda la hora de captura | NTP al despertar y enviar `tomada` |
| 5 | Si falla el WiFi o Google, **la foto se pierde** | Guardar en la microSD y reenviar en el siguiente ciclo |
| 6 | Considera éxito cualquier `302` aunque el script haya fallado | Seguir la redirección y validar el campo `ok` del JSON de Apps Script v2 |
| 7 | No reporta su propio estado | Mandar el *heartbeat* con RSSI, voltaje, versión del firmware, reinicios y fotos en cola |
| 8 | IP fija, propia de una red específica | DHCP por defecto, con IP fija opcional por configuración |

Entregable: un **firmware de referencia + Apps Script v2 + hoja de instalación** (checklist de montaje: orientación,
que no quede de cabeza (Limoncito y el Puente llegan rotados 180°), encuadre de referencia y prueba de envío). Este
paquete es el estándar para cualquier obra nueva. [CAM-02, CAM-04]

---

## 4. Indicadores de impacto propuestos

| Dimensión | Indicador | Equipo |
|---|---|---|
| Operación | % de días con cobertura ≥ 80 % de lo esperado, por cámara | CGR |
| Operación | Tiempo medio hasta detectar una cámara caída (de la última foto a la alerta S-01) | CGR |
| Detección | Alertas confirmadas ÷ alertas revisadas (precisión) | CGR |
| Detección | Días entre el inicio de un atraso y su primera alerta | CGR |
| Oportunidad | Tiempo medio de atención de una alerta (de abierta a cerrada) | CGR |
| Eficiencia | Visitas de campo evitadas o priorizadas gracias al índice de riesgo; costo por obra monitoreada | CGR |
| IA | % de resultados de IA corregidos por el auditor; costo de IA por obra y mes | CGR |
| Ciudadanía | Aportes recibidos, % con respuesta y tiempo de respuesta | Ciudadanía |
| Ciudadanía | Aportes que originaron una observación o una alerta confirmada | Ciudadanía |
| Ciudadanía | Visitas y suscriptores por obra | Ciudadanía |

Se mostrarían en una pestaña "Indicadores" del administrador y en un resumen público agregado. [KPI-01, KPI-02]

---

## 5. Código de los colabs que conviene reutilizar

| Del colab | Para qué en dIAra | Dónde |
|---|---|---|
| Regex de fecha-hora `(20\d{2})(\d{2})(\d{2})[-_](\d{2})(\d{2})(\d{2})` | Unificar el parseo de nombres (incluido el nombre estándar nuevo) | `src/etl/catalogo.py` |
| `descriptor()` HOG 6×8×9 + promedio diario + **referencia fija** + **disimilitud entre ventanas** | Alerta S-03 de cambio de encuadre y nueva referencia tras un cambio confirmado | `src/etl/encuadre.py` (nuevo) |
| `orb_metrics()` (ORB + homografía RANSAC, escala estimada) | Confirmar candidatos de S-03 y separar *movimiento de la cámara* de *zoom* y de *obra nueva* | `src/etl/encuadre.py` |
| Cobertura diaria e `intervalos_sin_datos` | S-01, S-02 y el EDA | `src/etl/cruce.py` |
| Heatmap día × hora (fines de semana en rojo, separador de meses) | Vista "Salud de la cámara" en el panel | Frontend (un gráfico JS con los mismos datos) |
| Muestreo estratificado por día, con semilla, cerca de una hora objetivo | Selección para Gemini y para etiquetar | `src/ia/muestreo.py` (nuevo) |
| Brillo + Tenengrad tras eliminar ruido, con el estado `INSUFFICIENT_LIGHT` | Comparar con la nitidez `FIND_EDGES` actual. Tenengrad es más estándar, pero requiere recalibrar los umbrales | `src/etl/curacion.py` |
| Panel antes/después de un candidato | Evidencia visual adjunta a la alerta S-03 y al PDF | `src/reporte_pdf.py` |
| Superposición entre originales y tratadas | Trazabilidad entre las carpetas `imagenes_tratadas` y las originales | Paso `estado` del ETL |

*Nota:* los colabs usan OpenCV, que el MVP no tiene (usa Pillow). Se puede agregar `opencv-python-headless` a
`requirements-ia.txt` sin afectar al servidor web, o reescribir el HOG con NumPy y Pillow si se quiere mantener
liviano el servidor.

---

## 6. Deuda técnica que limita el escalamiento

1. **SQLite a PostgreSQL** (Cloud SQL), necesario para 502 obras y varios procesos.
2. **Mover a la base la configuración por obra que hoy vive en el código** (`config.ETL["carpetas"]`, `rotacion`,
   `excluir`, `nitidez_min_obra`).
3. **Pruebas automatizadas** (no hay `tests/`) y CI en GitHub Actions.
4. Seguridad pendiente: límite de intentos de login, revocación de sesiones y difuminado de rostros y placas antes de
   publicar.
5. Licencia AGPL de Ultralytics: decidirlo antes de producción (alternativas con licencias permisivas, a verificar: los
   detectores de torchvision, con licencia BSD, o RT-DETR en su implementación original, con licencia Apache-2.0).
6. **No subir a este repositorio** el documento de la CGR ni el firmware con credenciales.
