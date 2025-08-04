# 1. Clone / copy files
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."         # your key
python ai_shell_cli.py
