"""Versioned authenticated credential storage. Unlock secrets never go in .env."""
import base64
import getpass
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ENV_NAME = "OPENAI_API_KEY_ENCRYPTED"
AAD = b"ai-shell-cli:OPENAI_API_KEY:v1"


def _derive(passphrase, salt):
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(passphrase.encode())


def encrypt_key(key, passphrase):
    if len(passphrase) < 12:
        raise ValueError("Use a passphrase of at least 12 characters.")
    if not key.strip() or any(c.isspace() for c in key):
        raise ValueError("The API key must be a nonempty value without whitespace.")
    salt, nonce = os.urandom(16), os.urandom(12)
    ciphertext = AESGCM(_derive(passphrase, salt)).encrypt(nonce, key.encode(), AAD)
    return "v1:" + base64.urlsafe_b64encode(salt + nonce + ciphertext).decode()


def decrypt_key(value, passphrase):
    try:
        version, token = value.split(":", 1)
        if version != "v1" or len(token) > 16384:
            raise ValueError()
        data = base64.b64decode(token, altchars=b"-_", validate=True)
        if len(data) < 45:
            raise ValueError()
        return AESGCM(_derive(passphrase, data[:16])).decrypt(data[16:28], data[28:], AAD).decode()
    except (ValueError, InvalidTag, UnicodeError) as exc:
        raise ValueError("Cannot unlock API key: wrong passphrase or damaged encrypted value.") from exc


def read_values(path):
    path = Path(path).expanduser()
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(?:export\s+)?(OPENAI_API_KEY(?:_ENCRYPTED)?)\s*=\s*(.*?)\s*$", line)
        if match:
            values[match[1]] = match[2].strip("\"'")
    return values


def write_encrypted(path, value):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Refusing to replace a symlink credential file.")
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [line for line in old.splitlines() if not re.match(r"^\s*(?:export\s+)?OPENAI_API_KEY(?:_ENCRYPTED)?\s*=", line)]
    lines.append(f"{ENV_NAME}={value}")
    fd, temporary = tempfile.mkstemp(prefix=".aishell-key-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def hidden_input(prompt):
    # getpass otherwise falls back to echoing stdin on some terminals.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning as exc:
            raise ValueError("A terminal with hidden input is required for credential setup/unlock.") from exc


def load_key(path=".env"):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key
    values = read_values(path)
    encrypted = values.get(ENV_NAME)
    if encrypted:
        return decrypt_key(encrypted, hidden_input("Unlock API key — passphrase: "))
    if values.get("OPENAI_API_KEY"):
        return values["OPENAI_API_KEY"]
    raise RuntimeError("No API key configured. Run: python ai_shell_cli.py key set")


def secure_base_url():
    value = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("OPENAI_BASE_URL must use HTTPS and must not contain credentials.")
    return value


def child_environment():
    # Keep the API credential out of generated programs' inherited environment.
    return {k: v for k, v in os.environ.items() if not k.startswith("OPENAI_") and k != "AISHELL_PASSPHRASE"}


def setup_key(path, from_env=False):
    key = os.getenv("OPENAI_API_KEY", "") if from_env else hidden_input("OpenAI API key (hidden): ")
    if not key:
        raise ValueError("No API key supplied.")
    passphrase = hidden_input("New passphrase (12+ characters): ")
    if passphrase != hidden_input("Confirm passphrase: "):
        raise ValueError("Passphrases do not match.")
    write_encrypted(path, encrypt_key(key, passphrase))
