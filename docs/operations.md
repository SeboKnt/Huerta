# Operations guide

## Required cloud environment variables

- `COSMOS_URI`
- `COSMOS_KEY`
- `COSMOS_DATABASE`
- `COSMOS_CONTAINER`
- `DEVICE_TOKEN_SECRET`
- Optional: `ALLOWED_WRITE_ACCOUNTS` (comma/semicolon separated)

## Local development

From `/home/runner/work/Huerta/Huerta/cloud`:

1. `python -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `func start`

## Tests

From `/home/runner/work/Huerta/Huerta/cloud`:

- `python -m unittest discover -s tests`

## Device lifecycle at a glance

1. Device polls `/agent/poll` with serial + telemetry.
2. Backend resolves hashed device ID and returns control/command payload.
3. Device executes commands and reports completion through `/agent/report`.
4. Backend updates telemetry, terminal output, and control flags.
5. Device may deep sleep when not kept awake or when sleep is requested.

## Troubleshooting quick checks

- `GET /health` for Cosmos configuration/connectivity
- `GET /auth/debug` for identity header/allowlist diagnostics
- Device-side serial monitor for shell and heartbeat logs
