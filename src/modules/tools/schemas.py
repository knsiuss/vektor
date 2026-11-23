from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolRiskLevel = Literal["read", "mutating"]


class ToolDefinition(BaseModel):
    """OpenAI-compatible function tool specification registered in Vektor."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = Field(min_length=1, max_length=512)
    parameters_schema: dict[str, Any]
    risk_level: ToolRiskLevel = "read"

    def to_openai_tool(self) -> dict[str, Any]:
        """Serialize into standard OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


class ToolExecutionRecord(BaseModel):
    """Audit record of a single tool invocation during an AI runtime turn."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: Literal["success", "blocked", "error"]
    output: str
