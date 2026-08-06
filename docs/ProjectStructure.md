# Project structure

```
local-voice/
├── desktop/                  Tauri v2 shell (Rust) — owns all OS integration
│   ├── src/
│   │   ├── engine/
│   │   │   ├── handshake.rs      parse and validate the engine's startup line
│   │   │   ├── launcher.rs       resolve bundled binary vs development virtualenv
│   │   │   ├── process.rs        spawn, await handshake, shut down
│   │   │   └── mod.rs
│   │   ├── lib.rs                Tauri builder, state, commands
│   │   └── main.rs
│   ├── capabilities/default.json Tauri permission set
│   ├── tauri.conf.json
│   ├── build.rs
│   └── Cargo.toml
│
├── ui/                       React + TypeScript + Tailwind, rendered in the shell
│   ├── src/
│   │   ├── components/           presentational units
│   │   ├── hooks/                stateful behaviour
│   │   ├── services/
│   │   │   ├── connection.ts     resolve engine address (shell or dev env)
│   │   │   ├── engineClient.ts   typed HTTP client
│   │   │   └── generated/        produced from schema/openapi.json, not committed
│   │   ├── styles/index.css      Tailwind v4 entry and theme tokens
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── eslint.config.js
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── package.json
│
├── engine/                   Python 3.12 sidecar — owns the AI pipeline
│   ├── app/
│   │   ├── domain/               entities and ports; zero I/O, no dependencies
│   │   │   ├── audio.py          AudioChunk, AudioFormat, resampling
│   │   │   ├── buffer.py         bounded accumulation of a recording
│   │   │   ├── ports.py          AudioSource, Transcriber, TextEnhancer
│   │   │   ├── transcript.py     Transcript and its segments
│   │   │   └── vad.py            endpointing: calibration and confirmation
│   │   ├── adapters/             concrete implementations of the ports
│   │   │   ├── audio/            sounddevice capture, device registry, WAV
│   │   │   ├── speech/           faster-whisper, model catalogue
│   │   │   └── enhancement/      Ollama client, prompt profiles
│   │   ├── pipeline/
│   │   │   ├── recording.py      when to stop recording
│   │   │   └── dictation.py      record → transcribe → clean up
│   │   ├── api/
│   │   │   ├── routes/           system and dictation endpoints
│   │   │   ├── dependencies.py   context injection and token authentication
│   │   │   └── schemas.py        response models; source of truth for TS types
│   │   ├── config/
│   │   │   ├── paths.py          per-platform directories
│   │   │   └── settings.py       layered configuration and its invariants
│   │   ├── observability/
│   │   │   ├── logging.py        structured formatters, stderr only
│   │   │   └── redaction.py      Sensitive[T]
│   │   ├── runtime/
│   │   │   ├── context.py        EngineContext, the composition root state
│   │   │   ├── services.py       assembly of the long-lived collaborators
│   │   │   ├── handshake.py      the stdout contract
│   │   │   ├── server.py         socket binding and uvicorn lifecycle
│   │   │   ├── shutdown.py       cooperative shutdown signal
│   │   │   ├── threads.py        detached blocking work
│   │   │   └── watchdog.py       parent-process supervision
│   │   ├── tools/
│   │   │   ├── dictate.py        laa-dictate: the pipeline from a terminal
│   │   │   └── benchmark.py      laa-benchmark: measure models on this machine
│   │   ├── bootstrap.py          create_app; the only place assembly happens
│   │   └── __main__.py           CLI entrypoint
│   └── pyproject.toml
│
├── schema/openapi.json       Committed API contract; regenerated, checked in CI
├── models/                   Model weights, downloaded on first run, never committed
├── scripts/
│   └── generate_icons.py     Bundle icons, defined in code rather than committed blind
├── docs/
└── .github/workflows/
```

## Conventions

**Package `__init__.py` files contain a docstring and nothing else.** They do not re-export.
See `docs/Architecture.md` for the import cycle this prevents.

**Directories are added in the phase that needs them.** `adapters/`, `domain/`, and `pipeline/`
appear when Phase 1 starts implementing the audio path. Empty scaffolding directories are not
created ahead of use.

**Nothing large is committed.** Model weights (`models/`), build output (`ui/dist`, `target/`),
and generated TypeScript (`ui/src/services/generated/`) are all ignored. `schema/openapi.json`
*is* committed, because its diff is the drift signal.

**The engine's test suite (`engine/tests/`) is not tracked in this repository.** It exists and
runs in local development, but is intentionally excluded from what's pushed. Commands elsewhere
in the docs reflect this: only `ruff`, `mypy`, and the Rust/TypeScript equivalents are given as
reproducible checks, since those are what a fresh clone can actually run.

Note that the repository's `.gitignore` scopes `/lib/` to the root rather than leaving it
unanchored, so a future `ui/src/lib/` is not silently excluded — git cannot re-include a path
whose parent directory is ignored.
