# janus-biometrics

Verificación biométrica local de identidad (cara y voz) para Janus —
spec-18. Verificación uno a uno contra la plantilla del dueño, nunca
identificación entre varias personas. Procesamiento local por defecto:
ningún dato biométrico sale del equipo salvo un proveedor remoto
configurado y reconocido de forma explícita.

## Estado

En desarrollo. Implementado hasta ahora: `base.py`, `errors.py`,
`registry.py`, `policy.py`, `store.py` (cifrado AES-256-GCM), `service.py`,
`models.py` (descarga + verificación de hash), proveedor `null` y un primer
`providers/sface.py` (YuNet + MiniFASNet + SFace) sin pesos ONNX reales
todavía. Ver `HANDOFF.md` para el detalle de qué falta y qué no se pudo
verificar por ejecución en cada sesión.

## Dependencias locales

Depende de `janus-config` (solo `SecretRef` por ahora) y `janus-platform`,
resueltas como paths locales del monorepo vía `[tool.uv.sources]` en
`pyproject.toml` (`../config`, `../platform`), no como paquetes publicados.

## Instalación

```bash
uv sync --extra face   # opencv-python-headless para el proveedor de cara
uv run pytest -v
uv run ruff check .
```

Ver `docs/specs/spec-18-biometrics.md` en el monorepo para la spec
funcional completa.
