# ai-shell-cli

An interactive natural-language script shell using the OpenAI Responses API.
It generates a structured script artifact, displays it for review, saves it
with an appropriate extension, and can run it after explicit confirmation.

## Features

- Generates Bash, Python, JavaScript, PowerShell, and other script formats.
- Uses structured OpenAI output instead of parsing Markdown code blocks.
- Adds a suitable file extension and shebang when known.
- Saves without silently overwriting existing files.
- Runs scripts through an installed interpreter without `shell=True`.
- Requires confirmation before every generated or saved script execution.
- Opens a normal interactive shell with `:shell`.
- Reports model refusals, content filtering, and incomplete responses.

## Install

```bash
git clone git@github.com:vrosuits/ai-shell-cli.git
cd ai-shell-cli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
python ai_shell_cli.py
```

Optional configuration:

```bash
export OPENAI_MODEL="gpt-5.5"
export OPENAI_REASONING_EFFORT="low"
export OPENAI_TEXT_VERBOSITY="low"
export OPENAI_MAX_OUTPUT_TOKENS="2048"
```

## Interactive Commands

```text
:help             Show command help.
:show             Show the last generated script.
:save [path]      Save it with the correct extension.
:run [path]       Confirm and run the generated or specified script.
:shell            Open an interactive Bash-compatible shell.
:clear            Forget the current generated script.
:quit             Exit.
```

Any other input is treated as a script-generation request:

```text
ai-shell> write a bash script that lists files larger than 100 MB

Generated bash script:
   #!/usr/bin/env bash
   find . -type f -size +100M -print

Use :save [path] to save it or :run to execute it.
```

Examples:

```text
:save find-large-files
:run
:run ./existing_script.py
:shell
```

If no filename is supplied, `:save` uses the model's suggested filename. If
that file already exists, a numbered filename is selected. If an explicit
destination already exists, the CLI asks before overwriting it.

## Languages

The CLI knows extensions and common interpreters for Bash, POSIX shell, Zsh,
Fish, Python, JavaScript, TypeScript, PowerShell, Ruby, Perl, PHP, Lua, AWK,
sed, Go, R, and Windows batch files.

It can also save common non-script source and data formats including C, C++,
C#, Java, Kotlin, Rust, Swift, SQL, HTML, CSS, JSON, YAML, and TOML. Formats
without a directly supported runtime are saved but not executed. Unknown
formats can run only when their source contains a usable shebang.

The required interpreter must be installed and available on `PATH`.

## Safety

Generated code can delete data, change permissions, install software, or send
information over the network. Always review the displayed script. The CLI
requires confirmation before execution, but confirmation does not make unsafe
code safe.

## Test

```bash
python -m unittest discover -s tests -v
```
