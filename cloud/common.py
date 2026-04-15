from core.app import app
from core.auth import (
    _auth_diagnostics,
    _compute_device_auth_hash,
    _extract_identity,
    _extract_serial_number,
    _is_allowed_write_identity,
    _log_unauthorized_attempt,
    _require_write_access,
)
from core.config import (
    _ALLOWED_WRITE_ACCOUNTS,
    _BASE_DIR,
    _BUILD_INFO,
    _COSMOS_CONTAINER,
    _COSMOS_DATABASE,
    _COSMOS_KEY,
    _COSMOS_URI,
    _DEVICE_TOKEN_SECRET,
    _INDEX_PATH,
)
from core.db import _get_container_client
from core.device_view import _ensure_terminal_fields, _telemetry_summary, _to_device_response
from core.http import _json_response
from core.time_utils import _is_connected, _parse_utc, _utc_now_iso, _utc_plus_seconds_iso
