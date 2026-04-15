from azure.cosmos import CosmosClient

from core.config import _COSMOS_CONTAINER, _COSMOS_DATABASE, _COSMOS_KEY, _COSMOS_URI

_CONTAINER_CLIENT = None


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
