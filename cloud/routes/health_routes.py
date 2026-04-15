import azure.functions as func

from core.app import app
from core.config import _BUILD_INFO, _COSMOS_CONTAINER, _COSMOS_DATABASE, _COSMOS_KEY, _COSMOS_URI, _INDEX_PATH
from core.db import _get_container_client
from core.http import _json_response


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
