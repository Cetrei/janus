# proto/

Source of truth for the Janus semantic model (spec-01). Package `janus_proto.v1`.

## Layout

```
buf.yaml               single module, lint STANDARD, breaking FILE
buf.gen.yaml           Python generation into ../libs/proto-py/src
janus_proto/v1/*.proto schemas (path must match the package: PACKAGE_DIRECTORY_MATCH)
```

Generated code is committed under `libs/proto-py/src/janus_proto/v1/`. Only `v1/` is generated. `__init__.py`, `helpers.py` and `capability_ids.py` are hand written and `buf generate` must never delete them (no `clean: true`).

## Commands

Run from `proto/`:

```
buf lint
buf breaking --against '.git#branch=main,subdir=proto'
buf generate
```

CI runs all three and then `git diff --exit-code`, so stale generated code fails the build.

## Offline fallback

Remote plugins run on the BSR and need network. Without it, from the repo root:

```
python -m grpc_tools.protoc -I proto \
  --python_out=libs/proto-py/src \
  --pyi_out=libs/proto-py/src \
  --grpc_python_out=libs/proto-py/src \
  proto/janus_proto/v1/*.proto
```

Requires `grpcio-tools`. Output can differ byte for byte from the BSR plugins unless the versions match, so commit only output generated with the pinned plugin versions.

## Versioning policy

* Compatible changes stay in `v1`: new optional fields with new numbers.
* Never reuse a field number. Removed fields are marked `reserved`.
* Every enum starts with `*_UNSPECIFIED = 0` and its values are prefixed by the enum name.
* An incompatible change needs a new `janus_proto.v2` package. Never edit `v1` in place.
* Tokens travel in gRPC metadata (`authorization`), never in messages.
