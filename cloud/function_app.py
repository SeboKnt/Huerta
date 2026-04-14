import json
from pathlib import Path
from datetime import datetime, timezone

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_BASE_DIR = Path(__file__).parent
_INDEX_PATH = _BASE_DIR / "static" / "index.html"

_DEVICES = {
    "esp32-garden-01": {
        "id": "esp32-garden-01",
        "name": "Garden Node 01",
        "status": "online",
        "firmware": "1.0.0",
        "ip": "192.168.178.51",
        "last_seen_utc": "2026-04-14T10:00:00Z",
        "watering_enabled": True,
    },
    "esp32-garden-02": {
        "id": "esp32-garden-02",
        "name": "Garden Node 02",
        "status": "offline",
        "firmware": "1.0.0",
        "ip": "192.168.178.52",
        "last_seen_utc": "2026-04-13T22:41:00Z",
        "watering_enabled": False,
    },
}


def _json_response(payload: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload),
        mimetype="application/json",
        status_code=status_code,
    )


@app.route(route="health")
def health(req: func.HttpRequest) -> func.HttpResponse:
    payload = {
        "status": "ok",
        "service": "Huerta Function",
        "message": "Azure Function is running",
    }
    return _json_response(payload, status_code=200)


@app.route(route="devices", methods=["GET"])
def list_devices(req: func.HttpRequest) -> func.HttpResponse:
    payload = {
        "status": "ok",
        "count": len(_DEVICES),
        "devices": list(_DEVICES.values()),
    }
    return _json_response(payload, status_code=200)


@app.route(route="devices/{device_id}", methods=["GET"])
def get_device(req: func.HttpRequest) -> func.HttpResponse:
    device_id = req.route_params.get("device_id", "")
    device = _DEVICES.get(device_id)
    if device is None:
        return _json_response(
            {"status": "error", "message": f"device '{device_id}' not found"},
            status_code=404,
        )

    return _json_response({"status": "ok", "device": device}, status_code=200)


@app.route(route="devices/{device_id}/action", methods=["POST"])
def device_action(req: func.HttpRequest) -> func.HttpResponse:
    device_id = req.route_params.get("device_id", "")
    device = _DEVICES.get(device_id)
    if device is None:
        return _json_response(
            {"status": "error", "message": f"device '{device_id}' not found"},
            status_code=404,
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
        device["status"] = "restarting"
    elif action == "set_watering":
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return _json_response(
                {"status": "error", "message": "enabled must be boolean"},
                status_code=400,
            )
        device["watering_enabled"] = enabled
    else:
        return _json_response(
            {
                "status": "error",
                "message": "unsupported action, use 'restart' or 'set_watering'",
            },
            status_code=400,
        )

    device["last_seen_utc"] = datetime.now(timezone.utc).isoformat()
    return _json_response({"status": "ok", "device": device}, status_code=200)


@app.route(route="")
def index(req: func.HttpRequest) -> func.HttpResponse:
    try:
        html = _INDEX_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return func.HttpResponse(
            "index.html not found",
            status_code=500,
            mimetype="text/plain",
        )

    return func.HttpResponse(
        html,
        status_code=200,
        mimetype="text/html",
    )
