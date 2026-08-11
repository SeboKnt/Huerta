from core.time_utils import _is_connected, _parse_utc, _utc_now_iso


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
        "temperature_c": telemetry.get("temperature_c"),
        "humidity_pct": telemetry.get("humidity_pct"),
        "soil_moisture_pct": telemetry.get("soil_moisture_pct"),
    }


def _get_irrigation_history(item: dict) -> list[dict]:
    history = item.get("irrigation_history")
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _append_irrigation_cycle(item: dict, duration_sec: int, source: str = "manual") -> None:
    history = _get_irrigation_history(item)
    history.insert(
        0,
        {
            "started_at_utc": _utc_now_iso(),
            "duration_sec": int(duration_sec),
            "source": source,
        },
    )
    item["irrigation_history"] = history[:20]


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


def _merge_device_config(item: dict, config_payload: dict) -> dict:
    if not isinstance(config_payload, dict):
        return _get_device_config(item)

    config = item.get("device_config")
    if not isinstance(config, dict):
        config = {}

    updates = {}
    for key in ("wifi_ssid", "wifi_password", "report_interval_sec", "watering_duration_sec", "sleep_mode", "wake_interval_sec"):
        if key in config_payload:
            value = config_payload[key]
            if key in ("report_interval_sec", "watering_duration_sec", "wake_interval_sec"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = 60 if key == "report_interval_sec" else 600 if key == "wake_interval_sec" else 60
            elif key == "sleep_mode":
                value = bool(value)
            updates[key] = value

    merged = {**config, **updates}
    item["device_config"] = merged
    return merged


def _set_ota_status(item: dict, state: str, version: str = "", message: str = "") -> dict:
    status = item.get("ota_status")
    if not isinstance(status, dict):
        status = {}

    state = str(state or "idle").strip() or "idle"
    status["state"] = state
    if version is not None:
        status["version"] = str(version)
    if message is not None:
        status["message"] = str(message)
    status["last_updated_utc"] = _utc_now_iso()
    item["ota_status"] = status
    return status


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


def _merge_watering_schedule(item: dict, schedule_payload: dict) -> dict:
    if not isinstance(schedule_payload, dict):
        return _get_watering_schedule(item)

    schedule = item.get("watering_schedule")
    if not isinstance(schedule, dict):
        schedule = {}

    updates = {}
    if "enabled" in schedule_payload:
        updates["enabled"] = bool(schedule_payload["enabled"])
    for key in ("interval_hours", "duration_sec"):
        if key in schedule_payload:
            try:
                updates[key] = max(0, int(schedule_payload[key]))
            except (TypeError, ValueError):
                updates[key] = 0
    for key in ("day", "start_time"):
        if key in schedule_payload and isinstance(schedule_payload[key], str):
            updates[key] = schedule_payload[key].strip()

    merged = {**schedule, **updates}
    item["watering_schedule"] = merged
    return _get_watering_schedule(item)


def _merge_plant_profile(item: dict, profile_payload: dict) -> dict:
    if not isinstance(profile_payload, dict):
        return _get_plant_context(item)

    profile = item.get("plant_profile")
    if not isinstance(profile, dict):
        profile = {}

    updates = {}
    for key in ("plant_name", "plant_species", "room", "notes"):
        if key in profile_payload and isinstance(profile_payload[key], str):
            updates[key] = profile_payload[key].strip()
    for key in ("temperature_c", "humidity_pct", "soil_moisture_pct"):
        if key in profile_payload:
            value = profile_payload[key]
            if value is None or value == "":
                updates[key] = None
            else:
                try:
                    updates[key] = float(value)
                except (TypeError, ValueError):
                    pass

    merged = {**profile, **updates}
    item["plant_profile"] = merged
    return _get_plant_context(item)


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


def _get_plant_context(item: dict) -> dict:
    profile = item.get("plant_profile")
    if not isinstance(profile, dict):
        profile = {}

    telemetry = item.get("telemetry_latest")
    if not isinstance(telemetry, dict):
        telemetry = {}

    def _climate_value(telemetry_key: str, profile_key: str):
        live = telemetry.get(telemetry_key)
        if live is not None:
            return live
        return profile.get(profile_key)

    return {
        "plant_name": profile.get("plant_name") or item.get("name", "Unnamed plant"),
        "plant_species": profile.get("plant_species", ""),
        "room": profile.get("room", "Unknown room"),
        "temperature_c": _climate_value("temperature_c", "temperature_c"),
        "humidity_pct": _climate_value("humidity_pct", "humidity_pct"),
        "soil_moisture_pct": _climate_value("soil_moisture_pct", "soil_moisture_pct"),
        "notes": profile.get("notes", ""),
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
        "plant_context": _get_plant_context(item),
    }
