#!/usr/bin/env python3
"""
Natural-language script generator with save and execution support.

(c) Copyright 2024 Antony J Ingram, All rights reserved
"""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Tuple

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from aishell_core.credentials import load_key, secure_base_url, child_environment, setup_key, read_values, ENV_NAME
from aishell_core.display import Display, MODES
from aishell_core.extensions import Extensions
from aishell_core.policy import Policy, LEVELS


MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low")
TEXT_VERBOSITY = os.getenv("OPENAI_TEXT_VERBOSITY", "low")
MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "2048"))


class GeneratedScript(BaseModel):
    language: str = Field(
        min_length=1,
        description="The lowercase programming or shell language name."
    )
    suggested_filename: str = Field(
        min_length=1,
        description="A short safe filename without directories."
    )
    code: str = Field(
        min_length=1,
        description="Complete executable source code with no Markdown fences."
    )


@dataclass(frozen=True)
class LanguageSpec:
    extension: str
    commands: Tuple[Tuple[str, ...], ...] = ()
    shebang: Optional[str] = None


LANGUAGE_SPECS: Dict[str, LanguageSpec] = {
    "bash": LanguageSpec(".sh", (("bash",),), "#!/usr/bin/env bash"),
    "sh": LanguageSpec(".sh", (("sh",),), "#!/bin/sh"),
    "zsh": LanguageSpec(".zsh", (("zsh",),), "#!/usr/bin/env zsh"),
    "fish": LanguageSpec(".fish", (("fish",),), "#!/usr/bin/env fish"),
    "python": LanguageSpec(
        ".py", ((sys.executable,), ("python3",), ("python",)),
        "#!/usr/bin/env python3",
    ),
    "javascript": LanguageSpec(
        ".js", (("node",), ("deno", "run")), "#!/usr/bin/env node"
    ),
    "typescript": LanguageSpec(
        ".ts", (("tsx",), ("ts-node",), ("deno", "run"))
    ),
    "powershell": LanguageSpec(
        ".ps1", (("pwsh", "-File"), ("powershell", "-File"))
    ),
    "ruby": LanguageSpec(".rb", (("ruby",),), "#!/usr/bin/env ruby"),
    "perl": LanguageSpec(".pl", (("perl",),), "#!/usr/bin/env perl"),
    "php": LanguageSpec(".php", (("php",),), "#!/usr/bin/env php"),
    "lua": LanguageSpec(".lua", (("lua",),), "#!/usr/bin/env lua"),
    "awk": LanguageSpec(".awk", (("awk", "-f"),)),
    "sed": LanguageSpec(".sed", (("sed", "-f"),)),
    "go": LanguageSpec(".go", (("go", "run"),)),
    "r": LanguageSpec(".R", (("Rscript",),)),
    "batch": LanguageSpec(".bat", (("cmd", "/c"),)),
    "c": LanguageSpec(".c"),
    "cpp": LanguageSpec(".cpp"),
    "csharp": LanguageSpec(".cs"),
    "java": LanguageSpec(".java"),
    "kotlin": LanguageSpec(".kt"),
    "rust": LanguageSpec(".rs"),
    "swift": LanguageSpec(".swift"),
    "sql": LanguageSpec(".sql"),
    "html": LanguageSpec(".html"),
    "css": LanguageSpec(".css"),
    "json": LanguageSpec(".json"),
    "yaml": LanguageSpec(".yaml"),
    "toml": LanguageSpec(".toml"),
    "text": LanguageSpec(".txt"),
}

LANGUAGE_ALIASES = {
    "shell": "bash",
    "shellscript": "bash",
    "shell script": "bash",
    "posix shell": "sh",
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "ts": "typescript",
    "ps1": "powershell",
    "pwsh": "powershell",
    "rb": "ruby",
    "pl": "perl",
    "golang": "go",
    "rscript": "r",
    "bat": "batch",
    "cmd": "batch",
    "c++": "cpp",
    "cs": "csharp",
    "c#": "csharp",
    "rs": "rust",
    "gawk": "awk",
    "yml": "yaml",
    "plain text": "text",
}

EXTENSION_LANGUAGES = {
    spec.extension.lower(): language
    for language, spec in LANGUAGE_SPECS.items()
}

SHEBANG_LANGUAGES = {
    "bash": "bash",
    "zsh": "zsh",
    "fish": "fish",
    "python": "python",
    "node": "javascript",
    "deno": "javascript",
    "ruby": "ruby",
    "perl": "perl",
    "php": "php",
    "lua": "lua",
    "awk": "awk",
    "sed": "sed",
    "/bin/sh": "sh",
    "env sh": "sh",
}

SYSTEM_PROMPT = """\
You generate complete scripts for a local command-line tool.

Choose the language that best matches the user's request. Default to Bash for
Unix command sequences unless the user asks for another language. Return a
complete script, not an explanation. Include a shebang when appropriate.
Use comments inside the script where they improve safety or clarity.
Never wrap the code in Markdown fences.
"""

HELP_TEXT = """Commands:
  :help                  Show help.
  :show                  Inspect the complete current script.
  :save [path]           Save source (confirm overwrites).
  :run [path]            Run using the active autonomy policy.
  :shell                 Open a shell after manual approval.
  :mode MODE             classic, color, raw, summary.
  :autonomy 0..6         Change execution approval threshold.
  :status                Show session settings.
  :policy                Explain policy for the current script.
  :levels                List all seven autonomy levels.
  :sound on|off          Toggle terminal completion bell.
  :plugins               List explicitly loaded plugin manifests.
  :tools                 List tools; :tool NAME to inspect and execute.
  :skills                List skills; :skill NAME|off to select one.
  :commands              List prompt templates; :command NAME INPUT to use.
  :clear                 Forget current script.
  :quit                  Exit.

Describe a script to generate it. Generation alone never runs a script.
Use --prompt TEXT --run for a one-shot generate/review/execute workflow.
"""

_display = None
_policy = None
_autonomy = 0
_env_file = Path(".env")
_extensions = Extensions()


def display():
    return _display or Display()


def policy():
    return _policy or Policy()


def ask(prompt):
    # Keep prompts out of stdout, particularly in raw mode.
    print(prompt, end="", file=sys.stderr, flush=True)
    return input()

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        base_url = secure_base_url()
        _client = OpenAI(api_key=load_key(_env_file), base_url=base_url)
    return _client


def canonical_language(language: str) -> str:
    normalized = " ".join(language.strip().lower().split())
    if normalized.endswith(" script"):
        normalized = normalized[:-7].strip()
    return LANGUAGE_ALIASES.get(normalized, normalized)


def safe_filename(filename: str) -> str:
    basename = Path(filename).name.strip()
    basename = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    basename = basename.strip("._-")
    return basename or "generated_script"


def language_spec(language: str) -> LanguageSpec:
    return LANGUAGE_SPECS.get(
        canonical_language(language),
        LanguageSpec(".txt"),
    )


def clean_code(script: GeneratedScript) -> str:
    code = script.code.strip()
    if code.startswith("```") and code.endswith("```"):
        lines = code.splitlines()
        code = "\n".join(lines[1:-1]).strip()

    spec = language_spec(script.language)
    if spec.shebang and not code.startswith("#!"):
        code = f"{spec.shebang}\n{code}"
    return f"{code}\n"


def response_error(response) -> str:
    refusals = [
        content.refusal
        for item in response.output
        if item.type == "message"
        for content in item.content
        if content.type == "refusal"
    ]
    if refusals:
        return f"The model refused the request: {' '.join(refusals)}"

    if response.error:
        return f"{response.error.code}: {response.error.message}"

    reason = (
        response.incomplete_details.reason
        if response.incomplete_details
        else None
    )
    if reason == "max_output_tokens":
        return (
            "The response used the output-token budget before producing a "
            "complete script. Increase OPENAI_MAX_OUTPUT_TOKENS."
        )
    if reason == "content_filter":
        return "The response was stopped by the content filter."

    return (
        f"The API returned no script (status={response.status}, "
        f"model={response.model}, response_id={response.id})."
    )


def generate_script(query: str) -> GeneratedScript:
    request = {
        "model": MODEL,
        "instructions": SYSTEM_PROMPT + ("\nSelected user skill:\n" + _extensions.instructions() if _extensions.instructions() else ""),
        "input": query,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "text_format": GeneratedScript,
    }
    if MODEL.startswith(("gpt-5", "o1", "o3", "o4")):
        request["reasoning"] = {"effort": REASONING_EFFORT}
    if MODEL.startswith("gpt-5"):
        request["text"] = {"verbosity": TEXT_VERBOSITY}

    response = get_client().responses.parse(**request)
    script = response.output_parsed
    if script is None:
        raise RuntimeError(response_error(response))

    script.language = canonical_language(script.language)
    script.suggested_filename = safe_filename(script.suggested_filename)
    script.code = clean_code(script)
    return script


def normalized_path(path: Path, language: str) -> Path:
    spec = language_spec(language)
    if spec.extension == ".txt" and path.suffix:
        return path
    if path.suffix.lower() != spec.extension.lower():
        if path.suffix:
            return path.with_suffix(spec.extension)
        return Path(f"{path}{spec.extension}")
    return path


def default_script_path(script: GeneratedScript) -> Path:
    raw_name = safe_filename(script.suggested_filename)
    return normalized_path(Path(raw_name), script.language)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for number in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find an available filename for {path}.")


def save_script(
    script: GeneratedScript,
    destination: Optional[str] = None,
    overwrite: bool = False,
) -> Path:
    path = (
        normalized_path(Path(destination).expanduser(), script.language)
        if destination
        else unique_path(default_script_path(script))
    )
    if path.exists() and not overwrite:
        raise FileExistsError(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(clean_code(script), encoding="utf-8")
    if language_spec(script.language).commands or script.code.startswith("#!"):
        path.chmod(path.stat().st_mode | 0o100)
    return path.resolve()


def language_from_path(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as script_file:
            first_line = script_file.readline().lower()
    except (OSError, UnicodeDecodeError):
        first_line = ""
    if first_line.startswith("#!"):
        for marker, language in SHEBANG_LANGUAGES.items():
            if marker in first_line:
                return language
    return EXTENSION_LANGUAGES.get(path.suffix.lower(), "text")


def parse_path_argument(argument: str) -> str:
    argument = argument.strip()
    if not argument:
        return ""
    try:
        parts = shlex.split(argument)
    except ValueError:
        return argument
    return parts[0] if len(parts) == 1 else argument


def command_for_script(path: Path, language: str) -> Sequence[str]:
    spec = language_spec(language)
    for candidate in spec.commands:
        executable = candidate[0]
        resolved = (
            executable
            if os.path.isabs(executable) and os.access(executable, os.X_OK)
            else shutil.which(executable)
        )
        if resolved:
            return [resolved, *candidate[1:], str(path)]

    try:
        with path.open(encoding="utf-8") as script_file:
            first_line = script_file.readline()
    except UnicodeDecodeError:
        first_line = ""
    if first_line.startswith("#!"):
        path.chmod(path.stat().st_mode | 0o100)
        return [str(path.resolve())]

    canonical = canonical_language(language)
    if spec.commands:
        expected = ", ".join(command[0] for command in spec.commands)
        raise RuntimeError(
            f"No interpreter for {canonical} was found. Install one of: "
            f"{expected}."
        )
    raise RuntimeError(
        f"Files identified as {canonical} can be saved but are not directly "
        "runnable by this CLI."
    )


def confirmed(prompt: str, input_fn: Callable[[str], str] = ask) -> bool:
    return input_fn(prompt).strip().lower() in {"y", "yes"}


def execute_path(
    path: Path,
    language: Optional[str] = None,
    input_fn: Callable[[str], str] = ask,
) -> Optional[int]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    detected_language = language or language_from_path(path)
    source = path.read_text(encoding="utf-8")
    decision = policy().assess(source, detected_language)
    ui = display()
    ui.message(f"Execution policy: {decision.description}")
    if decision.blocked:
        ui.message("Execution blocked by policy.", error=True)
        return None
    if not decision.automatic(_autonomy):
        # Review the actual source, including existing files and summary mode.
        review = GeneratedScript(language=detected_language, suggested_filename=path.name, code=source)
        if ui.mode == "raw":
            ui.message(source)
        else:
            ui.script(review, force=True)
        if not confirmed("Run this script? [y/N] ", input_fn):
            ui.message("Execution cancelled.")
            return None
    else:
        ui.message(f"Automatically approved at autonomy {_autonomy}/6.")

    # Run precisely the reviewed bytes, not a file that can change at the prompt.
    with tempfile.TemporaryDirectory(prefix="ai-shell-run-") as temp_dir:
        snapshot = Path(temp_dir) / path.name
        snapshot.write_text(source, encoding="utf-8")
        command = command_for_script(snapshot, detected_language)
        ui.message(f"Running {path.name} with {Path(command[0]).name} …")
        result = subprocess.run(
            command, cwd=Path.cwd(), check=False, env=child_environment(),
            stdout=sys.stderr if ui.mode == "raw" else None,
        )
    ui.message(f"Process exited with status {result.returncode}.")
    ui.notify()
    return result.returncode


def execute_generated(
    script: GeneratedScript,
    input_fn: Callable[[str], str] = ask,
) -> Optional[int]:
    spec = language_spec(script.language)
    with tempfile.TemporaryDirectory(prefix="ai-shell-cli-") as temp_dir:
        path = Path(temp_dir) / f"generated{spec.extension}"
        path.write_text(clean_code(script), encoding="utf-8")
        return execute_path(path, script.language, input_fn)


def open_shell(input_fn: Callable[[str], str] = ask) -> Optional[int]:
    shell = os.getenv("SHELL") or shutil.which("bash") or shutil.which("sh")
    if not shell:
        raise RuntimeError("No interactive shell was found.")
    decision = policy().assess(f"aishell-interactive-shell {shell}", "text")
    display().message(f"Shell policy: {decision.description}")
    if decision.blocked:
        display().message("Shell launch blocked by policy.")
        return None
    if not decision.automatic(_autonomy) and not confirmed(f"Open interactive shell {shell}? [y/N] ", input_fn):
        display().message("Shell launch cancelled.")
        return None
    display().message("Type 'exit' to return to ai-shell-cli.")
    return subprocess.run([shell], cwd=Path.cwd(), check=False, env=child_environment(), stdout=sys.stderr if display().mode == "raw" else None).returncode


def show_script(script: GeneratedScript) -> None:
    display().script(script.model_copy(update={"code": clean_code(script)}))


def make_parser():
    parser = argparse.ArgumentParser(description="AI Shell — generate, inspect and execute scripts.")
    parser.add_argument("--mode", choices=MODES, default="classic")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--ascii", action="store_true", help="Use ASCII borders and indicators")
    parser.add_argument("--sound", action="store_true", help="Ring the terminal bell on completion")
    parser.add_argument("--autonomy", type=int, choices=range(7), default=0)
    parser.add_argument("--policy", type=Path, help="Explicit replacement dangerous-command policy")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--plugin", action="append", default=[], type=Path, help="Load an explicit JSON plugin (repeatable)")
    parser.add_argument("--skill", help="Activate a skill from a loaded plugin")
    parser.add_argument("--prompt", help="Generate once, then exit")
    parser.add_argument("--run", action="store_true", help="Execute the generated script through policy (requires --prompt)")
    parser.add_argument("--demo", action="store_true", help="Preview the UI without API access or execution")
    sub = parser.add_subparsers(dest="subcommand")
    key = sub.add_parser("key", help="Secure credential setup and status")
    key.add_argument("action", choices=("set", "status"))
    key.add_argument("--file", type=Path, default=Path(".env"))
    key.add_argument("--from-env", action="store_true", help="Encrypt the existing environment key")
    return parser


def generate_with_status(query):
    ui = display()
    with ui.working("Generating script …"):
        script = generate_script(query)
    show_script(script)
    ui.notify()
    return script


def main(argv=None) -> int:
    global _display, _policy, _autonomy, _env_file, _extensions
    parser = make_parser()
    args = parser.parse_args(argv)
    _display = Display(args.mode, args.color, args.ascii, args.sound)
    ui = display()
    if args.run and not args.prompt:
        parser.error("--run requires --prompt")
    try:
        if args.subcommand == "key":
            if args.action == "set":
                if args.file.exists() and not confirmed(f"Update credential entries in {args.file}? [y/N] "):
                    return 1
                setup_key(args.file, args.from_env)
                ui.message(f"Encrypted key saved to {args.file}. Passphrase is not stored. Environment keys take precedence.")
            else:
                values = read_values(args.file)
                ui.message(f"Environment key: {'present' if os.getenv('OPENAI_API_KEY') else 'absent'}; file: {'encrypted' if ENV_NAME in values else 'plaintext' if 'OPENAI_API_KEY' in values else 'no key'}")
            return 0
        _policy = Policy(args.policy)
        _autonomy, _env_file = args.autonomy, args.env_file
        _extensions = Extensions()
        for path in args.plugin:
            _extensions.load(path)
        if args.skill:
            if args.skill not in _extensions.skills:
                raise ValueError(f"Unknown skill: {args.skill}")
            _extensions.active_skill = args.skill
        if args.demo:
            ui.banner(MODEL, _autonomy)
            show_script(GeneratedScript(language="python", suggested_filename="hello_terminal.py", code='#!/usr/bin/env python3\nfrom pathlib import Path\n\n# A little clarity goes a long way.\nfor path in sorted(Path.cwd().iterdir()):\n    print(f"{path.name:32} {path.stat().st_size:>10,} bytes")\n'))
            ui.table("Session", [("Display", args.mode), ("Autonomy", f"{_autonomy} / {LEVELS[_autonomy]}"), ("Execution", "Demo only; no code executed"), ("Commands", ":mode  :levels  :tools  :skills  :policy")])
            ui.notify()
            return 0
        if args.prompt:
            current = generate_with_status(args.prompt)
            if args.run:
                # Batch mode must never consume piped input as approval.
                approval = ask if sys.stdin.isatty() else lambda _: "no"
                result = execute_generated(current, input_fn=approval)
                return 1 if result is None else result
            return 0
    except (OSError, RuntimeError, ValueError, EOFError) as error:
        ui.message(str(error), error=True)
        return 1
    except OpenAIError as error:
        ui.message(f"OpenAI request failed ({type(error).__name__}). Check credentials, connectivity and model access.", error=True)
        return 1

    ui.banner(MODEL, _autonomy)
    if ui.mode != "raw":
        ui.message("Type :help for commands or describe a script to generate.")
    current = None
    while True:
        try:
            entry = ask("\nai-shell> ").strip()
            if not entry:
                continue
            command, _, argument = entry.partition(" ")
            command = command.lower()
            if command in {":quit", ":exit", "quit", "exit"}:
                return 0
            if command == ":help":
                ui.message(HELP_TEXT)
            elif command == ":clear":
                current = None
                ui.message("Current generated script cleared.")
            elif command == ":show":
                if current:
                    ui.script(current, force=True)
                else:
                    ui.message("No script has been generated yet.")
            elif command == ":mode":
                if argument not in MODES:
                    raise ValueError("Choose classic, color, raw, or summary.")
                ui.mode = argument
                ui.message(f"Display mode: {argument}")
            elif command == ":autonomy":
                level = int(argument)
                if level not in LEVELS:
                    raise ValueError("Autonomy must be 0..6.")
                _autonomy = level
                ui.message(f"Autonomy: {level} / {LEVELS[level]}")
            elif command == ":levels":
                ui.table("Autonomy (cumulative)", [(str(k), v) for k, v in LEVELS.items()])
            elif command == ":status":
                ui.table("Session", [("Model", MODEL), ("Mode", ui.mode), ("Autonomy", f"{_autonomy} / {LEVELS[_autonomy]}"), ("Policy", str(policy().path)), ("Skill", _extensions.active_skill or "off"), ("Sound", "on" if ui.sound else "off")])
            elif command == ":policy":
                ui.message(policy().assess(clean_code(current), current.language).description if current else "Generate a script first.")
            elif command == ":sound":
                if argument not in {"on", "off"}:
                    raise ValueError("Use :sound on or :sound off.")
                ui.sound = argument == "on"
                ui.message(f"Sound: {argument}")
            elif command == ":plugins":
                ui.message("\n".join(_extensions.sources) or "No plugins loaded. Start with --plugin PATH.")
            elif command in {":tools", ":skills", ":commands"}:
                entries = getattr(_extensions, command[1:])
                ui.table(command[1:].title(), [(name, value.get("language", "") if isinstance(value, dict) else value) for name, value in entries.items()] or [("None", "Load an explicit --plugin PATH")])
            elif command == ":skill":
                if argument != "off" and argument not in _extensions.skills:
                    raise ValueError(f"Unknown skill: {argument}")
                _extensions.active_skill = None if argument == "off" else argument
                ui.message(f"Skill: {argument}")
            elif command == ":tool":
                if argument not in _extensions.tools:
                    raise ValueError(f"Unknown tool: {argument}")
                tool = _extensions.tools[argument]
                current = GeneratedScript(language=canonical_language(tool["language"]), suggested_filename=argument, code=tool["code"])
                current.code = clean_code(current)
                show_script(current)
                execute_generated(current)
            elif command == ":shell":
                open_shell()
            elif command == ":save":
                if not current:
                    raise ValueError("No script has been generated yet.")
                destination = parse_path_argument(argument) or None
                try:
                    path = save_script(current, destination)
                except FileExistsError as error:
                    path = Path(error.filename or error.args[0])
                    decision = policy().assess(f"aishell-overwrite {path}", "text")
                    if decision.blocked:
                        ui.message("Overwrite blocked by policy.")
                        continue
                    if not decision.automatic(_autonomy) and not confirmed(f"{path} exists. Overwrite it? [y/N] "):
                        ui.message("Save cancelled.")
                        continue
                    path = save_script(current, destination, overwrite=True)
                ui.message(f"Saved {current.language} script to {path}")
            elif command == ":run":
                if argument.strip():
                    execute_path(Path(parse_path_argument(argument)))
                elif current:
                    execute_generated(current)
                else:
                    raise ValueError("No script has been generated yet.")
            elif command == ":command":
                name, _, supplied = argument.partition(" ")
                current = generate_with_status(_extensions.prompt(name, supplied))
            elif command.startswith(":"):
                ui.message(f"Unknown command: {command}. Type :help.")
            else:
                current = generate_with_status(entry)
                if ui.mode != "raw":
                    ui.message("Use :save [path] or :run.")
        except EOFError:
            return 0
        except KeyboardInterrupt:
            ui.message("Interrupted. Type :quit to exit.")
        except (OSError, RuntimeError, ValueError) as error:
            ui.message(str(error), error=True)
        except OpenAIError as error:
            ui.message(f"OpenAI request failed ({type(error).__name__}). Check credentials, connectivity and model access.", error=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
