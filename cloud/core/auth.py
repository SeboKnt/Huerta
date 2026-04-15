import base64
import hashlib
import hmac
import json
import logging

import azure.functions as func

from core.config import _ALLOWED_WRITE_ACCOUNTS, _DEVICE_TOKEN_SECRET
from core.http import _json_response


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
