"""Conservative execution hints, not a shell parser or security sandbox."""
from dataclasses import dataclass
from pathlib import Path
import re
import shlex

LEVELS = {
    0: "Manual", 1: "Inspect", 2: "Read", 3: "Create",
    4: "Modify", 5: "Network", 6: "Automatic",
}
DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "dangerous_cmds.txt"


@dataclass(frozen=True)
class Decision:
    required_level: int
    reasons: tuple
    blocked: bool = False

    def automatic(self, level):
        return not self.blocked and level >= self.required_level

    @property
    def description(self):
        action = "blocked" if self.blocked else (
            "manual approval" if self.required_level == 7 else
            f"level {self.required_level}+"
        )
        return f"{action}: {'; '.join(self.reasons)}"


class Policy:
    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_POLICY
        self.rules = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                action, label, pattern = line.split("|", 2)
                if action not in {"block", "manual", "1", "2", "3", "4", "5", "6"}:
                    raise ValueError("invalid level")
                self.rules.append((action, label, re.compile(pattern, re.I | re.M)))
            except (ValueError, re.error) as exc:
                raise ValueError(f"Invalid policy rule at {self.path}:{number}") from exc

    def assess(self, code, language="bash"):
        matches = [(action, label) for action, label, pattern in self.rules if pattern.search(code)]
        if any(action == "block" for action, _ in matches):
            return Decision(7, tuple(label for _, label in matches), True)
        # Only simple shell commands receive lower automatic thresholds.
        required = 1
        tiers = {
            **dict.fromkeys(("pwd", "date", "uname", "whoami", "hostname", "uptime", "echo", "printf"), 1),
            **dict.fromkeys(("ls", "cat", "head", "tail", "wc", "stat", "file", "du", "df"), 2),
            **dict.fromkeys(("mkdir", "touch"), 3),
            **dict.fromkeys(("cp", "mv", "chmod"), 4),
            **dict.fromkeys(("curl", "wget", "ping"), 5),
        }
        if language not in {"bash", "sh", "zsh"}:
            required = 6
        else:
            for line in code.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                # Expansions, redirects, compound commands and substitutions are opaque.
                if re.search(r"[;&|<>$`\\(){}\x00-\x08\x1b]", line):
                    required = 6
                    break
                try:
                    words = shlex.split(line)
                    tier = tiers.get(words[0], 6) if words else 1
                    # These commands also have mutating forms; only bare inspection is tier 1.
                    if words and words[0] in {"date", "hostname"} and len(words) > 1:
                        tier = 6
                    if words and words[0] == "file" and any(w == "--compile" or (w.startswith("-") and "C" in w) for w in words[1:]):
                        tier = 6
                    required = max(required, tier)
                except ValueError:
                    required = 6
        reasons = ["simple command classification" if required < 6 else "general or complex code"]
        for action, label in matches:
            required = max(required, 7 if action == "manual" else int(action))
            reasons.append(label)
        return Decision(required, tuple(reasons))
