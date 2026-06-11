# 1. Clone / copy files
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."         # your key
export OPENAI_MODEL="gpt-5.5"          # optional; this is the default
export OPENAI_REASONING_EFFORT="low"   # optional: none, low, medium, high, xhigh
export OPENAI_TEXT_VERBOSITY="low"     # optional: low, medium, high
export OPENAI_MAX_OUTPUT_TOKENS="1024" # optional; increase if responses are incomplete
python ai_shell_cli.py
