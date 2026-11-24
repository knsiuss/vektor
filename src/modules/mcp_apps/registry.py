from dataclasses import dataclass

from modules.mcp_apps.widgets import OPS_HEALTH_WIDGET_HTML, OPS_HEALTH_WIDGET_URI

MCP_APP_MIME_TYPE = "text/html;profile=mcp-app"


@dataclass(frozen=True, slots=True)
class UIResource:
    """Registered MCP App HTML resource addressable by ui:// URI."""

    uri: str
    name: str
    mime_type: str
    html: str


class UIResourceRegistry:
    """In-memory cache and lookup registry for MCP App UI resources."""

    def __init__(self) -> None:
        self._resources: dict[str, UIResource] = {}

    def register(self, resource: UIResource) -> None:
        self._resources[resource.uri] = resource

    def get(self, uri: str) -> UIResource | None:
        return self._resources.get(uri)

    def list_uris(self) -> list[str]:
        return list(self._resources.keys())


def build_default_ui_registry() -> UIResourceRegistry:
    """Create the default registry populated with built-in Vektor MCP App widgets."""
    registry = UIResourceRegistry()
    registry.register(
        UIResource(
            uri=OPS_HEALTH_WIDGET_URI,
            name="Vektor Ops Health Monitor",
            mime_type=MCP_APP_MIME_TYPE,
            html=OPS_HEALTH_WIDGET_HTML,
        )
    )
    return registry
