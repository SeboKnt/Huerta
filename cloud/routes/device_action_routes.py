import uuid

import azure.functions as func
from azure.cosmos import exceptions

from core.app import app
from core.auth import _require_write_access
from core.db import _get_container_client
from core.http import _json_response
from core.time_utils import _utc_now_iso
from core.device_view import _to_device_response


@app.route(route="devices/{device_id}/action", methods=["POST"])
def device_action(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

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
            {"status": "error", "message": f"failed to load device: {exc}"},
            status_code=500,
        )

    try:
        body = req.get_json()
    except ValueError:
        return _json_response(
            {"status": "error", "message": "invalid JSON body"},
            status_code=400,
        )

    action = body.get("action")
    if action == "restart":
        item["status"] = "restarting"
    elif action == "identify":
        duration_sec = body.get("duration_sec", 15)
        if not isinstance(duration_sec, int) or duration_sec < 1 or duration_sec > 120:
            return _json_response(
                {"status": "error", "message": "duration_sec must be an integer between 1 and 120"},
                status_code=400,
            )

        item["identify_requested"] = True
        item["identify_duration_sec"] = duration_sec
        item["identify_requested_at_utc"] = _utc_now_iso()
    elif action in ("relay_debug_on", "relay_on"):
        item["relay_debug_requested"] = True
        item["relay_debug_state"] = "on"
        item["relay_debug_request_id"] = str(uuid.uuid4())
        item["relay_debug_requested_at_utc"] = _utc_now_iso()
    elif action in ("relay_debug_off", "relay_off"):
        item["relay_debug_requested"] = True
        item["relay_debug_state"] = "off"
        item["relay_debug_request_id"] = str(uuid.uuid4())
        item["relay_debug_requested_at_utc"] = _utc_now_iso()
    else:
        return _json_response(
            {
                "status": "error",
                "message": "unsupported action, use 'restart', 'identify', 'relay_on' or 'relay_off'",
            },
            status_code=400,
        )

    item["last_command_at_utc"] = _utc_now_iso()
    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to update device: {exc}"},
            status_code=500,
        )

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)
