import os

from core.app import app

# Keep the historic placeholder in this file so existing CI replacement still works.
os.environ.setdefault("APP_BUILD_INFO", "__BUILD_INFO__")

# Import route modules for decorator registration.
import routes.agent_routes  # noqa: F401
import routes.auth_routes  # noqa: F401
import routes.device_action_routes  # noqa: F401
import routes.device_routes  # noqa: F401
import routes.health_routes  # noqa: F401
import routes.power_routes  # noqa: F401
import routes.terminal_routes  # noqa: F401
