from core.app import app

# Import route modules for decorator registration.
import routes.agent_routes  # noqa: F401
import routes.auth_routes  # noqa: F401
import routes.device_action_routes  # noqa: F401
import routes.device_routes  # noqa: F401
import routes.health_routes  # noqa: F401
import routes.power_routes  # noqa: F401
import routes.terminal_routes  # noqa: F401
