# Architecture

## Why it is split this way

Two processes, in two languages, chosen for what each is actually good at.

**Rust owns the operating system.** Global hotkeys, clipboard, tray, window focus, and
auto-paste all live in the Tauri shell. Doing this from Python on Windows would require
low-level keyboard hooks, which need elevation and are routinely flagged as keyloggers by
antivirus software. Tauri registers shortcuts from the process that already owns the window
message loop, which is where they belong.

**Python owns the AI pipeline.** Audio capture, voice activity detection, speech recognition,
vocabulary correction, and text enhancement. This is where the mature libraries are.

```
┌──────────────────────────────────────────────┐
│ Tauri v2 desktop shell (Rust, parent)        │
│  hotkeys · tray · windows · clipboard        │
│  focus capture/restore · auto-paste          │
│  engine lifecycle + health                   │
│                                              │
│   ┌────────────────┐  HTTP 127.0.0.1         │
│   │ WebView        │  ephemeral port         │
│   │ React + TS     │  + per-session token    │
│   └────────────────┘                         │
└───────────────────┬──────────────────────────┘
                    │ spawn, then read one stdout line
┌───────────────────▼──────────────────────────┐
│ Engine sidecar (Python 3.12, FastAPI)        │
│  audio → VAD → ASR → vocabulary → enhance    │
└──────────────────────────────────────────────┘
```

## The startup handshake

The engine binds its socket *before* uvicorn starts, so the ephemeral port is known in time to
publish. It then writes exactly one line to stdout and nothing else, ever:

```json
{"port":51234,"token":"…","pid":31048,"version":"0.1.0","schema_version":1}
```

All log output goes to stderr. A stray log record on stdout would corrupt the line the shell
is parsing, so this separation is enforced by a test.

`schema_version` lets a future change be detected rather than silently misparsed.

### The pid field is not redundant

`pid` is the process actually running the engine, which is **not** necessarily the process the
shell spawned. On Windows a virtualenv's `python.exe` is a trampoline that launches the real
interpreter as a further child with a different pid. A shell that force-killed only its direct
child could leave the engine running as an orphan, still holding the microphone. The handshake
pid is authoritative.

## Why HTTP on loopback rather than stdio

Stdio would avoid a listening socket entirely. HTTP was chosen because it keeps the engine
independently runnable and testable — `pytest` and `curl` work against it with no Rust in the
picture, which keeps the AI work unblocked by the desktop build.

The cost is that any local process can reach the port. That is closed by two things:

1. **Loopback is enforced in code.** `ServerSettings` rejects any host outside
   `{127.0.0.1, ::1, localhost}`, so the engine cannot be misconfigured into exposure.
2. **A per-session bearer token**, minted at launch and delivered only over the handshake pipe.
   Every route requires it.

## Process supervision

Supervision runs in both directions, because either process can die abruptly:

- The **shell stops the engine** on exit.
- The **engine watches the shell** by pid and exits when it disappears. This is the reliable
  half: it survives the shell being killed from Task Manager, and does not depend on the
  process tree.

## Privacy as a property of the code

Claims are enforced mechanically, not by discipline:

| Claim | Enforcement |
| --- | --- |
| Never reachable off-machine | Validator rejects non-loopback hosts |
| No other process can drive it | Per-session bearer token on every route |
| Transcripts are not logged | `Sensitive[T]` renders as `<redacted>` in `str` and `repr`; disclosure needs an explicit opt-in **and** DEBUG level |
| No orphaned microphone handle | Parent-pid watchdog |

`Sensitive` is the important one. Because its string forms are already redacted, an accidental
`f"{transcript}"` or `logger.info("%s", transcript)` is safe by default rather than being a
leak waiting for review to catch.

## Layering inside the engine

```
api/        thin HTTP routing, no logic
pipeline/   orchestration
adapters/   concrete implementations (audio, ASR, LLM)
domain/     entities and ports, zero I/O
```

Dependencies point inward. Assembly happens once, in `bootstrap.create_app`, and handlers
receive what they need through `EngineContext` rather than reaching for module-level state.

Package `__init__.py` files deliberately do **not** re-export their contents. Barrel exports
here caused a real import cycle (`runtime.context` → `runtime/__init__` → `runtime.server` →
`bootstrap` → `api.dependencies` → `runtime.context`). Importing from concrete modules is both
clearer about provenance and immune to that class of failure.

## Streaming readiness

Version 1 transcribes in batch after the user stops speaking. The interfaces are nonetheless
shaped as async iterators from the outset:

```python
class AudioSource(Protocol):
    def stream(self) -> AsyncIterator[AudioChunk]: ...

class Transcriber(Protocol):
    def transcribe(self, chunks: AsyncIterator[AudioChunk]) -> AsyncIterator[TranscriptSegment]: ...
```

The batch implementation drains the iterator and yields one segment. Adding streaming later
means writing a second adapter — no interface change, no pipeline change, no interface rewrite.
These ports are introduced in the phase that first implements them, not speculatively.

## Contract generation

The engine exports its own OpenAPI document (`python -m app --export-openapi`), which is
committed at `schema/openapi.json` and turned into TypeScript by `openapi-typescript`. Changing
a Pydantic model without regenerating shows up as a diff in CI rather than as a runtime
mismatch between the two languages.

## Hardware constraints shaping later phases

Measured on the development machine, and load-bearing for model defaults:

- **Thread count dominates transcription speed, and intuition got it backwards.** This
  document previously claimed that using every logical processor would push work onto
  efficiency cores and slow transcription down. Measured on the i5-1335U, the opposite is true
  by a factor of nearly five:

  | threads | 2 | 4 | 6 | 8 | 12 |
  | --- | --- | --- | --- | --- | --- |
  | realtime factor | 0.54 | 0.51 | 0.45 | 0.11 | 0.10 |

  The default is now every logical processor. The lesson generalises: performance claims in
  this project need `laa-benchmark` behind them, not reasoning about core topology.
- **~16 GB RAM with little free in practice.** Speech and language models must not both be
  resident without a headroom check. Whisper `medium` and `large-v3` are not viable defaults.
- **Intel Iris Xe, and CTranslate2 is CUDA-only.** There is no GPU path on this hardware. CPU
  is not a fallback; it is the target.
