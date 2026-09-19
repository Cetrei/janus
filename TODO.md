# TODO — Janus

Estado del proyecto: arquitectura pura (docs 00-10) + tech-stack (doc 11) + modelo de
agentes (doc 12) cerrados. Este archivo es la lista viva de lo que falta antes de
poder implementar. Se actualiza a medida que cada punto se resuelve (vía `/discuss`,
`/adr` o `/spec`).

Orden de trabajo acordado: **documentar todo → ADRs de las decisiones grandes → specs
por componente → kanban (GitHub Projects u otra app) → implementación.**

---

## 1. Discusiones de arquitectura pendientes (`/discuss`)

### 1.1 ~~Sistema agéntico completo de Janus~~ — RESUELTO
Ver `docs/12-modelo-de-agentes-de-janus.md`. Cubre: composición AgentCore/AgentPersona,
memoria de dos niveles con búsqueda semántica, skills/comandos compartidos con
delegación por especialidad, config por agente (TOML + Pydantic + hot-reload
condicional), orquestación exclusiva de Janus por ensamblado de toolset, voz con
proveedor intercambiable (Kokoro/Whisper de default), cambio dinámico de modelo vía
tool call, y concurrencia con cola FIFO por tipo de agente (Janus exento).

### 1.2 ~~Multi-avatar / multi-identidad-visible en un mismo canal~~ — RESUELTO
Ver `docs/12-modelo-de-agentes-de-janus.md`, secciones 4.3 y 4.4. Comportamiento por
defecto: Janus es la única identidad visual del canal, resume el trabajo de los
subagentes, y el usuario puede suscribirse a la sesión (por tarea) de un subagente
puntual para hablarle directo. Identidad visual del subagente en modo avanzado
configurable por agente (`channel_identity: "own_bot" | "shared_with_prefix"`).
Verificado técnicamente contra OpenClaw: soportado vía multi-token (con bugs
conocidos) o webhooks (aún no maduro).

### 1.3 ~~Motor de reglas para políticas de fallo extensibles~~ — RESUELTO
Ver `docs/11-tech-stack.md` sección 12. Alcance de v1: catálogo rico predefinido de
políticas (on-failure, exponential-backoff, circuit-breaker) declaradas por nombre en
`config/janus.toml`, sin motor de reglas custom todavía. Diseño interno con ABC
`FailurePolicy` para que agregar políticas custom en el futuro no requiera
reestructurar `libs/capabilities/`.

### 1.4 Descubrimiento y arbitraje — flecos menores
- Confirmar el nombre final del archivo de config (se usó `config/janus.toml` como
  supuesto de trabajo, nunca confirmado explícitamente).
- Licencia del propio código de Janus (abierto o privado).

### 1.5 Nuevos flecos abiertos por el doc 12
- Un archivo de config por agente vs una sección por agente en un único archivo TOML.
- Catálogo inicial concreto de categorías de memoria (qué categorías existen desde el
  día uno: preferencias, proyectos, setup técnico, ¿alguna más?).
- Alternativa al MCP de filesystem para escritura de config, si se decide evaluar una
  superior (quedó explícitamente abierto, sin alternativa concreta evaluada).

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
      evaluadas de doc 11 sección "dilema" y por qué se descartaron A y B)
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
- [ ] **ADR — Composición AgentCore/AgentPersona, no herencia** (doc 12, sección 1.1)
- [ ] **ADR — Orquestación exclusiva de Janus por ensamblado de toolset**, no por
      permisos en runtime (doc 12, sección 4.1) — vale la pena documentar bien el
      razonamiento de seguridad detrás de esto.
- [ ] **ADR — Memoria por categorías con búsqueda semántica vía `sqlite-vec`**, en vez
      de una base vectorial dedicada aparte (doc 12, sección 2.3)
- [ ] **ADR — Kokoro + Whisper/faster-whisper como defaults de voz**, con
      intercambiabilidad por agente (doc 12, sección 5)
- [ ] **ADR — Concurrencia: tope solo por número de agentes (no por recursos), cola
      FIFO por carriles de tipo, Janus exento** (doc 12, sección 7)

---

## 3. Specs de implementación pendientes (`/spec`)

Se generan después de cerrar los puntos 1 y 2. Orden sugerido (de más fundacional a
más periférico):

1. `libs/adapters/` — contratos ABC (`SpokeAdapter` y variantes)
2. `libs/config/` — esquema Pydantic + parser TOML, incluyendo schemas de
   `AgentCore`/`AgentPersona` con marca `requires_restart` por campo
3. `libs/persistence/` — acceso SQLite vía `aiosqlite`, runner de migraciones, esquema
   de memoria de dos niveles
4. `libs/memory/` — categorización y búsqueda semántica sobre `sqlite-vec`
5. `proto/` + generación `buf` → `libs/proto-py/`
6. `apps/core-gateway/` — Core de Traducción + Registro de Capacidades (orquestador
   central)
7. `libs/auth/` — tokens scopeados
8. `libs/observability/` — logging estructurado + ring buffer + Redis pub/sub
9. `libs/reasoning-engine/` — extracción y refactor del motor de Hermes, incluyendo
   ensamblado de toolset por agente
10. `libs/capabilities/` — Registro de Capacidades extendido: delegación por
    especialidad, cola/concurrencia por tipo de agente, cambio dinámico de proveedor
11. `packages/channel-gateway-core/` + `apps/channel-gateway/` — fork de OpenClaw
    (incluye resolver 1.2, multi-avatar)
12. `crates/gui-automation/` — automatización de GUI en Rust + binding PyO3

---

## 4. Después de las specs

- [ ] Crear kanban (GitHub Projects u otra herramienta) a partir de las specs ya
      escritas — cada spec se descompone en tareas concretas del kanban, no al revés.
- [ ] Empezar implementación.

---

## Próximo paso inmediato

Quedan tres discusiones menores abiertas (1.2, 1.3, 1.4/1.5) antes de pasar a ADRs.
Ninguna es tan grande como la 1.1 ya resuelta — se pueden resolver en una sola sesión
de `/discuss` combinada, o arrancar directo con `/adr` de las decisiones ya firmes y
volver a estas cuando surjan naturalmente durante los `/spec`.
