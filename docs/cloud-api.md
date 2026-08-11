# Cloud API reference

Base: Azure Functions app with no route prefix (`host.json` sets `routePrefix` to empty).

## Public/read endpoints

- `GET /` – static dashboard HTML
- `GET /health` – service and Cosmos connectivity health
- `GET /auth/debug` – auth diagnostics + write-access eligibility
- `GET /devices` – list devices (returns HTML dashboard when `Accept: text/html`)
- `GET /devices/{device_id}` – single device model
- `GET /devices/{device_id}/summary` – normalized summary (stats, alerts, relay)
- `GET /devices/{device_id}/terminal` – terminal session/output state

## Write/protected endpoints

These require authenticated Microsoft identity headers and optional allowlist approval.

- `POST /devices` – register device from serial + name
- `PATCH /devices/{device_id}` – rename device
- `DELETE /devices/{device_id}` – delete device
- `POST /devices/{device_id}/power/wake` – request wake and keep-awake window
- `POST /devices/{device_id}/power/sleep` – request deep sleep
- `POST /devices/{device_id}/action` – one of:
  - `restart`
  - `identify` (with `duration_sec` 1..120)
  - `relay_toggle`
  - `relay_on` / `relay_off`
- `POST /devices/{device_id}/terminal/open` – open terminal session (`keep_awake_seconds` 30..3600)
- `POST /devices/{device_id}/terminal/command` – queue terminal command (max length 200)

## Firmware-facing endpoints

- `POST /agent/poll`
  - Input: `serial_number` + optional telemetry/status
  - Output: control flags, queued commands, normalized device payload
- `POST /agent/report`
  - Input: serial + execution/status/telemetry updates
  - Effect: persists command execution output, identify state, relay completion, telemetry, and power/session transitions

## Identity and authorization

- Device identity key = `HMAC_SHA256(serial_number, DEVICE_TOKEN_SECRET)`
- Write access is restricted to Microsoft identities (`aad`, `microsoft`, `entra`)
- Optional allowlist env var: `ALLOWED_WRITE_ACCOUNTS`
