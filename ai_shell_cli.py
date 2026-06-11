#!/usr/bin/env python3
"""
Natural-language script generator with save and execution support.

(c) Copyright 2024 Antony J Ingram, All rights reserved
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from textwrap import indent
from typing import Callable, Dict, Optional, Sequence, Tuple

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field


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

HELP_TEXT = """\
Commands:
  :help             Show this help.
  :show             Show the last generated script.
  :save [path]      Save it, adding the correct extension when needed.
  :run [path]       Confirm and run the generated or specified script.
  :shell            Open an interactive Bash-compatible shell.
  :clear            Forget the current generated script.
  :quit             Exit.

Any other input is sent to the model as a script request.
"""

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is missing."
            )
        _client = OpenAI(api_key=api_key)
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
        "instructions": SYSTEM_PROMPT,
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


def confirmed(prompt: str, input_fn: Callable[[str], str] = input) -> bool:
    return input_fn(prompt).strip().lower() in {"y", "yes"}


def execute_path(
    path: Path,
    language: Optional[str] = None,
    input_fn: Callable[[str], str] = input,
) -> Optional[int]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    detected_language = language or language_from_path(path)
    command = command_for_script(path, detected_language)
    print(f"\nAbout to run: {shlex.join(command)}")
    if not confirmed("Run this script? [y/N] ", input_fn):
        print("Execution cancelled.")
        return None

    result = subprocess.run(command, cwd=Path.cwd(), check=False)
    print(f"\nProcess exited with status {result.returncode}.")
    return result.returncode


def execute_generated(
    script: GeneratedScript,
    input_fn: Callable[[str], str] = input,
) -> Optional[int]:
    spec = language_spec(script.language)
    with tempfile.TemporaryDirectory(prefix="ai-shell-cli-") as temp_dir:
        path = Path(temp_dir) / f"generated{spec.extension}"
        path.write_text(clean_code(script), encoding="utf-8")
        return execute_path(path, script.language, input_fn)


def open_shell(input_fn: Callable[[str], str] = input) -> Optional[int]:
    shell = os.getenv("SHELL") or shutil.which("bash") or shutil.which("sh")
    if not shell:
        raise RuntimeError("No interactive shell was found.")
    if not confirmed(f"Open interactive shell {shell}? [y/N] ", input_fn):
        print("Shell launch cancelled.")
        return None
    print("Type 'exit' to return to ai-shell-cli.")
    return subprocess.run([shell], cwd=Path.cwd(), check=False).returncode


def show_script(script: GeneratedScript) -> None:
    print(f"\nGenerated {script.language} script:")
    print(indent(clean_code(script).rstrip(), "   "))


def main() -> None:
    print(f"Natural-Language Script Shell | model {MODEL}")
    print("Type :help for commands or describe a script to generate.")
    current: Optional[GeneratedScript] = None

    while True:
        try:
            entry = input("\nai-shell> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not entry:
            continue

        command, _, argument = entry.partition(" ")
        command = command.lower()

        if command in {":quit", ":exit", "quit", "exit"}:
            print("Bye.")
            break
        if command == ":help":
            print(HELP_TEXT)
            continue
        if command == ":clear":
            current = None
            print("Current generated script cleared.")
            continue
        if command == ":show":
            if current:
                show_script(current)
            else:
                print("No script has been generated yet.")
            continue
        if command == ":shell":
            try:
                open_shell()
            except (OSError, RuntimeError) as error:
                print(f"Shell error: {error}", file=sys.stderr)
            continue
        if command == ":save":
            if not current:
                print("No script has been generated yet.")
                continue
            destination = parse_path_argument(argument) or None
            try:
                path = save_script(current, destination)
            except FileExistsError as error:
                path = Path(error.filename or error.args[0])
                if not confirmed(f"{path} exists. Overwrite it? [y/N] "):
                    print("Save cancelled.")
                    continue
                path = save_script(current, destination, overwrite=True)
            except OSError as error:
                print(f"Save error: {error}", file=sys.stderr)
                continue
            print(f"Saved {current.language} script to {path}")
            continue
        if command == ":run":
            try:
                if argument.strip():
                    execute_path(Path(parse_path_argument(argument)))
                elif current:
                    show_script(current)
                    execute_generated(current)
                else:
                    print("No script has been generated yet.")
            except (OSError, RuntimeError) as error:
                print(f"Execution error: {error}", file=sys.stderr)
            continue
        if command.startswith(":"):
            print(f"Unknown command: {command}. Type :help.")
            continue

        try:
            current = generate_script(entry)
        except (OpenAIError, RuntimeError, ValueError) as error:
            print(f"OpenAI API error: {error}", file=sys.stderr)
            continue

        show_script(current)
        print("\nUse :save [path] to save it or :run to execute it.")


if __name__ == "__main__":
    main()
