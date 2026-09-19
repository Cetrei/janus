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

Cada agente tiene un archivo de configuración legible por humano (TOML, consistente
con el resto del stack fijado en doc 11 sección 7) donde se declaran: reglas, voz,
skills habilitados, comandos habilitados, proveedor de modelo, y cualquier otro
parámetro de `AgentCore`/`AgentPersona`.

Esta config es editable por tres vías, todas igualmente válidas:
1. El usuario, directamente, editando el archivo.
2. La propia IA (cualquier agente, típicamente Janus), a través de una herramienta ya
   existente en vez de construir un mecanismo de escritura propio (no-reinvención): el
   **MCP de filesystem** (o una alternativa superior si se evalúa y se decide
   reemplazarlo), acompañado de un **skill que documenta cómo usarla correctamente**
   para este propósito específico.
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

Este documento no introduce nuevas piezas de primer nivel en el monorepo — se apoya en
la estructura ya fijada en el doc 11, extendiendo responsabilidades:

- `libs/reasoning-engine/` — gana la responsabilidad de ensamblado de toolset por
  agente (sección 4.2) y la composición `AgentCore`/`AgentPersona` (sección 1.1).
- `libs/capabilities/` — gana la lógica de cola/concurrencia por tipo de agente
  (sección 7) y la resolución de cambio dinámico de proveedor de modelo (sección 6).
- `libs/persistence/` — gana el esquema de memoria de dos niveles (sección 2.2).
- `libs/memory/` (nueva) — lógica de categorización y búsqueda semántica sobre
  `sqlite-vec` (sección 2.3-2.4).
- `libs/config/` — gana los schemas Pydantic de `AgentCore`/`AgentPersona` con la
  marca `requires_restart` por campo (sección 3.3).
- `config/` — gana un archivo de configuración por agente (además de
  `config/janus.toml`), o una sección por agente dentro del mismo archivo — **decisión
  de detalle diferida a `/spec`**.

No se introduce ninguna dependencia nueva de lenguaje o runtime respecto al doc 11:
todo lo aquí definido es Python, dentro de la estructura ya establecida.

---

## 9. Explícitamente diferido (no decidido en este documento)

1. **Un archivo de config por agente vs una sección por agente en un único archivo** —
   mencionado en la sección 8, decisión de detalle para `/spec`.
2. **Multi-avatar/multi-identidad-visible en un mismo canal** (doc 11, punto diferido
   2) — sigue sin resolverse; ahora es más relevante porque cada agente tiene
   `AgentPersona` propia, lo cual hace más deseable (aunque no obligatorio) que esa
   identidad se refleje visualmente en canales que lo soporten. Verificar contra
   `channel-gateway` (fork de OpenClaw) en su `/spec`.
3. **Motor de reglas para políticas de fallo extensibles** (doc 11, punto diferido 3)
   — sigue sin resolverse, ahora con una conexión adicional: la política de aprobación
   de cambio de proveedor (sección 6 de este documento) podría beneficiarse del mismo
   motor de reglas si se construye.
4. **Definición exacta del catálogo de categorías de memoria** (sección 2.2) — se
   estableció el mecanismo (categorías + búsqueda semántica), pero no el catálogo
   inicial concreto de categorías (p. ej. si "preferencias de comunicación" y "setup
   técnico" son categorías separadas o una sola). Diferido a `/spec` de
   `libs/memory/`.
5. **Esquema exacto de la tabla de solicitudes en cola** (sección 7.2) — el modelo
   conceptual (cola general + carriles por tipo + FIFO) está fijado; el esquema de
   persistencia/estructura de datos concreto se resuelve en `/spec`.
6. **Alternativa al MCP de filesystem, si existe una superior** (sección 3.1) — se
   dejó abierta la posibilidad de reemplazarlo por algo mejor evaluado más adelante;
   no se evaluó ninguna alternativa concreta en esta sesión.

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
