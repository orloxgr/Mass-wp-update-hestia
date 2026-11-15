"""Real console/CLI contract, with no package installation or service mutation."""
import argparse
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import progress


class InstallerOutput(unittest.TestCase):
    def invoke(self, callback, **options):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = progress.execute(callback, title='Test addon', version='1.2.3', **options)
        return code, out.getvalue(), err.getvalue()

    def test_default_summary_retains_nested_details_and_actual_counts(self):
        def install():
            progress.stage('Domain 2/2: two.example.test')
            return dict(ok=True, accounts=2, route_updates=0, credentials_preserved=True,
                        unsupported=[dict(domain='other.example.test', reason='No native include')])
        code, out, err = self.invoke(install)
        self.assertEqual(code, 0)
        self.assertIn('Test addon - Installation completed', out)
        for text in ('Version: 1.2.3', 'Accounts: 2', 'Route updates: 0',
                     'Credentials preserved: Yes', 'other.example.test', 'No native include', 'Elapsed:'):
            self.assertIn(text, out)
        self.assertNotIn('{', out)
        self.assertNotIn('\033', out)
        self.assertIn('Domain 2/2:', err)

    def test_json_stdout_contains_one_complete_document_and_no_progress(self):
        result = dict(ok=True, mode='upgrade-or-reinstall', generation='abc', data_preserved=True)
        code, out, err = self.invoke(lambda: result, json_output=True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), dict(version='1.2.3', **result))
        self.assertIn('Test addon 1.2.3', err)
        self.assertNotIn('Elapsed:', out)

    def test_failure_reports_native_details_stage_and_nonzero_exit(self):
        def install():
            progress.stage('Validating staged PHP files')
            raise subprocess.CalledProcessError(255, ['php', '-l'],
                                                output=b'Errors parsing index.php', stderr=b'PHP parse error')
        for machine in (False, True):
            with self.subTest(machine=machine):
                code, out, err = self.invoke(install, json_output=machine)
                self.assertEqual(code, 1)
                self.assertIn('Errors parsing index.php', err)
                self.assertIn('PHP parse error', err)
                self.assertIn('Traceback', err)
                if machine:
                    result = json.loads(out)
                    self.assertIs(result['ok'], False)
                    self.assertEqual(result['stage'], 'Validating staged PHP files')
                else:
                    self.assertIn('Installation failed', out)
                    self.assertIn('Last stage: Validating staged PHP files', out)
                    self.assertNotIn('Installation completed', out)

    def test_missing_completion_cannot_be_reported_as_success(self):
        for result in (None, {}, {'ok': False}):
            code, out, _ = self.invoke(lambda: result, json_output=True)
            self.assertEqual(code, 1)
            self.assertIs(json.loads(out)['ok'], False)

    def test_closed_stdout_and_stderr_do_not_undo_completed_work(self):
        out, err = io.StringIO(), io.StringIO()
        out.close(); err.close()
        finished = []
        def install():
            progress.stage('Applying service settings')
            finished.append(True)
            return {'ok': True}
        for machine in (False, True):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = progress.execute(install, title='Test', version='1', json_output=machine)
            self.assertEqual(code, 0)
        self.assertEqual(finished, [True, True])

    def test_slow_work_keeps_reporting_without_changing_result_or_deadline(self):
        err = io.StringIO()
        with progress.reporting(err, interval=.01):
            progress.stage('Waiting for native readiness')
            time.sleep(.05)
        self.assertIn('Still working', err.getvalue())
        self.assertIn('Waiting for native readiness', err.getvalue())
        before = err.getvalue()
        progress.stage('Panel operation must stay silent')
        time.sleep(.02)
        self.assertEqual(before, err.getvalue())

    def test_terminal_color_is_optional_and_never_written_to_logs(self):
        class Terminal(io.StringIO):
            def isatty(self): return True
        for environment, color in (({}, True), ({'NO_COLOR': ''}, False), ({'TERM': 'dumb'}, False)):
            out = Terminal()
            with patch.dict(os.environ, environment, clear=True):
                progress.summary('Test', {'ok': True, 'version': '1'}, .2, stream=out)
            self.assertEqual('\033[32m' in out.getvalue(), color)

    def test_real_cli_argument_dispatch_and_output_modes(self):
        # Execute the actual entry-point AST with only the system-changing work
        # mocked. This tests argparse/--json/removal and exit codes on any OS.
        source = ROOT / 'tools/install.py'
        tree = ast.parse(source.read_text())
        entry = next(node for node in tree.body if isinstance(node, ast.If)
                     and ast.unparse(node.test) == "__name__ == '__main__'")
        flags = [[], ['--json']]
        if any('--uninstall' in ast.unparse(node) for node in entry.body):
            flags += [['--uninstall'], ['--uninstall', '--json']]
        for arguments in flags:
            for failing in (False, True):
                with self.subTest(arguments=arguments, failing=failing):
                    callback = Mock(return_value={'ok': True, 'data_preserved': True})
                    if failing: callback.side_effect = RuntimeError('Native validation rejected')
                    namespace = dict(__name__='__main__', __doc__='Test installer', argparse=argparse,
                                     progress=progress, META=dict(title='Test', version='1.2.3'),
                                     VERSION='1.2.3', perform=callback, install=callback, uninstall=callback)
                    out, err = io.StringIO(), io.StringIO()
                    with patch.object(sys, 'argv', [str(source), *arguments]), \
                            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                            self.assertRaises(SystemExit) as stopped:
                        exec(compile(ast.Module(body=[entry], type_ignores=[]), str(source), 'exec'), namespace)
                    self.assertEqual(stopped.exception.code, int(failing))
                    callback.assert_called_once()
                    if '--json' in arguments:
                        self.assertEqual(json.loads(out.getvalue())['ok'], not failing)
                    else:
                        self.assertIn('Removal' if '--uninstall' in arguments else 'Installation', out.getvalue())
                        self.assertNotIn('{', out.getvalue())


if __name__ == '__main__':
    unittest.main()
