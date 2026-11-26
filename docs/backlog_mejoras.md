# dIAra · Backlog de mejoras

Sale de [`propuesta_mejoras_cgr.md`](propuesta_mejoras_cgr.md). También está en [`backlog_mejoras.csv`](backlog_mejoras.csv) para importarlo a GitHub Projects, Jira o Trello.

**Prioridad (MoSCoW):** Must = imprescindible para la siguiente entrega · Should = importante · Could = deseable.  
**Tamaño:** S ≈ 1–3 días · M ≈ 1 semana · L ≈ 2 semanas · XL > 2 semanas (para una persona; a ajustar en la planificación).  
**Origen:** pregunta de la CGR (G1-P4 = grupo 1, pregunta 4) o colab del profesor.

## Resumen por fase

- **Fase 1 (Must, 29 ítems):** CAM-01, CAM-02, CAM-03, CAM-05, CAM-06, PIP-01, PIP-02, ALE-01, ALE-02, ALE-03, EDA-01, EDA-02, IA-01, IA-02, IA-03, IA-05, ADM-01, ADM-03, CIU-04, PUB-01, INT-01, GOB-02, GOB-01, TEC-02, VIZ-01, VIZ-02, VIZ-04, VIZ-07, VIZ-11
- **Fase 2 (Should, 24 ítems):** CAM-04, PIP-03, PIP-04, IA-04, IA-06, IA-07, ADM-02, ADM-04, CON-01, CON-02, CIU-01, CIU-02, UX-01, INT-02, SEG-01, KPI-01, TEC-01, TEC-03, TEC-04, VIZ-03, VIZ-05, VIZ-06, VIZ-08, VIZ-10
- **Fase 3 (Could, 10 ítems):** ALE-04, EDA-03, IA-08, CIU-03, PUB-02, INT-03, INT-04, KPI-02, VIZ-09, VIZ-12

Orden sugerido dentro de la Fase 1: primero **CAM-06, CAM-01, CAM-03, ADM-01, ADM-03, TEC-02** (bases), después **EDA-01, EDA-02, PIP-01, PIP-02** (datos automáticos), luego **ALE-01, ALE-02, ALE-03, CAM-05** (alertas útiles) y en paralelo **IA-01, IA-02, IA-03, IA-05, GOB-01** (costo de la IA) e **INT-01, GOB-02, CIU-04, PUB-01**. Los VIZ Must (VIZ-01, 02, 04, 07, 11) son cortos y se pueden hacer en cualquier momento.

## CAM · Cámaras y captura estandarizada

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| CAM-01 | Apps Script v2 | Must | M | — | G1-P1, G1-P7 |
| CAM-02 | Firmware ESP32 de referencia | Must | L | CAM-01 | Anexo firmware |
| CAM-03 | Política de frecuencia de captura | Must | S | — | G1-P2, G1-P8 |
| CAM-05 | Ciclo de vida de la cámara | Must | M | ADM-01 | G1-P2, G4 Limoncito |
| CAM-06 | Rotar credenciales expuestas | Must | S | — | Anexo firmware |
| CAM-04 | Kit de instalación de cámara | Should | S | CAM-02 | Anexo firmware |

<details><summary><b>CAM-01</b> · Apps Script v2</summary>

*Historia:* Como equipo técnico quiero que el Apps Script use la cámara y la carpeta que envía la ESP32, la hora de captura y responda con un estado verificable, para que cada foto quede bien identificada.

*Criterios de aceptación:* Usa los parámetros id/folder con lista blanca y token; nombre {PROYECTO}_{CAMARA}_{AAAAMMDD}_{HHMMSS}.jpg; guarda hora de captura y de recepción; LockService; respuesta JSON {ok, error} que el firmware valida (ContentService no permite códigos HTTP de error); probado con 2 cámaras.

</details>

<details><summary><b>CAM-02</b> · Firmware ESP32 de referencia</summary>

*Historia:* Como equipo técnico quiero un firmware estándar para que toda obra nueva capture igual.

*Criterios de aceptación:* Secretos fuera del código; TLS verificado; NTP y envío de 'tomada'; intervalo y ventana horaria configurables; cola en microSD con reenvío; heartbeat (RSSI, voltaje, firmware, reinicios).

</details>

<details><summary><b>CAM-03</b> · Política de frecuencia de captura</summary>

*Historia:* Como CGR quiero una frecuencia recomendada por tipo de obra para controlar costo y volumen.

*Criterios de aceptación:* Documento con escenarios (5/15/30 min, jornada vs 24 h) y GB/mes por cámara y para 10/50/502 obras, medido con archivos reales.

</details>

<details><summary><b>CAM-05</b> · Ciclo de vida de la cámara</summary>

*Historia:* Como auditor quiero confirmar la instalación y como admin registrar el retiro de la cámara para saber si la falta de fotos es esperada.

*Criterios de aceptación:* Estados Pendiente de instalación → Instalada → Confirmada por auditor → Retirada (con motivo e historial); el auditor ve las obras con cámara por confirmar.

</details>

<details><summary><b>CAM-06</b> · Rotar credenciales expuestas</summary>

*Historia:* Como equipo quiero cambiar la clave WiFi y volver a desplegar el Apps Script porque circularon en el documento.

*Criterios de aceptación:* Nueva clave del MIFI; nuevo deployment ID; el documento no está en el repositorio.

</details>

<details><summary><b>CAM-04</b> · Kit de instalación de cámara</summary>

*Historia:* Como instalador quiero un checklist para que la cámara no quede de cabeza, mal encuadrada o sin señal.

*Criterios de aceptación:* Checklist (orientación, encuadre de referencia, prueba de envío, foto de referencia guardada como base para S-03); plantilla imprimible.

</details>

## PIP · Pipeline automático de imágenes

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| PIP-01 | Estado por foto en el pipeline | Must | M | — | G1-P6 |
| PIP-02 | Pipeline programado | Must | L | PIP-01, ADM-03 | G1-P5, G1-P6 |
| PIP-03 | Vista Administración → Pipeline | Should | M | PIP-02 | G1-P6 |
| PIP-04 | Ingesta directa por API | Should | M | CAM-01, PIP-02 | G1-P5 |

<details><summary><b>PIP-01</b> · Estado por foto en el pipeline</summary>

*Historia:* Como admin quiero saber qué fotos están pendientes, procesadas o con error.

*Criterios de aceptación:* Columna estado (pendiente/descargada/curada/analizada/error) + motivo + reintentos en etl_imagenes; migración sin perder datos.

</details>

<details><summary><b>PIP-02</b> · Pipeline programado</summary>

*Historia:* Como CGR quiero que listar→descargar→curar→detectar→publicar→alertas corra solo.

*Criterios de aceptación:* Tarea en programador.py con bloqueo en la base; frecuencia configurable; reintentos con tope; corre para todas las obras con carpeta o API.

</details>

<details><summary><b>PIP-03</b> · Vista Administración → Pipeline</summary>

*Historia:* Como admin quiero ver la última ejecución, los pendientes y los errores por obra.

*Criterios de aceptación:* Tabla por obra; botón 'reintentar errores'; el último error es visible.

</details>

<details><summary><b>PIP-04</b> · Ingesta directa por API</summary>

*Historia:* Como CGR quiero que las fotos lleguen a dIAra sin depender de una carpeta pública de Drive.

*Criterios de aceptación:* El Apps Script v2 reenvía a POST /api/camaras/{pid}/imagenes; las fotos por API entran al mismo pipeline de curación.

</details>

## ALE · Alertas y protocolo de atención

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| ALE-01 | Ciclo de vida de alertas | Must | L | — | G2 |
| ALE-02 | A-05 inactividad con datos reales | Must | M | — | G2 |
| ALE-03 | Alertas de salud de la cámara S-01..S-06 | Must | L | EDA-02, ADM-01 | G1-P1, G4 |
| ALE-04 | Alertas públicas para la ciudadanía | Could | M | ALE-02, ALE-03 | G8 |

<details><summary><b>ALE-01</b> · Ciclo de vida de alertas</summary>

*Historia:* Como auditor quiero clasificar cada alerta (abierta, en revisión, justificación solicitada, confirmada, descartada) con motivo.

*Criterios de aceptación:* Tabla alertas persistente (hoy se calculan al vuelo); historial de transiciones; plazo de atención configurable; vencidas resaltadas.

</details>

<details><summary><b>ALE-02</b> · A-05 inactividad con datos reales</summary>

*Historia:* Como auditor quiero una alerta de inactividad basada en personas detectadas e índice de cambio, no en la maquinaria sintética.

*Criterios de aceptación:* N días hábiles con clima apto sin personas ni cambio > umbral; umbrales en config; probada con Limoncito y el Puente.

</details>

<details><summary><b>ALE-03</b> · Alertas de salud de la cámara S-01..S-06</summary>

*Historia:* Como auditor quiero saber si la cámara dejó de enviar, bajó su cobertura, se movió, está empañada, tiene el reloj corrido o se retiró antes de tiempo.

*Criterios de aceptación:* Las 6 reglas de la propuesta §3 G4; se muestran en el panel, las tarjetas, el Seguimiento y el PDF; no cuentan como alerta de la obra sino de la cámara.

</details>

<details><summary><b>ALE-04</b> · Alertas públicas para la ciudadanía</summary>

*Historia:* Como ciudadano quiero saber si la obra lleva días sin actividad visible o la cámara no transmite.

*Criterios de aceptación:* Solo señales no sensibles (sin brecha ni hallazgos); textos aprobados; respeta la regla de routes/publico.py.

</details>

## EDA · EDA automático y salud de la cámara

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| EDA-01 | EDA automático por obra | Must | M | — | G1-P1, G1-P3, colab tres proyectos |
| EDA-02 | Detección de cambio de encuadre | Must | L | — | G4, colab PROERI v2 |
| EDA-03 | Comparar Tenengrad frente a FIND_EDGES | Could | S | — | colab tres proyectos |

<details><summary><b>EDA-01</b> · EDA automático por obra</summary>

*Historia:* Como auditor quiero ver el heatmap día × hora de fotos, los días sin fotos y el horario efectivo de la cámara.

*Criterios de aceptación:* Sección 'Salud de la cámara' en el panel; mismo cálculo que el colab (cobertura, intervalos sin datos); exportable a CSV.

</details>

<details><summary><b>EDA-02</b> · Detección de cambio de encuadre</summary>

*Historia:* Como auditor quiero saber cuándo se movió la cámara y ver el antes y el después.

*Criterios de aceptación:* Módulo src/etl/encuadre.py con el HOG + referencia fija + ventanas + ORB del colab PROERI v2; candidatos con panel antes/después; un cambio confirmado reinicia la referencia; validado con Limoncito (11/02/2026) y PROERI (04/03/2026).

</details>

<details><summary><b>EDA-03</b> · Comparar Tenengrad frente a FIND_EDGES</summary>

*Historia:* Como equipo de datos quiero decidir qué métrica de nitidez usar en la curación.

*Criterios de aceptación:* Informe con las dos métricas sobre las fotos ya etiquetadas (empañadas y nítidas) y los umbrales recalibrados.

</details>

## IA · IA: prompt, costos, confianza y revisión humana

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| IA-01 | Muestreo reproducible y por evento | Must | M | — | G1-P3 |
| IA-02 | Prompt compacto con salida estructurada | Must | M | — | G1-P4 |
| IA-03 | Evaluación del prompt contra etiquetas | Must | M | IA-02 | G1-P4, G1-P8 |
| IA-05 | Tabla ia_resultados vinculada a la foto | Must | M | IA-02 | G1-P5 |
| IA-04 | Procesamiento por lote y multi-imagen | Should | M | IA-02, PIP-02 | G1-P4, G1-P8 |
| IA-06 | Cola de revisión humana | Should | L | IA-05 | G1-P5, G8 |
| IA-07 | Mostrar el nivel de confianza | Should | S | IA-05 | G8 |
| IA-08 | Modelo local afinado para la obra | Could | XL | IA-06, TEC-04 | README límite conocido |

<details><summary><b>IA-01</b> · Muestreo reproducible y por evento</summary>

*Historia:* Como equipo quiero elegir qué fotos van a la IA de pago con un criterio documentado.

*Criterios de aceptación:* src/ia/muestreo.py: estratificado por día, semilla fija, hora objetivo, más fotos con cambio alto o detecciones; % configurable.

</details>

<details><summary><b>IA-02</b> · Prompt compacto con salida estructurada</summary>

*Historia:* Como CGR quiero un prompt que describa hechos con confianza y sin dictámenes.

*Criterios de aceptación:* Prompt y esquema JSON versionados en el repositorio; responseSchema; campos de confianza y no_determinable; sin 'dictamen vinculante' ni EPP por trabajador.

</details>

<details><summary><b>IA-03</b> · Evaluación del prompt contra etiquetas</summary>

*Historia:* Como equipo quiero medir la calidad y el costo de cada versión del prompt y del modelo.

*Criterios de aceptación:* Conjunto de 100–200 fotos etiquetadas a mano; métricas (error en conteo de personas, acierto actividad sí/no, tokens y costo por foto); tabla comparativa de 2–3 modelos.

</details>

<details><summary><b>IA-05</b> · Tabla ia_resultados vinculada a la foto</summary>

*Historia:* Como auditor quiero ver el resultado de la IA junto a cada foto.

*Criterios de aceptación:* Tabla con drive_id, modelo, versión del prompt, tokens, costo, JSON; se ve en el panel de imágenes.

</details>

<details><summary><b>IA-04</b> · Procesamiento por lote y multi-imagen</summary>

*Historia:* Como CGR quiero bajar el costo procesando varias fotos por llamada y en lote.

*Criterios de aceptación:* Varias fotos por día en una llamada; Batch API; reintentos; tope de gasto mensual configurable que detiene el envío.

</details>

<details><summary><b>IA-06</b> · Cola de revisión humana</summary>

*Historia:* Como auditor quiero confirmar o corregir los resultados de la IA para que el sistema aprenda.

*Criterios de aceptación:* Cola con las fotos marcadas requiere_revision_humana o con baja confianza; corregir conteos y actividad; las correcciones se guardan como etiquetas exportables (formato YOLO).

</details>

<details><summary><b>IA-07</b> · Mostrar el nivel de confianza</summary>

*Historia:* Como ciudadano y auditor quiero saber cuánta confianza tiene cada dato automático.

*Criterios de aceptación:* Auditor: valor numérico; público: alta/media/baja + leyenda 'pendiente de verificación'.

</details>

<details><summary><b>IA-08</b> · Modelo local afinado para la obra</summary>

*Historia:* Como equipo quiero detectar obreros en zonas techadas y maquinaria de obra.

*Criterios de aceptación:* Afinar el detector con las etiquetas de IA-06; supera al YOLO COCO en el conjunto de prueba de Limoncito abril–julio.

</details>

## ADM · Administración de proyectos

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| ADM-01 | Frecuencia y volumen esperados en el alta | Must | S | — | G1-P2 |
| ADM-03 | Configuración del ETL por obra en la base | Must | M | — | G1-P9 |
| ADM-02 | Notificar al auditor de una obra nueva | Should | S | CAM-05 | G1-P2 |
| ADM-04 | Identificadores externos | Should | S | — | G5, G8 |

<details><summary><b>ADM-01</b> · Frecuencia y volumen esperados en el alta</summary>

*Historia:* Como admin quiero definir la frecuencia, el horario y las fotos esperadas por día de cada obra.

*Criterios de aceptación:* Campos en el formulario y en la base; se usan en S-02 y en la cobertura.

</details>

<details><summary><b>ADM-03</b> · Configuración del ETL por obra en la base</summary>

*Historia:* Como admin quiero registrar la carpeta de Drive, la rotación y los períodos excluidos sin tocar código.

*Criterios de aceptación:* Se mueven a la base config.ETL carpetas/rotacion/excluir/nitidez_min_obra; formulario en Editar proyecto; config.py queda como valores por defecto.

</details>

<details><summary><b>ADM-02</b> · Notificar al auditor de una obra nueva</summary>

*Historia:* Como auditor quiero enterarme cuando me asignan una obra nueva.

*Criterios de aceptación:* Aviso en el Home del auditor y en el correo; enlace para confirmar la instalación (CAM-05).

</details>

<details><summary><b>ADM-04</b> · Identificadores externos</summary>

*Historia:* Como admin quiero registrar el código PROERI, BPIP y CFIA de cada obra.

*Criterios de aceptación:* Campos opcionales y validados; visibles en la ficha y en el PDF; exportables.

</details>

## CON · Empresa ejecutora

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| CON-01 | Responder justificaciones de alertas | Should | M | ALE-01 | G2, G5 |
| CON-02 | Documentar la finalidad única del perfil | Should | S | — | G5 |

<details><summary><b>CON-01</b> · Responder justificaciones de alertas</summary>

*Historia:* Como empresa ejecutora quiero responder las solicitudes de justificación del auditor.

*Criterios de aceptación:* El auditor envía la solicitud desde la alerta; la empresa la ve sin el detalle del análisis de la IA; responde con texto y adjunto; queda en el historial de la alerta.

</details>

<details><summary><b>CON-02</b> · Documentar la finalidad única del perfil</summary>

*Historia:* Como CGR quiero que la finalidad del perfil contratista esté definida y aprobada.

*Criterios de aceptación:* Texto en el README y en la pantalla del contratista; términos de uso aceptados en el primer ingreso.

</details>

## CIU · Participación ciudadana

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| CIU-04 | Redirección de denuncias | Must | S | — | G7 |
| CIU-01 | Pre-triage de aportes con IA | Should | M | IA-02 | G7 |
| CIU-02 | Vincular un aporte a una alerta u observación | Should | S | ALE-01 | G7 |
| CIU-03 | Derivación y seguimiento ciudadano | Could | M | CIU-02 | G7 |

<details><summary><b>CIU-04</b> · Redirección de denuncias</summary>

*Historia:* Como ciudadano quiero que, si mi aporte es una denuncia, se me indique el canal oficial de la CGR.

*Criterios de aceptación:* Aviso claro y enlace al formulario oficial de denuncias de la CGR; dIAra no tramita denuncias.

</details>

<details><summary><b>CIU-01</b> · Pre-triage de aportes con IA</summary>

*Historia:* Como auditor quiero que los aportes lleguen clasificados y resumidos.

*Criterios de aceptación:* Categoría sugerida, resumen, detección de rostros o placas y '¿es foto de obra?'; la IA solo sugiere y el auditor decide.

</details>

<details><summary><b>CIU-02</b> · Vincular un aporte a una alerta u observación</summary>

*Historia:* Como auditor quiero usar un aporte como evidencia.

*Criterios de aceptación:* Vínculo aporte↔observación/alerta; se ve en ambos lados y en el PDF.

</details>

<details><summary><b>CIU-03</b> · Derivación y seguimiento ciudadano</summary>

*Historia:* Como ciudadano quiero saber qué pasó con mi aporte.

*Criterios de aceptación:* Número de seguimiento; estados recibido/revisado/derivado (a la Contraloría de Servicios de la institución)/cerrado; consulta pública por número.

</details>

## PUB · Sitio público

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| PUB-01 | Difuminar rostros y placas | Must | M | — | Seguridad README |
| PUB-02 | Timelapse semanal automático | Could | M | PUB-01, PIP-02 | G3 |

<details><summary><b>PUB-01</b> · Difuminar rostros y placas</summary>

*Historia:* Como CGR quiero que ninguna foto pública exponga a personas.

*Criterios de aceptación:* Difuminado automático antes de publicar la última foto y el timelapse; prueba con fotos reales.

</details>

<details><summary><b>PUB-02</b> · Timelapse semanal automático</summary>

*Historia:* Como ciudadano quiero ver la evolución de la obra.

*Criterios de aceptación:* Generado con las fotos aptas (1–2 por día); se publica con difuminado; reemplaza la necesidad de un dron o POV sin presupuesto.

</details>

## UX · Experiencia del auditor

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| UX-01 | Separar actividad, avance declarado y avance planificado | Should | M | — | G3 |

<details><summary><b>UX-01</b> · Separar actividad, avance declarado y avance planificado</summary>

*Historia:* Como auditor quiero no confundir la actividad observada con el avance físico.

*Criterios de aceptación:* Gráfico con 3 series (actividad observada, avance de la bitácora, curva del cronograma); se renombra 'avance observado' donde no se mide avance físico.

</details>

## INT · Integraciones externas

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| INT-01 | Investigar ePROERI y PROERI | Must | S | — | G5, G6, G8 |
| INT-02 | Investigar CFIA y la Bitácora Digital de Obra | Should | S | — | G5 |
| INT-03 | Investigar el Banco de Proyectos de Inversión Pública | Could | S | — | G5 |
| INT-04 | Investigar SICOP | Could | S | — | G8 |

<details><summary><b>INT-01</b> · Investigar ePROERI y PROERI</summary>

*Historia:* Como equipo quiero saber qué datos de las obras PROERI se pueden obtener y con qué identificador.

*Criterios de aceptación:* Informe: datos disponibles, formato, acceso, contacto, identificador común; decisión de seguir o no.

</details>

<details><summary><b>INT-02</b> · Investigar CFIA y la Bitácora Digital de Obra</summary>

*Historia:* Como equipo quiero saber si se puede leer la bitácora oficial en lugar de pedirle al contratista que la cargue dos veces.

*Criterios de aceptación:* Informe de acceso y datos; decisión.

</details>

<details><summary><b>INT-03</b> · Investigar el Banco de Proyectos de Inversión Pública</summary>

*Historia:* Como equipo quiero saber qué aporta el BPIP (código, monto, etapa).

*Criterios de aceptación:* Informe; si hay datos abiertos, un prototipo de importación.

</details>

<details><summary><b>INT-04</b> · Investigar SICOP</summary>

*Historia:* Como equipo quiero saber qué datos de plazos y montos se pueden traer para las obras que no son de PROERI.

*Criterios de aceptación:* Informe; prototipo con el n.º de procedimiento que ya existe.

</details>

## SEG · Seguimiento y priorización por riesgo

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| SEG-01 | Índice de riesgo por obra | Should | M | ALE-01, ALE-03 | G6 |

<details><summary><b>SEG-01</b> · Índice de riesgo por obra</summary>

*Historia:* Como CGR quiero ordenar las obras por riesgo para decidir cuáles visitar.

*Criterios de aceptación:* Puntaje explicable (pesos documentados): alertas confirmadas, brecha del plazo, salud de la cámara, aportes, monto; ranking en Seguimiento; exportable; sensibilidad revisada con la CGR.

</details>

## KPI · Indicadores de impacto

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| KPI-01 | Pestaña Indicadores (administración) | Should | M | ALE-01, CIU-03 | G4, G7 |
| KPI-02 | Indicadores públicos agregados | Could | S | KPI-01 | G7 |

<details><summary><b>KPI-01</b> · Pestaña Indicadores (administración)</summary>

*Historia:* Como CGR quiero medir si dIAra mejora la fiscalización.

*Criterios de aceptación:* Los indicadores de la propuesta §4 calculados; con tendencia mensual.

</details>

<details><summary><b>KPI-02</b> · Indicadores públicos agregados</summary>

*Historia:* Como ciudadano quiero ver la actividad global del programa.

*Criterios de aceptación:* Obras monitoreadas, % de cámaras activas, aportes atendidos; sin datos de auditoría.

</details>

## GOB · Presupuesto y gobernanza

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| GOB-01 | Estimación de costos y solicitud de presupuesto | Must | S | CAM-03, IA-03 | G1-P8 |
| GOB-02 | Encaje con los productos de la CGR | Must | S | — | G6 |

<details><summary><b>GOB-01</b> · Estimación de costos y solicitud de presupuesto</summary>

*Historia:* Como CGR quiero saber cuánto cuesta operar dIAra con 10, 50 y 502 obras.

*Criterios de aceptación:* Hoja con la fórmula (almacenamiento, IA, servidor) por escenario, usando los costos medidos en IA-03 y CAM-03; borrador de la solicitud.

</details>

<details><summary><b>GOB-02</b> · Encaje con los productos de la CGR</summary>

*Historia:* Como equipo quiero definir en qué producto de la CGR (auditoría, seguimiento) se usaría dIAra.

*Criterios de aceptación:* Investigación y propuesta de una página validada con la CGR; ajusta el foco del roadmap.

</details>

## TEC · Deuda técnica y plataforma

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| TEC-02 | Pruebas automatizadas + CI | Must | M | — | Deuda técnica |
| TEC-01 | Migrar SQLite a PostgreSQL | Should | L | — | README pendientes |
| TEC-03 | Seguridad de las sesiones | Should | M | — | README pendientes |
| TEC-04 | Licencia del detector | Should | S | — | README IA |

<details><summary><b>TEC-02</b> · Pruebas automatizadas + CI</summary>

*Historia:* Como equipo quiero detectar regresiones al agregar alertas y módulos.

*Criterios de aceptación:* pytest para alertas, curación, permisos por rol y API de cámaras; GitHub Actions en cada push.

</details>

<details><summary><b>TEC-01</b> · Migrar SQLite a PostgreSQL</summary>

*Historia:* Como equipo quiero una base que persista en Cloud Run y soporte varios procesos.

*Criterios de aceptación:* Capa de acceso compatible; migración de datos; despliegue con Cloud SQL documentado.

</details>

<details><summary><b>TEC-03</b> · Seguridad de las sesiones</summary>

*Historia:* Como CGR quiero proteger los accesos.

*Criterios de aceptación:* Límite de intentos de login; revocación de sesión al cerrar; recuperación de la contraseña por correo.

</details>

<details><summary><b>TEC-04</b> · Licencia del detector</summary>

*Historia:* Como CGR quiero evitar la obligación de AGPL en producción.

*Criterios de aceptación:* Decisión documentada: licencia comercial o un detector con licencia permisiva, evaluado con IA-03.

</details>

## VIZ · Visualización (guía Cairo)

| ID | Título | Prioridad | Tamaño | Depende de | Origen |
|---|---|---|---|---|---|
| VIZ-01 | Eje de tiempo real y huecos visibles | Must | M | — | Cairo cap. 6, colab PROERI v2, guía §2 #1 y #9 |
| VIZ-02 | Nulos nunca como cero | Must | S | — | Guía §2 #2 |
| VIZ-04 | Semántica de color única | Must | S | — | Cairo caps. 6 y 8, guía §2 #4, #8 y #11 |
| VIZ-07 | Ayudas visibles sin pasar el mouse | Must | S | — | Cairo cap. 9 (visibilidad), guía §2 #6 y #7 |
| VIZ-11 | Lista de control de gráficos en las revisiones de código | Must | S | — | Guía §3 |
| VIZ-03 | Clima en dos paneles | Should | S | VIZ-05 | Cairo cap. 6, guía §2 #3 |
| VIZ-05 | Módulo común de gráficos | Should | M | VIZ-01, VIZ-02 | Cairo cap. 9 (consistencia), guía §2 #10 |
| VIZ-06 | Graficar la diferencia reportado − observado | Should | S | VIZ-05 | Cairo cap. 6, guía §2 #5 |
| VIZ-08 | Franja 'qué requiere atención' en el panel | Should | M | — | Cairo cap. 9, guía §2 #12 |
| VIZ-10 | Sitio público según la rueda de visualización | Should | M | PUB-01 | Cairo cap. 3, guía §2 #13 |
| VIZ-09 | Small multiples de todas las obras | Could | M | VIZ-05, SEG-01 | Cairo caps. 3–4 (densidad), guía §2 #14 |
| VIZ-12 | Retroalimentación en las acciones | Could | S | — | Cairo cap. 9 (retroalimentación), guía §2 #16 |

<details><summary><b>VIZ-01</b> · Eje de tiempo real y huecos visibles</summary>

*Historia:* Como auditor quiero que los gráficos no inventen continuidad en los días sin datos.

*Criterios de aceptación:* Eje X por fecha calendario en graficoAvance y graficoEmpresa; línea cortada en los huecos; días sin datos sombreados; marcas semanales y de mes.

</details>

<details><summary><b>VIZ-02</b> · Nulos nunca como cero</summary>

*Historia:* Como auditor quiero que 'sin dato' no se dibuje como 0 %.

*Criterios de aceptación:* graficoEmpresa salta los valores nulos; prueba con una serie mixta; se aplica a todo gráfico nuevo.

</details>

<details><summary><b>VIZ-04</b> · Semántica de color única</summary>

*Historia:* Como usuario quiero que el rojo signifique siempre alerta.

*Criterios de aceptación:* Tokens de color únicos para la web y el PDF; el rojo solo para las alertas; las series con una paleta neutra y un acento; verificado con un simulador de daltonismo.

</details>

<details><summary><b>VIZ-07</b> · Ayudas visibles sin pasar el mouse</summary>

*Historia:* Como auditor en el celular quiero leer qué significa cada indicador.

*Criterios de aceptación:* kpi() muestra el texto auxiliar debajo del valor; los títulos de los gráficos dicen la conclusión; funciona en el celular.

</details>

<details><summary><b>VIZ-11</b> · Lista de control de gráficos en las revisiones de código</summary>

*Historia:* Como equipo quiero revisar cada gráfico nuevo con criterios comunes.

*Criterios de aceptación:* Lista de control de la guía §3 en la plantilla de PR; se aplica a los gráficos existentes una vez.

</details>

<details><summary><b>VIZ-03</b> · Clima en dos paneles</summary>

*Historia:* Como auditor quiero leer la lluvia y la temperatura sin un doble eje engañoso.

*Criterios de aceptación:* Dos paneles apilados con el mismo eje X; línea del umbral de 5 mm; también en el PDF.

</details>

<details><summary><b>VIZ-05</b> · Módulo común de gráficos</summary>

*Historia:* Como equipo quiero un solo código para los ejes, las fechas, los huecos y las leyendas.

*Criterios de aceptación:* assets/js/graficos.js usado por proyecto, admin y contratista; se eliminan las copias; misma apariencia en todas las páginas.

</details>

<details><summary><b>VIZ-06</b> · Graficar la diferencia reportado − observado</summary>

*Historia:* Como auditor quiero ver directamente cuánto reporta de más la empresa.

*Criterios de aceptación:* Mini gráfico de la diferencia con una banda de tolerancia (umbral C-01); se marcan los días fuera de banda.

</details>

<details><summary><b>VIZ-08</b> · Franja 'qué requiere atención' en el panel</summary>

*Historia:* Como auditor quiero ver primero lo importante y después los detalles.

*Criterios de aceptación:* Resumen de 1–3 frases arriba del panel; las secciones de detalle se pueden plegar; sigue el mantra de Shneiderman.

</details>

<details><summary><b>VIZ-10</b> · Sitio público según la rueda de visualización</summary>

*Historia:* Como ciudadano quiero entender en lenguaje llano qué pasa en mi obra.

*Criterios de aceptación:* Foto o timelapse + una frase llana + el estado; mapa de las obras; sin alertas sensibles; prueba con 3–5 personas ajenas al proyecto.

</details>

<details><summary><b>VIZ-09</b> · Small multiples de todas las obras</summary>

*Historia:* Como CGR quiero comparar la actividad de muchas obras a la vez.

*Criterios de aceptación:* Cuadrícula de mini series por obra con la misma escala, ordenada por el índice de riesgo; escala para 50+ obras.

</details>

<details><summary><b>VIZ-12</b> · Retroalimentación en las acciones</summary>

*Historia:* Como usuario quiero saber que mi acción se está procesando.

*Criterios de aceptación:* Botones con el estado 'procesando…' y desactivados mientras esperan la API; los errores se muestran en contexto.

</details>
