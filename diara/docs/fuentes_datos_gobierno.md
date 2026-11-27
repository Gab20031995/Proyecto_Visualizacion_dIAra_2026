# Fuentes de datos de gobierno para las obras de dIAra

Investigación del 27-nov-2026 sobre de dónde sacar los datos de contratación de las obras (presupuesto, contratista,
fechas, estado) para cruzarlos con lo que observa dIAra. Solo se consideran **fuentes de gobierno**.
Datos de referencia de las obras piloto: [`data/referencia/contrataciones_obras.csv`](../data/referencia/contrataciones_obras.csv).

## 1. Hallazgo principal: no todo está en SICOP

Las tres obras piloto (Escuela Limoncito, Puente María Aguilar, Liceo Ticabán) **no tienen su contrato de
construcción en SICOP**:

| Obra | Dónde está la contratación |
|---|---|
| Escuela Barrio Limoncito (MEP) | **E-PROERI** — programa PROERI, préstamo BCIE 2317, reglas del BCIE |
| Puente María Aguilar (CONAVI) | **E-PROERI** — mismo programa |
| Liceo de Ticabán (MEP) | Ni SICOP ni E-PROERI: probablemente contratado por la Junta Administrativa con autorización técnica de la DIE |

En SICOP solo aparecen compras menores relacionadas (equipamiento, audio, obras municipales). Por eso el campo
`proyectos.contratacion` (hoy descrito como "n.º de contratación SICOP") debe aceptar también números E-PROERI
(`2024LPI-0026-PROERI-MEP`) y saber de qué sistema viene cada número.

## 2. Fuentes oficiales y qué aporta cada una

| Fuente | URL | Cómo se consulta | Qué aporta |
|---|---|---|---|
| SIAC (Contraloría) | interno CGR | Acceso institucional | Actividad contractual de todas las instituciones |
| SICOP – Expediente electrónico | `https://www.sicop.go.cr/moduloPcont/pcont/ctract/es/CE_CEJ_ESQ001.jsp` | Formulario POST (`sch_cartelNm` = descripción, `sch_cont_ymd1/2` = rango dd/mm/aaaa, `page_size`); respuesta HTML con tabla | Procedimientos ordinarios: n.º, institución, descripción, fecha |
| E-PROERI – Procesos de licitación | `https://www.e-proeri.org/#/licitaciones` | Aplicación web (SPA); detalle por proceso con pestañas *Documentos*, *Ofertas recibidas*, *Resultado evaluación* | Estado, **n.º de ofertas**, **notificación de adjudicación** (contratista y precio), aviso de licitación con ubicación y coordenadas |
| E-PROERI – E-Reporting | `https://www.e-proeri.org/#/EReporting2/MEP` y `/CONAVI` | Tablero público, corte mensual | Por obra: código (`MEP-CE-029`, `CONAVI-PU-069`), estado, **fecha de finalización**, monto (USD), provincia/cantón/distrito |
| BCIE – Plan General de Adquisiciones | `https://adquisiciones.bcie.org/` | PDF | **Monto presupuestado** y fechas previstas de cada proceso (línea base para sobrecostos y atrasos) |
| DIE-MEP – Autorizaciones técnicas | `https://die.mep.go.cr/` | PDF por centro educativo | Obras contratadas por Juntas: objeto, monto máximo autorizado |
| Comunicados MEP / MOPT | mep.go.cr, mopt.go.cr | Noticias | Fechas de inicio y entrega, montos finales |

Notas técnicas de E-PROERI: los documentos se descargan como `data:application/pdf;base64,...` dentro de la página; el
tablero E-Reporting no muestra el avance físico/financiero por obra; los contratos y órdenes de inicio requieren
usuario registrado. Las adjudicaciones de procesos anteriores a la plataforma están en
`https://www.proyectoscostarica.org/licitaciones-proeri/<numero>` (UNOPS solo difunde, no contrata).

**Cuidado con los nombres:** hay dos puentes PROERI sobre el río María Aguilar (`CONAVI-PU-069` en Curridabat y
`CONAVI-PU-034` en la Circunvalación) y "Limoncito" coincide con obras de Coto Brus, CEN-CINAI y SENARA. Cruzar
siempre por código o coordenadas, nunca solo por nombre.

## 3. Estrategia de acceso recomendada (bajo costo)

En orden de prioridad:

1. **SIAC interno de la CGR** — dIAra es un proyecto de la Contraloría; conectarlo primero, sin depender de terceros.
2. **Convenio CGR – Hacienda (DCoP)** para una réplica o vista de solo lectura de la base de SICOP. El Observatorio de
   Compra Pública de Hacienda ya se alimenta de SICOP y SIAC, así que el flujo de datos existe. Respaldo: art. 6 de la
   Ley General de Contratación Pública (N.º 9986) y Ley Orgánica de la CGR (N.º 7428).
3. **Oficios a las unidades ejecutoras** (PROERI, DIE-MEP, CONAVI) pidiendo un intercambio periódico (CSV mensual) con
   una plantilla fija: código de obra, n.º de contratación, contratista, monto adjudicado y modificado, orden de inicio,
   fecha fin, prórrogas, % avance físico y pagos.
4. **Conectores a portales públicos** (respaldo mientras llegan los convenios): consulta a SICOP por número de
   procedimiento y **copia semanal de E-Reporting** guardando el historial para detectar cambios de fecha fin o monto.
   Respetar robots.txt y términos de uso, limitar la frecuencia y no guardar datos personales sin necesidad (Ley 8968).

SICOP no publica datos abiertos completos (lo señalaron el compromiso OGP CR0052 y la auditoría de la CGR sobre
calidad de la información de SICOP), por eso se prefiere el convenio al scraping.

## 4. Mejoras propuestas al sistema

### Modelo de datos (`proyectos`, `store.py` / `proyectos.py`)
- `fuente_contratacion`: `SICOP` | `E-PROERI` | `Junta` | `Otra`.
- `codigo_obra_externo`: código del ejecutor (`MEP-CE-029`, `CONAVI-PU-069`), clave de cruce con E-Reporting.
- `codigo_centro_educativo` (MEP; Limoncito = 3345) para obras escolares.
- `moneda` + `monto_adjudicado` (hoy solo `monto_crc`): los contratos PROERI se adjudican en USD o CRC. Convertir con
  el tipo de cambio BCCR de la fecha de adjudicación para comparar.
- `monto_presupuestado` (línea base BCIE/DIE), `ofertas_recibidas`, `fecha_adjudicacion`.
- Si un contrato cubre varias obras (lote de 5 puentes), guardar también el monto asignado a la obra.

### Nuevas alertas de contratación (complementan C-01..C-05 del contratista)
- **Oferente único**: `ofertas_recibidas == 1` (caso Limoncito y PU-069).
- **Sobrecosto de adjudicación**: monto adjudicado / presupuestado > umbral (Limoncito ~ +25%).
- **Corrimiento de fecha fin**: la fecha de E-Reporting cambia entre copias semanales.
- **Licitación fracasada repetida** para la misma obra.
- **Concentración**: un mismo contratista o consorcio en muchos lotes.
- **Plazo vs. avance**: % del plazo consumido contra el avance observado por la IA (ya existe la base en
  `seguimiento.py`; falta alimentar `fecha_inicio`/`fecha_fin` con datos oficiales).

### Conectores (nuevo módulo sugerido `backend/src/fuentes/`)
- `sicop.py`: consulta por número o descripción al Expediente electrónico.
- `eproeri.py`: snapshot de E-Reporting (MEP, CONAVI) y lectura de notificaciones de adjudicación.
- Guardar cada archivo original con hash SHA-256, URL y fecha de captura (cadena de custodia) antes de extraer datos.
- Programarlos como las tareas existentes de `tareas/` (1 vez por semana).
