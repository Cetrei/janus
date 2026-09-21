# Stack — Automatización de interfaz gráfica y licencia

## 1. Automatización de interfaz gráfica

Base conceptual: `architecture/10-automatizacion-de-interfaz-grafica.md`.

Decisión explícita: dividido entre Rust y Python, no resuelto enteramente en un solo
lenguaje.

- **`crates/gui-automation/` (Rust)**: trabajo pesado de bajo nivel — captura de
  pantalla, inyección de eventos de input a nivel de OS, posiblemente OCR/visión si
  hace falta. Expuesto como extensión nativa a Python vía `PyO3`/`maturin`.
- **`core-gateway` (Python)**: orquesta la lógica de alto nivel — qué acción tomar,
  cuándo, en respuesta a qué tarea — llamando a la extensión Rust.
- **Multiplataforma real**: como el target incluye Raspberry Pi (Linux), el crate
  necesita abstraer por sistema operativo; Linux vía X11/Wayland es la prioridad real,
  no un caso secundario.

El detalle fino de esta pieza (qué biblioteca exacta de Rust, cómo se abstrae por SO)
quedó diferido a la fase de `/spec` de este componente y está propuesto en
`specs/spec-12-gui-automation.md`, con un spike de validación previo. Dato relevante
verificado en septiembre de 2026: Raspberry Pi OS usa Wayland (`labwc`) por defecto y las
opciones de input para Wayland son aún experimentales, así que no se puede asumir X11.

## 2. Licencia

Decisión confirmada: **código abierto, licencia MIT**, con aviso de copyright a nombre
de Joanfer como creador (`Copyright (c) 2026 Joanfer` en el archivo `LICENSE` de la
raíz del monorepo). MIT exige que ese aviso se preserve en cualquier copia o
redistribución —incluido cualquier fork futuro que terceros hagan de Janus—, lo cual
es el mecanismo legal concreto que garantiza la atribución de autoría. Coherente con
la licencia MIT de Hermes (`stack/05-harnesses-hermes-openclaw.md`, sección 1), que ya
permitía esta elección sin restricción.

---

## Documentos relacionados
- `architecture/03-contrato-de-spoke.md` — el contrato del spoke tipo 2.4 que este
  mecanismo satisface.
- `architecture/09-preguntas-abiertas.md` — pregunta 11 (tecnología concreta) y 12
  (alcance de aplicaciones soportadas).
- `stack/02-monorepo.md` — dónde vive `crates/gui-automation/`.
