"""Installer publication and output against a disposable Hestia directory tree."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import hestia
import progress


@unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid() == 0, 'Disposable Linux lab as root')
class InstallerPublication(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        folder = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='mwu-install-', dir='/var/lib'))
        base = Path(folder)
        spec = importlib.util.spec_from_file_location('masswp_installer', ROOT / 'tools/install.py')
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        native = base / 'hestia'
        for name in ('web/inc', 'web/js/custom_scripts', 'bin'):
            (native / name).mkdir(parents=True, exist_ok=True)
        (native / 'web/inc/main.php').write_text('<?php')
        locations = dict(TARGET=base/'installed', RELEASES=base/'releases',
                         ROUTE=native/'web/plugins/mass-wp-update',
                         COMMAND=native/'bin/v-mass-wp-update', MENU=native/'web/js/custom_scripts/mass.js')
        self.stack.enter_context(patch.object(hestia, 'ROOT', native))
        for key, value in locations.items():
            self.stack.enter_context(patch.object(self.installer, key, value))
        self.lifecycle = self.stack.enter_context(patch.object(self.installer.lifecycle, 'install'))
        self.lint = self.stack.enter_context(patch.object(self.installer.subprocess, 'run'))

    def test_install_and_reinstall_publish_reporter_and_keep_machine_mode_explicit(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = progress.execute(self.installer.install, title='Mass WP Update', version='test')
        self.assertEqual(code, 0)
        self.assertIn('Installation completed', out.getvalue())
        self.assertIn('Validating the staged Hestia panel PHP files', err.getvalue())
        generation = self.installer.TARGET.resolve()
        self.assertEqual((generation/'src/progress.py').read_bytes(), (ROOT/'src/progress.py').read_bytes())
        self.assertNotIn('__INSTALL_ROOT__', (self.installer.ROUTE/'index.php').read_text())
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = progress.execute(self.installer.install, title='Mass WP Update', version='test', json_output=True)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())['data_preserved'])
        self.assertEqual(self.installer.TARGET.resolve(), generation)
        self.assertEqual(self.lifecycle.call_count, 2)

    def test_php_lint_error_has_no_success_and_does_not_publish_generation(self):
        import subprocess
        self.lint.side_effect = subprocess.CalledProcessError(255, ['php', '-l'], stderr='Syntax error')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = progress.execute(self.installer.install, title='Mass WP Update', version='test')
        self.assertEqual(code, 1)
        self.assertIn('Installation failed', out.getvalue())
        self.assertIn('Syntax error', err.getvalue())
        self.assertFalse(self.installer.TARGET.exists())
        self.lifecycle.assert_not_called()


if __name__ == '__main__':
    unittest.main()
