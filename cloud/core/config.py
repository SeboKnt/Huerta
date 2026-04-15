import os
from pathlib import Path

_BASE_DIR = Path(__file__).parent.parent
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
