# janus-platform

Concentra en una sola librería mínima todo lo que cambia entre Linux y
Windows (spec-16), para que el resto de un monorepo no tenga ramas por
plataforma repetidas.

## Standalone by design

Esta librería depende únicamente de la librería estándar de Python
(`psutil` y `uvloop` son extras opcionales, nunca obligatorios). No
importa ningún otro paquete `janus_*`. Si querés usarla en otro
proyecto: copiá esta carpeta, `pip install -e .` (o publicá el wheel),
y listo — no hay nada más del monorepo que arrastrar.

Plataformas soportadas de host: Linux (x86_64 y aarch64) y Windows 10/11
(x86_64). macOS y WSL quedan fuera (WSL no tiene pantalla utilizable
para automatización de GUI, ver `platform_info()`).

## Superficie pública

```
default_state_dir() -> Path
make_private(path, directory=False) -> None
write_private(path, data: bytes) -> None
privacy_status(path) -> PrivacyStatus
path_is_within(child, root) -> bool

InstanceLock(path)
spawn(argv, env=None, cwd=None, new_session=True) -> ProcessHandle
ProcessHandle.pid / .poll() / .wait() / .terminate(grace_s)

install_shutdown_handlers(loop, on_signal)
configure_event_loop()

platform_info() -> PlatformInfo
```

Ver `docs/specs/spec-16-platform.md` en el monorepo de origen para la
spec funcional completa, si la tenés a mano; este README es autosuficiente
para el uso de la librería en sí.
