"""Version 1 notification hooks. No callback imports, commands, or response actions."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

EVENTS = frozenset({"startup", "shutdown", "error", *(
    f"{phase}_{action}" for phase in ("before", "after")
    for action in ("generate", "execute", "save", "shell", "patch", "plugin_load", "retrieve", "agent")
)})
OPERATIONS = frozenset({"session", "generate", "execute", "save", "shell", "patch", "plugin_load", "retrieve", "agent"})
OUTCOMES = frozenset({"started", "completed", "failed", "cancelled", "blocked"})


def validate_event(event):
    fields = {"version", "id", "timestamp", "event", "operation", "outcome"}
    if not isinstance(event, dict) or set(event) != fields:
        raise ValueError("Invalid hook event fields")
    if type(event["version"]) is not int or event["version"] != 1:
        raise ValueError("Unsupported hook event version")
    if not isinstance(event["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", event["id"]):
        raise ValueError("Invalid hook event ID")
    if type(event["timestamp"]) is not int:
        raise ValueError("Invalid hook timestamp")
    if any(not isinstance(event[k], str) for k in ("event", "operation", "outcome")):
        raise ValueError("Invalid hook event metadata")
    if event["event"] not in EVENTS or event["operation"] not in OPERATIONS or event["outcome"] not in OUTCOMES:
        raise ValueError("Invalid hook event metadata")
    expected = "session" if event["event"] in {"startup", "shutdown"} else event["event"].split("_", 1)[-1]
    if event["event"] != "error" and event["operation"] != expected:
        raise ValueError("Hook event and operation do not match")
    return event


def signature(body, timestamp, secret):
    return "sha256=" + hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()


def verify_notification(body, headers, secret, seen, now=None):
    """Receiver utility only: validate/authenticate/deduplicate; never dispatch actions.

    `seen` is an application-owned id -> timestamp dictionary. Receivers must
    serialize access and persist replay state if they need restart protection.
    """
    now = int(time.time()) if now is None else now
    if len(secret.encode()) < 32 or not isinstance(body, bytes) or len(body) > 4096:
        raise ValueError("Invalid notification")
    headers = {k.lower(): v for k, v in headers.items()}
    timestamp = headers.get("x-aishell-timestamp", "")
    digest = headers.get("x-aishell-signature", "")
    if not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,12}", timestamp):
        raise ValueError("Invalid notification timestamp")
    if abs(now - int(timestamp)) > 300:
        raise ValueError("Expired notification")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256=[a-f0-9]{64}", digest):
        raise ValueError("Invalid notification signature")
    if not hmac.compare_digest(digest, signature(body, timestamp, secret)):
        raise ValueError("Invalid notification signature")
    event = validate_event(json.loads(body))
    if event["timestamp"] != int(timestamp):
        raise ValueError("Notification timestamps do not match")
    for key in list(seen):
        if seen[key] < now - 300:
            del seen[key]
    if event["id"] in seen:
        raise ValueError("Replayed notification")
    seen[event["id"]] = event["timestamp"]
    return event


class HookManager:
    def __init__(self, config=None, audit_path=None):
        self.handlers = ()
        self.audit_path = None
        self._active = False
        if config is None:
            return
        path = Path(config).expanduser()
        if path.stat().st_size > 65536:
            raise ValueError("Hook configuration exceeds 64 KiB")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"version", "hooks"} or type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("Hook configuration requires version 1 and hooks")
        if not isinstance(data["hooks"], list) or len(data["hooks"]) > 16:
            raise ValueError("Configure at most 16 hooks")
        handlers, names = [], set()
        for hook in data["hooks"]:
            if not isinstance(hook, dict):
                raise ValueError("Invalid hook configuration")
            base = {"name", "enabled", "events", "type"}
            kind = hook.get("type")
            fields = base | ({"url", "secret_env"} if kind == "webhook" else set())
            if kind not in {"log", "webhook"} or set(hook) != fields:
                raise ValueError("Hooks support only log and webhook notification handlers")
            name = hook["name"]
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in names:
                raise ValueError("Invalid or duplicate hook name")
            names.add(name)
            if type(hook["enabled"]) is not bool or not isinstance(hook["events"], list) or not hook["events"] or any(not isinstance(e, str) or e not in EVENTS for e in hook["events"]):
                raise ValueError("Hook requires enabled boolean and known event names")
            item = dict(hook)
            item["events"] = tuple(hook["events"])
            if kind == "webhook":
                if not isinstance(hook["url"], str):
                    raise ValueError("Webhook URL must be HTTPS")
                url = urlsplit(hook["url"])
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError("Webhook URL must be HTTPS without credentials, query or fragment")
                env_name = hook["secret_env"]
                if not isinstance(env_name, str) or not re.fullmatch(r"AISHELL_WEBHOOK_[A-Z0-9_]+", env_name):
                    raise ValueError("Webhook secrets must use a dedicated AISHELL_WEBHOOK_ environment variable")
                item["secret"] = os.getenv(env_name, "")
                if hook["enabled"] and len(item["secret"].encode()) < 32:
                    raise ValueError("Enabled webhook requires a signing secret of at least 32 bytes")
            if hook["enabled"]:
                handlers.append(item)
        self.handlers = tuple(handlers)
        self.audit_path = Path(audit_path or Path.home() / ".local/state/ai-shell-cli/hooks.jsonl").expanduser()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._record({"activity": "configured", "handlers": len(handlers)})

    def _record(self, record):
        if self.audit_path is None:
            return
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(self.audit_path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Audit log must be a regular, singly-linked file")
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            line = json.dumps({"logged_at": int(time.time()), **record}, separators=(",", ":")) + "\n"
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                fd = -1
                stream.write(line)
                stream.flush()
        finally:
            if fd != -1:
                os.close(fd)

    def emit(self, event, operation="session", outcome="completed"):
        if self.audit_path is None or self._active:
            return
        payload = validate_event({"version": 1, "id": uuid4().hex, "timestamp": int(time.time()),
                                  "event": event, "operation": operation, "outcome": outcome})
        self._active = True
        try:
            self._record({"activity": "event", **payload})
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            for handler in self.handlers:
                if event not in handler["events"]:
                    continue
                self._record({"activity": "dispatch", "id": payload["id"], "handler": handler["name"]})
                status = "delivered"
                try:
                    if handler["type"] == "webhook":
                        headers = {"Content-Type": "application/json", "X-AIShell-Timestamp": str(payload["timestamp"]),
                                   "X-AIShell-Signature": signature(body, payload["timestamp"], handler["secret"])}
                        # Never follow redirects, read response bodies, or use proxy environment settings.
                        with httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client:
                            with client.stream("POST", handler["url"], content=body, headers=headers) as response:
                                if not 200 <= response.status_code < 300:
                                    status = "failed"
                except Exception:
                    # Exceptions may contain URLs, response bodies or secrets. Log only a fixed status.
                    status = "failed"
                self._record({"activity": "result", "id": payload["id"], "handler": handler["name"], "status": status})
        finally:
            self._active = False

    @contextmanager
    def action(self, operation):
        self.emit("before_" + operation, operation, "started")
        result = {"outcome": "completed"}
        try:
            yield result
        except BaseException:
            self.emit("error", operation, "failed")
            self.emit("after_" + operation, operation, "failed")
            raise
        else:
            if result["outcome"] == "failed":
                self.emit("error", operation, "failed")
            self.emit("after_" + operation, operation, result["outcome"])
