# AI Shell

A terminal workbench that turns natural-language requests into runnable scripts.
Review highlighted source, select an approval level, load tools and skills, and
keep your API credential encrypted on disk. The original generate → inspect →
save/run workflow remains the default.

## Versions

**[v2.0.0 — latest release](https://github.com/vrosuits/ai-shell-cli/releases/tag/v2.0.0)**
is the upgraded workbench shown on the default `main` branch.
The previous script generator remains available as
**[v1.0.0 — classic release](https://github.com/vrosuits/ai-shell-cli/releases/tag/v1.0.0)**,
including downloadable source archives and its original documentation.

```bash
# Get the current version:
git clone https://github.com/vrosuits/ai-shell-cli.git
cd ai-shell-cli

# Optional: use the preserved old version instead:
git switch --detach v1.0.0
```

To return to the new version, run `git switch main`. Update Python dependencies
with `python -m pip install -r requirements.txt` after switching versions.
Existing environment keys continue to work; encrypted storage is opt-in.
See [CHANGELOG.md](CHANGELOG.md) for changes and compatibility notes.

## Start here

Requires Python 3.10+ and the interpreter for any scripts you execute.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python ai_shell_cli.py --demo --mode color
python ai_shell_cli.py --mode color
```

An existing `OPENAI_API_KEY` environment variable works unchanged. To store a
key encrypted instead, use the hidden-input setup command below. `--demo` needs
no key, makes no API request, and never executes the displayed code.

## Four views

| Mode | Behavior |
| --- | --- |
| `classic` | Familiar indented script view; default. |
| `color` | ANSI 24-bit syntax colors, line numbers, Unicode panels and progress spinner. |
| `raw` | Source only on stdout. Prompts, status and executed-program stdout go to stderr. |
| `summary` | Generation/execution status, filename, language, line and byte counts. `:show` reveals source. |

```bash
python ai_shell_cli.py --mode color --sound
python ai_shell_cli.py --mode raw --prompt 'Write a Python hello-world script' > hello.py
python ai_shell_cli.py --mode summary --prompt 'List the current directory' --run --autonomy 2
```

Use `:mode color` to switch during a session. Color is terminal-aware;
`--color always` forces true-color output, while `--color never`, `NO_COLOR`, or
`TERM=dumb` disables it. `--ascii` uses ASCII chrome; source glyphs remain intact.
`--sound` / `:sound on` enables a terminal completion bell (audibility depends on
terminal settings). It is off by default. Display controls in generated source
are escaped for review; raw mode preserves the source.

## Seven autonomy levels

Autonomy controls **execution approval**, not whether generation automatically
runs code. Interactive generation always produces a reviewable artifact; use
`:run` or one-shot `--prompt ... --run` to execute. Level 0 is the default.

| Level | Name | Automatically approves |
| --- | --- | --- |
| 0 | Manual | Nothing; each execution requires `yes`. |
| 1 | Inspect | Simple `pwd`, `uname`, `whoami`, `echo`, `printf`, and similar inspection commands. |
| 2 | Read | Also simple `ls`, `cat`, `head`, `tail`, `wc`, `stat`, `file`, `du`, `df`. |
| 3 | Create | Also simple `mkdir` and `touch`. |
| 4 | Modify | Also simple `cp`, `mv`; dangerous rules still apply. |
| 5 | Network | Also simple `curl`, `wget`, `ping`. |
| 6 | Automatic | General scripts, other languages and compound shell code, subject to policy rules. |

```bash
python ai_shell_cli.py --mode color --autonomy 6
```

Use `:autonomy 0`, `:levels`, `:status`, and `:policy` inside the session.
Non-interactive one-shot execution never reads piped text as approval: when a
rule requires approval and stdin is not a terminal, execution is declined and
the CLI exits with status 1. Executed programs return their actual exit status.

### Dangerous-command policy

[dangerous_cmds.txt](dangerous_cmds.txt) is loaded relative to the installed
program, **not automatically from the current directory**. Choose an explicit
replacement with `--policy /path/to/policy.txt`. Missing or malformed policies
stop startup. Edit the file and restart to apply changes.

```text
# action|reason|case-insensitive regular expression
manual|Deletion|\b(rm|rmdir|unlink)\b
5|Network access|\b(curl|wget)\b
block|Forbidden operation|my-forbidden-command
```

Actions are `manual`, `block`, or a minimum automatic level `1`–`6`. Every
matching rule applies; the most restrictive wins. Numeric rules can raise the
base classification but cannot lower it. Shell substitutions, redirects,
compound syntax, and non-shell programs default to level 6. A block cannot be
overridden at an approval prompt. Default rules require manual approval for
privilege escalation, deletion, disk administration, credential access,
interactive shells, existing-file overwrites, and other sensitive operations.
Shell and overwrite rules use `aishell-interactive-shell` and
`aishell-overwrite` markers respectively.

**This is a heuristic review aid, not a sandbox or complete command parser.**
Obfuscated commands, imported modules, subprocesses, interpreter startup files,
and indirect effects can evade textual matching. Level 6 runs unrecognized
code automatically. Only use it with code and extensions you trust. Commands
run with your normal OS permissions. An opened interactive shell is outside
per-command inspection. Use an isolated OS/container account for untrusted code.

Every generated script, existing script, and extension tool uses the same
execution policy. Before a manual approval, the full script is shown even in
summary mode. Execution uses a private temporary snapshot so changing the
original file at the approval prompt does not replace the reviewed source.
The working directory stays unchanged, but the script's own path (`__file__`,
`$0`) points to that snapshot; scripts depending on sibling imports/files may
need explicit absolute paths. Imported code and referenced files are not frozen.

## Encrypted API-key setup

```bash
# Enter an existing key and a new passphrase through hidden terminal prompts:
python ai_shell_cli.py key set

# Or encrypt the existing OPENAI_API_KEY environment variable:
python ai_shell_cli.py key set --from-env

# Alternate destination; inspect status without displaying any secret:
python ai_shell_cli.py key set --file .env.local
python ai_shell_cli.py key status --file .env.local
python ai_shell_cli.py --env-file .env.local --mode color
```

The setup tool writes `OPENAI_API_KEY_ENCRYPTED=v1:...`, using AES-256-GCM
with a fresh salt and nonce and a scrypt-derived key (`N=131072, r=8, p=1`).
It requires a passphrase of at least 12 characters, asks for confirmation,
replaces existing key entries, preserves other `.env` entries, and writes
atomically with owner-only permissions on POSIX. Existing files require an
update confirmation; symlink targets are refused. The passphrase is never
stored alongside the ciphertext. No secret is accepted as a command argument.

Precedence: environment `OPENAI_API_KEY`, then encrypted file entry, then legacy
plaintext file entry. Only credential entries are read from `.env`; export model
settings in the environment. To use the encrypted file after migration, remove
the old environment export (`unset OPENAI_API_KEY` in Bash). Unlock prompts
occur when the first API request needs the key; the client is reused afterward.
A forgotten passphrase cannot be recovered: replace the encrypted entry using
your API key or a newly issued one. Encryption does not revoke existing keys.

The client requires an HTTPS `OPENAI_BASE_URL` (default:
`https://api.openai.com/v1`) and uses normal SDK certificate verification for
transport encryption. The provider receives the decrypted credential over TLS;
it must also exist in this process's memory while in use. Generated programs do
not inherit `OPENAI_*` environment variables, but they still have filesystem
access and can read files permitted to your account. Encryption cannot protect
against an already-compromised process or replace OS access controls. Windows
users should restrict access using filesystem ACLs. Existing plaintext backups,
exports and shell history are not erased by migration.

The implementation follows the [OpenAI authentication guidance](https://developers.openai.com/api/reference/overview)
and uses the [cryptography authenticated-encryption primitives](https://cryptography.io/en/latest/hazmat/primitives/aead/).

## Notification hooks and reviewed changes

Use `--hooks examples/hooks.json` to enable explicit lifecycle notifications and
private JSONL activity logs. Available hooks cover startup/shutdown, errors, and
before/after generation, execution, saves, shell launches, patch proposals and
plugin loading. External notifications use signed HTTPS requests; responses are
ignored and cannot modify source or configuration. There is no inbound server.

`:patch relative/file.py` writes the current proposed source as an inert review
patch without changing the target. Apply changes only after human review through
normal tests, version control and deployment. See [HOOKS.md](HOOKS.md) for the
stable event schema, authentication, receiver validation, configuration and limits.

## Tools, skills, commands, plugins and modules

Load explicitly selected JSON manifests; nothing in an arbitrary project's
plugin directory is imported or executed automatically:

```bash
python ai_shell_cli.py --mode color --plugin examples/developer.json --skill careful-shell
```

```text
:plugins
:tools
:tool disk
:skills
:skill careful-shell
:commands
:command test Python unittest
:skill off
```

A plugin bundles tool scripts, reusable prompt commands, and generation skills:

```json
{
  "version": 1,
  "tools": {
    "disk": {"language": "bash", "code": "df -h"},
    "my-module": {"language": "python", "code": "from my_package import report\nreport()"}
  },
  "commands": {"backup": "Generate a backup script for: {input}"},
  "skills": {"portable": "Prefer POSIX shell and quote every path."}
}
```

Repeat `--plugin` to combine manifests. Names must be lowercase letters,
digits, `_` or `-`, beginning with a letter; duplicates are errors. Invalid
manifests load no partial content. Loading reads data only. `:tool NAME` displays
and executes the tool through the normal policy inside a required Linux
Bubblewrap sandbox. Tools take no interpolated
arguments; edit the manifest or use a prompt template for parameterized work.
Python or other language modules can be called from tool scripts through the
installed interpreter. Install those modules in that interpreter's environment.
Install the OS `bubblewrap` package to run tools: they have no host workspace/home
mounts, network access, writable host filesystem, or interactive input. Their
output is sanitized and bounded. Sandbox failure never triggers an unsandboxed
retry. See [HOOKS.md](HOOKS.md) for platform and compatibility restrictions.

`:command NAME INPUT` substitutes `{input}` in a prompt, then generates a script;
it does not substitute arguments into executable shell text. A selected skill
adds its instructions to generation requests until disabled. These are
user-invoked tools and prompt skills, not an autonomous model tool-calling loop
or an MCP server. Plugin text and imported modules must be trusted.

## Interactive commands

```text
:help                  Full command help
:show                  Show all current source
:save [path]           Save with the correct language extension
:patch path            Write a review patch without applying it
:run [path]            Execute current or existing script through policy
:shell                 Open a normal shell (manual approval by default)
:mode MODE             Switch display mode
:autonomy 0..6         Change approval threshold
:levels                List levels
:status                Show session configuration
:policy                Explain current script's execution classification
:sound on|off          Toggle completion bell
:plugins               List loaded manifests
:tools                 List tools
:tool NAME             Inspect and execute a tool
:skills                List skills
:skill NAME|off        Select generation instructions
:commands              List prompt templates
:command NAME INPUT   Generate using a template
:clear                 Forget current source
:quit                  Exit
```

Saving without a destination chooses a unique filename. Explicit overwrites
require approval by default. Unknown `:commands` are never sent to the API.

## Models and languages

The existing Responses API structured-output integration is retained, including
refusal/incomplete-response handling and configurable output-token limits.

```bash
export OPENAI_MODEL="gpt-5.5"
export OPENAI_REASONING_EFFORT="low"
export OPENAI_TEXT_VERBOSITY="low"
export OPENAI_MAX_OUTPUT_TOKENS="2048"
```

Known runtimes include Bash, sh, Zsh, Fish, Python, JavaScript, TypeScript,
PowerShell, Ruby, Perl, PHP, Lua, AWK, sed, Go, R and batch. Other source/data
formats can be saved; they require an installed runtime or an executable
shebang to run. Interpreter availability is checked at execution time.

The optional Node launcher forwards all arguments and prefers the repository's
virtual environment. Set `AISHELL_PYTHON` to select another Python executable.
The npm package includes the Python modules, policy and dependency list; Python
dependencies still need installation with `pip install -r requirements.txt`.

## Verification

```bash
python -m unittest discover -s tests -v
python ai_shell_cli.py --demo --mode color
node aishell.js --demo --mode raw
```

Tests use synthetic credentials and mocked API responses; they do not spend API
credits. They cover policy thresholds and overrides, reviewed-source snapshots,
credential authentication and tamper rejection, plugin validation, terminal
fallbacks, source-only output and the original save/generate/run behavior.
