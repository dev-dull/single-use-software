"""Skills manager for reading, writing, and validating guidance skill files."""

from __future__ import annotations

import os
import re
from pathlib import Path


class SkillsManager:
    """Manage guidance skill Markdown files in a directory."""

    def __init__(self, skills_dir: str) -> None:
        self.skills_dir = Path(skills_dir)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_skills(self) -> list[dict]:
        """List all skill files with name, description, and path."""
        skills: list[dict] = []
        if not self.skills_dir.is_dir():
            return skills

        for path in sorted(self.skills_dir.glob("*.md")):
            name = path.stem
            description = ""
            try:
                text = path.read_text(encoding="utf-8")
                # Description is the first non-empty line after the title line.
                lines = text.splitlines()
                past_title = False
                for line in lines:
                    stripped = line.strip()
                    if not past_title:
                        if stripped.startswith("# "):
                            past_title = True
                        continue
                    if stripped and not stripped.startswith("---"):
                        # Strip leading blockquote marker if present.
                        description = stripped.lstrip("> ").rstrip()
                        break
            except OSError:
                pass

            skills.append({
                "name": name,
                "description": description,
                "path": str(path),
            })
        return skills

    def get_skill(self, name: str) -> dict | None:
        """Read a single skill file. Returns name, content, path or None."""
        path = self.skills_dir / f"{name}.md"
        if not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        return {
            "name": name,
            "content": content,
            "path": str(path),
        }

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def save_skill(self, name: str, content: str) -> None:
        """Write or overwrite a skill file. *name* must end in .md."""
        if not name.endswith(".md"):
            name = f"{name}.md"
        path = self.skills_dir / name
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete_skill(self, name: str) -> bool:
        """Delete a skill file. Returns False if file missing or protected."""
        if name.upper() == "AUTHORING":
            return False
        path = self.skills_dir / f"{name}.md"
        if not path.is_file():
            return False
        path.unlink()
        return True

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_skill(self, content: str) -> dict:
        """Basic validation of skill Markdown content."""
        errors: list[str] = []

        if not content or not content.strip():
            errors.append("Skill content must not be empty.")
            return {"valid": False, "errors": errors}

        if not re.search(r"^#\s+\S", content, re.MULTILINE):
            errors.append("Skill must contain a level-1 heading (# Title).")

        if errors:
            return {"valid": False, "errors": errors}
        return {"valid": True}
