# Firmware reference

## Purpose

The ESP32 firmware initializes relay control, connects to Wi‑Fi, starts a UART shell, and runs a cloud heartbeat loop.

## Main modules

- `main.c` – boot flow (`nvs_flash_init`, `relay_init`, Wi‑Fi start, shell start, heartbeat task)
- `wifi.c` – STA mode connection, reconnect, connectivity check, and active scan output
- `relay.c` – GPIO23 active-low relay state management (`on`, `off`, `toggle`)
- `shell.c` – UART shell input loop and command execution API
- `cloud_client.c` – HTTPS poll/report loop, telemetry upload, remote command execution, identify flow, deep sleep behavior

## Build-time config

`/home/runner/work/Huerta/Huerta/main/CMakeLists.txt` reads `/home/runner/work/Huerta/Huerta/.env` and compiles these macros:

- `WIFI_SSID`
- `WIFI_PASSWORD`
- `CLOUD_BASE_URL`

Required `.env` keys:

- `APP_WIFI_SSID`
- `APP_WIFI_PASSWORD`
- `APP_CLOUD_BASE_URL`

## Runtime behavior

- Heartbeat interval: 60s (`/agent/poll`)
- Keep-awake polling interval: 5s while terminal or wake is active
- Deep-sleep wake interval: 30s when sleeping
- Telemetry payload includes RAM, CPU load estimate, uptime, and stack high-water mark

## Supported shell / remote commands

- `help`
- `status`
- `reconnect`
- `scan`
- `serial`
- `identify`
- `relay`
- `relay t`
