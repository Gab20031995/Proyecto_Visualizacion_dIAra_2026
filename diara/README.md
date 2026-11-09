# dIAra · MVP
Pregunta guía: **¿Va la obra como se planificó?** (datos sintéticos).

## Correr local (PowerShell, desde esta carpeta)
    python -m venv .venv; .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    python backend/make_data.py
    python backend/demo_contratista.py      (opcional: empresa ejecutora de ejemplo con datos que generan alertas de cruce)
    uvicorn api:app --app-dir backend --port 8000 --reload

| Página | URL | Acceso |
|---|---|---|
| Sitio público | http://localhost:8000 | Libre |
| Login | http://localhost:8000/login | — |
| Administración | http://localhost:8000/admin | `admin@cgr.go.cr` / `admin` |
| Home del auditor | http://localhost:8000/auditor | `ana@cgr.go.cr` / `demo` (asignada a Escuela Limoncito) |
| Panel de un proyecto | http://localhost:8000/proyecto?p=P-001 | Auditor asignado o administrador |
| Empresa ejecutora | http://localhost:8000/contratista | `ing.obra@constructora.cr` / `demo` (creada por `demo_contratista.py`; P-001 y P-002) |

Los usuarios iniciales se crean la primera vez que arranca el servidor (se pueden cambiar con
`$env:ADMIN_EMAIL`, `$env:ADMIN_PASS`, `$env:AUDITOR_PASS` antes del primer arranque). En producción definir
también `$env:SECRET_KEY`; si no, las sesiones se cierran cada vez que se reinicia el servidor.

## Roles
- **Administrador**: ve el resumen y el seguimiento de todas las obras; crea, edita, suspende, cierra o cancela
  proyectos; crea y edita auditores (nombre, correo, frecuencia del reporte), activa/desactiva accesos, cambia
  contraseñas y asigna auditores a proyectos. Desde cada proyecto entra a la vista del auditor.
- **Contratista (empresa ejecutora)**: el ingeniero de la obra entra a `/contratista`, ve sus proyectos asignados y
  carga el cronograma, la bitácora de obra y los costos y presupuesto. Nunca ve el análisis de la IA, las alertas ni
  las observaciones del auditor: lo que declara se cruza con lo observado en el panel del auditor.
- **Auditor**: entra a su Home (`/auditor`) con el resumen de todos sus proyectos asignados, ordenados por urgencia,
  y desde ahí abre el panel de cada proyecto (`/proyecto?p=ID`). Solo ve los proyectos que tiene asignados.

## Estructura
    frontend/
      index.html            Landing pública: inicio, historia, cómo funciona, importancia y espacio ciudadano
      login.html            Acceso (redirige a /admin o /auditor según el rol)
      admin.html            Administración (Home del admin): resumen, seguimiento, proyectos, auditores, reportes, clima
      auditor.html          Home del auditor: resumen y tarjetas de sus proyectos asignados
      proyecto.html         Panel de un proyecto: una página con scroll por secciones (Resumen, Imágenes,
                            Observaciones, Empresa ejecutora, Clima, Calendario, Registros, Aportes ciudadanos)
      contratista.html      Empresa ejecutora: Home de sus proyectos y carga de cronograma, bitácora y costos
      assets/css/           base.css (todo el sitio), landing.css, panel.css (admin y auditor)
      assets/js/            common.js (todo el sitio), landing.js, login.js, panel.js (admin y auditor)
    backend/
      api.py                App FastAPI: páginas (/, /login, /auditor, /proyecto, /admin) y routers
      routes/sesion.py      /api/login, /api/logout, /api/yo y permisos (usuario, admin, proyecto asignado)
      routes/publico.py     /api/resumen, /api/aportes, /suscripciones, /aportes, /uploads/*
      routes/auditor.py     /api/mis-proyectos, /api/auditor/{proyecto}/... y /camara/{proyecto}/* (proyecto asignado)
      routes/admin.py       /api/admin/...  (solo administrador: proyectos, estados, auditores, seguimiento, reportes, clima)
      routes/camaras.py     /api/camaras/{proyecto}/...  (API de imágenes, token por proyecto)
      routes/contratista.py /api/contratista/...  (solo rol contratista, proyecto asignado)
      config.py             Umbrales de alertas, rutas y usuarios iniciales
      src/                  metrics, alerts, reports (PDF/Excel/correo), store (SQLite), auth, proyectos,
                            tablero (resumen por proyecto para las tarjetas)
      src/reporteria.py     Frecuencias, períodos, envío SMTP y registro de envíos
      src/reporte_pdf.py    Diseño del PDF del reporte (portada + una sección por proyecto)
      src/proyectos.py      Catálogo de obras (tabla), estados y transiciones, validación de ubicación y token de cámara
      src/seguimiento.py    Tabla comparativa de obras para Administración → Seguimiento (y su CSV)
      src/contratista.py    Cronograma, bitácora y costos de la empresa ejecutora y su cruce con la IA (alertas C-01..C-05)
      src/imagenes.py       Imágenes de cámara (recibidas por API + sintéticas)
      src/clima/            google.py, openmeteo.py, meteoblue.py, meteosource.py (proveedores),
                            comun.py (HTTP), __init__.py (guardado y registro consolidado)
      src/etl/              ETL de imágenes desde Drive: drive.py (extracción), catalogo.py (metadatos y descarga),
                            clima_historico.py (Open-Meteo histórico), curacion.py (aptas para IA, enderezado,
                            hojas de contacto), cruce.py (control cruzado fotos x clima)
      etl_imagenes.py       Línea de comandos del ETL (listar, descargar, clima, curar, cruce, hojas, todo, estado)
      src/ia/actividad.py   IA: personas y vehículos (YOLO) + índice de cambio por foto, resumen diario y cruce con lluvia
      ia_actividad.py       Línea de comandos de la IA (analizar, resumen); dependencias en requirements-ia.txt
      actualizar_clima.py   Consulta todas las fuentes de clima activas (programarlo cada ≤ 12 h)
      probar_clima.py       Diagnóstico: qué fuentes de clima están activas y por qué falla cada una
      make_data.py          Genera los datos sintéticos de cada obra
      demo_contratista.py   Carga una empresa ejecutora de ejemplo (no usar en producción)
      enviar_reportes.py    Envía los reportes por correo que tocan hoy (programarlo 1 vez al día)
    tests/                  Pruebas automáticas (pytest); ver «Pruebas automáticas»
    data/
      proyectos.csv         Carga inicial de la tabla proyectos (solo la primera vez)
      obras/<id>/           diario.csv y camara/ de cada obra (una obra sin carpeta = "sin datos")
      uploads/              Fotos de aportes ciudadanos
      etl/                  ETL de imágenes: drive/<id>/<origen>/<día>/ (originales de Drive), curadas/<id>/<día>/
                            (aptas para IA, enderezadas), <id>/*.csv (cruce) y <id>/hojas/ (hojas de contacto)
      diara.db              Base SQLite (se crea sola): proyectos, imagenes, usuarios, asignaciones, observaciones,
                            aportes, suscripciones, proyectos_historial (cambios de estado) y las 6 tablas de clima

## Proyectos (Administración → Proyectos)
Los proyectos viven en la tabla `proyectos` de la base. `data/proyectos.csv` solo se usa una vez, para cargar la
tabla la primera vez que arranca el servidor. Desde **+ Nuevo proyecto** o **✏️ Editar** se registran:
- **Datos generales**: nombre, institución, estado inicial (Planificado o En ejecución), contratista, descripción.
- **Contrato y cronograma**: n.º de contratación (SICOP), monto (₡), versión del cronograma, fechas de inicio y fin.
- **Ubicación**: provincia, cantón, distrito, señas, **latitud y longitud** (obligatorias). Se validan dentro de
  Costa Rica (incluida la Isla del Coco), con vista previa en el mapa y botón "Usar mi ubicación" para visitas de campo.
  Las coordenadas se usan para el clima de Google; "Probar clima" confirma que responden.
- **Cámara y datos**: código de cámara, **token de la API de imágenes** y la **captura esperada**: cada cuántos minutos
  toma foto y en qué horario (sin horario = 24 h). El formulario muestra las **fotos esperadas por día**
  (`proyectos.fotos_esperadas_dia`), base para medir la cobertura de la cámara y detectar cámaras caídas.
- **Imágenes desde Google Drive (ETL)**: carpeta de Drive (se puede pegar el enlace), rotación de las fotos, nitidez
  mínima propia (cámaras de baja resolución), ventana de días y **períodos excluidos** (`desde | hasta | motivo`).
  Antes estaban escritos en `config.ETL`; al primer arranque con esta versión se copian a la base **una sola vez**
  (`store._copiar_config_etl`) y desde entonces se editan solo aquí. El ETL los lee con `proyectos.config_etl(pid)`.

La lista se filtra por estado (por defecto, solo las **activas**) y se busca por nombre, institución, ubicación o ID.

**Estados de la obra.** El estado no se cambia en el formulario sino con los botones de cada tarjeta, que piden un
**motivo obligatorio** y quedan en la tabla `proyectos_historial` (quién, cuándo, estado anterior y nuevo):

| Desde | Acciones posibles |
|---|---|
| Planificado | Iniciar (→ En ejecución), Cancelar |
| En ejecución | Suspender, Cerrar (→ Finalizado), Cancelar |
| Suspendido | Reanudar (→ En ejecución), Cerrar, Cancelar |
| Finalizado | Reabrir (→ En ejecución) |
| Cancelado | Ninguna (definitivo) |

Las obras **Finalizadas o Canceladas** salen del resumen, dejan de consultar el clima y no se incluyen en los reportes
por correo; sus datos e historial se conservan. Las Suspendidas siguen activas, marcadas en naranja.

## Seguimiento y análisis (Administración → Seguimiento)
Tabla comparativa de todas las obras (`src/seguimiento.py`): avance previsto y observado, **brecha y su tendencia en
los últimos 7 registros** (▲ recupera / ▼ se atrasa más), alertas por gravedad, % del plazo contractual consumido
(requiere fechas de inicio y fin), días desde el último dato de la cámara, lluvia y días no aptos de la última semana,
observaciones abiertas y aportes por revisar. Incluye conteo por estado, gráfico de brecha por obra, alertas activas
por tipo (A-01 a A-04), los últimos cambios de estado y exportación a CSV (`/api/admin/seguimiento.csv`).

## Alertas: inactividad con datos reales (A-05) y ciclo de vida
**A-05, días hábiles sin actividad visible** (`src/alerts.py`). A-01 depende de la maquinaria, que la IA no mide en las
obras reales. A-05 usa lo que sí se mide: personas detectadas y el **índice de cambio** entre fotos seguidas (columna
`cambio_mediana` de `diario.csv`, la agrega `etl_imagenes.py publicar`).
- Alerta con 3 días hábiles seguidos (lunes a sábado, no feriados, clima apto, con fotos aptas) sin personas y con índice
  de cambio < 5 (ALTA desde 6 días). Umbrales en `config.UMBRALES`; feriados en `config.FERIADOS` (Jueves y Viernes
  Santo se calculan cada año). Verificar los feriados con el Ministerio de Trabajo.
- Domingos, feriados, días de lluvia y días sin fotos aptas no cuentan ni cortan la racha. Un día **sin índice de
  cambio** (fotos muy separadas, como en Ticabán) la corta: sin esa señal no se concluye nada.
- Con los datos actuales no se dispara en ninguna obra (tampoco simulando cada día de su historia). Límites: no ve
  obreros en zonas techadas u oscuras (Limoncito desde abril 2026) y en el Puente cuenta peatones.

**Ciclo de vida de las alertas** (`src/ciclo_alertas.py`; tablas `alertas` y `alertas_historial`). Toda alerta A-xx,
C-xx y S-xx se guarda e identifica de un día a otro por (obra, código, clave). En el panel, **Gestionar** cambia su
estado y **Historial de alertas** muestra todas, también las descartadas y las que ya no se detectan.

| Estado | Significado | Motivo |
|---|---|---|
| Abierta | Recién detectada (inicial) | — |
| En revisión | El auditor la está revisando | Opcional |
| Justificación solicitada | Se pidió explicación a la empresa (la respuesta llegará con el ítem CON-01 del backlog) | Obligatorio |
| Confirmada | El problema es real | Obligatorio |
| Descartada | Falsa alarma: **deja de contarse** en tarjetas, Seguimiento, PDF y correo | Obligatorio |

- Cada cambio queda en el historial (quién, cuándo, de qué a qué y por qué).
- Una descartada que **sube a ALTA se reabre sola**. Una que deja de detectarse queda "ya no se detecta"; si vuelve,
  conserva su estado.
- **Vencida**: Abierta o En revisión por más de `plazo_atencion_dias` (5) desde que el sistema la detectó. Se resalta en
  el panel, se avisa en los Home y en "Requiere atención" del PDF y del correo. El PDF muestra el estado de cada alerta.
- La empresa ejecutora no ve ni gestiona alertas.

## Salud de la cámara (panel del proyecto → Cámara)
Responde a lo que preguntó la CGR con Limoncito: "¿la obra terminó o la cámara dejó de funcionar?" (`src/salud_camara.py`).
Cuenta todas las fotos que llegaron: el catálogo de Drive del ETL (aunque no se hayan descargado), las de la API de
cámaras y las sintéticas de las obras de ejemplo. Cada instante de captura cuenta una sola vez.
- **Indicadores**: última foto, días desde la última foto, horario de captura (el configurado en el proyecto o, si no
  hay, el observado), fotos esperadas por día, cobertura de los últimos 7 días (recibidas ÷ esperadas) y total.
- **Mapa de calor día × hora** (como en los colabs): días sin fotos en gris, horario de captura, cambios de encuadre en
  rojo y una franja de calidad (verde: alguna foto apta para la IA; ámbar: ninguna; gris: sin evaluar).
- **Días sin fotos** (los 10 intervalos más largos) y **cambios de encuadre** con su panel antes/después y botones
  para confirmarlos o descartarlos (queda quién y cuándo).
- Se ve también en obras sin registro diario de la IA. La empresa ejecutora no tiene acceso.

**Alertas de cámara S-xx** (umbrales en `config.SALUD_CAMARA`). Van **aparte** de las A-xx y C-xx porque hablan de la
evidencia, no del avance. Se muestran en el panel, en las tarjetas y avisos de ambos Home y en el Seguimiento (columna
"Cámara", también en el CSV), en el reporte PDF y en el correo (ver «Reportes automáticos por correo»).

| Código | Regla | Cuándo aplica |
|---|---|---|
| S-01 | 3 h del horario de captura sin fotos (una cámara de día no "se cae" de noche) | Obra en ejecución |
| S-02 | 3 de los últimos 7 días con menos del 60 % de las fotos esperadas (requiere la frecuencia configurada) | Obra en ejecución |
| S-03 | Cambio de encuadre detectado y todavía "Por revisar" | Siempre |
| S-04 | 3 días seguidos con fotos, pero ninguna apta para la IA (lente empañado, quemadas…) | Obra en ejecución |
| S-05 | Las fotos de la API llegan más de 30 min después de su hora de captura (mediana, 7 días) | Siempre |
| S-06 (ALTA) | 3 días sin ninguna foto, o nunca llegó una (cámara caída o retirada). Si está activa no se muestran S-01 ni S-02 | Obra en ejecución |

Con los datos actuales, Limoncito, el Puente y Ticabán muestran S-06: la última foto cargada es de jul. 2026, abr. 2026
y sep. 2025. Puede ser que la cámara ya no envíe o que falte volver a correr el ETL; el texto de la alerta lo aclara.

## Auditores (Administración → Auditores)
Crear (nombre, correo, contraseña inicial, frecuencia del reporte y proyectos), **Editar** (nombre, correo de acceso y
frecuencia), cambiar la frecuencia directo en la tabla, activar/desactivar el acceso, cambiar contraseña y asignar
proyectos. El correo es el usuario de ingreso y no puede repetirse.

## Empresa ejecutora (perfil contratista)
La Administración crea las cuentas en **Contratistas** (empresa, ingeniero responsable, correo, teléfono), las edita,
las da de baja (desactiva el acceso; lo cargado se conserva) y les asigna obras, también desde el botón 🏗️ **Empresa**
de cada proyecto. Asignar auditores y asignar empresa son independientes: uno no borra al otro. La empresa no recibe
reportes por correo.

En `/contratista` el ingeniero carga, por obra:
- **Cronograma**: archivo CSV o Excel con `codigo, actividad, inicio, fin, peso` (hay plantilla). Cada carga es una
  versión nueva; los pesos se ajustan para sumar 100 %. Con él se calcula la curva planificada (lineal por actividad).
- **Bitácora de obra**: una entrada por día (clima, personal, maquinaria y si operó, horas, actividades, avance
  acumulado e incidentes). Se puede corregir durante 48 h; no se aceptan fechas futuras.
- **Costos y presupuesto**: partidas por archivo (`codigo, partida, monto`) y costos (gasto o estimación de pago) por
  partida. Los costos no se borran: se anulan con motivo.
Toda carga, corrección o anulación queda en `contratista_cambios`. En obras Finalizadas o Canceladas todo es de solo lectura.

**Cruce con la IA** (`src/contratista.py`, sección "Empresa ejecutora" del panel del auditor). Las alertas se suman a
las A-xx en el panel, las tarjetas, el Seguimiento y el PDF. Umbrales en `config.UMBRALES`:

| Código | Regla |
|---|---|
| C-01 | El avance reportado en la bitácora supera al observado por la IA en más de 5 pts |
| C-02 | El % del presupuesto ejecutado supera al avance físico observado en más de 10 pts |
| C-03 | La bitácora declara maquinaria operando o más personal del que detectó la IA |
| C-04 | La bitácora justifica el paro por lluvia fuerte y el clima registrado fue apto |
| C-05 | 3 o más de los últimos 7 días con actividad en cámara sin bitácora (solo si hay empresa asignada) |

## Si Administración aparece vacía
La página ahora muestra un aviso rojo cuando la API falla. Causas habituales: la página se abrió como archivo o con
otro servidor (p. ej. Live Server) en lugar de `http://localhost:8000/login`, o el proceso de uvicorn quedó corriendo
con código anterior. Solución: detener uvicorn (Ctrl+C), volver a iniciarlo y recargar con **Ctrl+F5**. Durante el
desarrollo conviene iniciarlo con `--reload` para que tome los cambios solo.

## API de imágenes (cámaras)
Cada proyecto tiene su propio token (se genera en Editar → Cámara; se muestra una sola vez y en la base queda solo su hash).

    POST /api/camaras/{proyecto}/imagenes      Authorization: Bearer <token>
         multipart: foto (JPEG/PNG, máx. 10 MB), tomada (ISO 8601, opcional)
                    personas, maquinaria (0/1), confianza (0-1): opcionales, si la cámara ya ejecuta la IA
    GET  /api/camaras/{proyecto}/estado        Authorization: Bearer <token>   (probar la conexión)

    curl -H "Authorization: Bearer dia_..." -F foto=@captura.jpg -F tomada=2026-10-24T14:30:00          https://<servidor>/api/camaras/P-004/imagenes

Las fotos se guardan en `data/obras/<id>/camara/` y en la tabla `imagenes`. Una obra sin registro diario de la IA
muestra en su panel las imágenes recibidas, las observaciones, el clima real y los aportes.

## ETL de imágenes desde Google Drive
Trae las fotos de la cámara de obra desde una carpeta **pública** de Drive (sin clave), arma una tabla de metadatos y
la cruza con el clima histórico de la zona. Es una zona de preparación: tablas `etl_*` separadas, **no cambia el panel
ni las alertas**. Es la base para entrenar y probar el modelo de IA.

    python backend/etl_imagenes.py todo         # listar + descargar + clima + curar + cruce + hojas (P-001 por defecto)
    python backend/etl_imagenes.py listar       # solo el catálogo (≈20 s, no descarga)
    python backend/etl_imagenes.py descargar --historico --limite 50   # también la etapa anterior; pocas para probar
    python backend/etl_imagenes.py estado
    python backend/etl_imagenes.py encuadre --proyecto P-001   # cambios de encuadre de la cámara (después de curar)

- **Carpeta de Drive de cada obra**: Administración → Proyectos → Editar → "Imágenes desde Google Drive" (ahí también
  la rotación, la nitidez mínima, la ventana de días y los períodos excluidos). Estructura y nombres (Limoncito, P-001):
  - `<día>/IMG_CAM_01_AAAAMMDD_HHMMSS.jpg`: cámara fija, desde el 17/04/2026 (origen `camara`). Llegan **de cabeza**.
  - `imagenes_tratadas/<día>/`: etapa anterior, sep. 2025 – abr. 2026 (origen `historico`), con nombres
    `AAAAMMDD-HHMMSS.jpg` o `IMG_HH-MM-SS.jpg` (la fecha sale de la carpeta). Incluye fotos de instalación y prueba.
  - `control.csv`: bitácora de `imagenes_tratadas`; el paso `listar` verifica que coincida con lo que hay en Drive.
- **Metadatos** (`etl_imagenes`): cámara, fecha y hora (del nombre, hora de Costa Rica), validación del nombre,
  y al descargar: tamaño, dimensiones, huella SHA-256 (duplicados) y brillo medio.
- **Clima** (`etl_clima_horas`): Open-Meteo histórico (reanálisis ERA5, ~5 días de atraso): lluvia, temperatura,
  humedad, nubosidad y radiación por hora.
- **Cruce** (`data/etl/P-001/`): `imagenes_metadatos.csv`, `imagenes_clima.csv` (cada foto con el clima de su hora y
  banderas: lluvia durante la captura, oscura con sol, nocturna, duplicada) y `resumen_diario.csv` (fotos, huecos de
  más de 60 min, días sin fotos, lluvia y temperatura del día). Umbrales en `config.ETL`.
- **Curación** (`curar`, `src/etl/curacion.py`): decide qué fotos sirven para la IA (`apta_ia` + `motivo_ia`).
  Bloquea: período excluido a mano (instalación), duplicada, nocturna, oscura, sobreexpuesta y borrosa o lente
  empañado (nitidez < 8; calibrado: empañadas ≤ 5,4, nítidas ≥ 11). Avisa (sigue apta): lluvia durante la captura.
  Las aptas se guardan **enderezadas** y sin metadatos en `data/etl/curadas/` (CAM_01 se gira 180°; `imagenes_tratadas`
  ya viene derecha). Tras cambiar un umbral: `curar --rehacer`.
- **Hojas de contacto** (`hojas`): `data/etl/P-001/hojas/<día>.jpg` con todas las fotos del día (verde apta, amarillo
  con aviso, rojo no apta + motivo) e `index.html` para recorrerlas.
- **Cambios de encuadre** (`encuadre`, `src/etl/encuadre.py`, método del colab "PROERI_cambio_camara_v2" sin OpenCV):
  por día, las 2 fotos de día más cercanas al mediodía (también las empañadas: igual muestran el encuadre); un
  descriptor de bordes por foto; disimilitud entre los 7 días con fotos antes y los 7 después; y, en cada cambio,
  correlación de fase para estimar cuántos píxeles se movió la imagen. Resultado: tablas `etl_encuadre_dias` y
  `etl_encuadre_cambios` (estado "Por revisar", se conserva al repetir), `data/etl/<id>/encuadre/serie_diaria.csv`,
  `cambios.csv` y un panel antes/después por cambio (`cambio_<fecha>.jpg`). Umbrales en `config.ENCUADRE`, calibrados con
  las tres obras reales. Un cambio aparece cuando ya hay 8 días con fotos después de él. Indica qué revisar, no
  prueba el movimiento. Base de la alerta S-03 (ítem ALE-03 del backlog).
- Lo que muestran los datos de Limoncito: 22/09–28/10/2025 fotos quemadas; nov. 2025–11/02/2026 lente empañado;
  desde el 11/02/2026 imagen nítida con **otro encuadre** (la cámara se movió). El paso `encuadre` encontró además un
  **movimiento entre el 06 y el 07/11/2025** (la imagen se corrió ~90 px a la izquierda: se ve en la grúa), no
  documentado antes. Puente (P-004) y Ticabán (P-005): sin cambios en el período descargado.
- Los originales se guardan **sin modificar**. Todo se puede repetir: solo baja y procesa lo nuevo.

## Datos reales en el panel (P-001 Escuela Limoncito)
`python backend/etl_imagenes.py publicar` (después del ETL y de `ia_actividad.py analizar`; se puede repetir) lleva
a la aplicación lo real (`src/etl/publicar.py`):
- **Fotos**: las aptas y enderezadas, en `data/obras/P-001/camara/` (enlace duro, sin duplicar espacio) y en la tabla
  `imagenes` con `fuente='etl'` y lo que detectó la IA (personas, vehículos, confianza).
- **Registro diario** (`diario.csv`): fotos, personas, horas con personas y el clima real (Open-Meteo histórico).
  Los días con fotos pero ninguna apta aparecen como **"Fotos no aptas"** con el motivo (p. ej. lente empañado).
- **Lo que no se mide queda vacío, no se inventa**: avance previsto/observado, maquinaria, tiempo muerto y confianza.
  El panel muestra **"⚪ Avance sin medición"** y "—" en avance y brecha; no se calculan las alertas que dependen de
  esos datos (A-01 a A-04, C-01, C-02). El sitio público muestra "Avance general: en medición".
- Los sintéticos de P-001 quedan respaldados en `data/obras/_sintetico/P-001/`; `data/obras/P-001/origen.json` marca
  la obra como real y `make_data.py` ya no la sobrescribe. P-004 (Puente María Aguilar) y P-005 (Liceo Ticabán) también
  son reales (solo su último mes con datos: "Ventana de días" del proyecto). P-002 sigue siendo de ejemplo.
- Para volver a los sintéticos: borrar `origen.json`, `diario.csv` y `camara/` de P-001, restaurar desde `_sintetico/`
  y ejecutar `DELETE FROM imagenes WHERE fuente='etl'`.

## IA: actividad en obra (fase de investigación)
Sobre las fotos aptas del ETL. Tablas propias (`ia_actividad`): **no cambia el panel ni las alertas**.

    python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 torchvision==0.29.1
    python -m pip install -r requirements-ia.txt
    python backend/ia_actividad.py analizar     # ~0,8 s por foto en CPU; se puede cortar y retomar
    python backend/ia_actividad.py resumen      # actividad_fotos.csv, actividad_diaria.csv (data/etl/P-001/)

- **Detección**: YOLO11-s preentrenado (COCO), personas y vehículos, con realce de contraste. Pesos en
  `data/ia/modelos/`. Parámetros en `config.IA`.
- **Índice de cambio**: % de píxeles que cambian respecto de la foto anterior del mismo día. Es una señal de apoyo
  (también la mueven sombras, nubes y cambios de color de la cámara).
- **Cruce con la lluvia**: por día, actividad en jornada (07:00–17:00) frente a la lluvia de la jornada; correlación
  de Spearman por mes.
- **Límite conocido**: con el patio abierto (feb.–abr. 2026) detecta bien a las personas; desde abril el área está
  techada, oscura y medio tapada y el modelo preentrenado **no ve a los obreros**. Para esa etapa hay que entrenar
  con fotos etiquetadas de esta cámara (las detecciones actuales sirven de pre-etiquetado).
- **Licencia**: Ultralytics/YOLO11 es AGPL-3.0; resolverlo antes de producción (ver `src/ia/__init__.py`).

## Clima real: varias fuentes consolidadas
| Fuente | Activación (variable de entorno) | Historial | Pronóstico | Condiciones |
|---|---|---|---|---|
| **Open-Meteo** | Activa por defecto, sin clave (`OPEN_METEO_ACTIVO=0` la apaga) | hasta 92 días (se piden 7) | 16 días | Gratis no comercial, CC BY 4.0 |
| **Google Weather** | `GOOGLE_MAPS_API_KEY` | 24 h | 10 días | De pago |
| **Meteoblue Free** | `METEOBLUE_API_KEY` | 3 días | 14 días | Gratis no comercial (1 año, créditos) |
| **Meteosource Free** | `METEOSOURCE_API_KEY` | no (de pago) | 7 días | 400 llamadas/día, mención y enlace |

**Activar las fuentes con clave** (sin clave, solo responde Open-Meteo):
1. Copie `.env.ejemplo` como `.env` (en `diara/`) y pegue las claves. `config.py` lo lee al arrancar; una variable
   definida en la consola tiene prioridad. El `.env` tiene secretos: no se comparte ni se sube a repositorios.
2. Cómo obtener cada clave:
   - **Google Weather**: en Google Cloud Console cree un proyecto, active la facturación, habilite **Weather API**
     (APIs y servicios → Biblioteca) y cree una clave en Credenciales; restrínjala a "Weather API". Tiene costo por
     uso: revise el precio y la cuota gratuita vigente en la consola.
   - **Meteoblue**: cree una cuenta en meteoblue.com y solicite la clave de la API gratuita (uso no comercial, válida
     por un año con créditos limitados) desde su cuenta.
   - **Meteosource**: cree una cuenta en meteosource.com con el plan gratuito; la clave aparece en el panel de la cuenta.
3. Verifique con `python backend/probar_clima.py`: muestra por fuente si está configurada, si responde y, si falla,
   la causa probable (clave inválida, API no habilitada, cuota agotada, sin conexión).
4. Reinicie uvicorn y use Administración → Clima → "Actualizar ahora" (o `python backend/actualizar_clima.py`).

**Registro consolidado por día**: se usa la **mediana** de las fuentes con el día completo (≥ 20 h). Confianza: **alta** si 2+ fuentes coinciden (±5 mm), **media** con una sola fuente, **baja**
si discrepan (⚠️) o solo hay datos parciales. Con ≥ 5 mm el día es no apto; un día incompleto solo puede confirmar
"no apto". El pronóstico y las condiciones actuales también son la mediana de las fuentes, con su grado de acuerdo.
Donde hay clima concluyente, reemplaza al sintético en el registro diario y las alertas lo usan. Umbrales en `CLIMA`
de `backend/config.py`.

**Tablas de clima (todo queda guardado para análisis y seguimiento):**

| Tabla | Contenido | Se actualiza |
|---|---|---|
| `clima_horas` | Dato observado por hora y fuente (con fecha de primera captura y de última revisión) | Cada actualización (upsert, sin duplicar) |
| `clima_dias` | Último pronóstico de cada fuente | Cada actualización |
| `clima_pronosticos_hist` | Foto diaria del pronóstico de cada fuente (fecha de emisión, día objetivo, anticipación) | Una por día; no se sobrescribe entre días |
| `clima_registro` | **Registro consolidado por día** (fuente única de verdad para alertas, reportes y análisis) | Se recalcula y guarda en cada actualización |
| `clima_registro_cambios` | Auditoría: cada cambio de un día ya registrado (campo, antes, después, motivo, fecha) | Automático |
| `clima_ejecuciones` | Bitácora: cada consulta a cada fuente (ok/error, datos recibidos, duración) | Automático |

Análisis en Administración → Clima: **precisión del pronóstico por fuente** (error medio, sesgo y acierto en
"día apto" según los días de anticipación) y exportación CSV de todas las tablas. Cada proyecto descarga su
registro (`/api/auditor/{proyecto}/clima/registro.csv`) y muestra su historial de cambios.

1. Configurar las claves que se tengan (todas opcionales; Open-Meteo funciona sin ninguna) y reiniciar el servidor.
2. Programar `python backend/actualizar_clima.py` al menos cada 12 h **en el mismo servidor de la base**
   (Programador de tareas de Windows o cron). También se puede ejecutar desde Administración → Clima.
3. **Uso no comercial**: Open-Meteo, Meteoblue y Meteosource gratuitos lo exigen. Confirmar con cada proveedor que
   el uso de la CGR califica, o contratar sus planes comerciales antes de producción. Mantener las atribuciones.

## Reportes automáticos por correo (Administración → Reportes)
Cada persona recibe **un PDF con el resumen de todos sus proyectos asignados** (el administrador: todas las obras).
La frecuencia se define por persona: **No recibir · Diario · Resumen semanal · Resumen quincenal**.

| Frecuencia | Se envía | Período del reporte |
|---|---|---|
| Diario | Todos los días | Día anterior |
| Semanal | Día configurable (por defecto, lunes) | 7 días anteriores |
| Quincenal | Dos días configurables (por defecto, 1 y 16) | Desde el envío quincenal anterior hasta el día previo |

**Contenido del PDF**: portada con indicadores (incluye **cámaras con alertas**) y resumen ejecutivo de todos los
proyectos (con una columna **Cámara** con los códigos S-xx), lista de "requiere atención" (incluye las cámaras caídas o
con alertas) y, por proyecto: ficha (institución, contratista, SICOP, monto, plazo, cámara, coordenadas), indicadores,
gráfico de avance previsto vs. observado, resumen de la IA, alertas, **salud de la cámara** (última foto, cobertura,
fotos y días sin fotos del período, alertas S-xx y cambios de encuadre), clima del período (registro consolidado),
observaciones, aportes ciudadanos y última imagen de la cámara. El correo repite los indicadores de la portada
(también "cámaras con alertas") y la lista de "requiere atención". El botón "Reporte PDF" de cada proyecto usa el mismo formato.

**Calendario y plantilla configurables** (Administración → Reportes → "Calendario de envío y plantilla del reporte"):
día del resumen semanal, los dos días del resumen quincenal (1 a 28), **hora de envío**, institución, unidad, color principal, logo
(PNG/JPG) y pie de página. Se guardan en la tabla `configuracion` (el logo en `data/plantilla/`) y aplican a los
próximos envíos y a "Ver PDF de ejemplo". El administrador también elige su propia frecuencia en la tabla de personas.

**Envío automático** (`src/programador.py`): con el servidor encendido, un proceso interno revisa cada 10 minutos y,
desde la hora configurada (por defecto 06:00, hora de Costa Rica), envía lo que corresponda. No hace falta programar
nada en Windows. Reglas (`reporteria.pendientes`):
- Nunca repite un período ya enviado.
- Si el servidor estaba apagado el día de un envío **semanal o quincenal**, lo envía en la siguiente revisión (hasta
  7 días después). Los **diarios** perdidos no se recuperan (llegaría una ráfaga de correos viejos).
- Un envío que falla se reintenta en las revisiones siguientes, **máximo 3 veces** por período; el error queda en el
  historial con la causa probable (contraseña rechazada, servidor o puerto incorrecto, remitente no permitido…).
- Un bloqueo en la base (`tareas_bloqueo`) evita envíos simultáneos si hay varios procesos.
- Se apaga con `REPORTES_AUTOMATICOS=0`; entonces hay que programar `tareas\enviar_reportes.bat` una vez al día.
  Si el servidor no está siempre encendido, se puede programar igual como respaldo (no duplica envíos).

**Configurar el correo** (sin esto funciona en **modo simulado**: genera y guarda el PDF sin enviarlo):
1. En `diara/.env` complete `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` y `SMTP_SEGURIDAD`
   (`starttls` en 587, `ssl` en 465). Ejemplos en `.env.ejemplo`:
   - **Microsoft 365** (correo institucional): `smtp.office365.com`, 587, `starttls`. El buzón necesita "SMTP
     autenticado" habilitado por TI, y `SMTP_FROM` debe ser la misma cuenta de `SMTP_USER`.
   - **Gmail**: `smtp.gmail.com`, 587, `starttls`, con una **contraseña de aplicación** (requiere verificación en dos pasos).
2. Reinicie uvicorn y pruebe con el botón **"✉ Correo de prueba"** de Administración → Reportes o con
   `python backend/enviar_reportes.py --prueba su_correo@dominio`.
3. Defina la frecuencia de cada persona y la hora de envío. El estado del envío automático, la última revisión y
   los pendientes se ven en el recuadro "Envío automático".

Cada envío queda en `reportes_envios` (enviado / simulado / error, período, origen: automático, programado,
administración o manual) con copia del PDF en `data/reportes/AAAA/MM/`. El correo lleva versión de texto y HTML
(indicadores, "requiere atención" y enlace al panel) y el PDF adjunto. Desde Administración: vista previa, enviar a
una persona, "Enviar pendientes ahora" e historial.

## Tareas programadas (Windows)
| Archivo | Frecuencia | Qué hace |
|---|---|---|
| `tareas\actualizar_clima.bat` | Cada ≤ 12 h | Consulta las fuentes de clima y actualiza el registro |
| `tareas\enviar_reportes.bat` | 1 vez al día (opcional) | Respaldo del envío automático: envía los reportes pendientes |
Salida en `data/tareas.log`. En el Programador de tareas: Crear tarea básica → Desencadenador → Acción "Iniciar un programa" → el `.bat`.

## Seguridad
- Contraseñas guardadas con PBKDF2 (nunca en texto plano). Sesión en cookie HttpOnly firmada, 8 horas.
- Cada petición vuelve a leer el usuario: desactivar a alguien o quitarle un proyecto aplica de inmediato.
- Un auditor recibe 404 en proyectos que no tiene asignados; `/api/admin/*` responde 403 a quien no es admin.
- Las fotos de aportes ciudadanos solo son públicas cuando un auditor las aprueba; mientras están pendientes solo las
  ven el auditor de esa obra y el admin.
- **Aislamiento de la empresa ejecutora**: el contratista solo accede a `/api/contratista/*` (y solo a sus obras),
  a su sesión y al sitio público. Recibe 404 en la vista del auditor, en las imágenes de cámara y en las fotos de
  aportes, y 403 en `/api/admin/*` y `/api/mis-proyectos`; las páginas de otros roles lo devuelven a `/contratista`.
  Nunca recibe el análisis de la IA, las alertas, las observaciones ni los reportes por correo.
- **Sitio público sin análisis de auditoría**: `/api/resumen` solo publica datos generales, estado administrativo y
  el avance general observado con su fecha. No publica el estado calculado (atrasada…), la brecha, lo previsto, el
  gráfico, el texto de la IA ni las alertas: lo que la auditoría está detectando no debe conocerlo la empresa
  fiscalizada antes de que el auditor lo revise (regla documentada en `routes/publico.py`).
  Cada obra muestra su **última foto en versión pública** (`/publico/foto/{id}`): las sintéticas sin los recuadros de
  detección (`camara/publica/`, las genera `make_data.py`) y las de la API reducidas a 960 px y sin metadatos (EXIF/GPS).
  Solo la última: el historial de imágenes es parte del expediente. Antes de producción: difuminar rostros y placas.
- `make_data.py` ya no borra las fotos recibidas por la API de cámaras: solo reemplaza las sintéticas.
- La documentación automática de la API (`/docs`, `/openapi.json`) está apagada porque describe todas las rutas del
  sistema. Para desarrollo: `$env:DIARA_DOCS="1"` antes de iniciar uvicorn.

## Despliegue web
- Docker / Cloud Run: `gcloud run deploy diara --source . --set-env-vars ADMIN_PASS=...,SECRET_KEY=...`
- Correo: variables SMTP_* (ver «Reportes automáticos por correo»).

## Pruebas automáticas
    pip install -r requirements-dev.txt     (una vez: instala pytest)
    python -m pytest                        (desde esta carpeta; tarda unos segundos)

- Están en `tests/` y **nunca tocan los datos reales**: `tests/conftest.py` define `DIARA_DATA_DIR` con una carpeta
  temporal (base nueva con los proyectos de `data/proyectos.csv` y los usuarios de ejemplo) y la borra al terminar.
- Cubren: alertas A-01..A-04 e indicadores (`test_alertas.py`), alertas C-01..C-05 del cruce con la empresa
  ejecutora (`test_alertas_contratista.py`), reglas de curación del ETL (`test_curacion.py`), permisos por rol y lo
  que publica el sitio público (`test_permisos.py`) y la API de cámaras (`test_api_camaras.py`).
- Los umbrales se leen de `config.py`: cambiar un umbral no rompe las pruebas, pero cambiar una **regla** sí.
- Al agregar una alerta o una regla nueva, agregar su prueba en el mismo cambio.
- GitHub las corre solo en cada push y pull request (`.github/workflows/pruebas.yml`, pestaña "Actions").

## Pendientes conocidos
- Falta límite de intentos de login y recuperación de contraseña por correo.
- Cerrar sesión borra la cookie, pero el token sigue siendo válido hasta vencer (sin lista de revocación).
- SQLite en Cloud Run no persiste: migrar a Cloud SQL (PostgreSQL) para producción.
- El "Resumen de la IA" se genera con reglas sobre los datos, no con un modelo de lenguaje.
- Fuera de alcance por ahora: integración con SICOP.
