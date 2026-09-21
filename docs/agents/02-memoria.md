# Agentes — Memoria

Dos niveles, por categorías, recuperada por tool.

## 1. Motivación y patrón de referencia

El objetivo explícito es que el esfuerzo de recordar recaiga en la infraestructura, no
en el modelo: el agente no necesita razonar sobre "qué debería recordar" — sabe qué
categorías de memoria existen y usa una tool dedicada para ir a buscar lo relevante al
turno actual. El resultado buscado es equivalente, en experiencia, a cómo Claude
maneja sus propios recuerdos (memoria por categorías, recuperada bajo demanda) — no se
imita el mecanismo interno, se imita el resultado.

## 2. Dos niveles de memoria

- **Memoria de agente** — lo que un agente puntual recuerda de su propio trabajo (ej.
  Implementer recuerda decisiones tomadas en un proyecto específico).
- **Memoria global** — lo que Janus recuerda del usuario en general, cruzando
  agentes: preferencias de comunicación, proyectos activos, setup técnico del usuario,
  y cualquier categoría que aplique transversalmente. Es la extensión natural de la
  Persistencia Transversal ya definida en
  `architecture/06-modelo-de-persistencia-y-estado.md`.

### 2.1 Catálogo de categorías: auto-extensible, con `profile` como semilla

El catálogo de categorías de memoria **no es fijo ni definido de antemano por
Janus** — cada agente puede crear categorías nuevas según lo que necesite recordar,
en vez de estar limitado a una lista predefinida. La única categoría garantizada en
todo agente, presente de fábrica, es **`profile`**: información sobre quién es el
usuario (nombre, contexto personal relevante, lo que cualquier agente necesita saber
para tratarlo bien desde el primer turno — por ejemplo, quién es Joanfer). El resto
del catálogo emerge orgánicamente según lo que cada agente decida que vale la pena
recordar, sin taxonomía rígida impuesta por la infraestructura.

## 3. Mecanismo: búsqueda semántica dentro de SQLite

La recuperación es por similitud semántica, no por clave exacta — esto es RAG
(Retrieval-Augmented Generation) aplicado a la propia memoria del sistema. Dado que
`stack/03-persistencia.md` (sección 1) ya fijó SQLite como único motor de persistencia
(sin excepción para este caso), la búsqueda vectorial se resuelve con una extensión de
SQLite en vez de introducir una base de datos vectorial aparte:

- **`sqlite-vec`** (sucesora moderna de `sqlite-vss`, sin servidor propio, corre dentro
  del mismo archivo `.db`) — permite indexar embeddings y buscar por similitud sin
  salir del motor SQLite ya elegido, preservando el criterio de bajo consumo de
  recursos para Raspberry Pi.

Cada entrada de memoria se guarda con: categoría, contenido, embedding, nivel (agente
o global), y el agente/proyecto asociado si aplica.

El modelo de embeddings es configurable en el sistema (`memory.embedding_model`) y la
dimensión del índice vectorial se deriva del modelo. El default de fábrica se elige para el
hardware del usuario (PC con 32 GB de RAM y 6 GB de VRAM): `intfloat/multilingual-e5-large`
sobre CPU, con un perfil `intfloat/multilingual-e5-small` para hardware chico como el
Raspberry Pi. Ver `specs/spec-07-memory.md`.

## 4. Tool de memoria

El agente dispone de una tool (`recall_memory` o equivalente) que recibe una consulta
y opcionalmente una categoría, y devuelve las entradas más relevantes por similitud —
nunca se inyecta el historial completo de memoria en el prompt de cada turno. Esta
tool vive en el toolset compartido (`agents/04-orquestacion-y-sesiones.md`),
disponible para todo agente, a diferencia de la tool de orquestación que es exclusiva
de Janus.

Vive en `libs/persistence/` (extensión del módulo ya definido en
`stack/03-persistencia.md`) más una nueva pieza `libs/memory/` para la lógica de
categorización y búsqueda semántica.

### 4.1 Captura: solo explícita

Escribir un recuerdo es siempre una decisión explícita: el agente llama a la tool
`remember` cuando lo considera valioso o cuando el usuario se lo pide. Vale para Janus y
para cada subagente, sobre su propio nivel de agente o sobre el global. La
infraestructura nunca escribe recuerdos por su cuenta: no hay captura automática, ni
siquiera como opción configurable. El esfuerzo que asume la infraestructura es el de
recuperar (`recall_memory`), no el de decidir qué guardar.

## 5. Indexación de identidad de agente y de proyectos del usuario — distinta de la memoria episódica

Esta es una segunda forma de indexación, con un propósito distinto al de la memoria
episódica de las secciones 1 a 4: no es "lo que el agente aprendió/recordó con el
tiempo", es **"lo que el agente es"** — el propio cuerpo de archivos que define su
identidad (`Implementer/Skills/`, `Implementer/Instructions/`, `Implementer/Rules/`,
`Implementer/Tools/`, etc., según la topología de carpetas obligatoria fijada en
`agents/03-skills-y-config.md`, sección 2.1), siempre disponible, no algo recuperado
por similitud a un hecho aprendido sino navegado para saber qué capacidades tiene el
agente y cómo usarlas.

**Motivación — cómo un modelo con filesystem gana capacidades de harness avanzado.**
Cada agente tiene típicamente un modelo en la nube, sin acceso nativo al disco del
host. Para que ese modelo entienda rápido quién es y qué puede hacer, la forma más
eficaz no es cargar todo en RAM (desperdicia contexto, no escala si el agente tiene
muchos skills/reglas), ni navegación simple archivo por archivo (lento, y el modelo
puede confundirse — problema real observado con el filesystem MCP oficial, ver
`agents/03-skills-y-config.md`, sección 2), ni una base de datos genérica sin
estructura de búsqueda: es un **índice híbrido precomputado** (BM25 + vectorial) sobre
esos archivos, consultado con búsqueda rápida en cada turno para traer solo lo
relevante al mensaje actual.

**Reutilizado de Hermes, no construido desde cero.** Verificado que Hermes ya resuelve
esto en tres capas relacionadas, todas coherentes con el criterio de bajo consumo /
sin dependencias externas ya fijado para Janus:

- **Knowledgebase RAG (`qmd`)** — indexa directorios de documentos en un único archivo
  SQLite por directorio indexado, combinando BM25 (vía FTS5 de SQLite) + búsqueda
  vectorial + reranking. Zero-server, embeddings locales por defecto (`fastembed`, sin
  Ollama ni API key).
- **Semantic Codebase Search** — indexación de código fuente vía Tree-sitter (parsing
  real de sintaxis) + embeddings, para preguntas conceptuales sobre código.
- **Hybrid Tool Pre-Selection** — en vez de inyectar todas las tools disponibles en
  cada prompt, precomputa un índice de tools (BM25 + vectorial) y hace búsqueda
  híbrida rápida (<50ms) por turno para inyectar solo las top-K tools relevantes al
  mensaje del usuario.

Este mecanismo completo se extrae junto con el resto del motor de razonamiento
(`stack/05-harnesses-hermes-openclaw.md`, sección 1, ampliada) hacia
`libs/reasoning-engine/` — no se construye aparte en el fork de filesystem, y no se
mezcla con `sqlite-vec` de memoria episódica.

**Dos usos del mismo mecanismo, mismo código, distinto directorio objetivo:**

- **Identidad de agente (activado por defecto, no opt-in)** — indexa la carpeta de
  identidad del propio agente. Se reconstruye cuando la config del agente cambia
  (conectado al hot-reload condicional de `agents/03-skills-y-config.md`, sección 4: si
  cambian skills/reglas, se reindexa).
- **Proyectos del usuario (opt-in, por proyecto)** — cuando el usuario lo activa,
  indexa un proyecto suyo para navegación/búsqueda rápida por parte de un agente,
  usando el mismo mecanismo apuntado a esa carpeta.

El índice vive como un archivo SQLite propio por directorio indexado (coherente con el
criterio "single file, trivially portable" que Hermes ya valida), separado de
`sqlite-vec` (memoria episódica) y de la base principal de `libs/persistence/`.

---

## Documentos relacionados
- `architecture/06-modelo-de-persistencia-y-estado.md` — base conceptual de la memoria
  de dos niveles.
- `stack/03-persistencia.md` — SQLite como motor único, sobre el que corre `sqlite-vec`.
- `stack/05-harnesses-hermes-openclaw.md` — extracción del motor de razonamiento que
  incluye el mecanismo de indexación de la sección 5.
- `agents/03-skills-y-config.md` — topología de carpetas por agente y hot-reload que
  dispara la reindexación.
- `agents/08-impacto-en-monorepo-y-diferido.md` — `libs/memory/` y el catálogo inicial
  de categorías diferido a `/spec`.
