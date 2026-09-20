# AGENT.md: Janus

Índice para que una sesión nueva continúe sin releer todo. Mantener al día cuando se tomen decisiones importantes.

## Qué es
Sistema operativo personal de agentes (estrella pura: ningún spoke habla con otro, todo pasa por Janus). Uso personal, un solo host (PC o Raspberry Pi). Licencia MIT, copyright Joanfer.

## Estado (2026-09-20)
Documentación y arquitectura completas y cerradas, sin ninguna decisión pendiente. **15 specs de implementación escritas** en `docs/specs/` (índice y tabla de decisiones en `docs/specs/README.md`). No hay código todavía. Ver `TODO.md` para lo único que falta antes y durante la implementación (verificaciones de licencia, spikes de fase 0, y armar el kanban).

## Mapa
* `TODO.md`: lo que falta antes y durante la implementación (estado de las specs y trabajo previo).
* `docs/README.md`: índice de la documentación.
* `docs/architecture/`: arquitectura pura, fuente de verdad. `09-preguntas-abiertas.md` documenta el historial de decisiones (todas RESUELTAS).
* `docs/stack/`: decisiones de implementación (lenguajes, monorepo, persistencia, proto, harnesses, config, seguridad).
* `docs/agents/`: modelo de agentes (memoria, skills, orquestación, voz, concurrencia).
* `docs/specs/`: una spec por componente. Índice, orden y tabla de decisiones propuestas en `docs/specs/README.md`.
* `docs/_deprecated/`: material archivado (ADRs retirados por decisión del usuario). No se usa.
* `CODING_STANDARDS.md`: estándares de código para contribuidores, en inglés. Nombres con la convención nativa de cada lenguaje (`snake_case` en Python y Rust, `camelCase` en TypeScript).

## Decisiones vigentes clave
* Núcleo: un solo proceso Python asyncio (`apps/core-gateway`). Harnesses base: Hermes extraído a `libs/reasoning-engine`, OpenClaw forkeado en `packages/channel-gateway-core`.
* Contratos: ABC en Python, modelo semántico en protobuf con `buf`, código generado commiteado (`janus_proto.v1`, spec 01).
* Persistencia: SQLite sin ORM (`aiosqlite`), migraciones `.sql`, `sqlite-vec` para memoria. Redis solo para lo efímero. Modelo de embeddings default `intfloat/multilingual-e5-large` (Pi: `multilingual-e5-small`).
* MVC evaluado y descartado: el proyecto es una arquitectura por capas con puertos.
* Monorepo con un workspace por ecosistema (`uv`, Cargo, bun), cada uno con su lockfile en la raíz, y prefijo `janus` en todos los paquetes (`janus_*`, `janus-*`, `@janus/*`). Detalle en `docs/stack/02-monorepo.md` secciones 3 y 4.
* Concurrencia interna de Janus: un `AgentRuntime` por `SESSION_KIND_JANUS_MAIN`, aviso selectivo a Janus vía `task_finalize` (regla en código, no juicio de Janus) para no gastar tokens de más, checklist de subtareas en tiempo real sin costo de turno, comunicación entre subagentes siempre mediada por Janus (`request_delegation`). Detalle completo: `docs/specs/spec-11-core-gateway.md`, requisitos 22 y 22bis.
* Aprobación (`ApprovalGateway`): cuatro valores (`ask_everytime`, `ask_once_per_session`, `allow_always`, `deny_always`), reusados también para GUI automation por tipo de acción (spec 12, requisito 22bis).

## Bloqueos y fases 0
* Spec 08: verificar la licencia de `ssoj13/filesystem-mcp-rs` antes de forkear.
* Specs 10, 12 y 14 empiezan con auditoría o spike; no escribir código antes de aprobar su resultado.
* Spec 13: medir Kokoro en el Raspberry Pi (`bench`) antes de comprometer la voz local.
