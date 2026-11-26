# dIAra · Guía de visualización basada en *The Functional Art* (Alberto Cairo, 2013)

Esta guía resume, **con nuestras propias palabras**, las ideas del libro que más sirven para pulir dIAra. Después
las aplica al código actual del frontend y del PDF. El libro no se sube al repositorio (tiene derechos de autor):
cada persona del equipo debe consultar su propia copia. Entre paréntesis se indica el capítulo donde está cada idea.

Las mejoras salen como ítems **VIZ-xx** en [`backlog_mejoras.md`](backlog_mejoras.md).

---

## 1. Principios del libro, en corto

### 1.1 La forma la deciden las preguntas, no el gusto (cap. 2)
- Antes de dibujar, hay que escribir **qué preguntas debe responder el gráfico**: comparar, ordenar, ver una
  relación, ver la evolución en el tiempo o ubicar en el mapa. La forma del gráfico depende de eso. Puede haber
  varias formas válidas, pero no cualquiera sirve.
- **Variables derivadas.** Los valores absolutos engañan cuando las unidades tienen tamaños distintos. Conviene
  normalizar: por persona, por día hábil, en % del plazo o en % de lo esperado. *En dIAra:* "fotos recibidas" no
  dice nada sin "fotos esperadas". "Personas detectadas" no dice nada sin "días hábiles con clima apto".
- **Las plantillas causan inercia.** Repetir un gráfico por costumbre impide preguntarse si sigue siendo el
  adecuado. Los gráficos que se repiten (como el PDF periódico) hay que revisarlos de vez en cuando.
- **Cuidado con la "plaga de burbujas"**: las burbujas y los círculos proporcionales se ven bien, pero se comparan
  mal.

### 1.2 La rueda de visualización: equilibrar tensiones según el público (cap. 3)
Cairo propone seis ejes para ubicar un gráfico. No son una medida exacta, sino una ayuda para pensar:

| Eje | Qué significa |
|---|---|
| Abstracción ↔ Figuración | De un gráfico de datos a una foto o ilustración realista |
| Funcionalidad ↔ Decoración | Elementos que ayudan a entender frente a adornos |
| Densidad ↔ Ligereza | Cantidad de datos por espacio usado |
| Multidimensionalidad ↔ Unidimensionalidad | Capas de información y formas de codificar los mismos datos |
| Originalidad ↔ Familiaridad | Formas nuevas frente a formas que todos saben leer (barras, líneas) |
| Novedad ↔ Redundancia | Decir cada cosa una vez frente a repetirla por otro medio (texto + gráfico, resaltados) |

- La complejidad debe ajustarse al **público**. Quien diseña codifica y el lector decodifica según lo que ya sabe
  del tema y de los tipos de gráfico.
- Un poco de **redundancia** (un texto que explica lo que muestra el gráfico, el dato clave resaltado) mejora la
  comprensión.

**dIAra tiene tres públicos con lugares distintos en la rueda:**

| Público | Posición recomendada |
|---|---|
| **Ciudadanía** (sitio público) | Más figurativo (foto real, timelapse), ligero, familiar, con mucha redundancia en texto llano |
| **Auditor** (panel de proyecto) | Abstracto, denso, multidimensional, familiar; los detalles disponibles a pedido |
| **Administración / CGR** (seguimiento) | Muy denso y comparativo (todas las obras en una vista), ordenado por urgencia |

### 1.3 Buscar profundidad: los gráficos no "simplifican" (cap. 4)
- Hay que aprovechar el espacio para dar **profundidad razonable** y recién después preocuparse por la estética.
- No hay que subestimar al lector. Un gráfico bien hecho **aclara** la información, no la recorta: permite que el
  lector compare su caso con los demás y saque sus propias conclusiones.

### 1.4 Cómo ve el cerebro (caps. 5–7)
- El ojo detecta **diferencias** (contraste de luz y de color) antes de pensar. Lo importante debe destacarse
  por contraste; el resto, en gris.
- El color y el tono se detectan sin esfuerzo, pero para **comparar cantidades** son malos.
- **La escala de Cleveland y McGill** ordena las codificaciones de la más precisa a la menos precisa:
  1. posición sobre una escala común;
  2. posición sobre escalas no alineadas;
  3. longitud, dirección, ángulo;
  4. área;
  5. volumen, curvatura;
  6. sombreado, saturación de color.

  Si el objetivo es comparar con precisión, conviene usar barras o puntos sobre un eje común. Si es ver un patrón
  general (por ejemplo, en un mapa o un heatmap), se puede bajar en la escala.
- Si lo que importa es una **diferencia** entre dos series (por ejemplo, reportado menos observado), es mejor
  **calcular y graficar la diferencia** que pedirle al ojo que compare dos curvas.
- Lo que cuenta no es la velocidad de lectura, sino si el gráfico deja ver algo que sin él no se vería.
- Principios de la Gestalt: proximidad, similitud y cercamiento agrupan elementos. Un mismo color debe significar
  siempre lo mismo.

### 1.5 Proceso y estilo (cap. 8)
- Primero se definen el objetivo y el alcance, después se investiga y se **bocetea en papel**, y recién después se
  pasa a la computadora.
- **Pocos colores**: 2–3 tonos con sus variantes, un neutro para el fondo y **un color de acento** para lo
  relevante. **Pocas tipografías**: una para títulos y otra para el texto.
- La composición se piensa como **rectángulos**: cuadrícula, alineación y jerarquía.

### 1.6 Interactividad (cap. 9)
- **Visibilidad**: los controles deben parecer controles. **Lo indispensable no se esconde detrás de un clic
  o de pasar el mouse.**
- **Retroalimentación**: cada acción debe tener una respuesta inmediata.
- **Restricciones**: se ofrecen solo las interacciones que sirven al objetivo.
- **Consistencia**: elementos iguales se ven y se ubican igual en todas las pantallas.
- **El mantra de Shneiderman**: *primero la vista general, después acercar y filtrar, luego los detalles a
  pedido*. Siempre hay que empezar con un título claro y una introducción breve.
- Técnicas útiles: desplazar, acercar, abrir y cerrar, ordenar, buscar y filtrar.
- Hay cuatro estilos de interacción: instrucción, conversación, manipulación y exploración.

---

## 2. Auditoría de dIAra con estos principios

| # | Dónde | Hallazgo | Principio | Propuesta |
|---|---|---|---|---|
| 1 | `frontend/assets/js/common.js:39` `graficoAvance` y `proyecto.html` `graficoEmpresa` | El eje X usa el **índice** del registro, no la fecha: si faltan días, se comprimen y la línea los une como si hubiera continuidad | Honestidad visual; el mismo aprendizaje del colab "sin interpolación" | Eje X **por fecha calendario**; cortar la línea en los huecos (o usar puntos) y sombrear los días sin datos |
| 2 | `proyecto.html` `graficoEmpresa` | Si en una serie hay `obs` nulos mezclados con valores, `Y(null)` se dibuja como **0 %** | Honestidad visual | Saltar los nulos (segmentos separados). Agregar una prueba |
| 3 | `proyecto.html` `pintarClima` | **Doble eje** (lluvia en mm a la izquierda, temperatura en °C a la derecha) en el mismo lienzo: el cruce de las curvas no significa nada | Cleveland: cada escala con su posición; evitar comparaciones falsas | **Dos paneles apilados** con el mismo eje X (small multiples). Marcar la línea de 5 mm (umbral de "no apto") |
| 4 | `proyecto.html` `graficoEmpresa` | La serie "Reportado en bitácora" usa `--al` (**rojo = alerta** en todo el sitio) | Consistencia de color, Gestalt de similitud | Rojo reservado **solo** para las alertas. Series con una paleta neutra y el acento solo en lo destacado |
| 5 | Gráfico de avance (3 series) | Para saber si la empresa reporta de más, el ojo tiene que comparar dos curvas | Graficar la diferencia (cap. 6) | Agregar un mini gráfico de la **diferencia reportado − observado**, con una banda de tolerancia (umbral C-01 = 5 pts) |
| 6 | `frontend/assets/js/panel.js:11` `kpi()` | La explicación del indicador va en `title`, que **solo aparece al pasar el mouse** y no existe en celulares | Visibilidad: lo indispensable no se esconde | Texto auxiliar visible bajo el valor; dejar el `title` solo como complemento |
| 7 | KPIs del panel | "Avance observado (IA)" cuando la IA no mide avance | Redundancia y honestidad de la etiqueta | Renombrar a "Actividad observada" y explicar en una línea qué se mide (se relaciona con UX-01) |
| 8 | `admin.html` `graficoBrechas` | ✅ Bien: barras divergentes ordenadas sobre un eje común, con el valor rotulado. Falta la línea del **umbral −10** (A-03), y el rojo y el verde no se distinguen con daltonismo | Cleveland + accesibilidad | Línea de referencia en −10 con su rótulo. Rótulos y patrones además del color |
| 9 | Ejes de fechas (todos los gráficos) | Solo 3 fechas rotuladas (inicio, medio, fin), sin marcas de semana ni de mes | Rectángulos y legibilidad | Marcas semanales y el nombre del mes, como en el heatmap del colab |
| 10 | Gráficos SVG duplicados en 4–5 archivos, cada uno con su propia escala | Cada gráfico resuelve a su manera los ejes, las fechas y los nulos | Consistencia (cap. 9) | Un único módulo `assets/js/graficos.js` (ejes, fechas, huecos, leyenda, tooltip) usado por el panel, admin, contratista y PDF |
| 11 | PDF (`backend/src/reporte_pdf.py`) | Paleta del PDF distinta de la web (`ROJO #c0392b` frente a `--al #d64545`; `AMBAR` distinto) | Consistencia | Una sola definición de tokens de color para la web y el PDF |
| 12 | Panel del proyecto | Sección larga con scroll y muchas KPI al mismo nivel | Vista general → filtrar → detalle | Arriba, una franja de **"qué requiere atención"** (1–3 frases redundantes con el gráfico). Detalles plegables debajo |
| 13 | Sitio público | Muestra datos generales y la última foto | Rueda: público ciudadano → figurativo, ligero, redundante | Timelapse, "¿qué está pasando en mi obra?" en lenguaje llano, mapa con las obras cercanas. Sin alertas sensibles (regla de `routes/publico.py`) |
| 14 | Seguimiento admin (todas las obras) | Tabla + brechas | Densidad para la CGR | **Small multiples**: una mini serie de actividad por obra en una cuadrícula, ordenada por riesgo (se relaciona con SEG-01) |
| 15 | Salud de la cámara (nuevo, EDA-01) | — | Patrón general → se puede usar sombreado | Heatmap día × hora (como el colab) para **patrones**. Para **comparar** cobertura entre cámaras, barras o puntos |
| 16 | Botones y acciones | Varias acciones sin estado de carga visible | Retroalimentación | Estado "procesando…" y desactivar el botón mientras se espera. El toast ya existe |

---

## 3. Lista de control para cada gráfico nuevo (usar en revisiones de código)

1. **Pregunta:** ¿qué pregunta responde este gráfico y para qué público (ciudadanía, auditor, CGR)?
2. **Forma:** ¿la codificación está alta en la escala de Cleveland para lo que hay que comparar? ¿Hace falta una
   variable derivada (%, por día, frente a lo esperado)?
3. **Tiempo:** ¿el eje X es de calendario real? ¿Los huecos se ven como huecos, sin líneas inventadas?
4. **Nulos:** "sin dato" se muestra como "sin dato", nunca como 0.
5. **Color:** ¿hay como máximo 2–3 tonos más un acento? ¿El rojo se usa solo para las alertas? ¿Se entiende en
   escala de grises y con daltonismo?
6. **Escalas:** nada de doble eje. ¿Las barras empiezan en 0? ¿Las escalas son comparables entre paneles?
7. **Redundancia:** ¿tiene un título que diga la conclusión, y no solo el tema? ¿El dato clave está anotado en
   el gráfico?
8. **Visibilidad:** ¿la información indispensable se ve sin pasar el mouse? ¿Funciona en el celular?
9. **Consistencia:** ¿usa el módulo común de gráficos y los tokens de color? ¿Se ve igual en la web y en el PDF?
10. **Honestidad:** ¿muestra la incertidumbre (confianza de la IA, datos parciales) en lugar de esconderla?
