# TODO — Janus

Estado del proyecto: arquitectura pura (`docs/architecture/`) + tech-stack
(`docs/stack/`) + modelo de agentes (`docs/agents/`) cerrados, y las **15 specs de
implementación escritas** (`docs/specs/`, 2026-09-19). Este archivo es la lista viva de lo
que falta antes y durante la implementación. Se actualiza a medida que cada punto se
resuelve.

Orden de trabajo acordado: **documentar todo → specs por componente → kanban
(GitHub Projects u otra app) → implementación.** Las dos primeras etapas están completas
y las decisiones propuestas de la sección 2 están confirmadas.

---

## 1. Discusiones de arquitectura — TODAS RESUELTAS

### 1.1 ~~Sistema agéntico completo de Janus~~ — RESUELTO
Ver `docs/agents/`. Cubre: composición AgentCore/AgentPersona,
memoria de dos niveles con búsqueda semántica, skills/comandos compartidos con
delegación por especialidad, config por agente (TOML + Pydantic + hot-reload
condicional), orquestación exclusiva de Janus por ensamblado de toolset, voz con
proveedor intercambiable (Kokoro/Whisper de default), cambio dinámico de modelo vía
tool call, y concurrencia con cola FIFO por tipo de agente (Janus exento).

### 1.2 ~~Multi-avatar / multi-identidad-visible en un mismo canal~~ — RESUELTO
Ver `docs/agents/04-orquestacion-y-sesiones.md`, secciones 3 y 4. Comportamiento por
defecto: Janus es la única identidad visual del canal, resume el trabajo de los
subagentes, y el usuario puede suscribirse a la sesión (por tarea) de un subagente
puntual para hablarle directo. Identidad visual del subagente en modo avanzado
configurable por agente (`channel_identity: "own_bot" | "shared_with_prefix"`).
Verificado técnicamente contra OpenClaw: soportado vía multi-token (con bugs
conocidos) o webhooks (aún no maduro).

### 1.3 ~~Motor de reglas para políticas de fallo extensibles~~ — RESUELTO
Ver `docs/stack/09-politicas-de-fallo.md`. Alcance de v1: catálogo rico predefinido de
políticas (on-failure, exponential-backoff, circuit-breaker) declaradas por nombre en
`config/janus.toml`, sin motor de reglas custom todavía. Diseño interno con ABC
`FailurePolicy` para que agregar políticas custom en el futuro no requiera
reestructurar `libs/capabilities/`.

### 1.4 ~~Descubrimiento y arbitraje — flecos menores~~ — RESUELTO
- Nombre del archivo de config: **confirmado** `config/janus.toml`.
- Licencia: **confirmada** — código abierto, MIT, copyright a nombre de Joanfer. Ver
  `docs/stack/10-gui-automation-y-licencia.md`, sección 2.

### 1.5 ~~Nuevos flecos abiertos por el modelo de agentes~~ — RESUELTO
- Config por agente: **resuelto** — cada agente es un folder con topología
  obligatoria (`Skills/`, `Instructions/`, `Rules/`, `Tools/`, `agent.md`,
  `agent.toml`). Ver `docs/agents/03-skills-y-config.md`, sección 2.1.
- Categorías de memoria: **resuelto** — catálogo auto-extensible, cada agente crea
  las que necesita; única categoría de fábrica garantizada es `profile`. Ver
  `docs/agents/02-memoria.md`, sección 2.1.
- Alternativa al MCP de filesystem: **resuelto** — fork de un port en Rust del filesystem
  MCP en `crates/filesystem-mcp/` con `bulk_edits` y `grep_files` regex. Corrección
  verificada en septiembre de 2026: el upstream ya trae `delete_path` recursivo; el
  delta real se mide en la spec 08.

### 1.6 ~~Flecos menores de indexación y filesystem~~ — RESUELTOS EN LAS SPECS
Propuestas en `docs/specs/`; ubicación de agentes confirmada, el resto por confirmar (ver sección 2):
- Ubicación de los folders de agente: `config/agents/<Nombre>/` y catálogo compartido en
  `config/catalog/` (spec 02). **Confirmada.**
- Catálogo inicial de categorías de memoria: solo `profile`; el mecanismo es
  auto-extensible (spec 07).
- Esquema de la tabla de solicitudes en cola: `agent_queue` (spec 03).
- Esquema de sesiones multi-participante: `sessions` y `session_participants` (spec 03).

---

## 2. Decisiones propuestas por las specs — pendientes de confirmación

Las specs cerraron varios residuales de `docs/architecture/09-preguntas-abiertas.md`
con una propuesta concreta. Ninguna se considera cerrada hasta que el usuario la
confirme (el detalle y la tabla completa están en `docs/specs/README.md`):

- [x] Ubicación de agentes en `config/agents/` y catálogo en `config/catalog/` (spec 02).
      Confirmado.
- [x] Espacio de nombres: prefijo `janus` en todos los paquetes de todos los lenguajes
      (`janus_*` en Python, `janus-*` en Rust, `@janus/*` en TypeScript) y Python 3.11 o
      superior, que es la versión que trae `tomllib` en la stdlib (specs 02 y 04, detalle en
      `stack/02` sección 4). Confirmado.
- [x] Workspaces: uno por ecosistema, `uv` (Python), Cargo (Rust) y bun (TypeScript), cada
      uno con su lockfile en la raíz (`stack/02` sección 3). Confirmado. Bun frente al fork
      de OpenClaw queda como verificación de la fase 0 de la spec 14.
- [x] Runtimes: `uvicorn` para las superficies HTTP de Python, Bun como runtime y gestor
      de TypeScript, Cargo para Rust (`stack/02` sección 3.1). Confirmado. Bun frente al
      fork y al streaming gRPC bidireccional queda como verificación de la fase 0 de la
      spec 14. Si falla, `channel-gateway` corre con Node 22 (`engines.node`,
      `.node-version` y un `command` que lanza `node`); camino aprobado por el usuario.
- [x] Colisión del namespace `janus` con el paquete de PyPI: resuelta renombrando el
      paquete proto a `janus_proto.v1` (spec 01).
- [x] `DependencyFailurePolicy` eliminado de `task.proto` (spec 01) y de la tabla `tasks`
      (spec 03): lo reemplaza `DependencyFailureTriage` de la pregunta 10 (spec 11).
- [x] Selección entre spokes (residual de la pregunta 1, spec 09): salud, luego
      política del usuario, luego rol solo para desempatar candidatos equivalentes.
      Ante un fallo, se maneja con una `FallbackChain` declarativa que el usuario
      define por agente/capacidad (N pasos encadenados, ej. Gemini, luego Claude,
      luego OpenRouter, luego esperar), y un `FailureTriageAdvisor` que es un juicio
      de Janus en runtime (no una tabla fija) sobre si seguir la cadena o escalar al
      usuario. Confirmado.
- [x] Captura de memoria (residual de la pregunta 2, spec 07): explícita y nada más.
      Janus y sus subagentes guardan con `remember` por decisión propia o pedido del
      usuario; no existe captura automática, ni como opción. Confirmado.
- [x] Identidad de remitente en capas (residual de la pregunta 3, specs 11 y 14):
      identificador por plataforma por defecto, más un secreto compartido opcional en un
      `.md` libre. El agente recibe por instrucción inyectada que debe comprobar si el
      remitente está verificado, y lo marca con una tool. La vigencia es configurable por
      canal (`never`, `per_message`, `per_session`, `ttl`; default `per_session`, elección
      del Architect, revisable) y, cuando vence, el núcleo reinyecta la información en el
      prompt al llamar a Janus. Confirmado.
- [x] Cascada por dependencia fallida (pregunta 10, spec 11): no es un enum estático; la
      decide Janus en runtime con `DependencyFailureTriage` (`RETRY`, `CANCEL_CASCADE`,
      `ASK_USER`). Confirmado.
- [x] Detección de GUI por árbol de accesibilidad con backends intercambiables
      (residual de la pregunta 11, spec 12). Enfoque confirmado; las librerías concretas
      (`atspi`, `xcap`, `enigo`) se deciden en el spike de la fase 0 de la spec 12.
- [x] Variantes de `approval` (specs 02 y 09, `agents/06`): las cuatro (`ask_everytime`,
      `ask_once_per_session`, `allow_always`, `deny_always`). Confirmado.
- [x] Modelo de embeddings (specs 02, 03 y 07): configurable en el sistema. El usuario
      confirmó la configurabilidad y que el default debe correr en su PC (32 GB de RAM,
      6 GB de VRAM). Default elegido por el Architect bajo esa restricción y revisable:
      `intfloat/multilingual-e5-large` (1024 dimensiones, CPU); perfil Pi:
      `intfloat/multilingual-e5-small` (384). La tabla vectorial pasa a crearse por
      dimensión desde una plantilla (spec 03, requisito 20bis).
- [x] Política de seguimiento de OpenClaw: sin cadencia fija, solo ante un disparador
      concreto (CVE público o canal roto). Confirmado (spec 14, `stack/05`).

---

## 2bis. Preguntas de `architecture/09` que quedaban abiertas — RESUELTAS EN ESTA RONDA

Las cuatro preguntas de `architecture/09` que ninguna spec resolvía quedaron cerradas
(detalle completo en el propio documento):

- [x] Pregunta 5 (procedencia de OpenClaude): cerrada, nunca se extiende ese código
      base, solo consumo como spoke vía protocolo.
- [x] Pregunta 9 (multi-usuario): redefinida. No es multi-tenencia; es concurrencia
      interna de Janus para atender al mismo usuario por canales distintos a la vez
      (ej. voz desde la cocina mientras programa por texto). Queda un residual de
      diseño nuevo en `specs/spec-11-core-gateway.md` (Open Questions).
- [x] Pregunta 12 (alcance de GUI de fábrica): mecanismo genérico más un puñado de
      adaptadores adicionales de fábrica, más allá de Claude/Gemini Desktop. Lista
      concreta pendiente como tarea de producto, no bloquea arquitectura.
- [x] Pregunta 13 (futuro de Relay): Relay (`claude-toolkit`) no se adopta ni se
      migra tal cual (atado a Linux); se reescribe su función desde cero, portable y
      dinámica, como spoke propio de Janus (código en el monorepo, no spoke externo).
      Reemplaza a Relay por completo. Sin spec propia todavía; se agrega al planificar
      el kanban.

Preguntas de `architecture/09` que las specs no resuelven y siguen ABIERTAS: ninguna.
Las cuatro que quedaban (5, 9, 12, 13) se resolvieron en esta ronda; ver sección 2bis.

---

## 3. Specs de implementación — ESCRITAS

Todas en `docs/specs/` (índice, orden y dependencias en `docs/specs/README.md`).

| # | Spec | Estado |
|---|---|---|
| 1 | `proto/` + `libs/proto-py/` | Escrita |
| 2 | `libs/config/` | Escrita |
| 3 | `libs/persistence/` | Escrita |
| 4 | `libs/adapters/` (contratos) | Escrita |
| 5 | `libs/auth/` | Escrita |
| 6 | `libs/observability/` | Escrita |
| 7 | `libs/memory/` | Escrita |
| 8 | `crates/filesystem-mcp/` | Escrita, bloqueada por verificar licencia del upstream |
| 9 | `libs/capabilities/` | Escrita |
| 10 | `libs/reasoning-engine/` | Escrita, empieza con auditoría de extracción |
| 11 | `apps/core-gateway/` | Escrita |
| 12 | `crates/gui-automation/` | Escrita, empieza con spike de validación |
| 13 | `libs/voice/` (nueva, sin dueño antes) | Escrita, con compuerta de rendimiento en el Pi |
| 14 | `packages/channel-gateway-core/` + `apps/channel-gateway/` | Escrita, empieza con auditoría del fork |
| 15 | Adaptadores concretos de spoke (nueva, sin dueño antes) | Escrita |

Cambios frente al orden original: `proto/` pasó al primer lugar y se agregaron las
specs 13 y 15, que cubren piezas que ninguna spec del plan original poseía.

---

## 4. Trabajo previo a la implementación

- [ ] Confirmar o ajustar las decisiones propuestas de la sección 2 restantes (ver 2bis
      para las de `architecture/09`, ya cerradas).
- [ ] Verificar la licencia de `ssoj13/filesystem-mcp-rs` (bloqueante de la spec 08) y
      decidir base alternativa si no hay licencia compatible con MIT.
- [ ] Confirmar la licencia del commit de OpenClaw que se forkeará (el README indica
      MIT) y del de Hermes (MIT verificado en el README).
- [ ] Escribir la spec del spoke propio que reemplaza a Relay/`claude-toolkit`
      (residual de la pregunta 13 de `architecture/09`): función de Relay rehecha,
      dinámica y multiplataforma, orquestando múltiples perfiles/instancias de un
      mismo harness. No existía dueño antes de esta ronda; se agrega como spec 16 o
      se incorpora a la 15, a decidir al planificar el kanban.
- [ ] Incorporar a la spec 11 el diseño de concurrencia interna de Janus (múltiples
      `SESSION_KIND_JANUS_MAIN` en paralelo por canal, residual de la pregunta 9).
- [ ] Diferido a la implementación: medir `multilingual-e5-large` (CPU y CUDA) en la PC
      del usuario y recalibrar el umbral de deduplicación de memoria y los objetivos de
      latencia (specs 07 y 10).
- [x] `CODING_STANDARDS.md` reconciliado con las specs: convención nativa de cada
      lenguaje (`snake_case` en Python y Rust, `camelCase` en TypeScript), decidido por el
      usuario. Las specs no cambian.
- [ ] Crear kanban (GitHub Projects u otra herramienta) a partir de las specs ya
      escritas: cada spec se descompone en tareas concretas, no al revés. Las fases 0
      (auditorías y spikes de las specs 8, 10, 12 y 14) son tareas explícitas.
- [ ] Empezar implementación por la spec 1 (`proto/`); en paralelo pueden ir las specs
      2, 3, 6, 8, 12 y 13.

---

## Notas

- **MVC**: se evaluó y no se adopta. Janus es un sistema de librerías y servicios por
  capas con puertos (`Protocol`) entre ellas y contratos ABC en las fronteras, y no
  tiene una interfaz de usuario propia dentro del alcance actual. Una GUI futura
  (`architecture/07`) será un cliente más del núcleo. Si algún día se construye,
  puede usar el patrón que convenga en ese cliente sin afectar al núcleo.
- Los ADRs se retiraron del flujo por decisión del usuario y quedaron archivados en
  `docs/_deprecated/adr/`. Las decisiones vigentes viven en `architecture/`, `stack/`,
  `agents/` y `specs/`.

---

## Próximo paso inmediato

Las specs están completas y todas las decisiones de la sección 2 quedaron confirmadas.
El siguiente paso es armar el kanban desde las specs.
