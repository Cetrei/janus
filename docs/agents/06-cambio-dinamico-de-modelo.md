# Agentes — Cambio dinámico de proveedor de modelo

Sugerido vía tool call, con aprobación configurable.

El cambio de proveedor de modelo de un agente es **tanto declarativo como dinámico**:

- **Declarativo**: el usuario configura, en la config del agente, qué proveedor de
  modelo usa por defecto.
- **Dinámico**: Janus decide sugerir un cambio según capacidad, costo y disponibilidad
  observados en tiempo real — por ejemplo, si el Registro de Capacidades detecta que
  el proveedor actual de Implementer no está respondiendo (timeout, error repetido),
  genera una sugerencia de cambio a otro proveedor disponible.

Este mecanismo se modela igual que cualquier otra acción del sistema: **como una tool
call** (`suggest_provider_change` o equivalente), sujeta a una política de aprobación
configurable por el usuario, con el mismo vocabulario ya usado en herramientas de
permisos conocidas: `ask_everytime`, `allow_always`, y variantes intermedias. Esta
política se declara en `config/janus.toml`, con posibilidad de override por agente.

Vive en `libs/capabilities/` (Registro de Capacidades), como una extensión de su
responsabilidad de resolución/selección ya definida en
`architecture/04-modelo-de-capacidades-y-enrutamiento.md` y acotada en
`stack/07-descubrimiento-y-capacidades.md`, sección 2.

---

## Documentos relacionados
- `architecture/04-modelo-de-capacidades-y-enrutamiento.md` — base conceptual de la
  resolución/selección que este mecanismo extiende.
- `stack/07-descubrimiento-y-capacidades.md` — alcance acotado del Registro de
  Capacidades a spokes externos.
- `architecture/09-preguntas-abiertas.md` — pregunta 1, política de prioridad entre
  criterios de selección.
- `agents/03-skills-y-config.md` — el proveedor de modelo como campo que requiere
  reinicio completo del agente al cambiarse.
