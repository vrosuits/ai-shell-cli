"""Read-only rclone adapter restricted to operator-configured aliases and roots."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from .credentials import child_environment


class CloudFiles:
    def __init__(self, config=None):
        self.remotes = {}
        self.config_file = None
        if config is None:
            return
        path = Path(config).expanduser()
        if path.stat().st_size > 65536:
            raise ValueError('Cloud configuration exceeds 64 KiB')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) != {'version', 'rclone_config', 'remotes'} or type(data['version']) is not int or data['version'] != 1:
            raise ValueError('Invalid cloud configuration')
        if not isinstance(data['rclone_config'], str) or not isinstance(data['remotes'], dict):
            raise ValueError('Cloud configuration needs rclone_config and remotes')
        self.config_file = Path(data['rclone_config']).expanduser().resolve()
        if not self.config_file.is_file():
            raise ValueError('Configured rclone credentials file is missing')
        for name, root in data['remotes'].items():
            if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', name) or not isinstance(root, str):
                raise ValueError('Invalid cloud alias')
            remote, sep, prefix = root.partition(':')
            if not sep or not re.fullmatch(r'[A-Za-z0-9_-]+', remote):
                raise ValueError('Use a named rclone remote, not an inline backend')
            self.clean_path(prefix)
            self.remotes[name] = remote + ':' + prefix.rstrip('/')

    @staticmethod
    def clean_path(path):
        if not isinstance(path, str) or len(path) > 2048 or path.startswith('/') or any(c in path for c in '\\:*?[]\x00\r\n') or '..' in PurePosixPath(path).parts:
            raise ValueError('Cloud path must be a relative literal path without traversal or wildcards')
        return path

    def target(self, alias, path):
        if alias not in self.remotes:
            raise ValueError('Unknown cloud alias; configure it explicitly first')
        path = self.clean_path(path)
        root = self.remotes[alias]
        return root + ('/' if path and not root.endswith(':') else '') + path

    def _run(self, arguments, limit=1048576):
        executable = shutil.which('rclone')
        if not executable:
            raise RuntimeError('Install rclone and configure an account before using cloud files')
        command = [executable, '--config', str(self.config_file), '--retries', '1', '--low-level-retries', '1', '--timeout', '10s', *arguments]
        # Bounded pipe reads avoid exposing errors/credentials or accumulating an unlimited listing.
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL, env=child_environment())
            import threading
            timer = threading.Timer(30, process.kill)
            timer.start()
            try:
                data = process.stdout.read(limit + 1)
                if len(data) > limit:
                    raise ValueError('Cloud response exceeds size limit')
                if process.wait() != 0:
                    raise RuntimeError('Cloud read failed; check account access, path and rclone configuration')
                return data
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()

    def list(self, alias, path=''):
        target = self.target(alias, path)
        rows = json.loads(self._run(['lsjson', '--max-depth', '1', '--', target]))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Invalid cloud listing response')
        return {'alias': alias, 'path': path, 'items': [{k: r.get(k) for k in ('Name', 'Path', 'Size', 'IsDir', 'MimeType')} for r in rows[:100]],
                'truncated': len(rows) > 100, 'untrusted_content': True}

    def read(self, alias, path):
        target = self.target(alias, path)
        metadata = json.loads(self._run(['lsjson', '--stat', '--', target]))
        if not isinstance(metadata, dict) or metadata.get('IsDir') is not False or type(metadata.get('Size')) is not int or not 0 <= metadata['Size'] <= 1048576:
            raise ValueError('Cloud read requires a single file of known size at most 1 MiB')
        data = self._run(['cat', '--head', '1048577', '--', target])
        return data
