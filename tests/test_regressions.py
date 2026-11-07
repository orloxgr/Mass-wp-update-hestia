"""Real-site regressions: WordPress basenames, PHP CLI export and readable errors."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_backend as backend
import catalog
import diagnostics
import host
import jobs
import php_cli


class ErrorPresentationTests(unittest.TestCase):
    def test_database_dns_summary_keeps_the_full_original_trace(self):
        raw = 'Site command failed: PHP Fatal error: mysqli_sql_exception: getaddrinfo for database.example.test failed: Name or service not known\nStack trace:\n#0 wp-db.php'
        result = diagnostics.decorate(dict(error=raw))
        self.assertEqual(result['error'], raw)
        self.assertEqual(result['error_summary'], 'Cannot resolve database host database.example.test. Check DB_HOST in wp-config.php and DNS.')

    def test_external_download_dns_is_not_misreported_as_a_database_problem(self):
        raw = 'Could not download package: getaddrinfo for downloads.example.test failed'
        self.assertEqual(diagnostics.decorate(dict(error=raw))['error_summary'], raw)

    def test_undefined_exec_summary_does_not_change_the_failure(self):
        raw = 'Site command failed: Database export failed: PHP Fatal error: Call to undefined function exec()\nStack trace: ...'
        result = diagnostics.decorate(dict(error=raw))
        self.assertIn('exec() is disabled', result['error_summary'])
        self.assertEqual(result['error'], raw)

    def test_database_cli_restores_only_export_process_dependencies(self):
        self.assertEqual(php_cli.database_flags('exec,system,passthru,shell_exec,proc_open'), ['-d','disable_functions=system,passthru,shell_exec'])
        self.assertEqual(php_cli.database_flags(' system, EXEC '), ['-d','disable_functions=system'])
        self.assertEqual(php_cli.database_flags('proc_open,proc_close,proc_get_status,system'), ['-d','disable_functions=system'])
        self.assertEqual(php_cli.database_flags(''), [])
        self.assertEqual(php_cli.database_flags('system,shell_exec'), [])


@unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid() == 0, 'Disposable Linux Hestia lab only')
class WordPressIdentityTests(unittest.TestCase):
    setUp = backend.BackendTests.setUp
    tearDown = backend.BackendTests.tearDown

    def test_underscore_plugin_main_file_is_accepted(self):
        plugin = dict(file='facebook-thumb-fixer/_facebook-thumb-fixer.php', name='Facebook Thumb Fixer', version='1.7.7')
        data = dict(core='7.0',php='8.3',plugins=[plugin],themes=[dict(slug='_Theme name Ελληνικά',version='1')],multisite=False,layout_ok=True)
        with patch.object(host, 'wp', return_value=json.dumps(data)):
            result = host.inventory({}, self.base)
        self.assertEqual(result['plugins'][0]['file'], plugin['file'])
        metadata = catalog.inspect(backend.plugin_zip(self.base/'underscored.zip',main='_plugin.php'))
        self.assertEqual(metadata['plugin_file'], 'example-premium/_plugin.php')

    def test_safe_wordpress_basenames_do_not_require_download_slug_characters(self):
        for name in ('_plugin.php','Plugin name (old).php','Ελληνικά.php','--all'):
            with self.subTest(name=name): self.assertEqual(catalog.component(name), name)
        for name in ('','.', '..','../plugin.php','folder/file.php','folder\\file.php','bad\nname.php','bad\0name.php'):
            with self.subTest(name=name),self.assertRaises(ValueError):catalog.component(name)

    def test_plugin_name_cannot_turn_into_an_all_plugins_option(self):
        plugin = dict(file='--all/main.php',name='A plugin named --all',version='1')
        replies = [json.dumps([dict(name='--all',file=plugin['file'])]), 'Success']
        result = dict(actions=[],skipped=[])
        with patch.object(host,'wp',side_effect=replies) as command:
            jobs.regular_plugin_updates(dict(id='a'*32,domain='example.test'),self.base,dict(plugins=[plugin]),{},lambda message:None,result)
        args = command.call_args.args[1]
        self.assertEqual(args[0], 'eval')
        self.assertNotIn('--all', args)
        self.assertEqual(result['actions'], [plugin['name']])
