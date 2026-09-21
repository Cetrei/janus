# 10 — Automatización de Interfaz Gráfica

## Estado del documento
Arquitectura pura, con una excepción deliberada: dado que este mecanismo no tiene
equivalente en protocolos estándar (a diferencia de MCP/gRPC), este documento nombra
técnicas de referencia (p. ej. "hints" estilo Vimium/Vim) como ejemplos del patrón de
interacción esperado, sin fijar una tecnología concreta de implementación. Depende de
`03-contrato-de-spoke.md` sección 2.4 (tipo de spoke controlado por automatización de
interfaz gráfica) y se referencia desde `08-mapa-de-componentes-reales.md` para Claude
Desktop y Gemini Desktop.

---

## 1. Problema que resuelve

Existe una categoría de spoke —tipificada en el documento 03 como 2.4— que no expone
ningún protocolo programático: ni MCP, ni gRPC, ni API, ni webhooks. La única forma de
interactuar con ese spoke es la misma que tiene un humano frente a la pantalla: una
ventana, con botones y campos de texto. Claude Desktop y Gemini Desktop son los casos
motivadores concretos, pero el mecanismo descrito aquí no está limitado a ellos —
cualquier aplicación de escritorio arbitraria es, en principio, alcanzable por este
mismo mecanismo.

Este documento define la arquitectura de ese mecanismo: cómo Janus abre, ubica,
enfoca y opera una ventana ajena, y cómo traduce lo que ve en pantalla a acciones
ejecutables, sin que la aplicación objetivo coopere ni sepa que está siendo operada por
Janus.

## 2. Capacidades que este mecanismo debe proveer al núcleo

Como con cualquier otro spoke, lo que este mecanismo produce hacia el núcleo son
capacidades registrables en el Registro de Capacidades (documento 04). Este mecanismo
en particular provee, como mínimo, dos capacidades de **plataforma** (no de una
aplicación específica) de las que dependen luego los adaptadores concretos de cada
spoke tipo 2.4:

1. **Control de ventana**: localizar una ventana por aplicación/título, abrirla si no
   está abierta, cerrarla, moverla, enfocarla. Esta capacidad es agnóstica a qué
   aplicación se está controlando.
2. **Mapa de elementos interactuables**: dada una ventana enfocada, producir una lista
   de elementos interactuables visibles (campos de texto, botones, enlaces, cualquier
   control accionable), cada uno con una posición y un método de activación. Esta es
   la capacidad que hace posible el patrón de "hints" descrito en la sección 3.

Sobre estas dos capacidades de plataforma se construye, para cada spoke tipo 2.4
concreto (Claude Desktop, Gemini Desktop, o cualquier otro que se agregue), un
adaptador que sabe qué secuencia de interacciones corresponde a "enviar una pregunta y
leer la respuesta" para esa aplicación en particular (ver sección 5).

## 3. El patrón de interacción: mapa de hints por teclado

El mecanismo de referencia para resolver la capacidad de "mapa de elementos
interactuables" es el mismo patrón que usan extensiones de navegador tipo Vimium/Vim:

- Ante una ventana enfocada, se detectan los elementos interactuables visibles.
- A cada elemento se le asigna una etiqueta corta (una letra o combinación breve).
- Activar un elemento equivale a "presionar" su etiqueta — Janus sintetiza la pulsación
  de esa tecla (o secuencia) en lugar de requerir coordenadas de mouse.
- Las etiquetas son efímeras: se recalculan cada vez que cambia el conjunto de
  elementos visibles (p. ej. al enfocar una ventana distinta, o al cambiar de pantalla
  dentro de la misma aplicación).

Ejemplos del tipo de mapeo esperado (ilustrativos, no una lista cerrada ni fija):
`e` → botón de enviar, `t` → campo de texto principal, `c` → copiar respuesta. El
conjunto real de etiquetas y a qué elemento corresponde cada una es, para cada
aplicación, resultado de la detección descrita en la sección 4 — no una tabla fija
escrita a mano por adelantado para cada spoke, salvo en el caso de degradación descrito
en la sección 4.3.

Este patrón no está limitado a control por teclado — es el ejemplo de referencia por
ser el más simple de razonar y el más portable entre aplicaciones, pero esta
arquitectura no descarta otros mecanismos de activación (p. ej. coordenadas de clic
calculadas a partir de la misma detección) si en la implementación resultan más
confiables para un caso concreto. Lo que sí fija esta arquitectura es que **la
detección de elementos y su activación son dos pasos separables**: el mapa de hints es
una forma de resolver la activación una vez que la detección ya identificó qué existe y
dónde.

## 4. Requisito central: el mapeo debe mantenerse vigente

Este es el requisito que motiva la existencia de este documento como pieza propia de
arquitectura, no solo como detalle de implementación de un adaptador más: **el mapa de
elementos interactuables no puede ser una configuración estática escrita una sola vez y
asumida como válida para siempre**, porque la interfaz de una aplicación de escritorio
puede cambiar (una actualización de la app, un cambio de tema, una ventana de tamaño
distinto) y romper cualquier mapeo fijo sin aviso.

Esta arquitectura reconoce tres estrategias posibles, en orden de preferencia, y exige
que el mecanismo implementado declare explícitamamente cuál usa para cada spoke tipo
2.4 conectado — nunca debe quedar ambiguo cuál de las tres está en juego:

### 4.1. Mapeo en tiempo real (preferido)
El mecanismo detecta los elementos interactuables de la ventana enfocada **en el
momento de necesitarlos**, cada vez, sin depender de una configuración guardada de
antemano. Esta es la estrategia que más directamente resuelve el requisito de "que
mapee en tiempo real": si la interfaz cambió desde la última vez, la siguiente
detección ya refleja el cambio, sin intervención humana.

### 4.2. Configuración asistida y reutilizable (fallback si el tiempo real no es
viable o no es confiable para un spoke dado)
Cuando la detección automática en tiempo real no logra identificar con confianza los
elementos relevantes (p. ej. una aplicación cuya interfaz no expone suficiente
información estructural como para detectarla de forma fiable), el mecanismo debe
poder apoyarse en una configuración guardada por aplicación — pero esa configuración
debe poder generarse de la forma más simple posible para el usuario, no escribirse a
mano elemento por elemento. El caso de referencia es: el usuario ejecuta una rutina de
configuración una única vez por aplicación (p. ej. "mostrar los hints detectados ahora
y confirmar/corregir cuáles son correctos"), y esa confirmación se guarda como la
configuración base para esa aplicación, reutilizándose en interacciones futuras hasta
que se detecte que ya no es válida (ver 4.3).

### 4.3. Detección de invalidación
Independientemente de si se usa 4.1 o 4.2, el mecanismo debe poder **darse cuenta**
cuando un mapeo (en tiempo real o guardado) ya no corresponde a lo que hay en pantalla
—por ejemplo, si el elemento esperado en una posición o con una etiqueta dada ya no
existe o no responde como se esperaba— y reportar esa falla al núcleo de forma
explícita (ver el requisito de "degradar de forma explícita y detectable" del
documento 03, sección 2.4), en lugar de continuar operando a ciegas. Cuando la
estrategia vigente para un spoke es 4.2, esta detección de invalidación es,
adicionalmente, la señal que dispara que el usuario deba repetir la configuración
asistida.

## 5. Adaptador específico por spoke, sobre el mecanismo de plataforma

El mecanismo descrito en las secciones 2 a 4 es genérico y compartido por todos los
spokes tipo 2.4. Cada spoke concreto (Claude Desktop, Gemini Desktop, u otro) tiene,
además, un adaptador específico y liviano que solo necesita saber:

- Qué secuencia de interacciones (en términos de los elementos detectados: "escribir en
  el campo de entrada", "activar el control de envío", "leer el contenido del área de
  respuesta") corresponde al flujo de "hacerle una pregunta a este spoke y obtener su
  respuesta".
- Cuándo considerar que la respuesta terminó de generarse (p. ej. cuándo un indicador
  de "generando" deja de estar presente), para no leer una respuesta incompleta.

Esta separación (mecanismo genérico de plataforma + adaptador liviano por spoke) es lo
que permite que agregar soporte a una aplicación de escritorio nueva no implique
reconstruir el control de ventanas ni la detección de elementos desde cero — solo
implica describir, para esa aplicación, cuál es su flujo de "pregunta → respuesta"
sobre el mapa de elementos que el mecanismo genérico ya sabe producir.

## 6. Relación con el resto de la arquitectura

- Hacia el núcleo, este mecanismo se presenta como cualquier otro adaptador: la cara
  semántica traduce el resultado leído en pantalla al modelo semántico interno
  (documento 01, sección 4), y el spoke sigue sin saber que Janus existe.
- El Principio Arquitectónico #1 (estrella pura) se mantiene sin cambios: un spoke tipo
  2.4 nunca es contactado por otro spoke directamente, solo por Janus, exactamente
  igual que cualquier otro tipo.
- El Principio Arquitectónico #2 (no-reinvención) también aplica aquí: si en el futuro
  algún spoke tipo 2.4 (p. ej. una versión futura de Claude Desktop o Gemini Desktop)
  expone un protocolo programático real, ese spoke debe migrar a ser tratado como tipo
  2.1 (razonamiento) con un adaptador de protocolo convencional, y este mecanismo de
  automatización de interfaz deja de usarse para él — la automatización de GUI es un
  mecanismo de último recurso, no el preferido, precisamente porque es el más frágil
  de todos los tipos descritos en el documento 03.

## 7. Documentos relacionados
- `03-contrato-de-spoke.md`, sección 2.4 — el contrato que este mecanismo satisface.
- `08-mapa-de-componentes-reales.md` — Claude Desktop y Gemini Desktop como los casos
  concretos motivadores.
- `09-preguntas-abiertas.md` — elección de tecnología/framework concreto para
  detección de elementos y síntesis de input, y alcance exacto de qué otras
  aplicaciones de escritorio (más allá de Claude/Gemini Desktop) se soportarán de
  fábrica, ambos aún no decididos.
