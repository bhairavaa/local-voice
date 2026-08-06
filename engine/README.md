# Engine

The offline speech and text-processing sidecar for Local Voice.

The engine is a plain FastAPI application. It runs as a child process of the Tauri desktop
shell, but it is deliberately independent: you can start it and exercise it with `curl`
without building any Rust.

## Running

```bash
uv sync
uv run python -m app --environment development --log-format console
```

On startup the engine writes exactly one line to **stdout**:

```json
{"port":51234,"token":"…","pid":31048,"version":"0.1.0","schema_version":1}
```

That line is the handshake the desktop shell consumes. All log output goes to **stderr** so
it can never corrupt it. Every route requires the token as a bearer credential:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:<port>/health
```

## Configuration

Precedence, highest first: command-line flags → `LAA_` environment variables → TOML file →
declared defaults. Nested keys use a double underscore.

```bash
LAA_LOGGING__LEVEL=DEBUG LAA_SERVER__PORT=8765 uv run python -m app
```

The TOML file location defaults to the per-platform config directory and can be overridden
with `--config` or `LAA_CONFIG_FILE`.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```
