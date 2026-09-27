# janus-biometrics

Verificación biométrica local de identidad (cara y voz) para Janus —
spec-18. Verificación uno a uno contra la plantilla del dueño, nunca
identificación entre varias personas. Procesamiento local por defecto:
ningún dato biométrico sale del equipo salvo un proveedor remoto
configurado y reconocido de forma explícita.

## Estado

En desarrollo. Implementado hasta ahora: `base.py`, `errors.py`,
`registry.py`, `policy.py`, `store.py` (cifrado AES-256-GCM), `service.py`,
`models.py` (descarga + verificación de hash), proveedor `null`,
`providers/sface.py` (YuNet + MiniFASNet + SFace, con hashes reales en
`models.yaml` y ensamble de liveness de dos modelos) y `low_level.py`
(`detect_and_embed_faces`, requisito 8bis, usado por `libs/presence`).
`camera.py` (captura de cámara multiplataforma Linux/Windows/macOS,
multi-cámara vía `list_cameras()`, sin ninguna dependencia de
YuNet/SFace/MiniFASNet) y `overlay.py` (dibujo: brackets de detección
animados, zoom a la cara, panel de datos genérico) son módulos nuevos
pensados para que `libs/presence` los reuse tal cual para su propia UI de
múltiples cámaras y clip pausado con zoom (ver `libs/presence/SPEC.md`).
`tests/test_sface.py` (integración real contra los `.onnx`, skip limpio
si faltan pesos u opencv/onnxruntime) y `tests/manual_camera_check.py`
(prueba manual con cámara real y preview en vivo, ver más abajo) ya
existen. Pendiente confirmar por ejecución: ninguna sesión de agente tuvo
shell real en este repo, así que nada de lo anterior está confirmado
corriendo `pytest`/`ruff` de verdad salvo lo que el propio usuario haya
corrido y reportado. Ver `HANDOFF.md` para el detalle de qué falta y qué
no se pudo verificar por ejecución en cada sesión.

**Voz: no implementado.** `SpeakerVerifier`/`PcmAudio` existen como
interfaz en `base.py`, pero no hay ningún proveedor real registrado en
`registry.py` (solo `local:sface` y `null`) — no existe todavía un
`local:wespeaker-resnet34` ni ningún otro proveedor de voz. No hay nada
real contra lo que probar un micrófono todavía.

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

## Probar con cámara real

`tests/test_sface.py` corre automático con `pytest` pero solo prueba
casos sin cara real (imagen en blanco, mismatch de modelo, liberación de
sesiones) porque no hay fotos de cara con licencia libre en el repo
todavía. Para probar de verdad con tu propia cara, hay un script manual
separado (no es parte de la suite de pytest, es interactivo, con preview
en vivo y overlay de detección animado):

```bash
cd libs/biometrics
uv sync --extra face-gui
uv run python tests/manual_camera_check.py list      # lista cámaras que OpenCV puede abrir
uv run python tests/manual_camera_check.py enroll    # SPACE captura, ESC aborta; pide 5 fotos
uv run python tests/manual_camera_check.py verify    # captura 1 foto y la compara
```

**Importante: `face-gui`, no `face`.** El extra `face`
(`opencv-python-headless`) no tiene soporte de GUI (`cv2.imshow` no
funciona) y en Linux muchas builds headless de PyPI tampoco traen V4L2
habilitado para captura real — es probablemente la causa de "can't open
camera by index" si probaste con `--extra face` antes. `face-gui` instala
`opencv-python` (con GUI). No instales los dos extras en el mismo
entorno: `uv`/`pip` puede terminar resolviendo cualquiera de los dos
`cv2`, no ambos. Producción/tests (`providers/sface.py`, `low_level.py`,
`test_sface.py`) siguen usando `face` (headless); solo
`manual_camera_check.py` necesita `face-gui`.

Mientras el preview busca una cara muestra brackets ámbar pulsantes; con
exactamente una cara encuadrada, los brackets pasan a verde y SPACE
captura. Si no pasás `--camera`, `enroll`/`verify` auto-detectan: si
encuentran una sola cámara la usan directo, y si encuentran varias te
piden elegir con `--camera <index>` (a futuro, `libs/presence` está
pensado para correr contra varias a la vez, ver `libs/presence/SPEC.md`).
**No asumas que el índice es 0** — en Linux es común que V4L2 exponga
varios nodos de dispositivo por cámara física (uno de metadata, otro de
captura real), así que tu cámara real puede terminar en el índice 2, 3, o
el que sea; los warnings de OpenCV (`can't open camera by index`) para
los índices que no son el tuyo son normales y esperables, no un error —
es `list_cameras()` probando cada índice para encontrar cuál abre de
verdad.

Requiere:
- Una cámara real que OpenCV pueda abrir. Si `list` no encuentra ninguna,
  ver el mensaje de error de `enroll`/`verify` (`camera.py` da una pista
  específica por SO: grupo `video` y `/dev/video*` en Linux, permisos de
  cámara en Windows). `Camera.open()` pide 1280x720 a la cámara al abrirla
  (best-effort: si el dispositivo no soporta esa resolución, cae a la
  máxima que sí soporta, sin error) — esto le da más margen al gate de
  calidad, que mide el tamaño de cara como fracción del frame, no en
  píxeles absolutos, precisamente porque cámaras distintas (webcam de
  laptop, cámara fija de jardín/cuarto para `libs/presence`) van a variar
  mucho en resolución y distancia al sujeto.
- Entorno con pantalla (la ventana de preview usa `cv2.imshow`; no
  funciona por SSH sin X forwarding). En Linux con sesión Wayland, el Qt
  empaquetado por `opencv-python` puede no encontrar el plugin de Wayland
  y caer a XWayland con un bug de repintado conocido (el preview parpadea
  entre el frame real y un frame negro/viejo). Si ves eso, forzar el
  backend a X11 directo lo resuelve:
  `QT_QPA_PLATFORM=xcb uv run python tests/manual_camera_check.py enroll`.
- Los cuatro pesos ONNX (`yunet`, `sface`, `minifasnet_v2`,
  `minifasnet_v1se`) resueltos por `models.yaml`, ya sea porque están en
  `~/.cache/janus-models/` o porque `local_path` apunta a tu copia local.

`enroll` guarda el resultado en texto plano en
`tests/.manual_camera_check/owner.json` (no es el store cifrado real de
`store.py`, es solo para probar la cadena de modelos aislada). `verify`
congela el frame capturado, hace zoom a la cara detectada y muestra un
panel con el `BiometricResult` completo (decision, liveness, quality_ok,
reason) superpuesto; nunca muestra ni imprime el score numérico, por
diseño (requisito 16).

**Micrófono: no hay nada que probar todavía.** No existe un proveedor de
voz real (ver arriba), así que no tiene sentido un
`manual_microphone_check.py` hasta que `local:wespeaker-resnet34` (u otro
proveedor de voz) exista.

Ver `docs/specs/spec-18-biometrics.md` en el monorepo para la spec
funcional completa.
