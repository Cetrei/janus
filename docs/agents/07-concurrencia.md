# Agentes — Concurrencia

Tope configurable por tipo de agente, cola FIFO por carriles, Janus exento.

## 1. Por qué no hay tope de recursos (RAM/VRAM)

Se evaluó explícitamente y se descartó: si un agente usa un modelo local (vía Ollama u
otro runtime local), la gestión de recursos de ese modelo (VRAM, RAM) ya es
responsabilidad de ese runtime — Janus no necesita duplicar esa gestión. El único tope
que Janus impone es de **cantidad de agentes concurrentes**, no de recursos de
hardware.

## 2. Modelo de cola: general con carriles por tipo, no una cola global compartida

- **Cola general**: un registro único de todas las solicitudes pendientes, en orden de
  llegada, con metadata de qué tipo de agente requiere cada una. Sirve como vista
  unificada del estado del sistema (útil también para la superficie de observabilidad
  de `architecture/07-superficie-para-gui-futura.md`).
- **Tope configurable por tipo de agente**: cada tipo (Implementer, Debugger, etc.)
  tiene su propio máximo de instancias concurrentes, declarado en
  `config/janus.toml`:

```toml
[agents.implementer]
max_concurrent = 2

[agents.debugger]
max_concurrent = 1
```

- **Cola de espera por carril**: cuando el tope de un tipo se alcanza, las solicitudes
  de ese tipo específico esperan en orden FIFO (First In, First Out — la más antigua
  se atiende primero; ninguna solicitud se descarta ni sobreescribe, a diferencia de
  un ring buffer) a que un slot de ese mismo tipo se libere. Un tipo saturado nunca
  bloquea ni es bloqueado por la cola de otro tipo — si Implementer está lleno pero
  Debugger tiene cupo, una solicitud de Debugger se atiende de inmediato.

## 3. Janus-líder: exento de todo tope, nunca en cola, nunca expulsado

Janus, como agente líder, **no cuenta contra ningún tope de concurrencia y nunca
espera en la cola de espera**. Esto es una decisión explícita y sin excepciones: dado
que Janus es quien gestiona la cola, decide delegaciones, y es el punto de contacto
directo con el usuario, si Janus mismo pudiera quedar bloqueado esperando turno, el
sistema entero se trabaría sin que nadie pudiera ni siquiera informarle al usuario que
está saturado. Janus corre siempre, sin importar cuántos subagentes estén activos o en
espera.

Esta lógica de cola vive en `libs/capabilities/` (Registro de Capacidades), en
coordinación con `apps/core-gateway/` para el despacho efectivo de instancias de
`AgentCore`.

---

## Documentos relacionados
- `architecture/07-superficie-para-gui-futura.md` — consumidor futuro del estado de
  cola/concurrencia.
- `stack/07-descubrimiento-y-capacidades.md` — `libs/capabilities/`, donde vive la
  lógica de cola.
- `agents/04-orquestacion-y-sesiones.md` — las sesiones por tarea que coinciden 1:1 con
  los slots ocupados.
- `agents/08-impacto-en-monorepo-y-diferido.md` — esquema exacto de la tabla de
  solicitudes en cola, diferido a `/spec`.
