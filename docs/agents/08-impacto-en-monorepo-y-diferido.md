# Agentes — Impacto en el monorepo y diferido

## 1. Resumen de nuevas piezas de código respecto a `stack/`

`agents/` no introduce nuevas piezas de primer nivel en el monorepo más allá del fork
de filesystem ya incorporado a `stack/02-monorepo.md` — se apoya en la estructura ya
fijada ahí, extendiendo responsabilidades:

- `libs/reasoning-engine/` — gana la responsabilidad de ensamblado de toolset por
  agente (`agents/04-orquestacion-y-sesiones.md`, sección 2), la composición
  `AgentCore`/`AgentPersona` (`agents/01-modelo-de-agente.md`, sección 2), la gestión
  de sesiones multi-participante por tarea con suscripción/desuscripción dinámica
  (`agents/04-orquestacion-y-sesiones.md`, sección 3), y el mecanismo de indexación
  híbrida (BM25 + vectorial, extraído de Hermes: `qmd`, Semantic Codebase Search,
  Hybrid Tool Pre-Selection) para identidad de agente y proyectos del usuario
  (`agents/02-memoria.md`, sección 5).
- `libs/capabilities/` — gana la lógica de cola/concurrencia por tipo de agente
  (`agents/07-concurrencia.md`) y la resolución de cambio dinámico de proveedor de
  modelo (`agents/06-cambio-dinamico-de-modelo.md`).
- `libs/persistence/` — gana el esquema de memoria de dos niveles
  (`agents/02-memoria.md`, sección 2).
- `libs/voice/` (nueva, ver `specs/spec-13-voice.md`) — TTS y STT propios; no estaba
  asignada a ninguna pieza del layout de `stack/02`.
- `libs/memory/` (nueva) — lógica de categorización auto-extensible
  (`agents/02-memoria.md`, sección 2.1, catálogo `profile` como semilla) y búsqueda
  semántica sobre `sqlite-vec` (`agents/02-memoria.md`, secciones 3 y 4).
- `libs/config/` — gana los schemas Pydantic de `AgentCore`/`AgentPersona` con la
  marca `requires_restart` por campo (`agents/03-skills-y-config.md`, sección 4), y el
  schema de la topología de carpetas obligatoria por agente
  (`agents/03-skills-y-config.md`, sección 2.1).
- `crates/filesystem-mcp/` (`stack/02-monorepo.md`) — usado por todo agente vía
  `agent.toml`/escritura de config (`agents/03-skills-y-config.md`, sección 2), sin
  indexación propia — esa responsabilidad vive en `libs/reasoning-engine/`
  (`agents/02-memoria.md`, sección 5).
- `config/` — cada agente es un folder con su propia topología obligatoria
  (`agents/03-skills-y-config.md`, sección 2.1: `agent.toml` + `agent.md` + `Skills/`/
  `Instructions/`/`Rules/`/`Tools/`) en vez de un archivo único o una sección dentro de
  `config/janus.toml` — **decisión de ubicación exacta de esos folders dentro del
  monorepo (p. ej. `config/agents/` vs otra raíz) diferida a `/spec`**.

No se introduce ninguna dependencia nueva de lenguaje o runtime respecto a `stack/`:
todo lo aquí definido es Python (más el fork en Rust de filesystem ya incorporado a
`stack/02-monorepo.md`), dentro de la estructura ya establecida.

## 2. Explícitamente diferido (no decidido en `agents/`)

1. **Ubicación exacta de los folders de agente dentro del monorepo** (p. ej.
   `config/agents/<nombre>/` vs otra raíz) — la topología interna de cada folder
   (`agents/03-skills-y-config.md`, sección 2.1) está fijada y es obligatoria; dónde
   vive esa colección de folders se resuelve en `/spec`.
2. **Definición exacta del catálogo INICIAL de categorías de memoria más allá de
   `profile`** (`agents/02-memoria.md`, sección 2.1) — el mecanismo es auto-extensible
   por diseño; no hace falta catálogo cerrado, pero si en `/spec` conviene sembrar
   alguna categoría adicional de fábrica además de `profile`, se decide ahí.
3. **Esquema exacto de la tabla de solicitudes en cola**
   (`agents/07-concurrencia.md`, sección 2) — el modelo conceptual (cola general +
   carriles por tipo + FIFO) está fijado; el esquema de persistencia/estructura de
   datos concreto se resuelve en `/spec`.
4. **Esquema exacto de persistencia de sesiones multi-participante**
   (`agents/04-orquestacion-y-sesiones.md`, sección 3) — el modelo conceptual (sesión
   por tarea, suscripción dinámica, cierre por conteo de oyentes externos) está fijado;
   la estructura de datos concreta (tabla de sesiones, tabla de suscripciones) se
   resuelve en `/spec`.

Los cuatro puntos anteriores tienen propuesta concreta en `specs/` (specs 02, 03 y 07),
pendiente de confirmar.

Los puntos de motor de reglas de políticas de fallo, y de alternativa al MCP de
filesystem oficial, que figuraban aquí como diferidos, quedaron resueltos: ver
`stack/09-politicas-de-fallo.md` y `agents/03-skills-y-config.md`, sección 2
(`crates/filesystem-mcp/`), respectivamente.

---

## Documentos relacionados
- `stack/02-monorepo.md` — el layout del monorepo cuyas piezas ganan las
  responsabilidades de la sección 1.
- `agents/01-modelo-de-agente.md` a `agents/07-concurrencia.md` — el detalle de cada
  responsabilidad nueva.
- `TODO.md` — el modelo de agentes resuelve el punto 1.1; los puntos 1.2 (multi-avatar,
  `agents/04-orquestacion-y-sesiones.md`, secciones 3 y 4) y 1.3 (motor de reglas de
  políticas de fallo, `stack/09-politicas-de-fallo.md`) también figuran ya como
  resueltos, y los cuatro puntos de la sección 2 de este documento coinciden con el
  punto 1.6 de `TODO.md`.
