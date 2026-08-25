"""Plugin-style Skill registry with lazy handler loading."""

import importlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SKILLS_ROOT = ROOT / "skills"


class SkillRegistry:
    """Scan Skill metadata early; import handlers only when needed."""

    def __init__(self, skills_root: Path = SKILLS_ROOT):
        self.skills_root = Path(skills_root)
        self._metadata: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Any] = {}
        self._discover()

    def _discover(self) -> None:
        if not self.skills_root.exists():
            return
        for skill_dir in sorted(self.skills_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            metadata_path = skill_dir / "SKILL.md"
            handler_path = skill_dir / "handler.py"
            if not metadata_path.exists() or not handler_path.exists():
                continue
            metadata = self._parse_frontmatter(metadata_path)
            name = metadata.get("name", skill_dir.name)
            intents = metadata.get("intents", "")
            if isinstance(intents, str):
                intents = [item.strip() for item in intents.split(",") if item.strip()]
            metadata.update({"name": name, "intents": intents, "path": str(skill_dir)})
            self._metadata[name] = metadata

    @staticmethod
    def _parse_frontmatter(path: Path) -> dict[str, Any]:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        data: dict[str, Any] = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip("\"'")
        return data

    def metadata(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._metadata.values()]

    def metadata_prompt(self) -> str:
        return "\n".join(
            f"- {item['name']}: {item.get('description', '')}"
            for item in self._metadata.values()
        )

    def find_for_intent(self, intent: str) -> str | None:
        for name, metadata in self._metadata.items():
            if intent in metadata.get("intents", []):
                return name
        return None

    def load(self, name: str):
        if name in self._handlers:
            return self._handlers[name]
        if name not in self._metadata:
            raise KeyError(f"Skill plugin not found: {name}")
        module = importlib.import_module(f"server.skills.{name.replace('-', '_')}.handler")
        self._handlers[name] = module
        return module

    def run(self, name: str, **kwargs):
        return self.load(name).run(**kwargs)

    def run_for_intent(self, intent: str, **kwargs):
        name = self.find_for_intent(intent)
        if not name:
            raise KeyError(f"No Skill plugin mapped to intent: {intent}")
        return self.run(name, **kwargs)

    def loaded(self) -> list[str]:
        return sorted(self._handlers)


_REGISTRY: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SkillRegistry()
    return _REGISTRY
