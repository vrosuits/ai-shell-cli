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
from textwrap import indent

from openai import OpenAI, OpenAIError

# ── Configuration ────────────────────────────────────
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low")
TEXT_VERBOSITY = os.getenv("OPENAI_TEXT_VERBOSITY", "low")
MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "1024"))

API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    sys.exit("💥  OPENAI_API_KEY environment variable is missing.")

client = OpenAI(api_key=API_KEY)

SYSTEM_PROMPT = """\
You are an expert Unix system administrator.
Given a plain‑English request, reply ONLY with a concise list
of POSIX‑compatible shell commands (no extra prose). 
Include a one‑line comment after each command preceded by “# ”.
"""

# ── Core helper ───────────────────────────────────────
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
            "The response used the entire output-token budget before producing "
            "final text. Increase OPENAI_MAX_OUTPUT_TOKENS."
        )
    if reason == "content_filter":
        return "The response was stopped by the content filter."

    return (
        f"The API returned no text (status={response.status}, "
        f"model={response.model}, response_id={response.id})."
    )


def get_suggestions(query: str) -> str:
    request = {
        "model": MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": query,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    if MODEL.startswith(("gpt-5", "o1", "o3", "o4")):
        request["reasoning"] = {"effort": REASONING_EFFORT}
    if MODEL.startswith("gpt-5"):
        request["text"] = {"verbosity": TEXT_VERBOSITY}

    response = client.responses.create(**request)
    suggestions = response.output_text.strip()
    if not suggestions:
        raise RuntimeError(response_error(response))
    return suggestions

# ── CLI loop ──────────────────────────────────────────
def main() -> None:
    print(f"🔮  Natural‑Language → Shell • model {MODEL} • type 'exit' to quit")
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

        try:
            suggestions = get_suggestions(query)
        except (OpenAIError, RuntimeError) as error:
            print(f"\nOpenAI API error: {error}", file=sys.stderr)
            continue

        print("\n💡  Suggested command(s):")
        print(indent(suggestions, "   "))
        print("\n⚠️  Review carefully before running!")

if __name__ == "__main__":
    main()
