import azure.functions as func

from core.app import app
from core.auth import _compute_device_auth_hash, _log_unauthorized_attempt
from core.db import _get_container_client
from core.device_view import _ensure_terminal_fields, _to_device_response
from core.http import _json_response
from core.time_utils import _utc_now_iso
from services.telemetry_service import _extract_telemetry, _store_telemetry


@app.route(route="agent/poll", methods=["POST"])
def agent_poll(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    if not isinstance(body, dict):
        body = {}

    serial_number = body.get("serial_number", "")
    if not isinstance(serial_number, str) or not serial_number.strip():
        _log_unauthorized_attempt("poll", "", "missing serial_number", req)
        return _json_response({"status": "error", "message": "serial_number is required"}, status_code=400)

    serial_number = serial_number.strip()
    device_id = _compute_device_auth_hash(serial_number)

    try:
        container = _get_container_client()
        item = container.read_item(item=device_id, partition_key=device_id)
    except Exception as exc:
        return _json_response({"status": "error", "message": f"failed to poll commands: {exc}"}, status_code=500)

    _ensure_terminal_fields(item)
    _store_telemetry(item, _extract_telemetry(body))

    queued = [c for c in item.get("terminal_commands", []) if c.get("status") == "queued"]
    command_payload = [dict(c) for c in queued]
    # Queue semantics: once fetched by device, commands are removed from storage.
    # This prevents stale pending commands after reboot/offline periods.
    item["terminal_commands"] = []

    item["last_seen_utc"] = _utc_now_iso()
    if isinstance(body.get("status"), str):
        item["status"] = body["status"]
    elif item.get("status") == "restarting":
        # Clear stale restart status once the device polls again.
        item["status"] = "online"
    if isinstance(body.get("ip"), str):
        item["ip"] = body["ip"]
    if isinstance(body.get("firmware"), str):
        item["firmware"] = body["firmware"]

    try:
        container.replace_item(item=device_id, body=item)
    except Exception:
        pass

    payload = {
        "status": "ok",
        "device": _to_device_response(item),
        "commands": command_payload,
        "control": {
            "wake_requested": bool(item.get("wake_requested", False)),
            "deep_sleep_requested": bool(item.get("deep_sleep_requested", False)),
            "terminal_session_active": bool(item.get("terminal_session_active", False)),
            "keep_awake_until_utc": item.get("keep_awake_until_utc", ""),
            "identify_requested": bool(item.get("identify_requested", False)),
            "identify_duration_sec": int(item.get("identify_duration_sec", 15)),
            "watering_requested": bool(item.get("watering_requested", False)),
            "watering_duration_sec": int(item.get("watering_duration_sec", 0) or 0),
            "watering_request_id": item.get("watering_request_id", ""),
            "relay_debug_requested": bool(item.get("relay_debug_requested", False)),
            "relay_debug_state": item.get("relay_debug_state", ""),
            "relay_debug_request_id": item.get("relay_debug_request_id", ""),
        },
    }
    return _json_response(payload, status_code=200)


@app.route(route="agent/report", methods=["POST"])
def agent_report(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _json_response({"status": "error", "message": "invalid JSON body"}, status_code=400)

    if not isinstance(body, dict):
        return _json_response({"status": "error", "message": "invalid JSON body"}, status_code=400)

    serial_number = body.get("serial_number", "")
    if not isinstance(serial_number, str) or not serial_number.strip():
        _log_unauthorized_attempt("report", "", "missing serial_number", req)
        return _json_response({"status": "error", "message": "serial_number is required"}, status_code=400)

    serial_number = serial_number.strip()
    device_id = _compute_device_auth_hash(serial_number)

    try:
        container = _get_container_client()
        item = container.read_item(item=device_id, partition_key=device_id)
    except Exception as exc:
        return _json_response({"status": "error", "message": f"failed to update device report: {exc}"}, status_code=500)

    _ensure_terminal_fields(item)
    item["last_seen_utc"] = _utc_now_iso()

    if isinstance(body.get("status"), str):
        item["status"] = body["status"]
    elif item.get("status") == "restarting":
        # Clear stale restart status once the device reports again.
        item["status"] = "online"
    if isinstance(body.get("ip"), str):
        item["ip"] = body["ip"]
    if isinstance(body.get("firmware"), str):
        item["firmware"] = body["firmware"]

    if body.get("deep_sleep_entering") is True:
        item["terminal_session_active"] = False
        item["deep_sleep_requested"] = False

    if isinstance(body.get("identify_state"), bool):
        item["identify_requested"] = body["identify_state"]
        if body["identify_state"] is False:
            item["identify_requested_at_utc"] = _utc_now_iso()
        else:
            item["identify_duration_sec"] = int(body.get("identify_duration_sec", 15))
            item["identify_requested_at_utc"] = _utc_now_iso()

    watering_done_request_id = body.get("watering_done_request_id", "")
    if isinstance(watering_done_request_id, str) and watering_done_request_id:
        if watering_done_request_id == item.get("watering_request_id", ""):
            item["watering_requested"] = False
            item["watering_request_id"] = ""
            item["watering_duration_sec"] = 0

    relay_debug_done_request_id = body.get("relay_debug_done_request_id", "")
    if isinstance(relay_debug_done_request_id, str) and relay_debug_done_request_id:
        if relay_debug_done_request_id == item.get("relay_debug_request_id", ""):
            item["relay_debug_requested"] = False
            item["relay_debug_request_id"] = ""
            item["relay_debug_state"] = ""

    telemetry = _extract_telemetry(body)
    _store_telemetry(item, telemetry)

    output_lines = body.get("output_lines", [])
    if isinstance(output_lines, list):
        for line in output_lines[:20]:
            if isinstance(line, str) and line.strip():
                item["terminal_output"].append(f"{_utc_now_iso()} | {line.strip()}")
        if len(item["terminal_output"]) > 400:
            item["terminal_output"] = item["terminal_output"][-400:]

    executed_ids = body.get("executed_command_ids", [])
    if isinstance(executed_ids, list) and executed_ids:
        executed_set = set([x for x in executed_ids if isinstance(x, str)])
        for cmd in item.get("terminal_commands", []):
            if cmd.get("id") in executed_set:
                cmd["status"] = "done"
                cmd["done_at_utc"] = _utc_now_iso()

    # Keep queue clean across boots/reconnects; commands are ephemeral.
    if isinstance(item.get("terminal_commands"), list):
        item["terminal_commands"] = []

    if body.get("identify_done") is True:
        item["identify_requested"] = False

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response({"status": "error", "message": f"failed to persist device report: {exc}"}, status_code=500)

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)
