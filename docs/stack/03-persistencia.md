# Stack — Persistencia

## 1. Motor: SQLite, no Postgres

Decisión fijada explícitamente tras comparar ambos: para una persona, un solo host, un
solo proceso escritor, SQLite gasta menos recursos y es estrictamente más simple que
Postgres, sin perder nada que Janus vaya a necesitar. Postgres exigiría un proceso
servidor aparte con RAM base propia (administración de usuarios, conexiones, backups)
que no se justifica en un Raspberry Pi para una sola persona. El límite real de SQLite
(un solo escritor concurrente) nunca se toca porque `core-gateway` es, por diseño, el
único proceso que escribe.

## 2. Acceso: sin ORM, control total

Decisión explícita del usuario: **SQL crudo vía `aiosqlite`** (driver async, se
integra directo al event loop de `core-gateway` sin bloquear), sin SQLAlchemy, sin
SQLModel, sin query builder. Cada query vive como una función Python explícita en
`libs/persistence/`, con el SQL visible directamente en el código — nada de
abstracción intermedia que traduzca objetos a SQL por el desarrollador.

## 3. Migraciones: archivos `.sql` versionados, no strings hardcodeados

Requisito explícito del usuario: nunca un string de SQL embebido sueltamente en código
Python. Cada cambio de esquema vive en su propio archivo `.sql` numerado:

```
libs/persistence/migrations/
  0001_init.sql
  0002_tasks.sql
  0003_capabilities.sql
  ...
```

Runner de migraciones: minimalista y propio (dado el requisito de "control total"), en
vez de una dependencia externa como Alembic o yoyo-migrations — lee los archivos en
orden, lleva registro de cuáles ya se aplicaron, sin imponer ningún ORM.

## 4. Estructuras de datos y complejidad algorítmica

Distinción explícita que quedó fijada: la complejidad algorítmica (O(1), O(log n),
O(n log n)) que el usuario pidió **no la provee el motor SQL en sí** — SQLite modela un
grafo dirigido (p. ej. dependencias de tareas de `architecture/05-modelo-de-roles-y-
tareas.md`) como una tabla de aristas (`task_id`, `depends_on_id`) con índice B-tree,
dando búsquedas O(log n). La complejidad real de recorrido de grafos (topological sort,
detección de ciclos) se controla en la capa de lógica, no en SQL:

- El subconjunto de grafo relevante se carga a memoria como estructura real (dict de
  adyacencia) al arrancar o al tocar una tarea.
- Los algoritmos de grafo (Kahn's algorithm o DFS) corren en memoria, en Python puro
  para v1 — esto sí es O(V+E) real.
- SQLite es la capa de persistencia/respaldo de ese grafo, nunca el motor de cómputo.
- Optimización futura, explícitamente no prematura: si el grafo real demuestra ser
  cuello de botella, se extrae ese cálculo a un `crate` de Rust vía `PyO3`, no antes.

## 5. Redis: capa rápida efímera

Redis complementa a SQLite, no lo reemplaza. Usos fijados:

- Canal pub/sub para la superficie de observabilidad push
  (`architecture/07-superficie-para-gui-futura.md`).
- Stream en memoria de logs hacia una futura interfaz
  (`stack/08-seguridad-y-observabilidad.md`, sección 2).
- Estado efímero: sesiones activas en curso, locks.
- Estado de conexión de spokes externos registrados dinámicamente
  (`stack/07-descubrimiento-y-capacidades.md`, sección 1.2), cuando ese estado no
  necesita sobrevivir a un reinicio del sistema.

No es almacén de verdad — todo lo que debe sobrevivir reinicios y ser fuente de verdad
va a SQLite.

---

## Documentos relacionados
- `architecture/06-modelo-de-persistencia-y-estado.md` — base conceptual de
  `libs/persistence/`.
- `stack/01-contexto-y-lenguajes.md` — el contexto de un solo host que justifica SQLite.
- `agents/02-memoria.md` — el esquema de memoria de dos niveles que extiende
  `libs/persistence/`.
