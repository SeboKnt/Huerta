import azure.functions as func

from core.app import app
from core.auth import _require_write_access
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


@app.route(route="system/quota", methods=["GET"])
def system_quota(req: func.HttpRequest) -> func.HttpResponse:
    auth_error = _require_write_access(req)
    if auth_error:
        return auth_error

    configured = all([_COSMOS_URI, _COSMOS_KEY, _COSMOS_DATABASE, _COSMOS_CONTAINER])
    db_size_kb = 0
    db_quota_kb = 10485760  # Default 10GB free tier
    db_usage_str = ""
    db_quota_str = ""
    document_count = 0

    if configured:
        try:
            container = _get_container_client()
            container.read()
            headers = container.client_connection.last_response_headers
            
            # Extract Cosmos DB metadata usage/quota
            db_usage_str = headers.get("x-ms-resource-usage", "")
            db_quota_str = headers.get("x-ms-resource-quota", "")
            
            # Parse usage (e.g. "documentsSize=15;documentsCount=10")
            for part in db_usage_str.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    if k.strip() == "documentsSize":
                        db_size_kb = int(v.strip())
            
            for part in db_quota_str.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    if k.strip() == "documentsSize":
                        db_quota_kb = int(v.strip())
            
            # Count actual documents
            items = list(container.query_items(query="SELECT VALUE COUNT(1) FROM c", enable_cross_partition_query=True))
            if items:
                document_count = items[0]
        except Exception:
            pass

    # Estimate Azure Functions executions based on Cosmos DB telemetry counts
    estimated_monthly_executions = document_count * 15 + 1240
    estimated_gb_seconds = estimated_monthly_executions * 0.25

    return _json_response({
        "status": "ok",
        "cosmos_db": {
            "configured": configured,
            "document_count": document_count,
            "size_kb": db_size_kb,
            "quota_kb": db_quota_kb,
            "usage_percentage": min(100.0, (db_size_kb / db_quota_kb) * 100.0) if db_quota_kb > 0 else 0.0,
            "raw_usage": db_usage_str,
            "raw_quota": db_quota_str,
        },
        "azure_functions": {
            "free_executions_limit": 1000000,
            "estimated_executions": min(1000000, estimated_monthly_executions),
            "executions_usage_percentage": (estimated_monthly_executions / 1000000.0) * 100.0,
            "free_gb_seconds_limit": 400000,
            "estimated_gb_seconds": min(400000.0, estimated_gb_seconds),
            "gb_seconds_usage_percentage": (estimated_gb_seconds / 400000.0) * 100.0,
        }
      }, status_code=200)
