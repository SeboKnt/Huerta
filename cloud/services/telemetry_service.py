from core.time_utils import _utc_now_iso


def _extract_telemetry(body: dict) -> dict:
    telemetry = body.get("telemetry") if isinstance(body.get("telemetry"), dict) else {}

    ram_free_bytes = body.get("ram_free_bytes", telemetry.get("ram_free_bytes"))
    ram_min_free_bytes = body.get("ram_min_free_bytes", telemetry.get("ram_min_free_bytes"))
    cpu_load_pct = body.get("cpu_load_pct", telemetry.get("cpu_load_pct"))
    uptime_sec = body.get("uptime_sec", telemetry.get("uptime_sec"))
    stack_free_words = body.get("stack_free_words", telemetry.get("stack_free_words"))

    if not isinstance(ram_free_bytes, int):
        ram_free_bytes = None
    if not isinstance(ram_min_free_bytes, int):
        ram_min_free_bytes = None
    if not isinstance(cpu_load_pct, int):
        cpu_load_pct = None
    if not isinstance(uptime_sec, int):
        uptime_sec = None
    if not isinstance(stack_free_words, int):
        stack_free_words = None

    if cpu_load_pct is not None:
        if cpu_load_pct < 0:
            cpu_load_pct = 0
        if cpu_load_pct > 100:
            cpu_load_pct = 100

    telemetry_payload = {
        "ram_free_bytes": ram_free_bytes,
        "ram_min_free_bytes": ram_min_free_bytes,
        "cpu_load_pct": cpu_load_pct,
        "uptime_sec": uptime_sec,
        "stack_free_words": stack_free_words,
        "reported_at_utc": _utc_now_iso(),
    }

    return {key: value for key, value in telemetry_payload.items() if value is not None}


def _store_telemetry(item: dict, telemetry: dict) -> None:
    if not telemetry:
        return

    item["telemetry_latest"] = telemetry
    history = item.get("telemetry_history")
    if not isinstance(history, list):
        history = []

    history.append(telemetry)
    if len(history) > 50:
        history = history[-50:]

    item["telemetry_history"] = history
