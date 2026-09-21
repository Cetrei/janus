# Stack — Modelo semántico: Protocol Buffers

## 1. Por qué protobuf y no dataclasses a mano

Discutido explícitamente: el modelo semántico interno de Janus (lo que el Core de
Traducción usa para representar una solicitud/respuesta independiente de cualquier
spoke) no se ancla a MCP ni a ningún protocolo externo — sería una dependencia
conceptual hacia un spoke particular, violando el principio de que Janus no se adapta
a lo existente, sino que ofrece su propio modelo y facilita que otros se adapten a él
(vía SDK).

Protocol Buffers se eligió como formato de esa fuente de verdad porque:

- Ya está en el stack por necesidad de gRPC (comunicación con harnesses/spokes que
  hablan gRPC).
- Permite generar código para múltiples lenguajes (Python, TypeScript, Rust) desde una
  única definición, sin riesgo de que los SDKs se desincronicen entre sí — el riesgo
  real de mantener "una fuente de verdad a mano por lenguaje".

## 2. Herramienta: `buf`

`buf` gestiona lint y detección de breaking changes sobre los `.proto`, y genera el
código hacia cada consumidor (hoy: `libs/proto-py/`; en el futuro, cualquier SDK en
otro lenguaje que Janus decida ofrecer a integradores externos).

## 3. Ubicación: `proto/`, no dentro de ningún `libs/`/`crates/`/`packages/`

Un `.proto` no es código de ningún lenguaje de programación — es un lenguaje de
definición de esquema neutral (IDL). Meterlo dentro de una carpeta que por convención
implica un ecosistema de lenguaje específico (Cargo, npm) rompería esa convención. Por
eso `proto/` vive en la raíz del monorepo, como el resto de convenciones ya fijadas
(`stack/02-monorepo.md`).

---

## Documentos relacionados
- `architecture/01-conceptos-y-vocabulario.md` — el modelo semántico interno y las dos
  caras del Core de Traducción que este esquema formaliza.
- `stack/02-monorepo.md` — dónde viven `proto/` y `libs/proto-py/`.
