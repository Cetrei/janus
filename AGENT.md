# AGENT.md: Janus

Índice para que una sesión nueva continúe sin releer todo. Mantener al día cuando se tomen decisiones importantes.

## Qué es
Sistema operativo personal de agentes (estrella pura: ningún spoke habla con otro, todo pasa por Janus). Uso personal, un solo host (PC o Raspberry Pi). Licencia MIT, copyright Joanfer.

## Estado (2026-09-25)
Documentación y arquitectura completas y cerradas, sin ninguna decisión pendiente. **20 specs de implementación escritas** en `docs/specs/` (índice, orden y dependencias en `docs/specs/README.md`). Kanban armado en GitHub Issues: 20 épicos (uno por spec, label `epico` + `spec:NN-...`), cada uno con sus sub-issues ya desglosadas y vinculadas. No hay código todavía. Ver `TODO.md` para el puntero al próximo paso.

**Feature nueva fuera del índice de specs (2026-09-24):** `libs/presence/` (identificación ambiental 1:N, "quién entró a la casa") entró en diseño. Vive con su propia spec completa en `libs/presence/SPEC.md`, no en `docs/specs/`, porque es autocontenida y no modifica ninguna spec existente. Depende de `libs/biometrics` (spec-18, sin cambios, solo gana un consumidor externo) para detección+embedding de cara, y de `libs/presence/vendor/hnsw/` (índice HNSW en C puro, sin librerías, doble propósito académico y de producción) — código vendorizado directamente dentro de Janus, sin repo separado ni git submodule (decisión del usuario para no mantener un fork aparte), spec propia en `libs/presence/vendor/hnsw/SPEC.md`. Ese directorio usa camelCase para nombres de función/variable/archivo, excepción explícita frente al resto del monorepo (`CODING_STANDARDS.md` no cubre C). No depende de Janus ni de `libs/persistence`/`libs/adapters`/`libs/capabilities`: `presence` es un spoke propio. Detalle completo, decisiones y open questions en `libs/presence/SPEC.md`.

**Bug corregido en `libs/presence/vendor/hnsw/` (2026-09-25):** `searchMatchesBruteForceMostly` fallaba (grafo fragmentado en ~11 componentes desconexas). Causa raíz: al bajar de capa durante la inserción, el punto de entrada se recalculaba con descenso greedy de 1 vecino en vez de reusar el mejor candidato ya hallado por la búsqueda amplia (`efConstruction`), quedando atrapado en óptimos locales. Causa secundaria: poda de vecinos (`hnswReplaceFarthestNeighbor`) comparaba 1 a 1 contra el peor en vez de reconsiderar el conjunto completo. Ambas corregidas en `src/hnswIndex.c`. `make test` en verde. Pendiente a futuro (no bloqueante): heurística de diversidad de vecinos, por si aparece degradación de recall con datasets más grandes.

## Mapa
* `TODO.md`: puntero al kanban (GitHub Issues) y próximo paso concreto.
* `docs/README.md`: índice de la documentación.
* `docs/architecture/`: arquitectura pura, fuente de verdad.
* `docs/stack/`: decisiones de implementación (lenguajes, monorepo, persistencia, proto, harnesses, config, seguridad).
* `docs/agents/`: modelo de agentes (memoria, skills, orquestación, voz, concurrencia).
* `docs/specs/`: una spec por componente. Índice, orden y tabla de decisiones en `docs/specs/README.md`.
* `docs/_deprecated/`: material archivado. No se usa.
* `CODING_STANDARDS.md`: estándares de código para contribuidores.
