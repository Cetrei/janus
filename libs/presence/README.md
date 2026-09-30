# janus-presence

Identificación ambiental 1:N para Janus ("quién entró a la casa"). Distinto
y separado de `janus-biometrics` (verificación 1:1 del dueño, spec-18):
`presence` identifica cuál de varias personas conocidas es alguien, o si
es un desconocido nuevo, sin autorizar ninguna acción por sí mismo — solo
emite quién fue visto, con una confianza. Qué significa ese "quién" (dueño,
familiar, visita autorizada) es responsabilidad de quien consuma el evento
`person_seen`.

**Esta librería almacena biometría de terceros por diseño.** A diferencia
de `janus-biometrics`, que es estrictamente 1:1 y no retiene muestras,
`presence` guarda embeddings de forma indefinida (para poder reconocer a
la misma persona en el futuro) y snapshots temporales de desconocidos
mientras no se les asigna un nombre. No confundir las garantías de una
librería con las de la otra.

Ver `SPEC.md` para el detalle funcional completo.

## Estado

Implementado: `models.py`, `errors.py`, `store.py` (SQLite propio +
muestras cifradas AES-256-GCM), `index.py` (binding cffi a `hnsw-c`),
`frame_source.py` (`LocalCameraSource`, `McpCameraSource`),
`decision_gate.py` (integración opcional con `libs/decision`, spec-19),
`service.py` (`PresenceService`, orquesta todo). Pendiente antes de
considerarlo probado: compilar `vendor/hnsw/` y escribir los tests
(unit, integration, memory/bridge) que pide `SPEC.md`.

## Dependencias locales

Depende de `janus-biometrics` (detección + embedding de cara, YuNet +
SFace) y `janus-platform` (permisos de archivo), resueltas como paths
locales del monorepo vía `[tool.uv.sources]`, no como paquetes publicados.

## Compilar `hnsw-c` antes de instalar

`vendor/hnsw/` es la única pieza no-Python. El binding cffi (`index.py`,
vía `build_hnsw.py`) enlaza contra `hnsw.a`, que no viene compilado:

```bash
cd vendor/hnsw && make && cd ../..
```

Esto debe correrse (o volver a correrse tras cualquier cambio en
`vendor/hnsw/`) antes de `uv sync`, ya que el build hook de `pyproject.toml`
compila la extensión cffi contra ese `.a` en build-time y falla
explícitamente si no lo encuentra.

## Instalación

```bash
cd vendor/hnsw && make && cd ../..
uv sync --extra camera   # opencv-python-headless para LocalCameraSource
uv run pytest -v
uv run ruff check .
```

## Runner autónomo

Mientras no exista Janus, `presence` corre solo: observa las cámaras
configuradas, lleva el log de eventos y sirve una página local para revisar
y nombrar a los desconocidos (SPEC.md, requisito 39).

```bash
uv run python -m janus_presence run --config presence.toml
```

Config mínima (`presence.toml`). Los dos umbrales no tienen valor por
defecto: salen de calibrar con datos reales, así que el archivo tiene que
declararlos. Una clave desconocida es un error, para que un typo no pase
en silencio.

```toml
state_dir = "~/.local/share/janus"

[presence]
match_threshold = 0.6
match_threshold_ambiguous = 1.2

[[sources]]
source_id = "cuarto"
kind = "camera"
device = 0        # índice de la cámara local
sample_fps = 4
```

Al arrancar, el runner escribe en el log la URL de la página de revisión
(por defecto `http://127.0.0.1:8765/`, solo loopback) y la ruta del archivo
con el token de acceso (`<state_dir>/presence/review.token`, permisos 0600).
Se entra pegando ese token una vez; la sesión vence sola por inactividad.
Ctrl+C o SIGTERM cierran en orden (página, cámaras, jobs, base de datos).

Códigos de salida: `0` parada limpia, `1` no pudo arrancar o se detuvo por
un error corregible (clave o modelo ausente, puerto ocupado), `2` config o
argumentos inválidos. `--log-level debug|info|warning|error` ajusta el log.
