import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
import ai_shell_cli as cli
from aishell_core.hooks import HookManager, signature, verify_notification, validate_event
from aishell_core.proposals import propose_patch
from aishell_core.sandbox import sandbox_command, limit_resources


class HooksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'hooks.json'
        self.log = self.root / 'audit.jsonl'
        self.secret = 'synthetic-webhook-secret-' * 3
        self.hook = {'name': 'notify', 'enabled': True, 'events': ['startup', 'error'],
                     'type': 'webhook', 'url': 'https://example.com/events',
                     'secret_env': 'AISHELL_WEBHOOK_TEST'}
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {'AISHELL_WEBHOOK_TEST': self.secret}).start()

    def manager(self, hook=None):
        self.config.write_text(json.dumps({'version': 1, 'hooks': [hook or self.hook]}))
        return HookManager(self.config, self.log)

    def event(self):
        return {'version': 1, 'id': uuid4().hex, 'timestamp': int(time.time()),
                'event': 'startup', 'operation': 'session', 'outcome': 'started'}

    def test_authentication_tamper_staleness_and_replay(self):
        event = self.event()
        body = json.dumps(event).encode()
        headers = {'X-AIShell-Timestamp': str(event['timestamp']),
                   'X-AIShell-Signature': signature(body, event['timestamp'], self.secret)}
        seen = {}
        self.assertEqual(verify_notification(body, headers, self.secret, seen), event)
        with self.assertRaises(ValueError):
            verify_notification(body, headers, self.secret, seen)
        for changed, secret, now in [(body + b' ', self.secret, event['timestamp']),
                                     (body, 'wrong-' * 10, event['timestamp']),
                                     (body, self.secret, event['timestamp'] + 301)]:
            with self.assertRaises(ValueError):
                verify_notification(changed, headers, secret, {}, now=now)

    def test_reject_signed_code_and_unknown_fields(self):
        event = self.event()
        event['code'] = 'rewrite source'
        body = json.dumps(event).encode()
        headers = {'X-AIShell-Timestamp': str(event['timestamp']),
                   'X-AIShell-Signature': signature(body, event['timestamp'], self.secret)}
        with self.assertRaises(ValueError):
            verify_notification(body, headers, self.secret, {})
        with self.assertRaises(ValueError):
            validate_event({**self.event(), 'operation': 'save'})

    def test_sends_signed_minimal_event_and_ignores_response(self):
        requests = []
        def endpoint(request):
            requests.append(request)
            return httpx.Response(200, json={'code': 'rewrite source', 'autonomy': 6, 'hooks': []})
        original = httpx.Client
        manager = self.manager()
        with patch('aishell_core.hooks.httpx.Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(endpoint), **kw)):
            manager.emit('startup', outcome='started')
        self.assertEqual(len(requests), 1)
        event = verify_notification(requests[0].content, requests[0].headers, self.secret, {})
        self.assertEqual(set(event), {'version', 'id', 'timestamp', 'event', 'operation', 'outcome'})
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(records[-1]['status'], 'delivered')
        self.assertNotIn(self.secret, self.log.read_text())
        self.assertNotIn('https://', self.log.read_text())
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_does_not_follow_redirects_or_log_exception_secrets(self):
        for response in [httpx.Response(302, headers={'location': 'https://evil.invalid'}), None]:
            requests = []
            def endpoint(request):
                requests.append(request)
                if response is None:
                    raise RuntimeError(self.secret)
                return response
            original = httpx.Client
            manager = self.manager()
            with patch('aishell_core.hooks.httpx.Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(endpoint), **kw)):
                manager.emit('startup', outcome='started')
            self.assertEqual(len(requests), 1)
            self.assertEqual(json.loads(self.log.read_text().splitlines()[-1])['status'], 'failed')
            self.assertNotIn(self.secret, self.log.read_text())

    def test_configuration_rejects_executable_hooks_and_bad_endpoints(self):
        variants = [{**self.hook, 'type': 'script', 'code': 'evil'},
                    {**self.hook, 'url': 'http://example.com'},
                    {**self.hook, 'url': 'https://user:secret@example.com'},
                    {**self.hook, 'url': 'https://example.com?secret=foo'},
                    {**self.hook, 'events': ['rewrite_source']},
                    {**self.hook, 'enabled': 'true'},
                    {**self.hook, 'secret_env': 'OPENAI_API_KEY'}]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager(value)

    def test_disabled_hook_needs_no_secret_and_does_not_send(self):
        with patch.dict(os.environ, {}, clear=True):
            manager = self.manager({**self.hook, 'enabled': False})
        with patch('aishell_core.hooks.httpx.Client') as client:
            manager.emit('startup', outcome='started')
        client.assert_not_called()

    def test_missing_secret_and_symlink_log_fail_before_dispatch(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            self.manager()
        target = self.root / 'untouched'
        target.write_text('untouched')
        self.log.symlink_to(target)
        with self.assertRaises(OSError):
            self.manager()
        self.assertEqual(target.read_text(), 'untouched')

    def test_action_error_records_before_error_after(self):
        manager = self.manager({'name': 'log', 'enabled': True, 'events': ['error'], 'type': 'log'})
        with self.assertRaises(RuntimeError):
            with manager.action('generate'):
                raise RuntimeError('private prompt must not be logged')
        events = [record['event'] for line in self.log.read_text().splitlines() if 'event' in (record := json.loads(line))]
        self.assertEqual(events, ['before_generate', 'error', 'after_generate'])
        self.assertNotIn('private prompt', self.log.read_text())

    def test_startup_shutdown_and_plugin_loading_cli(self):
        config = {'version': 1, 'hooks': [{'name': 'audit', 'enabled': True, 'type': 'log', 'events': ['startup', 'shutdown']}]}
        self.config.write_text(json.dumps(config))
        result = subprocess.run([sys.executable, 'ai_shell_cli.py', '--hooks', str(self.config), '--hook-log', str(self.log), '--plugin', 'examples/developer.json', '--demo'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [r['event'] for line in self.log.read_text().splitlines() if 'event' in (r := json.loads(line))]
        self.assertEqual(events, ['startup', 'before_plugin_load', 'after_plugin_load', 'shutdown'])

    def test_audit_failure_prevents_action(self):
        manager = self.manager({'name': 'log', 'enabled': True, 'events': ['error'], 'type': 'log'})
        executed = []
        with patch.object(manager, '_record', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                with manager.action('save'):
                    executed.append(True)
        self.assertFalse(executed)

    def test_patch_command_leaves_target_unchanged_and_emits_events(self):
        self.manager({'name': 'log', 'enabled': True, 'events': ['error'], 'type': 'log'})
        original_state = {name: getattr(cli, name) for name in ('_display', '_policy', '_extensions', '_autonomy', '_env_file')}
        script = cli.GeneratedScript(language='python', suggested_filename='module.py', code='print("new")')
        try:
            with change_directory(self.root):
                Path('module.py').write_text('print("old")\n')
                with patch.object(cli, 'ask', side_effect=['make a replacement', ':patch module.py', ':quit']), patch.object(cli, 'generate_script', return_value=script), contextlib.redirect_stderr(io.StringIO()):
                    result = cli.main(['--hooks', str(self.config), '--hook-log', str(self.log), '--proposal-dir', str(self.root / 'proposals')])
                self.assertEqual(result, 0)
                self.assertEqual(Path('module.py').read_text(), 'print("old")\n')
                self.assertEqual(len(list((self.root / 'proposals').glob('*.patch'))), 1)
                self.assertIn('after_patch', self.log.read_text())
        finally:
            for name, value in original_state.items():
                setattr(cli, name, value)

    def test_no_hooks_no_network(self):
        with patch('aishell_core.hooks.httpx.Client') as client:
            HookManager().emit('startup')
        client.assert_not_called()


class ProposalTests(unittest.TestCase):
    def test_patch_never_applied_and_git_accepts_it(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'file.py'
            source.write_text('old without newline')
            with change_directory(folder):
                target = propose_patch('file.py', 'new without newline', Path(folder) / 'proposals')
                self.assertEqual(source.read_text(), 'old without newline')
                self.assertIn('--- a/file.py', target.read_text())
                check = subprocess.run(['git', 'apply', '--check', str(target)], capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stderr)

    def test_reject_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            with change_directory(folder):
                Path('real').write_text('old')
                Path('link').symlink_to('real')
                for name in ['../outside', '/absolute', 'link']:
                    with self.assertRaises(ValueError):
                        propose_patch(name, 'new', 'proposals')
                self.assertEqual(Path('real').read_text(), 'old')


@contextlib.contextmanager
def change_directory(path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class SandboxTests(unittest.TestCase):
    def test_unavailable_sandbox_fails_closed(self):
        with patch('aishell_core.sandbox.shutil.which', return_value=None), self.assertRaises(RuntimeError):
            sandbox_command(['/bin/sh', '/tmp/a.sh'], Path('/tmp/a.sh'))

    def test_real_plugin_cannot_read_home_write_source_or_use_network(self):
        from test_workbench import EndToEndTests
        EndToEndTests.require_sandbox(self)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'protected.txt'
            source.write_text('unchanged')
            script = Path(folder) / 'test.py'
            script.write_text('''import pathlib, socket
p = pathlib.Path(''' + repr(str(source)) + ''')
assert not p.exists(), "Host workspace exposed"
try:
    p.write_text('modified')
except OSError:
    pass
else:
    raise AssertionError('Host write allowed')
assert not pathlib.Path(''' + repr(str(Path.home() / '.ssh')) + ''').exists()
try:
    socket.create_connection(('1.1.1.1', 443), timeout=0.1)
except OSError:
    pass
else:
    raise AssertionError('Network allowed')
print('sandbox-ok')
''')
            result = subprocess.run(sandbox_command([sys.executable, str(script)], script), capture_output=True, text=True, timeout=15, preexec_fn=limit_resources)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('sandbox-ok', result.stdout)
            self.assertEqual(source.read_text(), 'unchanged')
