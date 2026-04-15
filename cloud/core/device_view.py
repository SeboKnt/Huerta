from core.time_utils import _is_connected


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
    }


def _to_device_response(item: dict) -> dict:
    device_id = item.get("deviceId") or item.get("id") or ""
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
        "relay_debug_state": item.get("relay_debug_state", ""),
        "relay_debug_request_id": item.get("relay_debug_request_id", ""),
        "telemetry": _telemetry_summary(item),
    }
