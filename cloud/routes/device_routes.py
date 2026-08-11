import base64

import azure.functions as func
from azure.cosmos import exceptions

from core.app import app
from core.auth import _compute_device_auth_hash, _require_write_access
from core.db import _get_container_client
from core.http import _json_response
from core.time_utils import _utc_now_iso
from core.device_view import _get_alerts, _get_stats, _merge_device_config, _merge_plant_profile, _merge_watering_schedule, _set_ota_status, _to_device_response
from routes.health_routes import index


@app.route(route="devices", methods=["GET"])
def list_devices(req: func.HttpRequest) -> func.HttpResponse:
    accept_header = (req.headers.get("accept") or "").lower()
    if "text/html" in accept_header:
        return index(req)

    try:
        container = _get_container_client()
        items = list(
            container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True,
            )
        )
        devices = [_to_device_response(item) for item in items]
        payload = {
            "status": "ok",
            "count": len(devices),
            "devices": devices,
        }
        return _json_response(payload, status_code=200)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to load devices: {exc}"},
            status_code=500,
        )


@app.route(route="devices/{device_id}/summary", methods=["GET"])
def get_device_summary(req: func.HttpRequest) -> func.HttpResponse:
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
            {"status": "error", "message": f"failed to load device summary: {exc}"},
            status_code=500,
        )

    return _json_response(
        {
            "status": "ok",
            "device_id": device_id,
            "summary": {
                "stats": _get_stats(item),
                "alerts": _get_alerts(item),
                "relay_state": str(item.get("relay_debug_state", "")).strip().lower() or "off",
            },
        },
        status_code=200,
    )


@app.route(route="devices/{device_id}", methods=["GET"])
def get_device(req: func.HttpRequest) -> func.HttpResponse:
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

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)


@app.route(route="devices/{device_id}", methods=["PATCH"])
def update_device(req: func.HttpRequest) -> func.HttpResponse:
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

    if isinstance(body.get("name"), str):
        new_name = body.get("name", "").strip()
        if not new_name:
            return _json_response(
                {"status": "error", "message": "name is required"},
                status_code=400,
            )
        if len(new_name) > 80:
            return _json_response(
                {"status": "error", "message": "name too long (max 80 chars)"},
                status_code=400,
            )
        item["name"] = new_name

    if "device_config" in body:
        _merge_device_config(item, body.get("device_config"))

    if "watering_schedule" in body:
        _merge_watering_schedule(item, body.get("watering_schedule"))

    if "plant_profile" in body:
        _merge_plant_profile(item, body.get("plant_profile"))

    if body.get("ota_action") in {"pending", "installing", "done", "failed", "rollback"}:
        ota_state = body.get("ota_action")
        if ota_state == "rollback":
            ota_state = "done"
        _set_ota_status(item, ota_state, version=body.get("firmware_version", ""), message=body.get("ota_message", ""))

    item["updated_at_utc"] = _utc_now_iso()

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to update device: {exc}"},
            status_code=500,
        )

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)


@app.route(route="devices/{device_id}/firmware", methods=["POST"])
def upload_firmware(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

    device_id = req.route_params.get("device_id", "")
    try:
        body = req.get_json()
    except ValueError:
        return _json_response({"status": "error", "message": "invalid JSON body"}, status_code=400)

    if not isinstance(body, dict):
        return _json_response({"status": "error", "message": "invalid JSON body"}, status_code=400)

    filename = body.get("filename")
    content_base64 = body.get("content_base64")
    version = body.get("firmware_version")
    if not isinstance(filename, str) or not filename.strip():
        return _json_response({"status": "error", "message": "filename is required"}, status_code=400)
    if not isinstance(content_base64, str) or not content_base64.strip():
        return _json_response({"status": "error", "message": "content_base64 is required"}, status_code=400)

    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception:
        return _json_response({"status": "error", "message": "content_base64 is not valid"}, status_code=400)

    try:
        container = _get_container_client()
        item = container.read_item(item=device_id, partition_key=device_id)
    except exceptions.CosmosResourceNotFoundError:
        return _json_response({"status": "error", "message": f"device '{device_id}' not found"}, status_code=404)
    except Exception as exc:
        return _json_response({"status": "error", "message": f"failed to load device: {exc}"}, status_code=500)

    item["firmware_upload"] = {
        "filename": filename.strip(),
        "size_bytes": len(content),
        "uploaded_at_utc": _utc_now_iso(),
    }
    if isinstance(version, str) and version.strip():
        item["firmware"] = version.strip()
    _set_ota_status(item, "pending", version=item.get("firmware", "unknown"), message=f"Uploaded {filename.strip()}")
    item["updated_at_utc"] = _utc_now_iso()

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response({"status": "error", "message": f"failed to update device: {exc}"}, status_code=500)

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)


@app.route(route="devices/{device_id}", methods=["DELETE"])
def delete_device(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

    device_id = req.route_params.get("device_id", "")

    try:
        container = _get_container_client()
        container.delete_item(item=device_id, partition_key=device_id)
    except exceptions.CosmosResourceNotFoundError:
        return _json_response(
            {"status": "error", "message": f"device '{device_id}' not found"},
            status_code=404,
        )
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to delete device: {exc}"},
            status_code=500,
        )

    return _json_response({"status": "ok", "deleted": True, "device_id": device_id}, status_code=200)


@app.route(route="devices", methods=["POST"])
def add_device(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

    try:
        body = req.get_json()
    except ValueError:
        return _json_response(
            {"status": "error", "message": "invalid JSON body"},
            status_code=400,
        )

    if not isinstance(body, dict):
        return _json_response(
            {"status": "error", "message": "invalid JSON body"},
            status_code=400,
        )

    serial_number = body.get("serial_number", "")
    if isinstance(serial_number, str):
        serial_number = serial_number.strip()
    else:
        serial_number = ""

    if not serial_number:
        return _json_response(
            {"status": "error", "message": "serial_number is required"},
            status_code=400,
        )

    hashed_device_id = _compute_device_auth_hash(serial_number)
    device_name = body.get("name", "").strip()

    if not hashed_device_id or not device_name:
        return _json_response(
            {"status": "error", "message": "serial_number and name are required"},
            status_code=400,
        )

    new_item = {
        "id": hashed_device_id,
        "deviceId": hashed_device_id,
        "device_auth_hash": hashed_device_id,
        "name": device_name,
        "status": "offline",
        "firmware": "unknown",
        "ip": "0.0.0.0",
        "last_seen_utc": _utc_now_iso(),
        "created_at_utc": _utc_now_iso(),
        "relay_debug_requested": False,
        "relay_debug_state": "",
        "relay_debug_request_id": "",
        "terminal_session_active": False,
        "terminal_commands": [],
        "terminal_output": [],
        "telemetry_history": [],
    }

    try:
        container = _get_container_client()
        container.create_item(body=new_item)
    except exceptions.CosmosResourceExistsError:
        return _json_response(
            {"status": "error", "message": f"device '{hashed_device_id}' already exists"},
            status_code=409,
        )
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to create device: {exc}"},
            status_code=500,
        )

    return _json_response(
        {
            "status": "ok",
            "device": _to_device_response(new_item),
        },
        status_code=201,
    )
