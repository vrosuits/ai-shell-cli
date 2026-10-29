"""Accessible terminal output with a clean source-only stdout mode."""
from contextlib import nullcontext
import os
import sys
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

MODES = ("classic", "color", "raw", "summary")


def safe_text(value):
    return "".join(c if c in "\n\t" or (c.isprintable() and c != "\x1b") else "?" for c in str(value))


class Display:
    def __init__(self, mode="classic", color="auto", ascii_only=False, sound=False):
        self.mode, self.sound = mode, sound
        self.ascii = ascii_only or not self._unicode_capable()
        enabled = color != "never" and "NO_COLOR" not in os.environ and os.getenv("TERM") != "dumb"
        self.console = Console(
            stderr=True, color_system="truecolor" if enabled else None,
            force_terminal=True if color == "always" and enabled else None,
            highlight=False, markup=False,
        )

    @staticmethod
    def _unicode_capable():
        try:
            "╭─╮ ◆ ✓".encode(sys.stderr.encoding or "ascii")
            return True
        except UnicodeEncodeError:
            return False

    def banner(self, model, level):
        if self.mode == "raw":
            return
        if self.mode != "color":
            self.message(f"Natural-Language Script Shell | model {model} | autonomy {level}/6")
            return
        title = Text("AI SHELL", style="bold #67e8f9")
        title.append("  /  create · inspect · execute" if not self.ascii else "  /  create - inspect - execute", style="#c4b5fd")
        title.append(f"\n{model}   |   autonomy {level}/6   |   :help", style="#94a3b8")
        self.console.print(Panel(title, border_style="#38bdf8", box=box.ASCII if self.ascii else box.ROUNDED))

    def message(self, message, error=False):
        self.console.print(safe_text(message), style="#fb7185" if error else "#94a3b8", soft_wrap=True)

    def script(self, script, force=False):
        code = script.code.rstrip() + "\n"
        if self.mode == "raw":
            sys.stdout.write(code)
            sys.stdout.flush()
        elif self.mode == "summary" and not force:
            self.message(f"Ready: {script.suggested_filename} | {script.language} | {len(code.splitlines())} lines | {len(code.encode())} bytes. :show to inspect.")
        elif self.mode == "color":
            self.console.print(Panel(
                Syntax(safe_text(code), script.language, theme="monokai", line_numbers=True, word_wrap=True, background_color="default"),
                title=Text(safe_text(script.suggested_filename), style="bold #67e8f9"),
                subtitle=Text(safe_text(script.language), style="#c4b5fd"),
                border_style="#475569", box=box.ASCII if self.ascii else box.ROUNDED,
            ))
        else:
            self.message(f"\nGenerated {script.language} script:")
            self.console.print(Text("\n".join("   " + line for line in safe_text(code).splitlines())))

    def table(self, title, rows):
        table = Table(title=title, box=box.ASCII if self.ascii else box.SIMPLE, show_header=False)
        table.add_column(style="#67e8f9")
        table.add_column(style="#cbd5e1")
        for left, right in rows:
            table.add_row(safe_text(left), safe_text(right))
        self.console.print(table)

    def working(self, message):
        if self.mode == "color" and self.console.is_terminal:
            return self.console.status(message, spinner="line" if self.ascii else "dots", spinner_style="#67e8f9")
        self.message(message)
        return nullcontext()

    def notify(self):
        if self.sound and self.console.is_terminal:
            sys.stderr.write("\a")
            sys.stderr.flush()
