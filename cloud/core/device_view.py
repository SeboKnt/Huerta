from core.time_utils import _is_connected, _parse_utc


def _ensure_terminal_fields(item: dict) -> None:
    if not isinstance(item.get("terminal_commands"), list):
        item["terminal_commands"] = []
    if not isinstance(item.get("terminal_output"), list):
        item["terminal_output"] = []
    if "terminal_session_active" not in item:
        item["terminal_session_active"] = False


def _telemetry_summary(item: dict) -> dict:
    telemetry = item.get("telemetry_latest")
    if not isinstance(telemetry, dict):
        telemetry = {}

    return {
        "ram_free_bytes": telemetry.get("ram_free_bytes"),
        "ram_min_free_bytes": telemetry.get("ram_min_free_bytes"),
        "cpu_load_pct": telemetry.get("cpu_load_pct"),
        "uptime_sec": telemetry.get("uptime_sec"),
        "stack_free_words": telemetry.get("stack_free_words"),
        "reported_at_utc": telemetry.get("reported_at_utc", ""),
        "water_level_percent": telemetry.get("water_level_percent"),
    }


def _get_irrigation_history(item: dict) -> list[dict]:
    history = item.get("irrigation_history")
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _get_device_config(item: dict) -> dict:
    config = item.get("device_config")
    if not isinstance(config, dict):
        config = {}
    return {
        "wifi_ssid": config.get("wifi_ssid", ""),
        "wifi_password": config.get("wifi_password", ""),
        "report_interval_sec": config.get("report_interval_sec", 60),
        "watering_duration_sec": config.get("watering_duration_sec", 60),
        "sleep_mode": config.get("sleep_mode", False),
        "wake_interval_sec": config.get("wake_interval_sec", 600),
    }


def _get_ota_status(item: dict) -> dict:
    status = item.get("ota_status")
    if not isinstance(status, dict):
        status = {}
    return {
        "state": status.get("state", "idle"),
        "version": status.get("version", ""),
        "last_updated_utc": status.get("last_updated_utc", ""),
        "message": status.get("message", ""),
    }


def _get_watering_schedule(item: dict) -> dict:
    schedule = item.get("watering_schedule")
    if not isinstance(schedule, dict):
        schedule = {}

    interval_hours = schedule.get("interval_hours")
    duration_sec = schedule.get("duration_sec")
    day = schedule.get("day", "")
    start_time = schedule.get("start_time", "")

    if not isinstance(interval_hours, int):
        interval_hours = 0
    if not isinstance(duration_sec, int):
        duration_sec = 0

    main_bits = []
    if interval_hours > 0:
        main_bits.append(f"Every {interval_hours}h")
    if duration_sec > 0:
        main_bits.append(f"for {duration_sec}s")

    detail_bits = []
    if day:
        detail_bits.append(day)
    if start_time:
        detail_bits.append(f"at {start_time}")

    summary = " ".join(main_bits)
    if detail_bits:
        detail_summary = " ".join(detail_bits)
        summary = f"{summary}; {detail_summary}" if summary else detail_summary

    return {
        "enabled": bool(schedule.get("enabled", False)),
        "interval_hours": interval_hours,
        "duration_sec": duration_sec,
        "day": day,
        "start_time": start_time,
        "summary": summary or "Disabled",
    }


def _get_relay_state(item: dict) -> str:
    state = item.get("relay_debug_state")
    if isinstance(state, str) and state.strip():
        return state.strip().lower()
    if item.get("relay_debug_requested"):
        return "on"
    return "off"


def _get_alerts(item: dict) -> list[dict]:
    alerts = []
    last_seen = _parse_utc(item.get("last_seen_utc", ""))
    telemetry = item.get("telemetry_latest") if isinstance(item.get("telemetry_latest"), dict) else {}

    if not last_seen:
        alerts.append({"type": "no_recent_contact", "message": "Device has no recent contact timestamp"})
    elif not _is_connected(item):
        alerts.append({"type": "no_recent_contact", "message": "Device has not contacted the backend recently"})

    if not telemetry:
        alerts.append({"type": "missing_telemetry", "message": "No telemetry has been received yet"})

    return alerts


def _get_stats(item: dict) -> dict:
    created_at = _parse_utc(item.get("created_at_utc", ""))
    last_seen = _parse_utc(item.get("last_seen_utc", ""))
    now = None
    if created_at is not None:
        now = created_at
    if last_seen is not None and (now is None or last_seen > now):
        now = last_seen

    uptime_seconds = 0
    if created_at is not None and now is not None:
        uptime_seconds = max(0, int((now - created_at).total_seconds()))

    history = item.get("telemetry_history") if isinstance(item.get("telemetry_history"), list) else []
    alerts = _get_alerts(item)
    return {
        "uptime_seconds": uptime_seconds,
        "connected": _is_connected(item),
        "telemetry_points": len(history),
        "alert_count": len(alerts),
        "alerts": alerts,
    }


def _to_device_response(item: dict) -> dict:
    device_id = item.get("deviceId") or item.get("id") or ""
    relay_state = _get_relay_state(item)
    return {
        "id": device_id,
        "name": item.get("name", device_id),
        "status": item.get("status", "offline"),
        "firmware": item.get("firmware", "unknown"),
        "ip": item.get("ip", "0.0.0.0"),
        "last_seen_utc": item.get("last_seen_utc", ""),
        "watering_enabled": bool(item.get("watering_enabled", False)),
        "identify_requested": bool(item.get("identify_requested", False)),
        "connected": _is_connected(item),
        "terminal_session_active": bool(item.get("terminal_session_active", False)),
        "keep_awake_until_utc": item.get("keep_awake_until_utc", ""),
        "relay_debug_requested": bool(item.get("relay_debug_requested", False)),
        "relay_debug_state": relay_state,
        "relay_debug_request_id": item.get("relay_debug_request_id", ""),
        "telemetry": _telemetry_summary(item),
        "stats": _get_stats(item),
        "alerts": _get_alerts(item),
        "irrigation_history": _get_irrigation_history(item),
        "device_config": _get_device_config(item),
        "ota_status": _get_ota_status(item),
        "watering_schedule": _get_watering_schedule(item),
    }
