from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=16)
def load_prompt(prompt_name: str = "system_default.md") -> str:
    """Load and validate a Markdown system prompt from the ai_runtime prompts directory."""
    if "/" in prompt_name or "\\" in prompt_name or ".." in prompt_name:
        raise ValueError(f"Invalid prompt filename: '{prompt_name}'.")

    prompt_path = _PROMPTS_DIR / prompt_name
    if not prompt_path.is_file():
        raise FileNotFoundError(f"System prompt file not found: '{prompt_path}'.")

    content = prompt_path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"System prompt file is empty: '{prompt_path}'.")

    return content
