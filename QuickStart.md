# Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# Explore without API access:
python ai_shell_cli.py --demo --mode color

# Configure encrypted storage if a key is not already in your environment:
python ai_shell_cli.py key set

# Launch with color, tools and optional terminal sound:
python ai_shell_cli.py --mode color --sound --plugin examples/developer.json
```

Describe a script, then use `:show`, `:save name`, or `:run`. Try `:tools`,
`:tool disk`, `:skills`, `:skill careful-shell`, and `:command test Python`.

Switch views with `:mode classic|color|raw|summary` (choose one value).
Use `:levels` to inspect the seven approval levels and `:autonomy 2` to allow
simple read commands automatically. Level 0 requires execution approval;
level 6 automatically approves general code except policy matches. Textual
policy rules are not a security sandbox. See [README.md](README.md).

```bash
# Emit source without terminal decorations:
python ai_shell_cli.py --mode raw --prompt 'Python hello world' > hello.py

# Generate and run with a conservative read-command threshold:
python ai_shell_cli.py --mode summary --autonomy 2 --prompt 'List files' --run

# Encrypt an existing environment key without displaying it:
python ai_shell_cli.py key set --from-env
unset OPENAI_API_KEY
python ai_shell_cli.py --mode color  # unlocks the encrypted key when needed
```
