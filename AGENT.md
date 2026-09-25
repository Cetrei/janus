# AGENT.md: Janus

Índice para que una sesión nueva continúe sin releer todo. Mantener al día cuando se tomen decisiones importantes.

## Qué es
Sistema operativo personal de agentes (estrella pura: ningún spoke habla con otro, todo pasa por Janus). Uso personal, un solo host (PC o Raspberry Pi). Licencia MIT, copyright Joanfer.

## Estado (2026-09-25)
Documentación y arquitectura completas y cerradas, sin ninguna decisión pendiente. **20 specs de implementación escritas** en `docs/specs/` (índice, orden y dependencias en `docs/specs/README.md`). Kanban armado en GitHub Issues: 20 épicos (uno por spec, label `epico` + `spec:NN-...`), cada uno con sus sub-issues ya desglosadas y vinculadas. No hay código todavía. Ver `TODO.md` para el puntero al próximo paso.

## Mapa
* `TODO.md`: puntero al kanban (GitHub Issues) y próximo paso concreto.
* `docs/README.md`: índice de la documentación.
* `docs/architecture/`: arquitectura pura, fuente de verdad.
* `docs/stack/`: decisiones de implementación (lenguajes, monorepo, persistencia, proto, harnesses, config, seguridad).
* `docs/agents/`: modelo de agentes (memoria, skills, orquestación, voz, concurrencia).
* `docs/specs/`: una spec por componente. Índice, orden y tabla de decisiones en `docs/specs/README.md`.
* `docs/_deprecated/`: material archivado. No se usa.
* `CODING_STANDARDS.md`: estándares de código para contribuidores.
