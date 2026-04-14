import json
from pathlib import Path

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

_BASE_DIR = Path(__file__).parent
_INDEX_PATH = _BASE_DIR / "static" / "index.html"


@app.route(route="health")
def health(req: func.HttpRequest) -> func.HttpResponse:
    payload = {
        "status": "ok",
        "service": "Huerta Function",
        "message": "Azure Function is running",
    }
    return func.HttpResponse(
        body=json.dumps(payload),
        mimetype="application/json",
        status_code=200,
    )


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
