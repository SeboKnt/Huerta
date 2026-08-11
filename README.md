# Huerta

Huerta is an IoT irrigation platform built with two parts:

- **ESP32 firmware** (`/main`): connects to Wi‑Fi, drives a relay, executes shell commands, sends telemetry, and follows cloud control signals.
- **Azure Functions backend** (`/cloud`): stores device state in Cosmos DB, exposes device APIs, and coordinates wake/sleep, terminal, identify, and relay actions.

## Repository layout

- `/main` – ESP-IDF firmware sources (Wi‑Fi, relay, shell, cloud heartbeat client)
- `/cloud` – Python Azure Functions app + routes + core services + tests
- `/.env.example` – firmware environment template
- `/docs` – focused project documentation

## Quick start

### 1) Firmware (ESP-IDF)

1. Copy env template:
   - `cp /home/runner/work/Huerta/Huerta/.env.example /home/runner/work/Huerta/Huerta/.env`
2. Edit `.env` and set:
   - `APP_WIFI_SSID`
   - `APP_WIFI_PASSWORD`
   - `APP_CLOUD_BASE_URL`
3. Build/flash with ESP-IDF from repo root:
   - `idf.py build`
   - `idf.py -p <PORT> flash monitor`

### 2) Cloud backend (Azure Functions)

1. Create virtualenv and install deps:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r /home/runner/work/Huerta/Huerta/cloud/requirements.txt`
2. Set required environment variables:
   - `COSMOS_URI`
   - `COSMOS_KEY`
   - `COSMOS_DATABASE`
   - `COSMOS_CONTAINER`
   - `DEVICE_TOKEN_SECRET`
3. Start Functions host from `/home/runner/work/Huerta/Huerta/cloud`:
   - `func start`

## Device command surface

The firmware shell and remote command execution support:

- `help`
- `status`
- `reconnect`
- `scan`
- `serial`
- `identify`
- `relay`
- `relay t`

## API surface (high-level)

- Health: `GET /health`
- Devices: `GET /devices`, `POST /devices`, `GET/PATCH/DELETE /devices/{device_id}`
- Device summary: `GET /devices/{device_id}/summary`
- Power: `POST /devices/{device_id}/power/wake`, `POST /devices/{device_id}/power/sleep`
- Actions: `POST /devices/{device_id}/action`
- Terminal: `GET /devices/{device_id}/terminal`, `POST /devices/{device_id}/terminal/open`, `POST /devices/{device_id}/terminal/command`
- Agent endpoints (firmware-facing): `POST /agent/poll`, `POST /agent/report`
- Auth diagnostics: `GET /auth/debug`

See detailed docs:

- `/home/runner/work/Huerta/Huerta/docs/firmware.md`
- `/home/runner/work/Huerta/Huerta/docs/cloud-api.md`
- `/home/runner/work/Huerta/Huerta/docs/operations.md`

## Run tests

From `/home/runner/work/Huerta/Huerta/cloud`:

- `python -m unittest discover -s tests`

## Notes

- Write routes require authenticated Microsoft identity and optional allowlist controls.
- Device IDs are HMAC-SHA256 hashes of serial numbers using `DEVICE_TOKEN_SECRET`.
