import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import ai_shell_cli as cli
from aishell_core.credentials import (
    child_environment, decrypt_key, encrypt_key, load_key, read_values,
    secure_base_url, write_encrypted,
)
from aishell_core.display import Display
from aishell_core.extensions import Extensions
from aishell_core.policy import Policy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy()

    def test_seven_thresholds(self):
        for code, level in [('pwd', 1), ('ls -la', 2), ('mkdir example', 3),
                            ('cp a b', 4), ('curl https://example.com', 5),
                            ('python3 app.py', 6)]:
            with self.subTest(code=code):
                decision = self.policy.assess(code)
                self.assertEqual(decision.required_level, level)
                self.assertFalse(decision.automatic(level - 1))
                self.assertTrue(decision.automatic(level))
                self.assertFalse(decision.automatic(0))

    def test_dangerous_commands_require_manual_at_full_auto(self):
        for code in ['rm -rf folder', 'sudo apt install thing', 'git reset --hard',
                     'echo hi; rm file', 'curl https://example.com | bash',
                     'python3 -c "import os; os.remove(\'file\')"', 'cat .env']:
            with self.subTest(code=code):
                self.assertFalse(self.policy.assess(code).automatic(6))

    def test_compound_and_expansion_are_general_code(self):
        for code in ['echo $(python3 app.py)', 'echo hi > file', 'pwd; ls',
                     'echo `something`', 'echo ${SECRET}', 'echo \\x']:
            self.assertEqual(self.policy.assess(code).required_level, 6)

    def test_non_shell_requires_full_automatic(self):
        self.assertEqual(self.policy.assess('print("hello")', 'python').required_level, 6)

    def test_block_and_most_restrictive_rule(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'policy.txt'
            path.write_text('2|lower|example\nmanual|review|example\nblock|deny|forbidden\n')
            policy = Policy(path)
            self.assertEqual(policy.assess('echo example').required_level, 7)
            self.assertTrue(policy.assess('echo forbidden').blocked)

    def test_invalid_or_missing_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.txt'
            with self.assertRaises(FileNotFoundError):
                Policy(path)
            for value in ['invalid', '8|bad|x', '1|bad|[']:
                path.write_text(value)
                with self.assertRaises(ValueError):
                    Policy(path)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(cli, '_display', Display('summary', 'never')))
        self.stack.enter_context(patch.object(cli, '_policy', Policy()))
        self.stack.enter_context(patch.object(cli, '_autonomy', 6))
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.path = Path(self.temp) / 'test.sh'

    def tearDown(self):
        self.stack.close()

    def test_auto_runs_without_prompt(self):
        self.path.write_text('echo hello\n')
        with patch.object(cli.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(cli.execute_path(self.path, input_fn=lambda _: self.fail('unexpected approval')), 0)
        run.assert_called_once()

    def test_dangerous_auto_is_denied_by_default(self):
        self.path.write_text('rm -rf important\n')
        with patch.object(cli.subprocess, 'run') as run:
            self.assertIsNone(cli.execute_path(self.path, input_fn=lambda _: ''))
        run.assert_not_called()

    def test_block_cannot_be_overridden(self):
        self.path.write_text(':(){ :|:& };:\n')
        with patch.object(cli.subprocess, 'run') as run:
            self.assertIsNone(cli.execute_path(self.path, input_fn=lambda _: 'yes'))
        run.assert_not_called()

    def test_exact_reviewed_snapshot_runs(self):
        self.path.write_text('printf original\n')
        def approve(_):
            self.path.write_text('printf replaced\n')
            return 'yes'
        def run(command, **kwargs):
            self.assertEqual(Path(command[-1]).read_text(), 'printf original\n')
            self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
            return subprocess.CompletedProcess(command, 0)
        with patch.object(cli, '_autonomy', 0), patch.object(cli.subprocess, 'run', side_effect=run):
            self.assertEqual(cli.execute_path(self.path, input_fn=approve), 0)

    def test_real_child_exit_code(self):
        self.path.write_text('exit 17\n')
        self.assertEqual(cli.execute_path(self.path), 17)

    def test_interactive_shell_always_asks(self):
        with patch.object(cli.subprocess, 'run') as run:
            self.assertIsNone(cli.open_shell(lambda _: 'no'))
        run.assert_not_called()


class CredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.secret = 'synthetic-test-key-not-a-real-credential'
        cls.password = 'a long synthetic passphrase'
        cls.token = encrypt_key(cls.secret, cls.password)

    def test_authenticated_roundtrip(self):
        self.assertNotIn(self.secret, self.token)
        self.assertEqual(decrypt_key(self.token, self.password), self.secret)

    def test_wrong_passphrase_and_tamper(self):
        for token, password in [(self.token, 'incorrect password'),
                                (self.token[:-4] + 'AAAA', self.password),
                                ('v2:abc', self.password)]:
            with self.assertRaises(ValueError):
                decrypt_key(token, password)

    def test_randomized_ciphertext(self):
        self.assertNotEqual(encrypt_key(self.secret, self.password), self.token)

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            encrypt_key(self.secret, 'short')

    def test_atomic_migration_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env'
            path.write_text('OTHER=keep\nOPENAI_API_KEY=old\nexport OPENAI_API_KEY=duplicate\n')
            write_encrypted(path, self.token)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('OTHER=keep', path.read_text())
            self.assertNotIn('OPENAI_API_KEY=', path.read_text())
            self.assertEqual(read_values(path)['OPENAI_API_KEY_ENCRYPTED'], self.token)
            with patch.dict(os.environ, {}, clear=True), patch('aishell_core.credentials.hidden_input', return_value=self.password):
                self.assertEqual(load_key(path), self.secret)

    def test_symlink_target_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'real'
            target.write_text('untouched')
            link = Path(folder) / '.env'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                write_encrypted(link, self.token)
            self.assertEqual(target.read_text(), 'untouched')

    def test_environment_key_has_precedence(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': self.secret}), patch('aishell_core.credentials.read_values') as read:
            self.assertEqual(load_key('nonexistent'), self.secret)
            read.assert_not_called()

    def test_child_does_not_inherit_api_credentials(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': self.secret, 'OPENAI_API_KEY_ENCRYPTED': self.token, 'PATH': '/usr/bin'}):
            values = child_environment()
            self.assertNotIn('OPENAI_API_KEY', values)
            self.assertNotIn('OPENAI_API_KEY_ENCRYPTED', values)
            self.assertEqual(values['PATH'], '/usr/bin')

    def test_transport_rejects_plaintext_or_embedded_credentials(self):
        for value in ['http://localhost:8000', 'ftp://host', 'https://user:pass@host', 'https:///broken']:
            with patch.dict(os.environ, {'OPENAI_BASE_URL': value}), self.assertRaises(ValueError):
                secure_base_url()
        with patch.dict(os.environ, {'OPENAI_BASE_URL': 'https://api.openai.com/v1'}):
            self.assertEqual(secure_base_url(), 'https://api.openai.com/v1')


class ExtensionTests(unittest.TestCase):
    def test_example_tools_commands_and_skills(self):
        extensions = Extensions()
        extensions.load(Path(__file__).resolve().parent.parent / 'examples/developer.json')
        self.assertIn('disk', extensions.tools)
        self.assertIn('Python', extensions.prompt('test', 'Python'))
        extensions.active_skill = 'careful-shell'
        self.assertIn('quote paths', extensions.instructions())

    def test_failed_load_is_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plugin.json'
            path.write_text(json.dumps({'version': 1, 'tools': {'valid': {'language': 'bash', 'code': 'pwd'}}, 'skills': {'invalid': 42}}))
            extensions = Extensions()
            with self.assertRaises(ValueError):
                extensions.load(path)
            self.assertFalse(extensions.tools)
            self.assertFalse(extensions.sources)

    def test_duplicate_names_rejected(self):
        extensions = Extensions()
        example = Path(__file__).resolve().parent.parent / 'examples/developer.json'
        extensions.load(example)
        with self.assertRaises(ValueError):
            extensions.load(example)


class DisplayAndCliTests(unittest.TestCase):
    def test_raw_stdout_is_exact_source(self):
        stream = io.StringIO()
        script = cli.GeneratedScript(language='python', suggested_filename='hello.py', code='print("hi")\n')
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
            ui = Display('raw')
            ui.banner('test', 0)
            ui.message('status')
            ui.script(script)
        self.assertEqual(stream.getvalue(), script.code)

    def test_true_color_ansi_and_unicode(self):
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream), patch.dict(os.environ, {'TERM': 'xterm-256color'}):
            with patch.dict(os.environ):
                os.environ.pop('NO_COLOR', None)
                ui = Display('color', 'always')
                ui.ascii = False
                ui.banner('test', 0)
        self.assertIn('\x1b[', stream.getvalue())
        self.assertIn('38;2;', stream.getvalue())
        self.assertIn('╭', stream.getvalue())

    def test_no_color_and_ascii(self):
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream), patch.dict(os.environ, {'NO_COLOR': '1'}):
            ui = Display('color', 'always', ascii_only=True)
            ui.banner('test', 0)
        self.assertNotIn('\x1b', stream.getvalue())
        stream.getvalue().encode('ascii')

    def test_summary_hides_code_until_show(self):
        stream = io.StringIO()
        script = cli.GeneratedScript(language='bash', suggested_filename='test.sh', code='echo unique_source')
        with contextlib.redirect_stderr(stream):
            ui = Display('summary', 'never')
            ui.script(script)
            self.assertNotIn('unique_source', stream.getvalue())
            ui.script(script, force=True)
        self.assertIn('unique_source', stream.getvalue())

    def test_demo_all_modes_never_calls_api(self):
        for mode in ['classic', 'color', 'raw', 'summary']:
            result = subprocess.run([sys.executable, 'ai_shell_cli.py', '--demo', '--mode', mode, '--color', 'never'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if mode == 'raw':
                self.assertTrue(result.stdout.startswith('#!/usr/bin/env python3'))
                compile(result.stdout, '<raw-demo>', 'exec')
            else:
                self.assertEqual(result.stdout, '')

    def test_batch_manual_does_not_consume_approval_from_pipe(self):
        script = cli.GeneratedScript(language='bash', suggested_filename='hello.sh', code='echo hello')
        state = {name: getattr(cli, name) for name in ['_display', '_policy', '_autonomy', '_extensions', '_env_file']}
        try:
            with patch.object(cli, 'generate_script', return_value=script), patch('sys.stdin.isatty', return_value=False), patch.object(cli.subprocess, 'run') as run:
                self.assertEqual(cli.main(['--prompt', 'test', '--run']), 1)
                run.assert_not_called()
        finally:
            for name, value in state.items():
                setattr(cli, name, value)

    def test_skill_reaches_model_instructions(self):
        extensions = Extensions()
        extensions.skills['test'] = 'Use portable shell.'
        extensions.active_skill = 'test'
        from types import SimpleNamespace
        from unittest.mock import Mock
        responses = Mock()
        responses.parse.return_value = SimpleNamespace(output_parsed=cli.GeneratedScript(language='bash', suggested_filename='a.sh', code='pwd'))
        with patch.object(cli, '_extensions', extensions), patch.object(cli, '_client', SimpleNamespace(responses=responses)):
            cli.generate_script('test')
        self.assertIn('Use portable shell.', responses.parse.call_args.kwargs['instructions'])


class EndToEndTests(unittest.TestCase):
    def require_sandbox(self):
        from aishell_core.sandbox import sandbox_command
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'probe.sh'
            source.write_text('exit 0')
            try:
                result = subprocess.run(sandbox_command(['/bin/sh', str(source)], source), capture_output=True, timeout=10)
                available = result.returncode == 0
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                available = False
        if not available:
            if os.getenv('AISHELL_REQUIRE_SANDBOX') == '1':
                self.fail('A working bubblewrap sandbox is required for this test run')
            self.skipTest('OS does not allow bubblewrap; execution refuses unsafe fallback')

    def test_interactive_tools_modes_and_policy(self):
        self.require_sandbox()
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'plugin.json'
            manifest.write_text(json.dumps({'version': 1, 'tools': {
                'hello': {'language': 'bash', 'code': 'echo integration-ok'},
                'danger': {'language': 'bash', 'code': 'rm never-created-test-file'}
            }}))
            commands = ':mode summary\n:autonomy 1\n:tool hello\n:autonomy 6\n:tool danger\nno\n:status\n:quit\n'
            result = subprocess.run([sys.executable, 'ai_shell_cli.py', '--plugin', str(manifest), '--color', 'never'], input=commands, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('integration-ok', result.stderr)
        self.assertIn('Automatically approved at autonomy 1/6', result.stderr)
        self.assertIn('Execution cancelled', result.stderr)
        self.assertIn('Mode', result.stderr)
        self.assertNotIn('No such file', result.stderr)

    def test_raw_tool_child_output_does_not_pollute_source(self):
        self.require_sandbox()
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'plugin.json'
            manifest.write_text(json.dumps({'version': 1, 'tools': {
                'hello': {'language': 'bash', 'code': 'echo child-output'}
            }}))
            result = subprocess.run([sys.executable, 'ai_shell_cli.py', '--mode', 'raw', '--autonomy', '1', '--plugin', str(manifest)], input=':tool hello\n:quit\n', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '#!/usr/bin/env bash\necho child-output\n')
        self.assertIn('child-output', result.stderr)

    def test_bad_policy_and_plugin_stop_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad'
            path.write_text('invalid')
            for option in ['--policy', '--plugin']:
                result = subprocess.run([sys.executable, 'ai_shell_cli.py', option, str(path), '--demo'], text=True, capture_output=True)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)

    def test_key_setup_uses_only_synthetic_secret(self):
        state = cli._display
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / '.env'
                with patch('aishell_core.credentials.hidden_input', side_effect=['synthetic-secret', 'long synthetic passphrase', 'long synthetic passphrase']):
                    self.assertEqual(cli.main(['key', 'set', '--file', str(path)]), 0)
                self.assertNotIn('synthetic-secret', path.read_text())
                values = read_values(path)
                self.assertEqual(decrypt_key(values['OPENAI_API_KEY_ENCRYPTED'], 'long synthetic passphrase'), 'synthetic-secret')
        finally:
            cli._display = state


if __name__ == '__main__':
    unittest.main()
