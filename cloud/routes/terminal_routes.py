import uuid

import azure.functions as func
from azure.cosmos import exceptions

from core.app import app
from core.auth import _require_write_access
from core.db import _get_container_client
from core.http import _json_response
from core.time_utils import _utc_now_iso, _utc_plus_seconds_iso
from core.device_view import _ensure_terminal_fields, _to_device_response
from core.time_utils import _is_connected


@app.route(route="devices/{device_id}/terminal", methods=["GET"])
def terminal_state(req: func.HttpRequest) -> func.HttpResponse:
    device_id = req.route_params.get("device_id", "")
    try:
        container = _get_container_client()
        item = container.read_item(item=device_id, partition_key=device_id)
    except exceptions.CosmosResourceNotFoundError:
        return _json_response(
            {"status": "error", "message": f"device '{device_id}' not found"},
            status_code=404,
        )
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to load terminal state: {exc}"},
            status_code=500,
        )

    _ensure_terminal_fields(item)
    output = item.get("terminal_output", [])
    commands = item.get("terminal_commands", [])
    payload = {
        "status": "ok",
        "device": _to_device_response(item),
        "terminal": {
            "connected": _is_connected(item),
            "session_active": bool(item.get("terminal_session_active", False)),
            "keep_awake_until_utc": item.get("keep_awake_until_utc", ""),
            "pending_commands": len(commands),
            "output": output[-80:],
        },
    }
    return _json_response(payload, status_code=200)


@app.route(route="devices/{device_id}/terminal/open", methods=["POST"])
def terminal_open(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

    device_id = req.route_params.get("device_id", "")
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    keep_awake_seconds = body.get("keep_awake_seconds", 900)
    if not isinstance(keep_awake_seconds, int) or keep_awake_seconds < 30 or keep_awake_seconds > 3600:
        return _json_response(
            {"status": "error", "message": "keep_awake_seconds must be an integer between 30 and 3600"},
            status_code=400,
        )

    try:
        container = _get_container_client()
        item = container.read_item(item=device_id, partition_key=device_id)
    except exceptions.CosmosResourceNotFoundError:
        return _json_response(
            {"status": "error", "message": f"device '{device_id}' not found"},
            status_code=404,
        )
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to open terminal session: {exc}"},
            status_code=500,
        )

    _ensure_terminal_fields(item)
    item["terminal_session_active"] = True
    item["wake_requested"] = True
    item["deep_sleep_requested"] = False
    item["keep_awake_until_utc"] = _utc_plus_seconds_iso(keep_awake_seconds)
    item["terminal_open_requested_at_utc"] = _utc_now_iso()

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to persist terminal session: {exc}"},
            status_code=500,
        )

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)


@app.route(route="devices/{device_id}/terminal/command", methods=["POST"])
def terminal_command(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

    device_id = req.route_params.get("device_id", "")
    try:
        body = req.get_json()
    except ValueError:
        return _json_response(
            {"status": "error", "message": "invalid JSON body"},
            status_code=400,
        )

    command = body.get("command", "")
    if not isinstance(command, str) or not command.strip():
        return _json_response(
            {"status": "error", "message": "command is required"},
            status_code=400,
        )

    command = command.strip()
    if len(command) > 200:
        return _json_response(
            {"status": "error", "message": "command too long (max 200 chars)"},
            status_code=400,
        )

    try:
        container = _get_container_client()
        item = container.read_item(item=device_id, partition_key=device_id)
    except exceptions.CosmosResourceNotFoundError:
        return _json_response(
            {"status": "error", "message": f"device '{device_id}' not found"},
            status_code=404,
        )
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to queue terminal command: {exc}"},
            status_code=500,
        )

    _ensure_terminal_fields(item)
    item["terminal_session_active"] = True
    item["wake_requested"] = True
    item["deep_sleep_requested"] = False
    item["keep_awake_until_utc"] = _utc_plus_seconds_iso(900)
    item["terminal_commands"].append(
        {
            "id": str(uuid.uuid4()),
            "command": command,
            "created_at_utc": _utc_now_iso(),
            "status": "queued",
        }
    )
    if len(item["terminal_commands"]) > 100:
        item["terminal_commands"] = item["terminal_commands"][-100:]

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to persist terminal command: {exc}"},
            status_code=500,
        )

    return _json_response(
        {
            "status": "ok",
            "queued": True,
            "pending_commands": len(item["terminal_commands"]),
            "device": _to_device_response(item),
        },
        status_code=202,
    )
