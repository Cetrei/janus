# Handoff — libs/platform (nuevo, completo) + libs/config (nuevo, PARCIAL) + libs/biometrics (actualizado)

## Motivo de esta sesión
`biometrics` no podía ni instalarse (`uv sync` fallaba: `janus-platform` no
existe en ningún índice). Se confirmó con el usuario que `platform` y
`config` son capas base agnósticas de Janus (spec-16 y spec-02 lo declaran:
"Depende de: nada"), no otro feature hermano — así que `biometrics`
dependiendo de ellas no rompe su propio agnosticismo (`libs/presence` sí
depende de `biometrics`, unidireccional, eso se mantiene intacto).
Pedido explícito del usuario: dejar `platform` y `config` armados de forma
que alguien pueda copiar la carpeta a otro proyecto y usarla sin arrastrar
el resto del monorepo.

## Qué se creó

### libs/platform/ — COMPLETO (spec-16, las 12 requisitos)
Standalone real: `pyproject.toml` propio, `dependencies = []` (solo stdlib;
`psutil` y `uvloop` son extras opcionales). Nada importa nada de `janus_config`,
`janus_biometrics` ni ningún otro paquete del monorepo.

```
libs/platform/
  pyproject.toml        # dependencies = [], extras: psutil, uvloop
  pytest.ini
  README.md              # deja explícito que es standalone
  src/janus_platform/
    __init__.py
    errors.py            # PlatformError, LockHeld, PlatformUnsupported
    paths.py             # default_state_dir, make_private, write_private, privacy_status, path_is_within
    lock.py               # InstanceLock (fcntl/msvcrt)
    process.py             # spawn, ProcessHandle (Popen, nunca create_subprocess_exec)
    loop.py                  # install_shutdown_handlers, configure_event_loop
    diagnostics.py            # platform_info, PlatformInfo
  tests/
    test_paths.py    (10 tests, skip en Windows: usa chmod POSIX)
    test_lock.py      (3 tests, skip en Windows: usa multiprocessing+fcntl)
    test_process.py    (5 tests, skip en Windows: usa comandos POSIX true/false/sleep)
    test_diagnostics.py  (3 tests, corren en cualquier plataforma)
```

**No ejecutado.** Mismo disclaimer que el resto de esta sesión: sin shell,
sin poder correr `uv sync` / `pytest` / `ruff` yo mismo.

**Nota de diseño**: los tests POSIX-specific tienen `pytestmark = pytest.mark.skipif(sys.platform == "win32", ...)`
porque no pude verificar el comportamiento en Windows (no tengo esa
plataforma disponible); si vas a correr esto en Windows, esos tests se
saltean solos y habría que escribir sus equivalentes con `icacls`/`msvcrt`
antes de confiar en la rama Windows del código.

### libs/config/ — PARCIAL, a propósito (spec-02 tiene 34 requisitos, solo se hizo 1)
**NO es la implementación completa de spec-02.** Solo existe `SecretRef`
(requisito 4), porque es lo único que `biometrics` necesitaba ahora mismo
(clave de cifrado de plantillas, requisito 17 de spec-18). El `README.md`
de `libs/config/` deja esto explícito en mayúsculas para que nadie asuma
que `load_settings`, `JanusSettings`, `ConfigWatcher`, topología de agentes,
etc. existen — no existen, ni un stub.

```
libs/config/
  pyproject.toml       # dependencies = ["pydantic>=2"], NO depende de janus_platform todavia
  README.md             # ESTADO: PARCIAL, explica que falta casi todo
  src/janus_config/
    __init__.py
    secrets.py          # SecretRef (env | file, exactamente uno), ConfigError
  tests/
    test_secrets.py     # 7 tests
```

Diferencia de interfaz importante: el `SecretRef` provisional que
`biometrics/base.py` declaraba usaba `env_var`/`file_path`; el real de
`janus_config` usa `env`/`file` (nombres de la spec-02, requisito 4). Nadie
en el código ya escrito (`service.py`, `store.py`, tests) instanciaba el
provisional, así que el cambio de nombre de campos no rompió nada — se
verificó leyendo cada archivo antes de tocar `base.py`.

### libs/biometrics/ — actualizado
- `base.py`: se quitó el `SecretRef` provisional, ahora importa y re-exporta
  `janus_config.SecretRef` (`from janus_config import SecretRef`). Los
  consumidores que ya importaban `SecretRef` desde `janus_biometrics.base`
  lo siguen encontrando ahí (re-export), pero con la interfaz real
  (`env`/`file`, no `env_var`/`file_path`).
- `pyproject.toml`: agregado `janus-config` y `janus-platform` como
  dependencias, resueltas como paths locales editables vía
  `[tool.uv.sources]` (`../config`, `../platform`), no como paquetes de un
  índice — esto es lo que arregla el error original de `uv sync`.

## Cómo correr todo (comandos exactos, sin verificar por esta sesión)

```bash
# libs/platform primero (no depende de nada)
cd /home/cetrei/Proyectos/AI/janus/libs/platform
uv sync
uv run pytest -v
uv run ruff check .

# libs/config (solo pydantic)
cd /home/cetrei/Proyectos/AI/janus/libs/config
uv sync
uv run pytest -v
uv run ruff check .

# libs/biometrics (ahora sí debería resolver janus-config y janus-platform como paths locales)
cd /home/cetrei/Proyectos/AI/janus/libs/biometrics
uv sync --extra face
uv run pytest -v
uv run ruff check .
```

## Pendiente real (sin cambios de fondo respecto al handoff anterior)
1. Ninguno de estos tres paquetes se probó ejecutando `uv sync`/`pytest`/`ruff`
   de verdad. Todo lo anterior (48/48 en la sesión más vieja, 13 tests de
   `models.py`, ahora 10+3+5+3 de platform y 7 de config) es código escrito
   con intención de pasar, no confirmado por ejecución.
2. `local:sface` (`providers/sface.py`) sigue sin pesos reales, sin hashes
   reales, sin poder importarse sin `opencv-python-headless` + `onnxruntime`
   instalados.
3. `libs/config` sigue faltando casi entero (ver su propio README). Si el
   siguiente paso de `biometrics` necesita algo más de config (por ejemplo
   `biometrics.key` leído desde `janus.toml` real), hay que construir eso
   también, no asumirlo.
4. Pasos 2-9 del handoff anterior (low_level.py, wespeaker, sensors,
   enrollment, models CLI, bench, NOTICE, tests de integración) sin tocar.

## Ronda de fixes tras primera ejecución real (esta sesión)
Primera corrida real de `uv sync` + `pytest` + `ruff` sobre los tres paquetes.
Resultado: `platform` 22/22 verde, `config` 7/7 verde, `biometrics` con 2
problemas de collection + 12 findings de ruff. Arreglado:
- Faltaba `README.md` en `biometrics/` (el `pyproject.toml` lo declaraba
  como `readme` y no existía -> `uv sync` fallaba el build). Creado.
- `test_service.py` y `test_store.py` (preexistentes, no de esta sesion)
  hacian `from tests.conftest import ...`, que solo resuelve si `tests`
  es un paquete importable desde la raiz -- no lo es aqui. Cambiado a
  `from conftest import ...` (import simple, pytest ya pone `tests/` en
  `sys.path` via rootdir cuando no hay `tests/__init__.py`).
- ruff: `Decision`/`Liveness` ahora heredan de `StrEnum` en vez de
  `(str, Enum)`; imports sin usar removidos (`field` en models.py, `Path`
  en providers/sface.py); lineas >100 cols partidas en errors.py, models.py,
  providers/sface.py; `datetime.timezone.utc` -> `datetime.UTC` en conftest.py
  (preexistente, corregido de paso).
Todavia no re-ejecutado por esta sesion -- pendiente que el usuario corra
`uv run pytest -v` y `uv run ruff check .` de nuevo en `libs/biometrics`.

## Confirmado por ejecucion real (esta sesion, ronda 2)
**61/61 tests pasaron** (`test_models.py` 13, `test_policy.py` 15,
`test_registry.py` 8, `test_service.py` 9, `test_store.py` 9, ademas de
los que ya estaban). Quedaron 2 findings triviales de orden de imports
(I001) en `test_service.py`/`test_store.py` por el import de `conftest`
separado en su propio bloque -- corregido fusionandolo al bloque anterior,
tal como sugeria el propio `ruff --fix`. **No re-ejecutado un tercer round
todavia** -- deberia salir limpio, pero no se confirmo por ejecucion.

`libs/platform` (22/22) y `libs/config` (7/7) siguen verdes de la corrida
anterior, sin cambios desde entonces.

Esto es lo primero en toda la saga de sesiones que queda realmente
confirmado de punta a punta: instala, corre, pasa. **`uv run ruff check .`
confirmado limpio (`All checks passed!`) tras corregir la agrupacion de
imports** (conftest va con pytest como third-party, separado por una linea
en blanco de los imports internos de janus_biometrics -- mi primer intento
de fix fue en la direccion equivocada, el segundo siguio el diff exacto
que ruff mostro).

**Estado real al cierre de esta sesion: platform 22/22, config 7/7,
biometrics 61/61, los tres con ruff limpio. Nada commiteado todavia.**

## Pendiente de gestión
- Nada commiteado todavía (dos libs nuevas + biometrics modificado, todo
  en working tree).
- Licencia de MiniFASNet sigue sin confirmar.
- Orden de trabajo: quedó documentado que `platform`/`config` deberían
  haberse implementado antes que `biometrics` según sus propias specs
  ("se implementa junto a la spec 1" / "2 de 15"); esta sesión resolvió
  el bloqueo puntual, no reordenó el proceso de las demás specs base.
