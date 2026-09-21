# 05 — Modelo de Roles y Tareas

## Estado del documento
Arquitectura pura. Depende de `01-conceptos-y-vocabulario.md` (definiciones de Rol y
Tarea) y `04-modelo-de-capacidades-y-enrutamiento.md` (cómo un rol consume
capacidades).

---

## 1. Propósito de este modelo

El dominio en el que Janus debe ser más fuerte que cualquier alternativa existente es
el desarrollo de software (ver `00-vision-y-alcance.md`, sección 2). Este documento
define cómo ese dominio se representa dentro de la arquitectura general de Janus, de
forma agnóstica a qué spoke concreto ejecuta cada parte del trabajo.

Este modelo generaliza un patrón de roles ya validado por el usuario en un sistema
previo (roles fijos de Architect, Implementer, Debugger, Documenter asignados
manualmente a distintos perfiles), reformulándolo para que:
- Un rol no esté atado permanentemente a un spoke concreto.
- El sistema pueda reasignar qué spoke ejecuta un rol sin que el resto del sistema (ni
  el usuario) necesite enterarse del cambio salvo que lo pida explícitamente.
- Puedan ejecutarse varios roles en paralelo, en distintos spokes, coordinados por
  Janus.

## 2. Rol como asignación, no como identidad de spoke

Un **rol** es una función abstracta con una responsabilidad definida dentro del ciclo
de vida de desarrollo de software. Un rol no es un spoke ni un modelo — es una etiqueta
semántica que el núcleo asigna, en un momento dado, a un spoke capaz de cumplir esa
función.

Roles de primera clase reconocidos por esta arquitectura (el conjunto puede ampliarse,
no es cerrado):

- **Architect** — responsable de decisiones de diseño de sistema, estructura, y
  contratos entre componentes, sin entrar en implementación concreta.
- **Implementer** — responsable de traducir una decisión de arquitectura en código
  funcional concreto.
- **Debugger** — responsable de diagnosticar y corregir fallos en código o sistemas
  existentes.
- **Documenter** — responsable de producir y mantener documentación consistente con el
  estado real del sistema.
- **DevOps** — responsable de despliegue, infraestructura, y operación continua de lo
  construido.

Un rol se asigna a un spoke en función de:
- Qué capacidades requiere ese rol para operar (p. ej. Implementer normalmente requiere
  una capacidad de edición de código con conciencia de AST; Architect normalmente
  requiere únicamente una capacidad de razonamiento).
- Qué spoke(s), según el Registro de Capacidades, sirven esas capacidades en el momento
  de la asignación.
- La política de selección vigente cuando hay más de un spoke candidato (ver
  `04-modelo-de-capacidades-y-enrutamiento.md`, sección 3).

La asignación de rol→spoke es, por diseño, **reconfigurable en tiempo de ejecución**:
si el spoke que hoy ejecuta Implementer deja de estar disponible, Janus debe poder
reasignar ese rol a otro spoke que sirva las capacidades necesarias, sin que la tarea en
curso se pierda (sujeto a lo que la persistencia transversal permita reconstruir, ver
`06-modelo-de-persistencia-y-estado.md`).

## 3. Tarea como unidad rastreable

Una **tarea** es una unidad discreta de trabajo asignada a un rol, con un ciclo de vida
que Janus rastrea independientemente de los detalles internos de cómo el spoke
asignado la resuelve. Como mínimo conceptual, una tarea tiene:
- Un rol responsable.
- Un estado (p. ej. pendiente, en progreso, bloqueada, completada, fallida — los
  valores exactos son detalle de implementación, no de esta arquitectura).
- Una relación con la sesión que la originó (ver `06-modelo-de-persistencia-y-
  estado.md`).
- Un resultado o artefacto producido, cuando corresponde.
- Trazabilidad de qué spoke concreto la ejecutó, incluso si el rol se reasignó a mitad
  de camino.

## 4. Multi-agente paralelo

Esta arquitectura debe soportar más de un rol ejecutándose de forma simultánea, cada
uno potencialmente en un spoke distinto, coordinados por el núcleo. Esto implica:

- El núcleo debe poder mantener el estado de múltiples tareas activas a la vez, cada
  una con su propio rol asignado, sin que el progreso de una bloquee a las demás salvo
  que exista una dependencia explícita entre ellas.
- Una tarea puede declarar una dependencia de otra (p. ej. una tarea de Implementer que
  depende de que una tarea de Architect haya producido cierto artefacto). El núcleo es
  responsable de no iniciar (o de pausar) una tarea cuyas dependencias no estén
  satisfechas.
- La ejecución paralela de roles no implica que los spokes involucrados se comuniquen
  entre sí — cada uno reporta su progreso y resultado exclusivamente a Janus, que es
  quien coordina el flujo entre tareas dependientes (Principio Arquitectónico #1
  aplicado también a la coordinación multi-tarea).

## 5. Relación entre rol, tarea y capacidad

El flujo general es:

1. Se crea una tarea, asociada a un rol y a una sesión.
2. El núcleo determina qué spoke ejecuta ese rol (asignación vigente, o nueva
   asignación si es la primera vez o la anterior ya no está disponible).
3. El spoke asignado, al ejecutar la tarea, puede requerir capacidades adicionales
   (p. ej. un rol Implementer que necesita buscar documentación externa). Esas
   necesidades se resuelven como cualquier otra solicitud de capacidad, por delegación
   a través del núcleo (ver documento 04), nunca contactando directamente a otro
   spoke.
4. El resultado de la tarea se persiste y se reporta hacia quien la originó (el
   usuario, u otra tarea que dependía de ella).

## 6. Documentos relacionados
- `04-modelo-de-capacidades-y-enrutamiento.md` — cómo se resuelven las necesidades de
  capacidad de un rol en ejecución.
- `06-modelo-de-persistencia-y-estado.md` — dónde y cómo se persisten sesiones, tareas y
  sus resultados.
- `08-mapa-de-componentes-reales.md` — qué spokes concretos son candidatos naturales
  para qué roles, según sus capacidades declaradas.
