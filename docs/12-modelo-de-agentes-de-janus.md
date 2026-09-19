# 12 — Modelo de Agentes de Janus

## Estado del documento
Segundo documento de arquitectura tras el tech-stack (doc 11). A diferencia de los
docs 00-10 (arquitectura pura, sin decisiones de implementación) y a diferencia del
doc 11 (stack de infraestructura: lenguajes, monorepo, persistencia), este documento
define el **modelo de agentes**: qué es un agente de Janus, cómo se compone, cómo se
persiste, cómo se le asignan herramientas y voz, cómo se orquesta y cómo compite por
recursos de concurrencia. Es la resolución completa del punto 1.1 dejado pendiente en
`TODO.md`.

Este documento asume y extiende, sin repetirlas, las decisiones ya fijadas en:
- `05-modelo-de-roles-y-tareas.md` (Architect/Implementer/Debugger/Documenter/DevOps
  como roles de referencia).
- `06-modelo-de-persistencia-y-estado.md` (persistencia transversal).
- `11-tech-stack.md`, sección 6 (Hermes extraído como `libs/reasoning-engine/`,
  OpenClaw forkeado como `channel-gateway`, división de responsabilidades voz/canales/
  razonamiento).

---

## 1. Qué es un agente de Janus

Un agente de Janus es una **entidad especializada en cierta tarea que actúa como una
"persona aparte"**, a la que se le puede delegar trabajo y que puede operar en
paralelo con otros agentes. Los roles del doc 05 (Architect, Implementer, Debugger,
Documenter, DevOps) son ejemplos concretos de agentes; el conjunto de agentes no está
cerrado a esa lista — el usuario puede definir agentes personalizados adicionales.

**Janus mismo es un agente**, con el rol distintivo de "líder": es quien orquesta,
delega, y decide. Esto significa que el diagrama de capas del sistema es:

```
Infraestructura (Core de Traducción, Registro de Capacidades, Persistencia)
        ↓
Agentes (N configuraciones — una de ellas es "Janus", el resto son subagentes)
        ↓
Motor de razonamiento compartido (libs/reasoning-engine/, ex-Hermes)
```

La infraestructura no tiene personalidad ni identidad — es el sustrato sobre el que
corren las configuraciones de agente. "Janus-el-agente-líder" no es lo mismo que "el
Core de Traducción"; es una configuración más, con su propia voz y su propio prompt,
que además tiene un privilegio único: acceso a la tool de orquestación (sección 4).

### 1.1 Composición: Ejecución vs Cosmética (OOP, composición no herencia)

Todo agente se modela separando dos responsabilidades que nunca se mezclan:

```python
class AgentCore(ABC):
    """Ejecución: modelo, instrucciones, reglas, skills, toolset asignado."""
    model_provider: ModelProviderRef
    system_prompt: str
    rules: list[Rule]
    skills: list[SkillRef]
    toolset: list[ToolRef]        # ensamblado por Janus, ver sección 4

class AgentPersona:
    """Cosmética: voz, personalidad, tono. No es un contrato de comportamiento,
    es composición pura — no implementa AgentCore ni lo extiende."""
    voice_provider: VoiceProviderRef
    tone: str
    personality_prompt: str | None

class Agent:
    """Un agente completo: composición de ambas partes."""
    core: AgentCore
    persona: AgentPersona
    name: str
```

`AgentCore` es `ABC` porque distintos tipos de agente (razonamiento de código, agente
de voz pura, futuros tipos) pueden implementar la ejecución de forma distinta, pero
todos cumplen el mismo contrato. `AgentPersona` no necesita ese contrato — es
configuración de datos, no comportamiento polimórfico.

---

## 2. Memoria: dos niveles, por categorías, recuperada por tool

### 2.1 Motivación y patrón de referencia

El objetivo explícito es que el esfuerzo de recordar recaiga en la infraestructura, no
en el modelo: el agente no necesita razonar sobre "qué debería recordar" — sabe qué
categorías de memoria existen y usa una tool dedicada para ir a buscar lo relevante al
turno actual. El resultado buscado es equivalente, en experiencia, a cómo Claude
maneja sus propios recuerdos (memoria por categorías, recuperada bajo demanda) — no se
imita el mecanismo interno, se imita el resultado.

### 2.2 Dos niveles de memoria

- **Memoria de agente** — lo que un agente puntual recuerda de su propio trabajo (ej.
  Implementer recuerda decisiones tomadas en un proyecto específico).
- **Memoria global** — lo que Janus recuerda del usuario en general, cruzando
  agentes: preferencias de comunicación, proyectos activos, setup técnico del usuario,
  y cualquier categoría que aplique transversalmente. Es la extensión natural de la
  Persistencia Transversal ya definida en el doc 06.

### 2.2.1 Catálogo de categorías: auto-extensible, con `profile` como semilla

El catálogo de categorías de memoria **no es fijo ni definido de antemano por
Janus** — cada agente puede crear categorías nuevas según lo que necesite recordar,
en vez de estar limitado a una lista predefinida. La única categoría garantizada en
todo agente, presente de fábrica, es **`profile`**: información sobre quién es el
usuario (nombre, contexto personal relevante, lo que cualquier agente necesita saber
para tratarlo bien desde el primer turno — por ejemplo, quién es Joanfer). El resto
del catálogo emerge orgánicamente según lo que cada agente decida que vale la pena
recordar, sin taxonomía rígida impuesta por la infraestructura.

### 2.3 Mecanismo: búsqueda semántica dentro de SQLite

La recuperación es por similitud semántica, no por clave exacta — esto es RAG
(Retrieval-Augmented Generation) aplicado a la propia memoria del sistema. Dado que el
doc 11 ya fijó SQLite como único motor de persistencia (sección 4.1, sin excepción
para este caso), la búsqueda vectorial se resuelve con una extensión de SQLite en vez
de introducir una base de datos vectorial aparte:

- **`sqlite-vec`** (sucesora moderna de `sqlite-vss`, sin servidor propio, corre dentro
  del mismo archivo `.db`) — permite indexar embeddings y buscar por similitud sin
  salir del motor SQLite ya elegido, preservando el criterio de bajo consumo de
  recursos para Raspberry Pi.

Cada entrada de memoria se guarda con: categoría, contenido, embedding, nivel (agente
o global), y el agente/proyecto asociado si aplica.

### 2.4 Tool de memoria

El agente dispone de una tool (`recall_memory` o equivalente) que recibe una consulta
y opcionalmente una categoría, y devuelve las entradas más relevantes por similitud —
nunca se inyecta el historial completo de memoria en el prompt de cada turno. Esta
tool vive en el toolset compartido (sección 4), disponible para todo agente, a
diferencia de la tool de orquestación que es exclusiva de Janus.

Vive en `libs/persistence/` (extensión del módulo ya definido en doc 11) más una nueva
pieza `libs/memory/` para la lógica de categorización y búsqueda semántica.

### 2.5 Indexación de identidad de agente y de proyectos del usuario — distinta de la memoria episódica

Esta es una segunda forma de indexación, con un propósito distinto al de la memoria
episódica de las secciones 2.1-2.4: no es "lo que el agente aprendió/recordó con el
tiempo", es **"lo que el agente es"** — el propio cuerpo de archivos que define su
identidad (`Implementer/skills/`, `Implementer/instructions/`, `Implementer/rules/`,
`Implementer/tools/`, etc., según la topología de carpetas obligatoria fijada en la
sección 3.1.1), siempre disponible, no algo recuperado por similitud a un hecho
aprendido sino navegado para saber qué capacidades tiene el agente y cómo usarlas.

**Motivación — cómo un modelo con filesystem gana capacidades de harness avanzado.**
Cada agente tiene típicamente un modelo en la nube, sin acceso nativo al disco del
host. Para que ese modelo entienda rápido quién es y qué puede hacer, la forma más
eficaz no es cargar todo en RAM (desperdicia contexto, no escala si el agente tiene
muchos skills/reglas), ni navegación simple archivo por archivo (lento, y el modelo
puede confundirse — problema real observado con el filesystem MCP oficial, ver sección
3.1), ni una base de datos genérica sin estructura de búsqueda: es un **índice híbrido
precomputado** (BM25 + vectorial) sobre esos archivos, consultado con búsqueda rápida
en cada turno para traer solo lo relevante al mensaje actual.

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

Este mecanismo completo se extrae junto con el resto del motor de razonamiento (doc
11, sección 6.1, ampliada) hacia `libs/reasoning-engine/` — no se construye aparte en
el fork de filesystem, y no se mezcla con `sqlite-vec` de memoria episódica.

**Dos usos del mismo mecanismo, mismo código, distinto directorio objetivo:**

- **Identidad de agente (activado por defecto, no opt-in)** — indexa la carpeta de
  identidad del propio agente. Se reconstruye cuando la config del agente cambia
  (conectado al hot-reload condicional de la sección 3.3: si cambian skills/reglas,
  se reindexa).
- **Proyectos del usuario (opt-in, por proyecto)** — cuando el usuario lo activa,
  indexa un proyecto suyo para navegación/búsqueda rápida por parte de un agente,
  usando el mismo mecanismo apuntado a esa carpeta.

El índice vive como un archivo SQLite propio por directorio indexado (coherente con el
criterio "single file, trivially portable" que Hermes ya valida), separado de
`sqlite-vec` (memoria episódica) y de la base principal de `libs/persistence/`.

---

## 3. Skills y comandos: catálogo compartido, delegación por especialidad

Los skills y comandos son un **catálogo único, compartido entre todos los agentes** —
no hay un set de skills distinto por agente. La especialización ocurre en el momento
de la delegación: cuando Janus determina que una solicitud requiere un skill/comando
de una categoría dada (p. ej. "esto es una tarea de código"), delega la ejecución al
agente configurado para esa especialidad (p. ej. Implementer), usando el mismo
mecanismo de resolución por capacidad ya definido en el doc 04, extendido ahora a
nivel de skill/comando y no solo a nivel de "tipo de tarea" genérico.

### 3.1 Config de agente: legible, editable por humano, IA o interfaz

#### 3.1.1 Topología de carpetas obligatoria: filesystem como harness

Cada agente vive en su propia carpeta, siguiendo una topología **obligatoria**, sin
excepciones — esta estructura es lo que permite que incluso un modelo simple, con solo
acceso a filesystem, alcance capacidades de harness avanzado (el mismo principio que
agent-roles ya demuestra):

```
Implementer/
  Skills/
  Instructions/
  Rules/
  Tools/
  agent.md
  agent.toml
```

`agent.toml` es la config validada por Pydantic (ver 3.2); `agent.md` es la
descripción legible de identidad/propósito del agente; `Skills/`, `Instructions/`,
`Rules/`, `Tools/` contienen los `.md` correspondientes a cada categoría, que el
agente indexa y navega vía el mecanismo de la sección 2.5. Cada agente es un folder;
no hay excepciones a esta convención para agentes nuevos que el usuario defina.

Cada agente tiene un archivo de configuración legible por humano (TOML, consistente
con el resto del stack fijado en doc 11 sección 7) donde se declaran: reglas, voz,
skills habilitados, comandos habilitados, proveedor de modelo, y cualquier otro
parámetro de `AgentCore`/`AgentPersona`.

Esta config es editable por tres vías, todas igualmente válidas:
1. El usuario, directamente, editando el archivo.
2. La propia IA (cualquier agente, típicamente Janus), a través de una herramienta ya
   existente en vez de construir un mecanismo de escritura propio (no-reinvención):
   **`crates/filesystem-mcp/`** (fork de `filesystem-mcp-rs`, ver doc 11 sección 3 —
   elegido sobre el MCP de filesystem oficial porque este último carece de
   eliminación de archivos, tiene búsqueda de patrones limitada, y no resuelve
   indexación; el fork agrega `delete_path` recursivo, `bulk_edits` y `grep_files`
   con regex), acompañado de un **skill obligatorio que documenta cómo usarla
   correctamente** — la mitigación directa al problema observado de que un modelo
   puede confundirse con su propio sistema de edición de archivos si solo cuenta con
   las tools, sin ejemplos concretos de uso (orden típico de llamadas, cuándo usar
   `edit_file` vs `bulk_edits`, ejemplo de dry-run antes de aplicar).
3. Una interfaz futura (doc 07).

### 3.2 Validación como barrera obligatoria, sin excepción por vía de escritura

Independientemente de qué vía escribió el archivo, **ninguna config se aplica a un
agente en ejecución sin pasar antes por validación Pydantic** (ya definida como
mecanismo en doc 11, sección 7.2). El flujo es:

```
Escritura (humano | IA vía MCP filesystem | interfaz) → archivo TOML modificado
    → Janus detecta el cambio o recibe orden de recarga
    → validación Pydantic
    → si es válida: se aplica (con hot-reload o reinicio completo, ver sección 3.3)
    → si es inválida: se rechaza, el cambio NO se aplica, se informa el error a quien
      lo originó (humano o IA)
```

Esto evita que una edición mal formada —humana o generada por una IA que alucinó un
campo o un valor fuera de rango— tumbe un agente corriendo en producción.

### 3.3 Hot-reload condicional por campo

No toda modificación de config se trata igual, por riesgo de confusión/alucinación de
la IA si su propia identidad cambia a mitad de una tarea en curso:

- **Campos que requieren reinicio completo del agente** (matar la sesión de
  razonamiento en curso, reinstanciar limpio): el prompt/reglas base, el proveedor de
  modelo, el toolset asignado. Cambiar esto en caliente arriesgaría que el agente
  quede en un estado inconsistente respecto a su propia identidad a mitad de turno.
- **Campos de hot-reload simple** (se aplican sin reiniciar nada): voz, tono,
  parámetros cosméticos de `AgentPersona` en general.

Cada campo del schema de configuración de un agente se marca explícitamente con
`requires_restart: true` o `requires_restart: false` — esta marca es parte del
contrato del schema, no una inferencia en runtime.

---

## 4. Orquestación: tool exclusiva de Janus, por ensamblado de toolset

### 4.1 El mecanismo de exclusividad

Toda capacidad de un agente —incluida la de delegar trabajo a otro agente— se modela
como una **tool**, de forma independiente del modelo subyacente (mismo patrón de
function-calling ya heredado del motor de razonamiento extraído, doc 11 sección 6.1).
La tool de orquestación (`delegate_to_agent` o equivalente) existe en el sistema, pero
**el Core de Traducción es responsable de ensamblar el toolset de cada agente antes de
instanciarlo**, y esa tool se incluye únicamente en el toolset de Janus.

Un subagente (Implementer, Debugger, cualquier otro) **no tiene la tool de
orquestación en su lista de herramientas disponibles** — no es un permiso que se le
niegue en runtime ante un intento de uso, es una capacidad que directamente no existe
en su espacio de herramientas. Esto es deliberadamente más robusto que un chequeo de
permisos: elimina la superficie de ataque de que un subagente comprometido (por
ejemplo, vía prompt injection) intente invocar la tool de orquestación, porque la tool
ni siquiera está declarada en su contexto.

### 4.2 Ensamblado de toolset por agente — responsabilidad central

Esta es una responsabilidad nueva y explícita del Core de Traducción (`apps/core-
gateway/`, extendiendo lo ya definido en doc 11): antes de instanciar cualquier
`AgentCore`, se construye su toolset específico a partir de:

- El catálogo compartido de skills/comandos (sección 3), filtrado según lo habilitado
  en la config de ese agente.
- La tool de memoria (sección 2.4), disponible para todo agente.
- La tool de orquestación, incluida únicamente para Janus.
- Cualquier tool adicional específica de la especialidad del agente (p. ej. terminal/
  ejecución de código para Implementer).

Esto vive como lógica de `libs/reasoning-engine/` en coordinación con
`libs/capabilities/` (Registro de Capacidades).

### 4.3 Comunicación bidireccional entre Janus y subagentes: sesiones por tarea

Cada agente (Janus incluido) expone un canal de comunicación bidireccional
implementado como **sesión de chat**, reutilizando tal cual el mecanismo de
persistencia de sesión que ya trae el motor de razonamiento extraído
(`libs/reasoning-engine/`, ex-Hermes) — no se construye un sistema de mensajería
interno nuevo (no-reinvención).

**Modelo de sesión:**

- **Una sesión es por tarea, no por agente en general.** Un agente (p. ej. Implementer)
  puede tener múltiples sesiones simultáneas si tiene múltiples tareas activas — esto
  coincide 1:1 con los slots de concurrencia definidos en la sección 7: cada slot
  ocupado de un tipo de agente es, en la práctica, una sesión activa de ese tipo.
- **Participante por defecto: Janus.** Toda sesión entre Janus y un subagente nace con
  Janus como único participante del lado de Janus — es, en esencia, un chat 1:1
  Janus↔subagente donde Janus manda instrucciones/tareas y el subagente responde.
- **El canal externo (`channel-gateway`) por defecto solo conecta con la sesión de
  Janus.** El usuario habla con Janus; Janus resume, sintetizando hitos relevantes (no
  cada paso intermedio), lo que los subagentes están haciendo en sus propias sesiones.
  El usuario puede consultarle a Janus el estado de cualquier subagente en cualquier
  momento — es una consulta normal a Janus, vía su tool de estado/observabilidad
  (conectada al doc 07), no un mecanismo especial.
- **Modo avanzado — suscripción del usuario a una sesión puntual.** El usuario puede
  suscribirse a la sesión de una tarea específica de un subagente (no a "todo lo que
  ese agente haga en el futuro"). Suscribirse no crea una sesión nueva ni reinicia la
  existente: agrega al usuario como participante adicional de la sesión Janus↔subagente
  que ya está corriendo. Una vez suscripto, el usuario ve esa sesión en el canal
  externo (con la identidad visual que corresponda según el modo fijado — bot propio o
  prefijo compartido sobre el bot de Janus, ver sección 4.4) y **puede escribirle
  directamente al subagente**, sin pasar por Janus. Esto no le da al subagente la tool
  de orquestación (sección 4.1 no cambia) — solo habilita que el usuario participe
  directamente de una conversación que ya existía.

**Ciclo de vida de la sesión — cierre por conteo de oyentes:**

- Una sesión no se cierra mientras tenga al menos un **oyente externo** (el usuario,
  suscripto vía canal o interfaz). Janus es participante permanente de toda sesión de
  subagente, pero **no cuenta para el umbral de cierre** — si contara, ninguna sesión
  cerraría nunca, porque Janus nunca se retira de una sesión que él mismo abrió.
- El cierre ocurre cuando el conteo de oyentes externos llega a 0 — esto es adicional
  a "la tarea terminó": una tarea completada con el usuario todavía suscripto no se
  cierra hasta que el usuario se desuscriba o cierre la vista, incluso si el subagente
  ya entregó el resultado.
- **Multiplicidad total, en ambos lados:** Janus puede tener N sesiones abiertas
  simultáneamente (una por subagente/tarea activa); el usuario también puede tener N
  suscripciones activas a la vez, accesibles tanto vía interfaz futura (doc 07) como
  vía cualquier canal externo conectado (`channel-gateway`).

Esto agrega una responsabilidad concreta, nueva respecto al doc 11, a
`libs/reasoning-engine/` (o a una pieza dedicada, a decidir en `/spec`): **gestión de
sesiones multi-participante con suscripción/desuscripción dinámica** — extensión sobre
la sesión persistente simple que el motor extraído ya resuelve de fábrica.

### 4.4 Identidad visual en canal: Janus por defecto, multi-bot opcional

Verificado técnicamente contra la documentación de OpenClaw (base de `channel-
gateway`): **es posible** que cada agente tenga identidad visual propia (nombre y
avatar distintos) en un mismo servidor/grupo, vía dos mecanismos:

1. **Un bot por agente (multi-token)** — cada agente registra su propia aplicación de
   bot (Discord, Telegram, etc.), con su propio token, nombre y avatar reales. Es el
   camino documentado y usado en producción por terceros, pero implica **trabajo
   manual externo por cada agente** (registrar la aplicación en la plataforma
   correspondiente) y tiene bugs activos conocidos y reportados en el proyecto base
   (confusión de identidad entre bots por enrutamiento incorrecto, filtrado que
   impide que los bots se vean entre sí) — no es una feature sin fricción.
2. **Webhooks con username/avatar por mensaje** — un único bot, identidad custom por
   mensaje vía webhook. Más liviano (no requiere N aplicaciones registradas), pero es
   una capacidad en desarrollo sobre el proyecto base, no un camino maduro todavía.

**Decisión de diseño:** el comportamiento por defecto es el descrito en 4.3 — Janus es
la única identidad visual presente en el canal; los subagentes nunca postean mensajes
propios sin que el usuario se haya suscripto explícitamente a su sesión. Cuando el
usuario se suscribe (modo avanzado), la identidad visual del subagente en ese canal se
rige por un campo de configuración en `AgentPersona`:

```
channel_identity: "own_bot" | "shared_with_prefix"
```

- `"own_bot"` — el agente tiene su propio bot registrado (mecanismo 1), asumiendo el
  usuario el costo de registro y los matices de estabilidad conocidos arriba.
- `"shared_with_prefix"` — el agente escribe sobre el bot de Janus, distinguido por un
  prefijo de texto (p. ej. `[Implementer]: ...`), sin necesidad de registro adicional.
  Este es razonable como default del modo avanzado, dado el menor costo operativo.

---

## 5. Voz: proveedor intercambiable por agente, con defaults propios

### 5.1 Defaults de fábrica

Janus trae, de fábrica, proveedores propios de síntesis (TTS) y reconocimiento (STT)
de voz, elegidos por ser gratuitos, ligeros, y viables en el hardware objetivo
(Raspberry Pi incluido, ver doc 11 sección 1):

- **TTS por defecto: Kokoro** (82M parámetros, licencia Apache-2.0). Corre en CPU sin
  necesidad de GPU, consenso claro en benchmarks 2026 como la opción "gratuita y
  ligera" de referencia. Limitación conocida: fuerte en inglés, expresividad/control
  de emoción más limitado que alternativas de mayor peso.
- **STT por defecto: Whisper** (o su variante liviana `faster-whisper`, ya usada en el
  propio ecosistema de Hermes según lo verificado en la discusión de tech-stack).

### 5.2 Intercambiabilidad por agente — mismo patrón que routing de modelo

El proveedor de TTS/STT **no está fijo a nivel de sistema** — es un campo de
`AgentPersona`, configurable por agente individual, con el mismo patrón de
intercambiabilidad ya definido para el routing de modelos de razonamiento (doc 11,
sección 6.3). Un agente puntual puede usar un proveedor distinto al default si el caso
lo amerita (ejemplo discutido: ElevenLabs o Fish Speech para un agente que necesite
mayor expresividad emocional, si hay GPU disponible y se acepta el costo/peso
correspondiente).

Este campo (`voice_provider` en `AgentPersona`) es de hot-reload simple (sección 3.3):
cambiar la voz de un agente no compromete su identidad de ejecución ni requiere
reiniciar su sesión de razonamiento.

---

## 6. Cambio dinámico de proveedor de modelo: sugerido vía tool call, con aprobación configurable

El cambio de proveedor de modelo de un agente es **tanto declarativo como dinámico**:

- **Declarativo**: el usuario configura, en la config del agente, qué proveedor de
  modelo usa por defecto.
- **Dinámico**: Janus decide sugerir un cambio según capacidad, costo y disponibilidad
  observados en tiempo real — por ejemplo, si el Registro de Capacidades detecta que
  el proveedor actual de Implementer no está respondiendo (timeout, error repetido),
  genera una sugerencia de cambio a otro proveedor disponible.

Este mecanismo se modela igual que cualquier otra acción del sistema: **como una tool
call** (`suggest_provider_change` o equivalente), sujeta a una política de aprobación
configurable por el usuario, con el mismo vocabulario ya usado en herramientas de
permisos conocidas: `ask_everytime`, `allow_always`, y variantes intermedias. Esta
política se declara en `config/janus.toml`, con posibilidad de override por agente.

Vive en `libs/capabilities/` (Registro de Capacidades), como una extensión de su
responsabilidad de resolución/selección ya definida en el doc 04 y acotada en el doc
11 sección 9.

---

## 7. Concurrencia: tope configurable por tipo de agente, cola FIFO por carriles, Janus exento

### 7.1 Por qué no hay tope de recursos (RAM/VRAM)

Se evaluó explícitamente y se descartó: si un agente usa un modelo local (vía Ollama u
otro runtime local), la gestión de recursos de ese modelo (VRAM, RAM) ya es
responsabilidad de ese runtime — Janus no necesita duplicar esa gestión. El único tope
que Janus impone es de **cantidad de agentes concurrentes**, no de recursos de
hardware.

### 7.2 Modelo de cola: general con carriles por tipo, no una cola global compartida

- **Cola general**: un registro único de todas las solicitudes pendientes, en orden de
  llegada, con metadata de qué tipo de agente requiere cada una. Sirve como vista
  unificada del estado del sistema (útil también para la superficie de observabilidad
  del doc 07).
- **Tope configurable por tipo de agente**: cada tipo (Implementer, Debugger, etc.)
  tiene su propio máximo de instancias concurrentes, declarado en
  `config/janus.toml`:

```toml
[agents.implementer]
max_concurrent = 2

[agents.debugger]
max_concurrent = 1
```

- **Cola de espera por carril**: cuando el tope de un tipo se alcanza, las solicitudes
  de ese tipo específico esperan en orden FIFO (First In, First Out — la más antigua
  se atiende primero; ninguna solicitud se descarta ni sobreescribe, a diferencia de
  un ring buffer) a que un slot de ese mismo tipo se libere. Un tipo saturado nunca
  bloquea ni es bloqueado por la cola de otro tipo — si Implementer está lleno pero
  Debugger tiene cupo, una solicitud de Debugger se atiende de inmediato.

### 7.3 Janus-líder: exento de todo tope, nunca en cola, nunca expulsado

Janus, como agente líder, **no cuenta contra ningún tope de concurrencia y nunca
espera en la cola de espera**. Esto es una decisión explícita y sin excepciones: dado
que Janus es quien gestiona la cola, decide delegaciones, y es el punto de contacto
directo con el usuario, si Janus mismo pudiera quedar bloqueado esperando turno, el
sistema entero se trabaría sin que nadie pudiera ni siquiera informarle al usuario que
está saturado. Janus corre siempre, sin importar cuántos subagentes estén activos o en
espera.

Esta lógica de cola vive en `libs/capabilities/` (Registro de Capacidades), en
coordinación con `apps/core-gateway/` para el despacho efectivo de instancias de
`AgentCore`.

---

## 8. Resumen de nuevas piezas de código respecto al doc 11

Este documento no introduce nuevas piezas de primer nivel en el monorepo más allá del
fork de filesystem ya incorporado al doc 11 — se apoya en la estructura ya fijada ahí,
extendiendo responsabilidades:

- `libs/reasoning-engine/` — gana la responsabilidad de ensamblado de toolset por
  agente (sección 4.2), la composición `AgentCore`/`AgentPersona` (sección 1.1), la
  gestión de sesiones multi-participante por tarea con suscripción/desuscripción
  dinámica (sección 4.3), y el mecanismo de indexación híbrida (BM25 + vectorial,
  extraído de Hermes: `qmd`, Semantic Codebase Search, Hybrid Tool Pre-Selection) para
  identidad de agente y proyectos del usuario (sección 2.5).
- `libs/capabilities/` — gana la lógica de cola/concurrencia por tipo de agente
  (sección 7) y la resolución de cambio dinámico de proveedor de modelo (sección 6).
- `libs/persistence/` — gana el esquema de memoria de dos niveles (sección 2.2).
- `libs/memory/` (nueva) — lógica de categorización auto-extensible (sección 2.2.1,
  catálogo `profile` como semilla) y búsqueda semántica sobre `sqlite-vec` (sección
  2.3-2.4).
- `libs/config/` — gana los schemas Pydantic de `AgentCore`/`AgentPersona` con la
  marca `requires_restart` por campo (sección 3.3), y el schema de la topología de
  carpetas obligatoria por agente (sección 3.1.1).
- `crates/filesystem-mcp/` (doc 11, sección 3) — usado por todo agente vía
  `agent.toml`/escritura de config (sección 3.1), sin indexación propia — esa
  responsabilidad vive en `libs/reasoning-engine/` (sección 2.5).
- `config/` — cada agente es un folder con su propia topología obligatoria (sección
  3.1.1: `agent.toml` + `agent.md` + `Skills/`/`Instructions/`/`Rules/`/`Tools/`) en
  vez de un archivo único o una sección dentro de `config/janus.toml` — **decisión de
  ubicación exacta de esos folders dentro del monorepo (p. ej. `config/agents/` vs
  otra raíz) diferida a `/spec`**.

No se introduce ninguna dependencia nueva de lenguaje o runtime respecto al doc 11:
todo lo aquí definido es Python (más el fork en Rust de filesystem ya incorporado al
doc 11), dentro de la estructura ya establecida.

---

## 9. Explícitamente diferido (no decidido en este documento)

1. **Ubicación exacta de los folders de agente dentro del monorepo** (p. ej.
   `config/agents/<nombre>/` vs otra raíz) — la topología interna de cada folder
   (sección 3.1.1) está fijada y es obligatoria; dónde vive esa colección de folders
   se resuelve en `/spec`.
2. **Definición exacta del catálogo INICIAL de categorías de memoria más allá de
   `profile`** (sección 2.2.1) — el mecanismo es auto-extensible por diseño; no hace
   falta catálogo cerrado, pero si en `/spec` conviene sembrar alguna categoría
   adicional de fábrica además de `profile`, se decide ahí.
3. **Esquema exacto de la tabla de solicitudes en cola** (sección 7.2) — el modelo
   conceptual (cola general + carriles por tipo + FIFO) está fijado; el esquema de
   persistencia/estructura de datos concreto se resuelve en `/spec`.
4. **Esquema exacto de persistencia de sesiones multi-participante** (sección 4.3) —
   el modelo conceptual (sesión por tarea, suscripción dinámica, cierre por conteo de
   oyentes externos) está fijado; la estructura de datos concreta (tabla de sesiones,
   tabla de suscripciones) se resuelve en `/spec`.

Los puntos de motor de reglas de políticas de fallo, y de alternativa al MCP de
filesystem oficial, que figuraban aquí como diferidos, quedaron resueltos: ver doc 11
sección 12 y sección 3.1 de este documento (`crates/filesystem-mcp/`),
respectivamente.

---

## 10. Documentos relacionados

- `00-vision-y-alcance.md` — visión general; este documento concreta el objetivo de
  "Jarvis personal" y "multi-agente paralelo" enumerado en su sección 4.
- `04-modelo-de-capacidades-y-enrutamiento.md` — base conceptual de la delegación por
  especialidad (sección 3) y la resolución de cambio de proveedor (sección 6).
- `05-modelo-de-roles-y-tareas.md` — los roles ahí definidos son la instancia concreta
  del concepto de "agente" definido en este documento.
- `06-modelo-de-persistencia-y-estado.md` — base conceptual de la memoria de dos
  niveles (sección 2).
- `07-superficie-para-gui-futura.md` — consumidor futuro del estado de cola/
  concurrencia (sección 7) y de la config de agentes (sección 3).
- `11-tech-stack.md` — stack de infraestructura sobre el que corre todo lo definido
  aquí; en particular sección 6 (división de responsabilidades Hermes/OpenClaw/Janus)
  y sección 7 (TOML + Pydantic).
- `TODO.md` — este documento resuelve el punto 1.1; los puntos 1.2 y 1.3 del TODO se
  mantienen abiertos y ahora tienen matices adicionales registrados en la sección 9 de
  este documento.
