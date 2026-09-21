# AGENT.md: Janus

Índice para que una sesión nueva continúe sin releer todo. Mantener al día cuando se tomen decisiones importantes.

## Qué es
Sistema operativo personal de agentes (estrella pura: ningún spoke habla con otro, todo pasa por Janus). Uso personal, un solo host (PC o Raspberry Pi). Licencia MIT, copyright Joanfer.

## Estado (2026-09-20)
Documentación y arquitectura completas y cerradas, sin ninguna decisión pendiente. **18 specs de implementación escritas** en `docs/specs/` (índice, orden, dependencias y tabla de decisiones en `docs/specs/README.md`). No hay código todavía. Ver `TODO.md` para lo que sigue.

## Mapa
* `TODO.md`: kanban y lo que sigue después de armarlo.
* `docs/README.md`: índice de la documentación.
* `docs/architecture/`: arquitectura pura, fuente de verdad. `09-preguntas-abiertas.md` documenta el historial de decisiones (todas RESUELTAS).
* `docs/stack/`: decisiones de implementación (lenguajes, monorepo, persistencia, proto, harnesses, config, seguridad).
* `docs/agents/`: modelo de agentes (memoria, skills, orquestación, voz, concurrencia).
* `docs/specs/`: una spec por componente. Índice, orden y tabla de decisiones en `docs/specs/README.md`.
* `docs/_deprecated/`: material archivado (ADRs retirados por decisión del usuario). No se usa.
* `CODING_STANDARDS.md`: estándares de código para contribuidores, en inglés. Nombres con la convención nativa de cada lenguaje (`snake_case` en Python y Rust, `camelCase` en TypeScript).
