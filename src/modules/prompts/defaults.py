"""Registry of editable Markdown prompt templates.

Each key maps to the shipped default. User overrides live in the database; the file on
disk stays the source of truth for a reset.
"""

from dataclasses import dataclass

from modules.ai_runtime.prompt_loader import load_prompt


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    key: str
    label: str
    description: str
    default_file: str


TEMPLATES: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        key="system",
        label="System / persona",
        description="How Vektor speaks and behaves on every turn.",
        default_file="system_default.md",
    ),
)

AVAILABLE = {template.key: template for template in TEMPLATES}


def default_content(key: str) -> str:
    """Return the shipped Markdown for a template key."""
    return load_prompt(AVAILABLE[key].default_file)
