import azure.functions as func

from core.app import app
from core.auth import _auth_diagnostics, _is_allowed_write_identity
from core.config import _BUILD_INFO
from core.http import _json_response


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
