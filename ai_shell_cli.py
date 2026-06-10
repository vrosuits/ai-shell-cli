#!/usr/bin/env python3
"""
Program name$  ai‑shell‑cli, version# 1.0.0
(c) Copyright 2024 Antony J Ingram, All rights reserved
-------------------------------------------------------
A simple interactive CLI that accepts natural‑language
questions and returns suggested *bash* commands using
the OpenAI API.
"""

import os
import sys
import json
from textwrap import indent

import openai

# ── Configuration ────────────────────────────────────
MODEL       = "gpt-4o"            # or another model ID you own
TEMP        = 0.1                 # keep answers deterministic
MAX_TOKENS  = 256

API_KEY     = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    sys.exit("💥  OPENAI_API_KEY environment variable is missing.")

openai.api_key = API_KEY

SYSTEM_PROMPT = """\
You are an expert Unix system administrator.
Given a plain‑English request, reply ONLY with a concise list
of POSIX‑compatible shell commands (no extra prose). 
Include a one‑line comment after each command preceded by “# ”.
"""

# ── Core helper ───────────────────────────────────────
def get_suggestions(query: str) -> str:
    completion = openai.ChatCompletion.create(
        model   = MODEL,
        messages = [
            {"role": "system",    "content": SYSTEM_PROMPT},
            {"role": "user",      "content": query}
        ],
        temperature = TEMP,
        max_tokens  = MAX_TOKENS,
    )
    return completion.choices[0].message.content.strip()

# ── CLI loop ──────────────────────────────────────────
def main() -> None:
    print("🔮  Natural‑Language → Shell • type 'exit' to quit")
    while True:
        try:
            query = input("\n📝  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋  Bye!")
            break
        if query.lower() in {"exit", "quit"}:
            print("👋  Bye!")
            break
        if not query:
            continue

        suggestions = get_suggestions(query)
        print("\n💡  Suggested command(s):")
        print(indent(suggestions, "   "))
        print("\n⚠️  Review carefully before running!")

if __name__ == "__main__":
    main()
