# AGENT.md: Janus

Índice para que una sesión nueva continúe sin releer todo. Mantener al día cuando se tomen decisiones importantes.

## Qué es
Sistema operativo personal de agentes (estrella pura: ningún spoke habla con otro, todo pasa por Janus). Uso personal, un solo host (PC o Raspberry Pi). Licencia MIT, copyright Joanfer.

## Estado (2026-09-19)
Documentación completa. Arquitectura, stack y modelo de agentes cerrados. **15 specs de implementación escritas** en `docs/specs/`. Siguiente paso: que el usuario confirme las decisiones propuestas y se arme el kanban desde las specs. No hay código todavía.

## Mapa
* `TODO.md`: lista viva. Decisiones pendientes de confirmar (sección 2), estado de las specs (sección 3) y trabajo previo a implementar (sección 4).
* `docs/README.md`: índice de la documentación.
* `docs/architecture/`: arquitectura pura, fuente de verdad. Preguntas abiertas en `09-preguntas-abiertas.md`.
* `docs/stack/`: decisiones de implementación (lenguajes, monorepo, persistencia, proto, harnesses, config, seguridad).
* `docs/agents/`: modelo de agentes (memoria, skills, orquestación, voz, concurrencia).
* `docs/specs/`: una spec por componente. Índice, orden y tabla de decisiones propuestas en `docs/specs/README.md`.
* `docs/_deprecated/`: material archivado (ADRs retirados por decisión del usuario). No se usa.

## Decisiones vigentes clave
* Núcleo: un solo proceso Python asyncio (`apps/core-gateway`). Harnesses base: Hermes extraído a `libs/reasoning-engine`, OpenClaw forkeado en `packages/channel-gateway-core`.
* Contratos: ABC en Python, modelo semántico en protobuf con `buf`, código generado commiteado.
* Persistencia: SQLite sin ORM (`aiosqlite`), migraciones `.sql`, `sqlite-vec` para memoria. Redis solo para lo efímero.
* MVC evaluado y descartado: el proyecto es una arquitectura por capas con puertos.

## Preguntas abiertas que las specs no resuelven
Ninguna. Las cuatro residuales de `architecture/09` (5 OpenClaude, 9 multi-usuario, 12
GUI de fábrica, 13 Relay) se cerraron en la sesión del 2026-09-20; ver el propio
documento y TODO.md sección 2bis para el detalle. Quedan solo residuales de
implementación derivados de esas respuestas (spec de reemplazo de Relay aún sin
escribir; diseño de concurrencia interna de Janus en spec 11).

## Bloqueos y fases 0
* Spec 08: verificar la licencia de `ssoj13/filesystem-mcp-rs` antes de forkear.
* Specs 10, 12 y 14 empiezan con auditoría o spike; no escribir código antes de aprobar su resultado.
* Spec 13: medir Kokoro en el Raspberry Pi (`bench`) antes de comprometer la voz local.

## Última sesión (2026-09-20)
Se corrigió spec 09: el residual de la pregunta 1 de `architecture/09` no era un enum
cerrado (`fallback`/`block`/`ask`) sino dos piezas separadas — una `FallbackChain`
declarativa de N pasos que el usuario define, y un `FailureTriageAdvisor` que es un
juicio de Janus en runtime sobre si seguir la cadena o escalar al usuario, no una tabla
fija. Se cerraron las cuatro preguntas que quedaban abiertas en `architecture/09`:
política de seguimiento de OpenClaw (sin cadencia fija, solo ante disparador), OpenClaude
(nunca se extiende, solo consumo como spoke), multi-usuario (redefinida como
concurrencia interna de Janus por canales, no multi-tenencia), alcance de GUI de fábrica
(genérico más adaptadores adicionales a definir) y futuro de Relay (se rehace su función
desde cero como spoke propio de Janus, portable, reemplazando a `claude-toolkit`).
Quedan dos residuales de implementación nuevos: la spec del spoke que reemplaza a Relay
(sin número aún) y el diseño de concurrencia interna de Janus en spec 11.
