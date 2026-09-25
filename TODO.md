# TODO — Janus

El kanban ya existe: GitHub Issues del repo, un épico por spec (20 specs, 20 épicos), cada uno con sus sub-issues. No hay TODO propio que mantener acá — este archivo es solo un puntero para no buscar a ciegas.

## Dónde está el trabajo

- Épicos: label `epico`, uno por spec (`spec:01-...` a `spec:20-...`).
- Prioridad: labels `prioridad:P1` / `P2` / etc.
- Empezar por: sub-issues sin dependencias marcadas como bloqueantes dentro de cada épico (ver el cuerpo de cada sub-issue, sección "Depende de").

## Próximo paso concreto

Arrancar implementación por spec 01 (`proto/`) y spec 16 (`libs/platform/`, prerrequisito de otras). En paralelo pueden ir specs 2, 3, 6, 8, 12, 13.

Ver `AGENT.md` para el estado general y `docs/specs/README.md` para el índice de specs con dependencias.
