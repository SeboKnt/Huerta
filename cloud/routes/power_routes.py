import azure.functions as func
from azure.cosmos import exceptions

from core.app import app
from core.auth import _require_write_access
from core.db import _get_container_client
from core.http import _json_response
from core.time_utils import _utc_now_iso, _utc_plus_seconds_iso
from core.device_view import _to_device_response


@app.route(route="devices/{device_id}/power/wake", methods=["POST"])
def power_wake(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

    device_id = req.route_params.get("device_id", "")
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    keep_awake_seconds = body.get("keep_awake_seconds", 600)
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
            {"status": "error", "message": f"failed to request wake: {exc}"},
            status_code=500,
        )

    item["wake_requested"] = True
    item["deep_sleep_requested"] = False
    item["keep_awake_until_utc"] = _utc_plus_seconds_iso(keep_awake_seconds)
    item["wake_requested_at_utc"] = _utc_now_iso()

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to persist wake request: {exc}"},
            status_code=500,
        )

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)


@app.route(route="devices/{device_id}/power/sleep", methods=["POST"])
def power_sleep(req: func.HttpRequest) -> func.HttpResponse:
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
            {"status": "error", "message": f"failed to request deep sleep: {exc}"},
            status_code=500,
        )

    item["deep_sleep_requested"] = True
    item["wake_requested"] = False
    item["terminal_session_active"] = False
    item["sleep_requested_at_utc"] = _utc_now_iso()

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to persist deep sleep request: {exc}"},
            status_code=500,
        )

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)
