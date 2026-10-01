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

## Quién entró y salió

El runner escribe una línea `visit_started` y otra `visit_ended` por visita en
`<state_dir>/presence/events.jsonl` (la estancia viene en `dwell_s`). El
subcomando `visits` las junta y las lista; funciona con el runner corriendo o
detenido y lee también el respaldo `events.jsonl.1`.

```bash
uv run python -m janus_presence visits --config presence.toml
uv run python -m janus_presence visits --config presence.toml --since 24h
uv run python -m janus_presence visits --config presence.toml --last 10 --json
```

`--since` acepta `90m`, `12h` o `7d`; `--last N` deja las N más recientes;
`--json` imprime un arreglo para usarlo desde un script. Los nombres salen de
la base de datos de presence (solo lectura); si no se pueden leer, se muestra
el id corto de la persona. Una visita sin hora de salida aparece como
`en curso`.

Una sola cámara solo sabe que alguien apareció y que dejó de verse: no
distingue entrar de salir. Para saber la dirección haría falta una segunda
cámara o un sensor de puerta.

## Home Assistant: luz al llegar

Si `presence.toml` tiene la sección `[home_assistant]`, el runner avisa a Home
Assistant en cada visita que se abre o se cierra con
`POST /api/events/janus_presence`. Home Assistant decide qué hacer; presence
solo dice a quién vio.

1. En tu perfil de Home Assistant crea un token de acceso de larga duración y
   guárdalo en `~/.config/janus/ha.token` con `chmod 600`. El runner se niega
   a arrancar si el archivo no existe, está vacío o lo pueden leer otros
   usuarios.
2. Agrega a `presence.toml`:

```toml
[home_assistant]
url = "http://127.0.0.1:8123"
token_file = "~/.config/janus/ha.token"
```

3. Crea una automatización en Home Assistant que escuche el evento. Este
   ejemplo enciende la luz cuando llega una persona con el nombre que le
   pusiste en la página de revisión (aquí `Joanfer`), después del atardecer:

```yaml
alias: Luz al llegar
trigger:
  - platform: event
    event_type: janus_presence
    event_data:
      kind: visit_started
      label: Joanfer
condition:
  - condition: sun
    after: sunset
action:
  - service: light.turn_on
    target:
      entity_id: light.bombillo
```

Datos del evento: `kind` (`visit_started` o `visit_ended`), `visit_id`,
`person_id`, `label`, `role`, `state`, `source_id`, `started_at`,
`last_seen_at`, `at` y `dwell_s` (solo al cerrar). `label` y `role` son `null`
para quien sigue sin nombre, así que una condición sobre `label` nunca se
cumple con un desconocido. Agrega `state: established` al `event_data` si
quieres exigir que la persona ya tenga varias confirmaciones tuyas; con
`provisional` basta un nombre. El rol (`role`) se asigna desde la página de
revisión con el campo "Rol" de cada persona con nombre (una palabra en
minúsculas, como `owner` o `family`); aparece como `role` en el evento y
puedes usarlo en lugar de `label` en `event_data`. El campo solo está en las
tarjetas de personas que todavía tienen apariciones por revisar, así que ponlo
antes de confirmar las suficientes para que la persona quede establecida.

Si Home Assistant está caído, el evento se reintenta unas veces y luego se
descarta con una advertencia; ver gente nunca espera a Home Assistant.

**Seguridad.** El evento de presencia no debe encadenarse a cerraduras ni a
alarmas: reconocer una cara no autoriza nada. Usa este evento solo para luces,
clima y medios. Los umbrales de coincidencia deciden a quién se le prende la
luz: ajústalos desde la página de revisión con tu cámara real antes de
confiar en la automatización.
