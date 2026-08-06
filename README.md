# Local AI Assistant

Offline, privacy-first dictation for the desktop. Press a hotkey, speak, and get clean text you
can paste anywhere.

Speech recognition and text cleanup run entirely on your machine. No audio and no text is sent
anywhere. There are no accounts, no telemetry, and no cloud services.

> **Status: the full loop is built.** Dictation works from the terminal today. The desktop
> shell compiles, registers global hotkeys, and copies results to the clipboard — but it has
> not yet been run end to end by a human, so treat the hotkey path as untested rather than
> broken.

## Try it now

```powershell
cd engine
uv sync
uv run laa-dictate
```

Speak, pause, and the text is printed. On first run this downloads the speech model
(480 MB); after that it is entirely offline. Pipe it straight to the clipboard:

```powershell
uv run laa-dictate | clip
```

## The workflow

| | Key | |
| --- | --- | --- |
| Start or stop dictating | `Ctrl` `Alt` `Space` | works from any application |
| Discard a recording | `Ctrl` `Alt` `Esc` | |

Speak, press the hotkey again, and the text is on your clipboard before the window even
appears — so you can switch away immediately and paste. Recording also stops on its own once
you pause.

Bindings are read from `LAA_SHELL__TOGGLE_HOTKEY` and `LAA_SHELL__CANCEL_HOTKEY`. A shortcut
already claimed by another application is reported in the log and skipped; the application
still starts.

## The one time it touches the network

Model weights are downloaded on first run. That is the only network access in the product's
life, and it is stated plainly here rather than buried. After setup the application runs with
no outbound connections at all — a property enforced by tests, not by assertion.

## How it is built

Two processes, each doing what it is good at:

- **Tauri shell (Rust)** owns everything touching the operating system: hotkeys, clipboard,
  tray, window focus, auto-paste. Global hotkeys from Python on Windows would need low-level
  keyboard hooks that require elevation and get flagged as keyloggers.
- **Engine sidecar (Python)** owns the AI pipeline: audio, voice activity detection, speech
  recognition, vocabulary correction, text enhancement.

They meet over HTTP on loopback with an ephemeral port and a per-session token, published by
the engine as a single line on stdout at startup. The engine cannot be configured to listen
off-machine, and every route requires the token.

See [docs/Architecture.md](docs/Architecture.md) for the reasoning, including why the handshake
carries a process id and why that matters.

## Getting started

```powershell
pwsh scripts/doctor.ps1     # reports what is missing; installs nothing
```

The engine and interface need only Python and Node. The desktop shell additionally needs Rust
and the MSVC C++ build tools.

```powershell
cd engine; uv sync; uv run pytest
cd ../ui;  npm install; npm run build
```

Full instructions are in [docs/DeveloperGuide.md](docs/DeveloperGuide.md).

## Design principles

- **Privacy is a property of the code, not a promise.** The loopback restriction, the token
  gate, and transcript redaction are all enforced mechanically and covered by tests.
- **Offline first.** The application must work identically with the network disconnected.
- **Built for modest hardware.** The reference machine is a CPU-only laptop with integrated
  graphics. CTranslate2 has no Intel GPU backend, so CPU performance is the target, not a
  fallback. The default model was chosen by measurement on that machine, not by guesswork —
  `uv run laa-benchmark` reproduces it.
- **Nothing is added to your words.** The default text pass fixes punctuation, casing, and
  grammar; it is not permitted to invent content. That is enforced in code, not just asked for
  in a prompt: a rewrite whose length shows the model summarised or answered the dictation is
  discarded and the raw transcript kept. Expanding a prompt is a separate, opt-in profile.
- **English only.** Deliberately. The English-specialised Whisper models are smaller and more
  accurate than the multilingual ones at the same size, so the others are not offered.

## Documentation

- [Architecture](docs/Architecture.md)
- [Project structure](docs/ProjectStructure.md)
- [Developer guide](docs/DeveloperGuide.md)
