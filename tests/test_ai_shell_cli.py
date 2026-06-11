import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ai_shell_cli as cli


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.request = None

    def parse(self, **kwargs):
        self.request = kwargs
        return self.response


class AiShellCliTests(unittest.TestCase):
    def setUp(self):
        self.original_client = cli._client

    def tearDown(self):
        cli._client = self.original_client

    def test_generate_script_uses_structured_output(self):
        response = SimpleNamespace(
            output_parsed=cli.GeneratedScript(
                language="py",
                suggested_filename="../../hello",
                code="print('hello')",
            )
        )
        responses = FakeResponses(response)
        cli._client = SimpleNamespace(responses=responses)

        script = cli.generate_script("write hello in Python")

        self.assertEqual(script.language, "python")
        self.assertEqual(script.suggested_filename, "hello")
        self.assertTrue(script.code.startswith("#!/usr/bin/env python3\n"))
        self.assertIs(responses.request["text_format"], cli.GeneratedScript)
        self.assertEqual(responses.request["reasoning"], {"effort": "low"})
        self.assertEqual(
            responses.request["text"],
            {"verbosity": "low"},
        )
        self.assertNotIn("verbosity", responses.request)

    def test_save_adds_correct_extension_and_shebang(self):
        script = cli.GeneratedScript(
            language="bash",
            suggested_filename="backup",
            code="printf 'done\\n'",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = cli.save_script(script, str(Path(temp_dir) / "job.py"))

            self.assertEqual(path.suffix, ".sh")
            self.assertTrue(path.read_text().startswith("#!/usr/bin/env bash\n"))
            self.assertTrue(os.access(path, os.X_OK))

    def test_save_does_not_overwrite_without_permission(self):
        script = cli.GeneratedScript(
            language="python",
            suggested_filename="example",
            code="print('new')",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "example.py"
            destination.write_text("old\n")

            with self.assertRaises(FileExistsError):
                cli.save_script(script, str(destination))
            self.assertEqual(destination.read_text(), "old\n")

    def test_default_save_uses_unique_filename(self):
        script = cli.GeneratedScript(
            language="javascript",
            suggested_filename="example",
            code="console.log('ok');",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                first = cli.save_script(script)
                second = cli.save_script(script)
            finally:
                os.chdir(original_cwd)

            self.assertEqual(first.name, "example.js")
            self.assertEqual(second.name, "example_1.js")

    def test_shebang_selects_bash_for_sh_extension(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "example.sh"
            path.write_text("#!/usr/bin/env bash\nprintf 'ok\\n'\n")

            self.assertEqual(cli.language_from_path(path), "bash")
            command = cli.command_for_script(path, "bash")
            self.assertEqual(Path(command[0]).name, "bash")

    def test_execute_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "example.py"
            path.write_text("print('should not run')\n")

            with patch("ai_shell_cli.subprocess.run") as run:
                result = cli.execute_path(path, input_fn=lambda _: "no")

            self.assertIsNone(result)
            run.assert_not_called()

    def test_execute_confirmed_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "example.py"
            path.write_text("print('ok')\n")
            completed = SimpleNamespace(returncode=0)

            with patch(
                "ai_shell_cli.subprocess.run", return_value=completed
            ) as run:
                result = cli.execute_path(path, input_fn=lambda _: "yes")

            self.assertEqual(result, 0)
            run.assert_called_once()
            self.assertEqual(Path(run.call_args.args[0][0]), Path(sys.executable))

    def test_quoted_path_argument(self):
        self.assertEqual(
            cli.parse_path_argument('"folder/my script"'),
            "folder/my script",
        )

    def test_shell_requires_confirmation(self):
        with patch("ai_shell_cli.subprocess.run") as run:
            result = cli.open_shell(input_fn=lambda _: "no")

        self.assertIsNone(result)
        run.assert_not_called()

    def test_safe_filename_removes_model_path(self):
        self.assertEqual(
            cli.safe_filename("../../odd script?.py"),
            "odd_script_.py",
        )


if __name__ == "__main__":
    unittest.main()
