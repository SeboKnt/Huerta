import os
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

from core.time_utils import _utc_now_iso, _parse_utc


def _extract_telemetry(body: dict) -> dict:
    telemetry = body.get("telemetry") if isinstance(body.get("telemetry"), dict) else {}

    ram_free_bytes = body.get("ram_free_bytes", telemetry.get("ram_free_bytes"))
    ram_min_free_bytes = body.get("ram_min_free_bytes", telemetry.get("ram_min_free_bytes"))
    cpu_load_pct = body.get("cpu_load_pct", telemetry.get("cpu_load_pct"))
    uptime_sec = body.get("uptime_sec", telemetry.get("uptime_sec"))
    stack_free_words = body.get("stack_free_words", telemetry.get("stack_free_words"))
    water_level_percent = body.get("water_level_percent", telemetry.get("water_level_percent"))
    temperature_c = body.get("temperature_c", telemetry.get("temperature_c"))
    humidity_pct = body.get("humidity_pct", telemetry.get("humidity_pct"))
    soil_moisture_pct = body.get("soil_moisture_pct", telemetry.get("soil_moisture_pct"))

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
    if not isinstance(water_level_percent, int):
        water_level_percent = None

    def _normalize_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    temperature_c = _normalize_float(temperature_c)
    humidity_pct = _normalize_float(humidity_pct)
    soil_moisture_pct = _normalize_float(soil_moisture_pct)

    if humidity_pct is not None:
        humidity_pct = max(0.0, min(100.0, humidity_pct))
    if soil_moisture_pct is not None:
        soil_moisture_pct = max(0.0, min(100.0, soil_moisture_pct))

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
        "water_level_percent": water_level_percent,
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "soil_moisture_pct": soil_moisture_pct,
        "reported_at_utc": _utc_now_iso(),
    }

    return {key: value for key, value in telemetry_payload.items() if value is not None}


def _send_telegram_notification(plant_name: str, device_id: str, moisture: float, target: float) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    msg = (
        f"⚠️ <b>Huerta Warnung!</b>\n"
        f"Die Pflanze <b>{plant_name}</b> (SN: <code>{device_id}</code>) ist zu trocken: <b>{moisture:.0f}%</b> (Sollwert: {target:.0f}%).\n"
        f"💧 Bitte gießen!"
    )
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML"
    }
    
    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            response.read()
    except Exception as exc:
        logging.error("Failed to send Telegram notification: %s", exc)


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

    # Live-Alarmierung (Telegram)
    soil_moisture = telemetry.get("soil_moisture_pct")
    if soil_moisture is not None:
        plant_profile = item.get("plant_profile", {})
        target = plant_profile.get("soil_moisture_pct")
        if target is None:
            target = item.get("watering_schedule", {}).get("soil_moisture_pct")

        target_val = float(target) if target is not None else 30.0

        if float(soil_moisture) < target_val:
            last_alert_str = item.get("last_telegram_alert_utc", "")
            should_send = True

            if last_alert_str:
                last_alert_dt = _parse_utc(last_alert_str)
                if last_alert_dt:
                    now = datetime.now(timezone.utc)
                    if now - last_alert_dt < timedelta(hours=12):
                        should_send = False

            if should_send:
                plant_name = plant_profile.get("plant_name") or item.get("name") or item.get("id") or "Unbekannt"
                device_id = item.get("id") or "unbekannt"
                _send_telegram_notification(plant_name, device_id, float(soil_moisture), target_val)
                item["last_telegram_alert_utc"] = _utc_now_iso()
