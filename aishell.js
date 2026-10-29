#!/usr/bin/env node
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const localPython = path.join(__dirname, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.AISHELL_PYTHON || (fs.existsSync(localPython) ? localPython : "python3");
const child = spawn(python, [path.join(__dirname, "ai_shell_cli.py"), ...process.argv.slice(2)], { stdio: "inherit" });
child.on("error", () => { console.error("Cannot launch Python. Install requirements.txt or set AISHELL_PYTHON."); process.exitCode = 1; });
child.on("exit", (code, signal) => { process.exitCode = code === null ? (signal === "SIGINT" ? 130 : 1) : code; });
