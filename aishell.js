#!/usr/bin/env node
const { spawn } = require("child_process");
const path = require("path");
const script = path.join(__dirname, "ai_shell_cli.py");
const child = spawn("python3", [script], { stdio: "inherit" });
child.on("exit", code => process.exit(code));
