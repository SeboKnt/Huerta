import json
import os
import uuid
import hmac
import hashlib
import base64
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import azure.functions as func
from azure.cosmos import CosmosClient, exceptions

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_BASE_DIR = Path(__file__).parent
_INDEX_PATH = _BASE_DIR / "static" / "index.html"

_COSMOS_URI = os.getenv("COSMOS_URI")
_COSMOS_KEY = os.getenv("COSMOS_KEY")
_COSMOS_DATABASE = os.getenv("COSMOS_DATABASE")
_COSMOS_CONTAINER = os.getenv("COSMOS_CONTAINER")
_DEVICE_TOKEN_SECRET = os.getenv("DEVICE_TOKEN_SECRET")
_BUILD_INFO = os.getenv("APP_BUILD_INFO", "__BUILD_INFO__")
_ALLOWED_WRITE_ACCOUNTS = {
    entry.strip().lower()
    for entry in os.getenv("ALLOWED_WRITE_ACCOUNTS", "").replace(";", ",").split(",")
    if entry.strip()
}

_CONTAINER_CLIENT = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_plus_seconds_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_connected(item: dict) -> bool:
    last_seen = _parse_utc(item.get("last_seen_utc", ""))
    if last_seen is None:
        return False
    return (datetime.now(timezone.utc) - last_seen).total_seconds() <= 120


def _ensure_terminal_fields(item: dict) -> None:
    if not isinstance(item.get("terminal_commands"), list):
        item["terminal_commands"] = []
    if not isinstance(item.get("terminal_output"), list):
        item["terminal_output"] = []
    if "terminal_session_active" not in item:
        item["terminal_session_active"] = False


def _compute_device_auth_hash(device_id: str) -> str:
    if not _DEVICE_TOKEN_SECRET:
        raise RuntimeError("missing DEVICE_TOKEN_SECRET (set this in Function App environment settings)")
    return hmac.new(
        _DEVICE_TOKEN_SECRET.encode("utf-8"),
        device_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _extract_serial_number(req: func.HttpRequest) -> str:
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    if not isinstance(body, dict):
        body = {}

    serial_number = body.get("serial_number") or ""
    if isinstance(serial_number, str):
        return serial_number.strip()
    return ""


def _log_unauthorized_attempt(operation: str, serial_number: str, reason: str, req: func.HttpRequest) -> None:
    remote_ip = (
        req.headers.get("X-Forwarded-For")
        or req.headers.get("X-Azure-ClientIP")
        or req.headers.get("X-Real-IP")
        or "unknown"
    )
    logging.warning(
        "Unauthorized %s attempt: serial=%s ip=%s reason=%s",
        operation,
        serial_number or "<missing>",
        remote_ip,
        reason,
    )

def _get_container_client():
    global _CONTAINER_CLIENT

    if _CONTAINER_CLIENT is not None:
        return _CONTAINER_CLIENT

    missing = []
    if not _COSMOS_URI:
        missing.append("COSMOS_URI")
    if not _COSMOS_KEY:
        missing.append("COSMOS_KEY")
    if not _COSMOS_DATABASE:
        missing.append("COSMOS_DATABASE")
    if not _COSMOS_CONTAINER:
        missing.append("COSMOS_CONTAINER")

    if missing:
        raise RuntimeError(f"missing Cosmos configuration: {', '.join(missing)}")

    client = CosmosClient(_COSMOS_URI, credential=_COSMOS_KEY)
    database = client.get_database_client(_COSMOS_DATABASE)
    _CONTAINER_CLIENT = database.get_container_client(_COSMOS_CONTAINER)
    return _CONTAINER_CLIENT


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
        "connected": _is_connected(item),
        "terminal_session_active": bool(item.get("terminal_session_active", False)),
        "keep_awake_until_utc": item.get("keep_awake_until_utc", ""),
    }


def _json_response(payload: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(payload),
        mimetype="application/json",
        status_code=status_code,
    )


def _extract_identity(req: func.HttpRequest):
    principal_name = (req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME") or "").strip().lower()
    principal_id = (req.headers.get("X-MS-CLIENT-PRINCIPAL-ID") or "").strip().lower()
    identity_provider = (req.headers.get("X-MS-CLIENT-PRINCIPAL-IDP") or "").strip().lower()

    encoded_principal = req.headers.get("X-MS-CLIENT-PRINCIPAL") or ""
    if encoded_principal and (not principal_name or not principal_id or not identity_provider):
        try:
            decoded = base64.b64decode(encoded_principal)
            parsed = json.loads(decoded.decode("utf-8"))
            if not principal_name:
                principal_name = str(parsed.get("userDetails", "")).strip().lower()
            if not principal_id:
                principal_id = str(parsed.get("userId", "")).strip().lower()
            if not identity_provider:
                identity_provider = str(parsed.get("identityProvider", "")).strip().lower()
        except Exception:
            pass

    return principal_name, principal_id, identity_provider


def _auth_diagnostics(req: func.HttpRequest) -> dict:
    principal_name, principal_id, identity_provider = _extract_identity(req)
    return {
        "principal_name": principal_name,
        "principal_id": principal_id,
        "identity_provider": identity_provider,
        "header_present": {
            "x_ms_client_principal": bool(req.headers.get("X-MS-CLIENT-PRINCIPAL")),
            "x_ms_client_principal_name": bool(req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")),
            "x_ms_client_principal_id": bool(req.headers.get("X-MS-CLIENT-PRINCIPAL-ID")),
            "x_ms_client_principal_idp": bool(req.headers.get("X-MS-CLIENT-PRINCIPAL-IDP")),
        },
        "allowlist_configured": bool(_ALLOWED_WRITE_ACCOUNTS),
    }


def _is_allowed_write_identity(principal_name: str, principal_id: str) -> bool:
    if not _ALLOWED_WRITE_ACCOUNTS:
        return True
    return principal_name in _ALLOWED_WRITE_ACCOUNTS or principal_id in _ALLOWED_WRITE_ACCOUNTS


def _require_write_access(req: func.HttpRequest):
    diagnostics = _auth_diagnostics(req)
    principal_name = diagnostics["principal_name"]
    principal_id = diagnostics["principal_id"]
    identity_provider = diagnostics["identity_provider"]

    if not principal_name and not principal_id:
        return _json_response(
            {
                "status": "error",
                "message": "authentication required for write operations",
                "auth_debug": diagnostics,
            },
            status_code=401,
        )

    if identity_provider and identity_provider not in {"aad", "microsoft", "entra"}:
        return _json_response(
            {
                "status": "error",
                "message": "only Microsoft identity provider is allowed for write operations",
                "auth_debug": diagnostics,
            },
            status_code=403,
        )

    # If no allowlist is configured, any authenticated Microsoft account may write.
    if not _ALLOWED_WRITE_ACCOUNTS:
        logging.warning(
            "ALLOWED_WRITE_ACCOUNTS is not set; allowing write access for authenticated Microsoft user '%s' (%s)",
            principal_name or "<missing-name>",
            principal_id or "<missing-id>",
        )
        return None

    if not _is_allowed_write_identity(principal_name, principal_id):
        return _json_response(
            {
                "status": "error",
                "message": "account is not in write allowlist",
                "account": principal_name or principal_id,
                "auth_debug": diagnostics,
            },
            status_code=403,
        )

    return None


@app.route(route="auth/debug", methods=["GET"])
def auth_debug(req: func.HttpRequest) -> func.HttpResponse:
    diagnostics = _auth_diagnostics(req)
    diagnostics["allowed_write"] = (
        bool(diagnostics["principal_name"] or diagnostics["principal_id"])
        and (
            (not diagnostics["identity_provider"])
            or diagnostics["identity_provider"] in {"aad", "microsoft", "entra"}
        )
        and _is_allowed_write_identity(diagnostics["principal_name"], diagnostics["principal_id"])
    )
    return _json_response({"status": "ok", "build": _BUILD_INFO, "auth": diagnostics}, status_code=200)


@app.route(route="health")
def health(req: func.HttpRequest) -> func.HttpResponse:
    configured = all([_COSMOS_URI, _COSMOS_KEY, _COSMOS_DATABASE, _COSMOS_CONTAINER])
    cosmos_connected = False
    cosmos_error = None

    if configured:
        try:
            container = _get_container_client()
            container.read()
            cosmos_connected = True
        except Exception as exc:
            cosmos_error = str(exc)

    payload = {
        "status": "ok",
        "service": "Huerta Function",
        "message": "Azure Function is running",
        "build": _BUILD_INFO,
        "cosmos_configured": configured,
        "cosmos_connected": cosmos_connected,
    }
    if cosmos_error:
        payload["cosmos_error"] = cosmos_error

    return _json_response(payload, status_code=200)


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

    new_name = body.get("name", "")
    if not isinstance(new_name, str) or not new_name.strip():
        return _json_response(
            {"status": "error", "message": "name is required"},
            status_code=400,
        )

    new_name = new_name.strip()
    if len(new_name) > 80:
        return _json_response(
            {"status": "error", "message": "name too long (max 80 chars)"},
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

    item["name"] = new_name
    item["updated_at_utc"] = _utc_now_iso()

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to update device: {exc}"},
            status_code=500,
        )

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

        # ESP can consume these fields to blink/enable an identification LED.
        item["identify_requested"] = True
        item["identify_duration_sec"] = duration_sec
        item["identify_requested_at_utc"] = _utc_now_iso()
    elif action == "set_watering":
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return _json_response(
                {"status": "error", "message": "enabled must be boolean"},
                status_code=400,
            )
        item["watering_enabled"] = enabled
    elif action == "toggle_watering":
        item["watering_enabled"] = not bool(item.get("watering_enabled", False))
    else:
        return _json_response(
            {
                "status": "error",
                "message": "unsupported action, use 'restart', 'identify', 'toggle_watering' or 'set_watering'",
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
        "watering_enabled": False,
        "terminal_session_active": False,
        "terminal_commands": [],
        "terminal_output": [],
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


@app.route(route="agent/poll", methods=["POST"])
def agent_poll(req: func.HttpRequest) -> func.HttpResponse:
    serial_number = _extract_serial_number(req)
    if not serial_number:
        _log_unauthorized_attempt("poll", "", "missing serial_number", req)
        return _json_response(
            {"status": "error", "message": "serial_number is required"},
            status_code=400,
        )

    device_id = _compute_device_auth_hash(serial_number)

    try:
        container = _get_container_client()
        item = container.read_item(item=device_id, partition_key=device_id)
    except exceptions.CosmosResourceNotFoundError:
        _log_unauthorized_attempt("poll", serial_number, "device not found", req)
        return _json_response(
            {"status": "error", "message": "device not authorized"},
            status_code=404,
        )
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to poll commands: {exc}"},
            status_code=500,
        )

    _ensure_terminal_fields(item)
    queued = [c for c in item.get("terminal_commands", []) if c.get("status") == "queued"]

    item["last_seen_utc"] = _utc_now_iso()
    try:
        container.replace_item(item=device_id, body=item)
    except Exception:
        pass

    payload = {
        "status": "ok",
        "device": _to_device_response(item),
        "commands": queued,
        "control": {
            "wake_requested": bool(item.get("wake_requested", False)),
            "deep_sleep_requested": bool(item.get("deep_sleep_requested", False)),
            "terminal_session_active": bool(item.get("terminal_session_active", False)),
            "keep_awake_until_utc": item.get("keep_awake_until_utc", ""),
            "identify_requested": bool(item.get("identify_requested", False)),
            "identify_duration_sec": int(item.get("identify_duration_sec", 15)),
        },
    }
    return _json_response(payload, status_code=200)


@app.route(route="agent/report", methods=["POST"])
def agent_report(req: func.HttpRequest) -> func.HttpResponse:
    serial_number = _extract_serial_number(req)
    if not serial_number:
        _log_unauthorized_attempt("report", "", "missing serial_number", req)
        return _json_response(
            {"status": "error", "message": "serial_number is required"},
            status_code=400,
        )

    device_id = _compute_device_auth_hash(serial_number)

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
        _log_unauthorized_attempt("report", serial_number, "device not found", req)
        return _json_response(
            {"status": "error", "message": "device not authorized"},
            status_code=404,
        )
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to update device report: {exc}"},
            status_code=500,
        )

    _ensure_terminal_fields(item)
    item["last_seen_utc"] = _utc_now_iso()

    if isinstance(body.get("status"), str):
        item["status"] = body["status"]
    if isinstance(body.get("ip"), str):
        item["ip"] = body["ip"]
    if isinstance(body.get("firmware"), str):
        item["firmware"] = body["firmware"]

    if body.get("deep_sleep_entering") is True:
        item["terminal_session_active"] = False
        item["deep_sleep_requested"] = False

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

    if body.get("identify_done") is True:
        item["identify_requested"] = False

    try:
        container.replace_item(item=device_id, body=item)
    except Exception as exc:
        return _json_response(
            {"status": "error", "message": f"failed to persist device report: {exc}"},
            status_code=500,
        )

    return _json_response({"status": "ok", "device": _to_device_response(item)}, status_code=200)


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
