# janus-config — ESTADO: PARCIAL

**Esta librería NO es la implementación completa de spec-02
(`docs/specs/spec-02-config.md`).** Spec-02 define 34 requisitos:
carga y validación de `janus.toml`, topología de agentes, catálogo de
skills, `ConfigWatcher`, `diff_settings`, `diff_agent`, etc.

De todo eso, **solo existe `secrets.py` (`SecretRef`)**, implementado
puntualmente para desbloquear `libs/biometrics`, que lo necesita para
la clave de cifrado de plantillas (spec-18, requisito 17) y no puede
importar el `SecretRef` provisional que tenía declarado en su propio
`base.py`.

## Qué falta (todo, salvo lo listado abajo)

- `load_settings`, `JanusSettings`, `ConfigError` (requisitos 1-19i)
- `ConfigWatcher`, `validate_candidate`, `diff_settings` (requisitos 20-22)
- `AgentConfig`, topología de carpetas, `discover_agents` (requisitos 23-31)
- Todo lo demás de la spec

No asumas que nada de esto existe. Si tu código necesita algo más que
`SecretRef`, hay que implementarlo — no está solo "sin testear", no
existe en absoluto.

## Lo que sí existe

```
from janus_config import SecretRef

ref = SecretRef(env="MY_SECRET")     # o SecretRef(file="/path/to/secret")
value: str = ref.resolve()            # SecretStr subyacente, .get_secret_value()
```

Ver `secrets.py` para el comportamiento exacto (validación de que
se declare exactamente una fuente, enmascarado en `repr()`).

## Standalone

Esta librería (en su estado actual) solo depende de `pydantic>=2` y
la librería estándar. No importa `janus_platform` todavía porque
`SecretRef` no lo necesita (spec-02 sí lo declara como dependencia
general de la librería completa, para otras partes como
`default_state_dir()` en `paths`, no implementadas aquí).
