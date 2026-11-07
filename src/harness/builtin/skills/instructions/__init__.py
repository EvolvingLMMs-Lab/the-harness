"""Skills the user installed in the app in the Agent Skills format (a folder with
SKILL.md: instructions for a kind of task, and the files they refer to). The system
prompt names each one with its description; read_skill() gives the rest when a task
needs it, so the prompt stays short however many there are."""

from pathlib import Path

# Files read_skill gives at most, in characters.
LIMIT = 60000


class AgentSkills:
    def read_skill(self, name, file="SKILL.md"):
        """The instructions of installed skill `name` (its SKILL.md), or another of its
        files by its path inside the skill ("reference.md", "scripts/fill.py"). Without
        such a file, ValueError lists the skill's files."""
        skills = getattr(self, "agent_skills", None) or {}
        if name not in skills:
            raise ValueError(f"No installed skill {name!r}; skills: {sorted(skills)}")
        folder = Path(skills[name]["path"]).resolve()
        path = (folder / str(file)).resolve()
        if folder not in path.parents or not path.is_file():
            files = sorted(str(item.relative_to(folder)).replace("\\", "/") for item in folder.rglob("*")
                           if item.is_file() and ".deps" not in item.parts)
            raise ValueError(f"No file {file!r} in skill {name}; its files: {files[:100]}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > LIMIT:
            text = text[:LIMIT] + f"\n[... {len(text) - LIMIT} more characters]"
        return text
