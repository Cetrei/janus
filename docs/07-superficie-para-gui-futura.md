# 07 — Superficie para GUI Futura

## Estado del documento
Arquitectura pura. No define ninguna GUI concreta, ni tecnología de interfaz. Define
únicamente los requisitos que el núcleo debe cumplir *hoy* para que una GUI (u otro
cliente externo) pueda construirse *después* sin requerir rediseño del núcleo.

---

## 1. Por qué este documento existe ahora, sin que exista una GUI

Uno de los objetivos explícitos de Janus es permitir, en el futuro, una interfaz gráfica
personalizada que permita interactuar con cada spoke de mejor manera que su interfaz
nativa. Ese objetivo no puede tratarse como "algo a resolver después" en el sentido de
posponer también sus requisitos arquitectónicos: si el núcleo no es observable y
controlable desde afuera desde el principio, construir esa GUI más adelante exigiría
modificar el núcleo, lo cual viola el espíritu de diseño agnóstico que motiva todo este
conjunto de documentos.

Por lo tanto, este documento fija requisitos que se cumplen en el núcleo **desde su
primera versión**, independientemente de si un cliente los consume hoy.

## 2. Principio: el núcleo no privilegia a ningún cliente

Un cliente de interacción con Janus —sea un canal de mensajería, una CLI, una futura
GUI, o el propio flujo de voz— consume la misma superficie observable y de control que
cualquier otro. Ninguna GUI futura debe requerir una vía de acceso especial al núcleo
que no esté disponible igualmente a cualquier otro cliente. Esto evita que el núcleo
desarrolle, con el tiempo, dos modelos de acceso paralelos (uno "de verdad" para
clientes internos y otro más limitado expuesto hacia afuera).

## 3. Qué debe ser observable

Como mínimo, debe poder consultarse desde afuera del núcleo, en todo momento:

- **Sesiones activas e históricas**, con su estado y los roles/spokes que participaron.
- **Tareas activas e históricas**, su estado, dependencias, y resultados.
- **Agentes/roles actualmente en ejecución**, incluyendo a qué spoke están asignados en
  este momento.
- **El Registro de Capacidades**, incluyendo qué spoke sirve cada capacidad y si está
  disponible.
- **Preferencias del usuario vigentes** (ver documento 06).
- **Eventos en tiempo real** de cambios de estado relevantes (una tarea que cambia de
  estado, una nueva sesión que se crea, un spoke que se desconecta) — no solo consulta
  bajo demanda ("pull"), sino también la posibilidad de suscribirse a cambios
  ("push"/streaming), dado que una GUI útil para "hablar con la PC en tiempo real" no
  puede depender exclusivamente de refrescos manuales.

## 4. Qué debe ser controlable

Como mínimo, debe poder iniciarse/modificarse desde afuera del núcleo, sujeto a
autenticación/autorización (cuyo mecanismo concreto es una decisión de implementación
fuera de alcance aquí):

- **Iniciar una nueva sesión o tarea.**
- **Reasignar manualmente un rol a un spoke distinto** (anulando la política de
  selección automática cuando el usuario lo desee explícitamente).
- **Pausar, cancelar o reanudar una tarea o sesión.**
- **Modificar preferencias del usuario** (políticas de selección, canales activos,
  etc.).
- **Registrar o retirar manualmente una capacidad o un spoke**, para los casos en que
  el descubrimiento automático (documento 03, sección 3, punto 4) no sea suficiente o
  el usuario quiera intervenir directamente.

## 5. Relación con los canales ya existentes

Dado que Janus ya contempla canales de mensajería y voz como vías de interacción
(`00-vision-y-alcance.md`, sección 4), una futura GUI no es la primera ni la única
superficie de control — es una superficie más, con la ventaja de poder representar
visualmente lo que un canal de texto o voz solo puede describir secuencialmente (por
ejemplo, mostrar varias tareas paralelas a la vez). Por eso este documento no define a
la GUI como un componente especial, sino como un consumidor más, sujeto a los mismos
requisitos de observabilidad y control que cualquier canal.

## 6. Documentos relacionados
- `06-modelo-de-persistencia-y-estado.md` — la fuente de los datos que este documento
  exige que sean observables.
- `05-modelo-de-roles-y-tareas.md` — el modelo de rol/tarea que la GUI futura
  necesitará poder mostrar y controlar.
- `09-preguntas-abiertas.md` — mecanismo concreto de autenticación/autorización para
  control externo, aún no decidido.
