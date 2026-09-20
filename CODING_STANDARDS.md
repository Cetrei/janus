# Coding Standards: Conventions and Style

Reference for contributors to Janus. Adapted from the author's general standards, with naming rules that follow each language's native convention.

Scope: Janus code is Python, Rust and TypeScript. The C++, Luau and game-specific sections are kept from the general standards and apply only if such code is ever added.

## Naming Conventions

Each language follows its own native convention, so linters, formatters and code generators work without overrides.

| Element | Python | Rust | TypeScript |
|---|---|---|---|
| Variables, functions, methods, attributes | `snake_case` | `snake_case` | `camelCase` |
| Constants | `SCREAMING_SNAKE_CASE` | `SCREAMING_SNAKE_CASE` | `SCREAMING_SNAKE_CASE` |
| Classes, interfaces, types, enums | `PascalCase` | `PascalCase` | `PascalCase` |
| Modules and files | `snake_case` | `snake_case` | `kebab-case` |
| Package names | `janus-<name>` (import `janus_<name>`) | `janus-<name>` | `@janus/<name>` |

Examples: `get_user`, `start_time` (Python, Rust); `getUser`, `startTime` (TypeScript); `MAX_SIZE`, `DEFAULT_TIMEOUT`; `StartTime`, `UserManager`, `DatabaseConnection`.

- Concrete implementations: PascalCase with a descriptive suffix (`StartTimeDefault`, `UserServiceCached`), in every language
- Data formats use `snake_case` keys: TOML configuration, JSON payloads and protobuf fields. Protobuf messages and services are `PascalCase`; enum values are `SCREAMING_SNAKE_CASE` prefixed with the enum name (required by `buf lint`)
- Package naming and workspace layout are defined in `docs/stack/02-monorepo.md`

## General Philosophy (Cross-Language)

### Paradigms and Architecture

- OOP when it is advantageous, avoiding over-engineering
- Dependency injection to delegate object creation, except for hardcoded dependencies
- Singletons only for services, or static classes depending on the language
- Robust but pragmatic code: flexible where possible, imperative where it defines behavior
- Early returns preferred over nested ifs, written as one-liners
- Composition over inheritance whenever possible

### Code Principles

- Pragmatic SOLID (avoid over-engineering)
- Small functions with a single responsibility (at most ~15-30 lines per function)
- Self-documenting code with descriptive names
- Immutability by default, mutability only when necessary
- Modularization so the code is understandable by humans
- Helper variables to improve readability and avoid duplication
- Functions must do one thing and do it well; prefer a function that calls other functions that each do one thing well

### Error Handling

- Early exits for parameter type checking
- Monads/Promises for expected behaviors (file not found, etc.)
- Exceptions only for exceptional errors that should not happen
- Clear validation of required parameters

### Testing

- TDD when size and complexity justify it
- Tests written afterwards for small or simple code
- Focus on modularization to make testing easier
- Test-driven development: implement a minimal failing test first, then implement the functionality that makes it pass, and repeat (every feature ends with a test that verifies it works)

### Documentation

- Minimal comments: self-documenting code is the priority
- Comments only on confusing or non-intuitive parts
- Extensive documentation only for public libraries and APIs

## Language-Specific Rules

- Python: PEP 8 naming, enforced with `ruff`
- Rust: standard Rust naming, enforced with `clippy -D warnings`
- TypeScript: camelCase, explicit interfaces and types
- C++: smart pointers and RAII by default
- Luau: gradual typing when available

## Game-Specific Optimization

### High-Performance Patterns

- Data-oriented design for high-performance systems (particles, physics, ECS)
- Object pooling for frequently created entities (bullets, enemies, effects)
- Arrays over individual objects for batch processing
- Cache-friendly data structures (contiguous arrays over linked lists)
- Minimize allocations in the game loop (reuse objects)

### Performance vs. Maintainability

- Performance over clean code in critical hotspots (render, physics, AI)
- Clean code in configuration and UI systems
- Performance first in rendering, physics, and update systems
- Profile before optimizing
- Comments only on non-intuitive optimizations

Keep this pragmatic and professional philosophy throughout all generated code.
