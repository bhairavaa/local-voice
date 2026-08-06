# Developer guide

## Prerequisites

Run the detector first. It reports only; it never installs anything.

```powershell
pwsh scripts/doctor.ps1
```

| Component | Needed for | Install |
| --- | --- | --- |
| Python 3.12+ | engine | <https://www.python.org/downloads/> |
| uv | engine | `python -m pip install uv` |
| Node.js 20+ | interface | <https://nodejs.org/> |
| Rust 1.77+ | desktop shell | <https://rustup.rs> |
| MSVC C++ build tools | desktop shell | "Desktop development with C++" from <https://visualstudio.microsoft.com/visual-cpp-build-tools/> |
| WebView2 runtime | desktop shell | Preinstalled on Windows 11 |

The engine and interface can be developed with no Rust toolchain present. Only the desktop
shell requires it.

## Dictating

The whole pipeline runs from the terminal, with no Rust and no desktop shell:

```powershell
cd engine
uv run laa-dictate                                  # speak, pause, get text
uv run laa-dictate --model base.en                  # faster, less accurate
uv run laa-dictate --enhance --profile email        # clean up with Ollama
uv run laa-dictate --quiet | clip                   # straight to the clipboard
```

Progress goes to stderr and only the transcript to stdout, so piping works.

### Choosing a model

Defaults were set by measurement, not assumption. Reproduce it on your own machine:

```powershell
uv run laa-benchmark --models tiny.en base.en small.en
uv run laa-benchmark --audio my-voice.wav           # a truer figure than synthetic audio
```

On the reference machine (i5-1335U, CPU only, four threads) `small.en` transcribes twenty
seconds of audio in 2.3 seconds, which is why it is the default.

### Text cleanup

Optional and off by default. It needs [Ollama](https://ollama.com) installed natively — not
Docker — plus a model:

```powershell
ollama pull qwen2.5:3b-instruct
```

Then set `enhancement.enabled = true`, or pass `--enhance`. The configured URL must be
loopback; the validator rejects anything else, so a transcript cannot be sent off the machine
by editing a config file. If Ollama is not running, dictation still works and returns the raw
transcript.

## Working on the engine

```powershell
cd engine
uv sync
uv run python -m app --environment development --log-format console
```

The first line on stdout is the handshake. Use its port and token to call the API:

```powershell
curl -H "Authorization: Bearer <token>" http://127.0.0.1:<port>/health
```

Checks:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

Tests needing real models or hardware are marked `slow` and excluded from the default run.
Include them with `uv run pytest -m slow`.

### Configuration

Precedence, highest first: command-line flags → `LAA_` environment variables → TOML file →
declared defaults. Nested keys use a double underscore.

```powershell
$env:LAA_LOGGING__LEVEL = "DEBUG"; uv run python -m app
```

Passing one nested value does not discard its siblings from lower-priority sources — `--port`
will not reset a host set in the TOML file. This is pinned by
`test_partial_override_preserves_sibling_values`.

### Transcripts in logs

Transcribed speech is wrapped in `Sensitive[T]` and renders as `<redacted>`. Revealing it
requires **both** `logging.include_transcripts = true` and `DEBUG` level, so raising the log
level alone can never start writing what the user dictated to disk.

## Working on the interface

```powershell
cd ui
npm install
npm run dev
```

Opened in a plain browser there is no shell to ask where the engine is, so supply it from a
running engine's handshake:

```powershell
$env:VITE_ENGINE_PORT = "51234"; $env:VITE_ENGINE_TOKEN = "…"; npm run dev
```

Checks:

```powershell
npm run lint
npm run typecheck
npm run build
```

### Regenerating the API client

TypeScript types are generated from the engine's own OpenAPI document, so the two languages
cannot drift:

```powershell
cd engine; uv run python -m app --export-openapi ../schema/openapi.json
cd ../ui; npm run generate:types
```

`npm run build` and `npm run typecheck` regenerate automatically. Commit `schema/openapi.json`
when it changes — CI fails if the committed document does not match what the engine produces.

## Working on the desktop shell

Requires Rust and the MSVC build tools. Note that the C++ **Redistributable** is not the same
thing as the **Build Tools** — only the latter provides `link.exe`, and Rust cannot produce a
binary without it.

```powershell
cd desktop
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check
```

To run the whole application:

```powershell
cargo install tauri-cli --version "^2"
cargo tauri dev
```

That starts the Vite dev server, builds the shell, and the shell starts the engine from
`engine/.venv` — so run `uv sync` in `engine/` first.

If `cargo` is not recognised, the terminal predates the rustup install. Open a new one, or add
it for the current session with `$env:Path += ";$env:USERPROFILE\.cargo\bin"`.

### Icons

Regenerate the bundle icons after changing the mark; the design is defined in the script rather
than committed as opaque binaries:

```powershell
python scripts/generate_icons.py
```

### Where the boundary sits

Everything touching the operating system lives in Rust: hotkeys, clipboard, window focus. The
hotkey handler does not call the engine itself — it emits an event, and the interface makes the
HTTP call using the client generated from the engine's own schema. A second HTTP client in Rust
would be a second implementation of the same contract, free to drift from it.

Hotkeys are registered from Rust only, so `capabilities/default.json` deliberately grants the
webview no shortcut permission: a compromised page cannot bind keys.

## Standards

- No hardcoded values; configuration over constants.
- Type hints everywhere in Python; `mypy --strict` must pass.
- No placeholder implementations, and no `TODO`/`FIXME` comments — ruff enforces the latter.
- Comments explain intent, not mechanics.
- Every phase must build, pass all checks, and leave earlier phases working.
