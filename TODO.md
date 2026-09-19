# TODO — Janus

Estado del proyecto: arquitectura pura (`docs/architecture/`) + tech-stack
(`docs/stack/`) + modelo de agentes (`docs/agents/`) cerrados, incluyendo todos los
flecos de discusión menores. Este
archivo es la lista viva de lo que falta antes de poder implementar. Se actualiza a
medida que cada punto se resuelve (vía `/discuss`, `/adr` o `/spec`).

Orden de trabajo acordado: **documentar todo → ADRs de las decisiones grandes → specs
por componente → kanban (GitHub Projects u otra app) → implementación.**

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
  `agent.toml`). Ver `docs/agents/03-skills-y-config.md`, sección 2.1. Pendiente solo la ubicación exacta de
  esos folders dentro del monorepo (ver sección 1.6 abajo).
- Categorías de memoria: **resuelto** — catálogo auto-extensible, cada agente crea
  las que necesita; única categoría de fábrica garantizada es `profile`. Ver
  `docs/agents/02-memoria.md`, sección 2.1.
- Alternativa al MCP de filesystem: **resuelto** — fork de `filesystem-mcp-rs` en
  `crates/filesystem-mcp/`, con `delete_path` recursivo, `bulk_edits`, `grep_files`
  regex. Ver `docs/stack/02-monorepo.md` y `docs/agents/03-skills-y-config.md`, sección 2.

### 1.6 Nuevos flecos menores abiertos en esta última ronda (indexación + filesystem)
Todos son detalle de `/spec`, ninguno bloquea el paso a ADRs:
- Ubicación exacta de los folders de agente dentro del monorepo (p. ej.
  `config/agents/<nombre>/` vs otra raíz). Ver `docs/agents/08-impacto-en-monorepo-y-diferido.md`, sección 2, punto 1.
- Catálogo inicial de categorías de memoria más allá de `profile`, si conviene
  sembrar alguna de fábrica. Ver `docs/agents/08-impacto-en-monorepo-y-diferido.md`, sección 2, punto 2.
- Esquema exacto de la tabla de solicitudes en cola (`docs/agents/07-concurrencia.md`, sección 2).
- Esquema exacto de persistencia de sesiones multi-participante (`docs/agents/04-orquestacion-y-sesiones.md`, sección 3).

---

## 2. ADRs pendientes de redactar (`/adr`)

Decisiones ya tomadas en `/discuss` que necesitan quedar registradas como Architecture
Decision Record, con el porqué y las alternativas descartadas, para trazabilidad
futura:

- [ ] **ADR — Python + `abc` como lenguaje y mecanismo de contrato del núcleo**
      (vs Go, vs TypeScript/Bun)
- [ ] **ADR — Monorepo poliglota por convención de lenguaje**
      (`apps/` + `libs/`/`crates/`/`packages/`/`proto/`, sin anidar por lenguaje
      genérico)
- [ ] **ADR — Un solo proceso asyncio para el núcleo, no microservicios internos**
      (Core de Traducción + Registro + Persistencia en el mismo runtime)
- [ ] **ADR — SQLite + `aiosqlite` sin ORM, en vez de Postgres**
      (contexto: un solo host, un solo usuario, un solo escritor)
- [ ] **ADR — Migraciones como archivos `.sql` versionados con runner propio**
      (vs Alembic/yoyo-migrations)
- [ ] **ADR — Redis como capa efímera, nunca fuente de verdad**
- [ ] **ADR — Protocol Buffers + `buf` como modelo semántico único**
      (vs dataclasses a mano por lenguaje)
- [ ] **ADR — Hermes: extracción quirúrgica + refactor, no servicio externo ni fork
      completo** (la decisión más grande de esta ronda; documentar las tres opciones
      evaluadas (ver `docs/stack/05-harnesses-hermes-openclaw.md`, sección 1) y por qué se descartaron A y B)
- [ ] **ADR — OpenClaw: fork completo, no extracción quirúrgica**
      (criterio de corte opuesto al de Hermes, y por qué)
- [ ] **ADR — División de responsabilidades voz/canales/razonamiento**
      (Janus posee voz e identidad; channel-gateway solo transporta; reasoning-engine
      solo razona — ninguno de los tres se solapa)
- [ ] **ADR — TOML + Pydantic para configuración, en vez de YAML**
- [ ] **ADR — Harnesses base vs spokes externos: sin arbitraje dinámico entre
      harnesses base** (asignación fija declarada por el usuario, nunca competencia
      en runtime)
- [ ] **ADR — Sistema de tokens scopeados propio, en vez de asumir confianza por
      localhost**
- [ ] **ADR — GUI automation dividida Rust (bajo nivel) + Python (orquestación)**
- [ ] **ADR — Composición AgentCore/AgentPersona, no herencia** (`docs/agents/01-modelo-de-agente.md`, sección 2)
- [ ] **ADR — Orquestación exclusiva de Janus por ensamblado de toolset**, no por
      permisos en runtime (`docs/agents/04-orquestacion-y-sesiones.md`, sección 1) — vale la pena documentar bien el
      razonamiento de seguridad detrás de esto.
- [ ] **ADR — Memoria por categorías, auto-extensible, con búsqueda semántica vía
      `sqlite-vec`** (`docs/agents/02-memoria.md`, secciones 2.1 y 3), en vez de una base vectorial
      dedicada aparte o un catálogo cerrado de categorías.
- [ ] **ADR — Kokoro + Whisper/faster-whisper como defaults de voz**, con
      intercambiabilidad por agente (`docs/agents/05-voz.md`)
- [ ] **ADR — Concurrencia: tope solo por número de agentes (no por recursos), cola
      FIFO por carriles de tipo, Janus exento** (`docs/agents/07-concurrencia.md`)
- [ ] **ADR — Sesiones multi-participante por tarea, reutilizando el mecanismo de
      sesión de Hermes**, con suscripción/desuscripción dinámica y cierre por conteo
      de oyentes externos (Janus nunca cuenta) (`docs/agents/04-orquestacion-y-sesiones.md`, sección 3)
- [ ] **ADR — Identidad visual en canal: Janus por defecto, multi-bot opcional por
      agente** (`channel_identity: own_bot | shared_with_prefix`), con los matices de
      estabilidad conocidos del multi-token en OpenClaw (`docs/agents/04-orquestacion-y-sesiones.md`, sección 4)
- [ ] **ADR — Topología de carpetas obligatoria por agente** (`Skills/`,
      `Instructions/`, `Rules/`, `Tools/`, `agent.md`, `agent.toml`) como mecanismo de
      "filesystem como harness" (`docs/agents/03-skills-y-config.md`, sección 2.1)
- [ ] **ADR — Fork de `filesystem-mcp-rs` sobre el MCP de filesystem oficial**, por
      carecer de eliminación recursiva, búsqueda de patrones limitada, y sin
      indexación — con skill obligatorio de uso para mitigar confusión del modelo
      (`docs/stack/02-monorepo.md`; `docs/agents/03-skills-y-config.md`, sección 2)
- [ ] **ADR — Indexación híbrida (BM25 + vectorial) extraída de Hermes** (`qmd`,
      Semantic Codebase Search, Hybrid Tool Pre-Selection) para identidad de agente y
      proyectos del usuario, separada de la memoria episódica en `sqlite-vec` (`docs/agents/02-memoria.md`,
      sección 5)
- [ ] **ADR — Licencia MIT, código abierto** (`docs/stack/10-gui-automation-y-licencia.md`, sección 2)

---

## 3. Specs de implementación pendientes (`/spec`)

Se generan después de cerrar los ADRs del punto 2. Orden sugerido (de más fundacional
a más periférico):

1. `libs/adapters/` — contratos ABC (`SpokeAdapter` y variantes)
2. `libs/config/` — esquema Pydantic + parser TOML, incluyendo schemas de
   `AgentCore`/`AgentPersona` con marca `requires_restart` por campo, y el schema de
   la topología de carpetas obligatoria por agente (incluye resolver 1.6: ubicación
   exacta de los folders)
3. `libs/persistence/` — acceso SQLite vía `aiosqlite`, runner de migraciones, esquema
   de memoria de dos niveles, esquema de cola de concurrencia y de sesiones
   multi-participante (incluye resolver 1.6: esquemas de cola y sesiones)
4. `libs/memory/` — categorización auto-extensible y búsqueda semántica sobre
   `sqlite-vec` (incluye resolver 1.6: catálogo inicial de categorías si aplica)
5. `crates/filesystem-mcp/` — fork de `filesystem-mcp-rs`, skill de uso correcto
6. `proto/` + generación `buf` → `libs/proto-py/`
7. `apps/core-gateway/` — Core de Traducción + Registro de Capacidades (orquestador
   central)
8. `libs/auth/` — tokens scopeados
9. `libs/observability/` — logging estructurado + ring buffer + Redis pub/sub
10. `libs/reasoning-engine/` — extracción y refactor del motor de Hermes, incluyendo
    ensamblado de toolset por agente, gestión de sesiones multi-participante, e
    indexación híbrida (identidad de agente + proyectos del usuario)
11. `libs/capabilities/` — Registro de Capacidades extendido: delegación por
    especialidad, cola/concurrencia por tipo de agente, cambio dinámico de proveedor,
    `FailurePolicy`
12. `packages/channel-gateway-core/` + `apps/channel-gateway/` — fork de OpenClaw,
    incluyendo identidad visual multi-bot/prefijo compartido
13. `crates/gui-automation/` — automatización de GUI en Rust + binding PyO3

---

## 4. Después de las specs

- [ ] Crear kanban (GitHub Projects u otra herramienta) a partir de las specs ya
      escritas — cada spec se descompone en tareas concretas del kanban, no al revés.
- [ ] Empezar implementación.

---

## Próximo paso inmediato

Toda la arquitectura y el stack están documentados y sin flecos de discusión
pendientes (solo detalles menores diferidos a `/spec`, listados en 1.6). El próximo
paso es arrancar la sección 2: redactar los ADRs, empezando por las decisiones más
fundacionales (lenguaje del núcleo, monorepo, persistencia) antes de las más
específicas (voz, sesiones, identidad visual).
