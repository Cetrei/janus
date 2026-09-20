# Feature Spec: libs/memory/ (memoria de dos niveles y búsqueda semántica)

> **Status**: Ready for implementation
> **Last updated**: 2026-09-19
> **Orden de implementación**: 7 de 15. Depende de: spec 03 (`Database`, tablas `memory_*` y `memory_vec`).

---

## Objective

Implementar la lógica de la memoria episódica de Janus (`agents/02` secciones 1 a 4): dos niveles (agente y global), categorías auto extensibles con `profile` como única semilla, y recuperación por similitud semántica sobre `sqlite-vec`.

El esfuerzo de recordar recae en la infraestructura: el agente no razona sobre qué recordar, usa la tool `recall_memory` para traer solo lo relevante al turno. Una vez implementada, cualquier agente puede guardar y recuperar recuerdos sin inyectar nunca el historial completo en el prompt.

Esta librería no cubre la indexación de identidad de agente ni de proyectos (`agents/02` sección 5), que vive en `libs/reasoning-engine` (spec 10) y usa archivos SQLite propios.

---

## Functional Requirements

### Escritura
1. `MemoryStore.remember(level, agent_name, category, content, source, project_ref=None) -> MemoryEntry` guarda una entrada con su embedding. `level` es `agent` o `global`; `agent_name` es obligatorio para `agent` y nulo para `global`.
2. Si la categoría no existe, se crea (catálogo auto extensible, `agents/02` sección 2.1). Las categorías tienen `description` opcional. La única categoría garantizada es `profile` en el nivel global, sembrada por migración.
3. Nombres de categoría: `^[a-z][a-z0-9_]{0,40}$`. Un agente puede crear categorías solo en su propio nivel y en el global.
4. `update(entry_id, content)` recalcula el embedding y `updated_at`. `forget(entry_id)` elimina entrada y vector. `forget_category(level, agent_name, category)` elimina la categoría completa (excepto `profile`, que se puede vaciar pero no borrar).
5. Deduplicación: antes de insertar, si existe una entrada de la misma categoría con similitud coseno mayor o igual a 0.95, se actualiza en lugar de duplicar y se devuelve la entrada existente con la marca `merged=True`.
6. Límites: `content` máximo 4000 caracteres; se rechaza con `MemoryTooLarge`. Máximo configurable de entradas por agente (default 10 000).

### Lectura
7. `MemoryStore.recall(query, level=None, agent_name=None, category=None, k=None) -> list[ScoredEntry]` calcula el embedding de la consulta y devuelve las `k` entradas más similares (default `memory.top_k_default`, 5), con su puntuación. Cuando `level` es nulo busca en el nivel del agente y en el global y fusiona resultados por puntuación.
8. Un filtro opcional por `category` y por `project_ref`.
9. `list_categories(level, agent_name)` devuelve las categorías con conteo y descripción, para que el agente sepa qué existe sin cargar contenido.

### Tool para el motor de razonamiento
10. `RecallMemoryTool` implementa la interfaz `Tool` de `libs/reasoning-engine` (spec 10) bajo el nombre `recall_memory`, con argumentos `query`, `category` opcional y `k` opcional. Devuelve texto compacto con categoría, contenido y fecha por resultado. Está disponible para todo agente.
11. `RememberTool` (`remember`) con `category`, `content` y `level`. Es la vía explícita de captura: el agente decide qué guardar. Un agente solo puede escribir su propio nivel `agent` o el `global`.
12. `ListMemoryCategoriesTool` (`list_memory_categories`).
13. Las tools no se inyectan con contenido de memoria por defecto. La única inyección automática es la categoría `profile` global, que se resume (máximo 1500 caracteres) en el arranque de cada sesión, porque `agents/02` sección 2.1 la define como lo que cualquier agente necesita para tratar bien al usuario desde el primer turno.

### Embeddings
14. `Embedder` (ABC) con `embed(texts, kind) -> list[list[float]]`, `model_id` y `dim`. Implementación por defecto `FastEmbedEmbedder`, con el modelo `intfloat/multilingual-e5-small` (384 dimensiones), que exige los prefijos `query: ` y `passage: `; `kind` selecciona el prefijo.
15. La inferencia corre en `asyncio.to_thread` para no bloquear el event loop. Los modelos se descargan en la primera ejecución a `state_dir/models/` y se validan por hash.
16. Cada entrada guarda `embedding_model`. Si el `model_id` configurado difiere del guardado, `reindex()` re embebe en lotes de 32 sin perder entradas.
17. Con `sqlite-vec` no disponible, `recall` degrada a coincidencia por texto (LIKE sobre contenido y categoría) y lo indica en el resultado (`degraded=True`).

### Captura automática (residual de la pregunta 2 de `architecture/09`)
18. Por defecto la captura es explícita (`remember`). Un hook opcional `on_task_completed` puede sugerir un resumen para guardar, desactivado por defecto (`memory.auto_capture = false`). Es una propuesta pendiente de confirmación (ver Open Questions).

---

## Non-Functional Requirements

* **Performance**: `recall` con 10 000 entradas menor a 60 ms p95 sin contar el embedding de la consulta; `embed` de una consulta corta menor a 200 ms p95 en Raspberry Pi 4 con el modelo pequeño. Objetivos propuestos, se ajustan tras medir.
* **Security**: la memoria es contenido del usuario; nunca se loguea el `content` completo; un agente no lee ni escribe el nivel `agent` de otro agente; el contenido recuperado es dato para el modelo, no instrucciones al sistema.
* **Reliability**: si el modelo de embeddings no está disponible, las escrituras se rechazan con `EmbedderUnavailable` (no se guarda un vector inválido) y la lectura degrada a texto.
* **Portability**: Python 3.11 o superior. Dependencias: `janus_persistence`, `fastembed` (u otra implementación de `Embedder`) y opcionalmente `sqlite-vec`. Prohibido importar `libs/adapters`, `libs/capabilities` y `apps/*`.

---

## Technical Decisions

### `sqlite-vec` para memoria episódica, índice híbrido aparte para identidad
* **Chosen**: `sqlite-vec` dentro de `janus.db` para las entradas de memoria (`agents/02` sección 3).
* **Reason**: mantiene SQLite como único motor y bajo consumo. El índice de identidad y proyectos (BM25 más vectorial) es otro mecanismo con su propio archivo por directorio y vive en la spec 10, tal como fija `agents/02` sección 5.
* **Rejected alternatives**: una base vectorial aparte (contradice `stack/03`); mezclar ambos índices (propósitos distintos).

### Modelo `intfloat/multilingual-e5-small` con 384 dimensiones
* **Chosen**: E5 multilingüe pequeño, 384 dimensiones.
* **Reason**: el usuario trabaja en español, el modelo cubre varios idiomas, es pequeño para el Pi y su dimensión coincide con la tabla `vec0` de la spec 03. Figura entre los modelos soportados de `fastembed`.
* **Rejected alternatives**: `paraphrase-multilingual-MiniLM-L12-v2` (mismos 384 dimensiones, pero hay un issue abierto de `fastembed` que reporta diferencias grandes frente a `sentence-transformers`); modelos grandes (peso excesivo en el Pi).

### Captura explícita por defecto
* **Chosen**: el agente llama a `remember`; la infraestructura no escribe recuerdos por su cuenta.
* **Reason**: evita ruido y almacenar información no relevante; consistente con que la infraestructura asuma el esfuerzo de recuperar, no de decidir qué es relevante para el usuario.
* **Rejected alternatives**: captura automática de cada turno (ruido y costo de embeddings sin control).

### Deduplicación por similitud alta
* **Chosen**: umbral 0.95 dentro de la misma categoría.
* **Reason**: evita crecimiento por repeticiones sin descartar matices; es configurable.

---

## Proposed Architecture

### Component Diagram
```mermaid
flowchart TD
    AG[agente] -->|recall_memory / remember| T[Tools de memoria]
    T --> S[MemoryStore]
    S --> E[Embedder fastembed en to_thread]
    S --> DB[(janus.db)]
    DB --> R[memory_entries + memory_categories]
    DB --> V[memory_vec vec0 384]
    SEED[sesion nueva] -->|resumen profile| AG
```

### Directory Structure
```
libs/memory/
  pyproject.toml
  src/janus_memory/
    __init__.py
    store.py          # MemoryStore: remember, recall, update, forget, reindex
    categories.py     # validación y catálogo auto extensible
    embedder.py       # Embedder ABC, FastEmbedEmbedder
    tools.py          # RecallMemoryTool, RememberTool, ListMemoryCategoriesTool
    profile.py        # resumen de la categoría profile para inicio de sesión
    errors.py         # MemoryTooLarge, EmbedderUnavailable, MemoryAccessDenied
  tests/
```

---

## Data Models

```
Entity MemoryEntry  { entry_id, level: agent|global, agent_name?, category, content,
                      embedding_model, project_ref?, source, created_at, updated_at }
Entity ScoredEntry  { entry: MemoryEntry, score: float }              # score = 1 - distancia coseno
Entity Category     { level, agent_name?, category, description?, count }
Entity RecallResult { entries: list[ScoredEntry], degraded: bool }
```

Tablas: `memory_entries`, `memory_categories` y `memory_vec` según spec 03.

---

## API Contracts

Librería más tools para el motor.

```
MemoryStore.remember(level, agent_name, category, content, source, project_ref=None) -> MemoryEntry
MemoryStore.recall(query, level=None, agent_name=None, category=None, k=None) -> RecallResult
MemoryStore.list_categories(level, agent_name=None) -> list[Category]
MemoryStore.reindex(batch_size=32) -> ReindexReport

Tool recall_memory { query: string, category?: string, k?: int(1..20) } -> text
Tool remember      { category: string, content: string, level: "agent"|"global" } -> text
Tool list_memory_categories {} -> text
```

Errores: `MemoryTooLarge`, `EmbedderUnavailable`, `MemoryAccessDenied` (un agente intenta otro nivel `agent`), `InvalidCategory`.

---

## Edge Cases

| Case | How to Handle |
|---|---|
| Consulta vacía | `recall` devuelve las entradas más recientes de la categoría pedida, sin embedding. |
| Modelo de embeddings cambiado | `embedding_model` distinto dispara `reindex()`; mientras tanto se ignoran vectores del modelo anterior y se degrada a texto para esas entradas. |
| Primera ejecución sin modelo descargado | Descarga con verificación de hash; si falla, `EmbedderUnavailable` y degradación a texto. |
| Entrada casi duplicada | Se fusiona (similitud mayor o igual a 0.95) y se devuelve `merged=True`. |
| Agente intenta leer memoria de otro agente | `MemoryAccessDenied`. |
| `sqlite-vec` no carga (intérprete sin extensiones) | `degraded=True`; se recomienda un Python con `enable_load_extension`. |
| Contenido con instrucciones ("ignora tus reglas") | Se almacena como dato; al recuperarse se entrega dentro de un bloque marcado como memoria y nunca con privilegio de sistema. |
| Crecimiento excesivo | Tope por agente; al alcanzarlo, `remember` falla con error claro y sugiere `forget`. |

---

## Testing Requirements

**Unit Tests**: validación de categorías; creación automática y semilla `profile`; deduplicación; límites; fusión de niveles en `recall`; degradación a texto; aislamiento entre agentes; prefijos `query:` y `passage:` del embedder con un `FakeEmbedder` determinista; `reindex` idempotente.

**Integration Tests**: ciclo `remember` y `recall` con `sqlite-vec` real y el modelo real (marcado como prueba lenta); comportamiento con `sqlite-vec` ausente; rendimiento con 10 000 entradas; las tools ejecutadas desde un `ToolContext` de prueba del motor.

---

## Security Checklist
- [ ] Aislamiento estricto del nivel `agent` por `agent_name`
- [ ] Contenido recuperado etiquetado como dato, sin privilegio de instrucción
- [ ] `content` completo nunca en logs
- [ ] Límites de tamaño y de cantidad
- [ ] Modelos descargados verificados por hash
- [ ] Inferencia fuera del event loop

---

## Open Questions
- [ ] Captura automática (`on_task_completed`): la pregunta 2 de `architecture/09` deja abierto qué dispara la escritura. Esta spec propone captura explícita por defecto y automática opcional. Confirmar.
- [ ] Verificar en la instalación real que `intfloat/multilingual-e5-small` está disponible en la versión de `fastembed` fijada y que sus wheels de `onnxruntime` existen para aarch64.
- [ ] Catálogo inicial adicional a `profile` (pendiente 1.6 de `TODO.md`): esta spec no siembra más categorías; el mecanismo es auto extensible por diseño.

---

## Handoff Note
Revisar esta spec antes de empezar. Crear un checklist desde los requisitos funcionales y marcarlo al avanzar. Levantar dudas antes de codificar, no durante. Implementar `embedder.py` con un `FakeEmbedder` primero, para desarrollar `store.py` sin descargar modelos.
