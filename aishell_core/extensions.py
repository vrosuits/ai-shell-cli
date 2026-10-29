"""Explicit, declarative plugins: loading never imports or executes plugin code."""
import json
from pathlib import Path
import re


class Extensions:
    def __init__(self):
        self.tools, self.commands, self.skills = {}, {}, {}
        self.active_skill = None
        self.sources = []

    def load(self, path):
        path = Path(path).expanduser().resolve()
        if path.stat().st_size > 262144:
            raise ValueError("Plugin manifest exceeds 256 KiB.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Plugin manifest requires version: 1.")
        staged = {}
        for category in ("tools", "commands", "skills"):
            entries = data.get(category, {})
            if not isinstance(entries, dict):
                raise ValueError(f"Plugin {category} must be an object.")
            for name, value in entries.items():
                if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in getattr(self, category):
                    raise ValueError(f"Invalid or duplicate extension name: {name}")
                if category == "tools":
                    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) and value[k].strip() for k in ("language", "code")):
                        raise ValueError(f"Tool {name} needs language and code strings.")
                elif not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{category} entry {name} must be a nonempty string.")
            staged[category] = entries
        for category, entries in staged.items():
            getattr(self, category).update(entries)
        self.sources.append(str(path))

    def instructions(self):
        return self.skills.get(self.active_skill, "")

    def prompt(self, name, argument):
        if name not in self.commands:
            raise ValueError(f"Unknown command template: {name}")
        return self.commands[name].replace("{input}", argument)
