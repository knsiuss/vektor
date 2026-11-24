import re
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """Lightweight metadata for progressive disclosure of SKILL.md files."""

    name: str
    description: str
    path: Path


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    header, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip().lower()] = val.strip().strip('"').strip("'")
    return meta, body.strip()


class SkillRegistry:
    """Discovers, reads, and saves agentskills.io-compatible SKILL.md files."""

    def __init__(self, root_dir: str | Path = "skills") -> None:
        self._root = Path(root_dir).resolve()

    def list_skills(self) -> list[SkillMetadata]:
        if not self._root.is_dir():
            return []
        skills: list[SkillMetadata] = []
        for skill_file in sorted(self._root.glob("*/SKILL.md")):
            raw = skill_file.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(raw)
            name = meta.get("name") or skill_file.parent.name
            desc = meta.get("description") or "Operational skill."
            skills.append(SkillMetadata(name=name, description=desc, path=skill_file))
        return skills

    def read_skill(self, name: str) -> str | None:
        slug = self._sanitize_slug(name)
        if not slug:
            return None
        for skill in self.list_skills():
            if skill.name.lower() == name.strip().lower() or skill.path.parent.name == slug:
                return skill.path.read_text(encoding="utf-8")
        return None

    def save_skill(self, *, name: str, description: str, instructions: str) -> Path:
        slug = self._sanitize_slug(name)
        if not slug:
            raise ValueError("Skill name must contain alphanumeric characters.")
        target_dir = (self._root / slug).resolve()
        if target_dir.parent != self._root:
            raise ValueError("Invalid skill path.")
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_path = target_dir / "SKILL.md"
        clean_desc = " ".join(description.split())[:240]
        content = (
            f"---\n"
            f"name: {slug}\n"
            f"description: {clean_desc}\n"
            f"---\n\n"
            f"{instructions.strip()}\n"
        )
        skill_path.write_text(content, encoding="utf-8")
        return skill_path

    def format_catalog_prompt(self) -> str:
        skills = self.list_skills()
        if not skills:
            return ""
        lines = [f"- {s.name}: {s.description}" for s in skills[:20]]
        return "Available skills (call read_skill to load instructions):\n" + "\n".join(lines)

    @staticmethod
    def _sanitize_slug(name: str) -> str:
        slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
        return slug[:64]
